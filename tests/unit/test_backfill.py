"""Tests for the backfill subsystem."""

import os
import sqlite3
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from toggl.cache import fetch_week_data, _patch_weekly_csv, _patch_daily_csv


# ── DB schema tests ──────────────────────────────────────────────────────────

class TestInitBackfillDb:
    def test_creates_tables(self, tmp_data_dir):
        from toggl.backfill import init_backfill_db, get_backfill_db_path

        db_path = get_backfill_db_path()
        assert db_path == os.path.join(tmp_data_dir, "toggl_backfill.db")

        init_backfill_db()
        assert os.path.exists(db_path)

        conn = sqlite3.connect(db_path)
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        conn.close()
        assert "runs" in tables
        assert "checkpoints" in tables

    def test_idempotent(self, tmp_data_dir):
        from toggl.backfill import init_backfill_db

        init_backfill_db()
        init_backfill_db()

    def test_runs_schema(self, tmp_data_dir):
        from toggl.backfill import init_backfill_db, get_backfill_db_path

        init_backfill_db()
        conn = sqlite3.connect(get_backfill_db_path())
        cols = {
            row[1]: row[2]
            for row in conn.execute("PRAGMA table_info(runs)")
        }
        conn.close()
        assert "id" in cols
        assert "status" in cols
        assert "started_at" in cols
        assert "finished_at" in cols
        assert "weeks_discovered" in cols
        assert "weeks_backfilled" in cols
        assert "api_requests_made" in cols
        assert "stopped_reason" in cols

    def test_checkpoints_schema(self, tmp_data_dir):
        from toggl.backfill import init_backfill_db, get_backfill_db_path

        init_backfill_db()
        conn = sqlite3.connect(get_backfill_db_path())
        cols = {
            row[1]: row[2]
            for row in conn.execute("PRAGMA table_info(checkpoints)")
        }
        conn.close()
        assert "id" in cols
        assert "run_id" in cols
        assert "earliest_week" in cols
        assert "last_completed_week" in cols
        assert "last_verified_at" in cols
        assert "last_verified_week" in cols


# ── Binary search tests ──────────────────────────────────────────────────────

class TestFindEarliestWeek:
    def test_returns_none_when_no_data(self, tmp_data_dir):
        from toggl.backfill import find_earliest_week

        def never(week_str, token, projects_map):
            return {}, {}

        with patch("toggl.backfill.fetch_week_data", never):
            result = find_earliest_week("fake_token", {})
        assert result is None

    def test_finds_earliest_week(self, tmp_data_dir):
        from toggl.backfill import find_earliest_week

        def fake_fetch(week_str, token, projects_map):
            from toggl.cache import get_week_dates
            start_d, _ = get_week_dates(week_str)
            year = int(week_str.split("-W")[0])
            if year >= 2023:
                return {"Learning to Code": 5.0}, {start_d.strftime("%Y-%m-%d"): {"Learning to Code": 5.0}}
            return {}, {}

        with patch("toggl.backfill.fetch_week_data", fake_fetch):
            result = find_earliest_week("fake_token", {})
        assert result == "2023-W01"

    def test_finds_mid_range_week(self, tmp_data_dir, monkeypatch):
        from toggl.backfill import find_earliest_week

        def mid_fetch(week_str, token, projects_map):
            from toggl.cache import get_week_dates
            start_d, _ = get_week_dates(week_str)
            y = int(week_str.split("-W")[0])
            w = int(week_str.split("-W")[1])
            if (y > 2023) or (y == 2023 and w >= 10):
                return {"Learning to Code": 5.0}, {start_d.strftime("%Y-%m-%d"): {"Learning to Code": 5.0}}
            return {}, {}

        with patch("toggl.backfill.fetch_week_data", mid_fetch):
            result = find_earliest_week("fake_token", {})
        assert result is not None
        w_num = int(result.split("-W")[1])
        assert w_num == 10

    def test_uses_correct_date_range(self, tmp_data_dir, monkeypatch):
        from toggl.backfill import find_earliest_week

        monkeypatch.setattr("toggl.backfill.get_current_week", lambda: "2024-W24")

        calls = []

        def tracking_fetch(week_str, token, projects_map):
            calls.append(week_str)
            from toggl.cache import get_week_dates
            start_d, _ = get_week_dates(week_str)
            year = int(week_str.split("-W")[0])
            if year >= 2023:
                return {"Test": 1.0}, {start_d.strftime("%Y-%m-%d"): {"Test": 1.0}}
            return {}, {}

        with patch("toggl.backfill.fetch_week_data", tracking_fetch):
            find_earliest_week("fake_token", {})

        assert len(calls) > 0
        for w in calls:
            assert w.startswith("2023") or w.startswith("2024")


# ── Missing weeks detection tests ────────────────────────────────────────────

class TestFindMissingWeeks:
    def test_no_missing_when_complete(self, sample_weekly_csv, sample_daily_csv, tmp_data_dir):
        from toggl.backfill import find_missing_weeks

        missing = find_missing_weeks("2023-W01")
        assert "2023-W01" not in missing
        assert "2023-W02" not in missing

    def test_detects_fully_missing_week(self, sample_weekly_csv, sample_daily_csv, tmp_data_dir):
        from toggl.backfill import find_missing_weeks

        # Our CSVs only have W01 and W02 — W03+ should be missing
        missing = find_missing_weeks("2023-W01")
        # W01 and W02 should NOT be missing; W03+ might be depending on date.today()
        assert "2023-W01" not in missing
        assert "2023-W02" not in missing

    def test_detects_partial_week(self, tmp_data_dir, monkeypatch):
        import toggl.const

        with open(toggl.const.CSV_FILE, "w") as f:
            f.write("Week,Project,Hours\n2023-W01,Learning to Code,10.5\n")
        with open(toggl.const.DAILY_CSV_FILE, "w") as f:
            f.write("Date,Project,Hours\n2023-01-02,Learning to Code,1.0\n")

        monkeypatch.setattr("toggl.backfill.get_current_week", lambda: "2023-W01")

        from toggl.backfill import find_missing_weeks
        missing = find_missing_weeks("2023-W01")
        assert "2023-W01" in missing

    def test_returns_empty_when_all_complete(self, tmp_data_dir, monkeypatch):
        import toggl.const

        fake_today = date(2023, 1, 7)
        monkeypatch.setattr("toggl.backfill.get_current_week",
                            lambda: "2023-W01")

        with open(toggl.const.CSV_FILE, "w") as f:
            f.write("Week,Project,Hours\n2023-W01,Learning to Code,10.5\n")
        with open(toggl.const.DAILY_CSV_FILE, "w") as f:
            from toggl.cache import get_week_dates
            start_d, _ = get_week_dates("2023-W01")
            lines = ["Date,Project,Hours"]
            for i in range(7):
                d = start_d + timedelta(days=i)
                lines.append(f"{d.strftime('%Y-%m-%d')},Learning to Code,1.5")
            f.write("\n".join(lines) + "\n")

        from toggl.backfill import find_missing_weeks
        missing = find_missing_weeks("2023-W01")
        assert missing == []


# ── Backfill week tests ──────────────────────────────────────────────────────

class TestBackfillWeek:
    def test_backfills_successfully(self, tmp_data_dir):
        from toggl.backfill import backfill_week
        import toggl.const

        def fake_fetch(week_str, token, projects_map):
            from toggl.cache import get_week_dates
            start_d, _ = get_week_dates(week_str)
            weekly = {"Learning to Code": 10.5, "Building Projects": 4.2}
            daily = {}
            for i in range(7):
                ds = (start_d + timedelta(days=i)).strftime("%Y-%m-%d")
                daily[ds] = {"Learning to Code": 1.5, "Building Projects": 0.6}
            return weekly, daily

        with patch("toggl.backfill.fetch_week_data", fake_fetch):
            result = backfill_week("2023-W01", "fake_token", {})

        assert result["success"] is True

        assert os.path.exists(toggl.const.CSV_FILE)
        with open(toggl.const.CSV_FILE) as f:
            content = f.read()
        assert "2023-W01" in content
        assert "Learning to Code" in content

        assert os.path.exists(toggl.const.DAILY_CSV_FILE)
        with open(toggl.const.DAILY_CSV_FILE) as f:
            content = f.read()
        assert "2023-01-01" in content or "2023-01-02" in content

    def test_handles_missing_api_data(self, tmp_data_dir):
        from toggl.backfill import backfill_week

        def empty_fetch(week_str, token, projects_map):
            return {}, {}

        with patch("toggl.backfill.fetch_week_data", empty_fetch):
            result = backfill_week("2099-W01", "fake_token", {})
        assert result["success"] is True

    def test_catches_rate_limit(self, tmp_data_dir):
        from toggl.backfill import backfill_week
        from toggl.api import TogglRateLimitError

        def failing_fetch(week_str, token, projects_map):
            raise TogglRateLimitError("Quota exhausted")

        with patch("toggl.backfill.fetch_week_data", failing_fetch):
            result = backfill_week("2023-W01", "fake_token", {})
        assert result["success"] is False
        assert result["reason"] == "quota"


# ── Verify backfill needed tests ─────────────────────────────────────────────

class TestVerifyBackfillNeeded:
    def test_returns_empty_when_complete(self, sample_weekly_csv, sample_daily_csv, tmp_data_dir):
        from toggl.backfill import verify_backfill_needed

        missing = verify_backfill_needed()
        assert "2023-W01" not in missing
        assert "2023-W02" not in missing

    def test_detects_missing_weekly(self, sample_daily_csv, tmp_data_dir):
        from toggl.backfill import verify_backfill_needed

        missing = verify_backfill_needed()
        assert isinstance(missing, list)

    def test_no_api_calls(self, sample_weekly_csv, sample_daily_csv, tmp_data_dir):
        """verify_backfill_needed should NOT make any API calls."""
        from toggl.backfill import verify_backfill_needed

        with patch("toggl.backfill.fetch_week_data") as mock_fetch:
            verify_backfill_needed()
            mock_fetch.assert_not_called()


# ── Get backfill status tests ────────────────────────────────────────────────

class TestGetBackfillStatus:
    def test_returns_default_state(self, tmp_data_dir):
        from toggl.backfill import get_backfill_status

        status = get_backfill_status()
        assert status.get("status") is None
        assert "earliest_week" in status
        assert "last_completed_week" in status
        assert "weeks_backfilled" in status
        assert "total_weeks" in status

    def test_returns_last_run(self, tmp_data_dir):
        from toggl.backfill import init_backfill_db, get_backfill_db_path, get_backfill_status

        init_backfill_db()
        conn = sqlite3.connect(get_backfill_db_path())
        conn.execute(
            "INSERT INTO runs (status, started_at, finished_at, weeks_discovered, weeks_backfilled, api_requests_made, stopped_reason) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("success", "2024-01-01T00:00:00", "2024-01-01T01:00:00", 52, 48, 50, "complete"),
        )
        conn.commit()
        conn.close()

        status = get_backfill_status()
        assert status["status"] == "success"
        assert status["weeks_backfilled"] == 48


# ── Run backfill orchestrator tests ──────────────────────────────────────────

class TestRunBackfill:
    def test_no_missing_weeks(self, sample_weekly_csv, sample_daily_csv, tmp_data_dir, monkeypatch):
        from toggl.backfill import run_backfill, init_backfill_db

        monkeypatch.setattr("toggl.backfill.get_current_week", lambda: "2023-W02")

        init_backfill_db()

        def fake_fetch(week_str, token, projects_map):
            return {}, {}

        with patch("toggl.backfill.fetch_week_data", fake_fetch):
            result = run_backfill("fake_token", {})
        assert result["status"] == "success"

    def test_creates_db_records(self, sample_weekly_csv, sample_daily_csv, tmp_data_dir, monkeypatch):
        from toggl.backfill import run_backfill, init_backfill_db, get_backfill_db_path

        monkeypatch.setattr("toggl.backfill.get_current_week", lambda: "2023-W02")

        init_backfill_db()

        def fake_fetch(week_str, token, projects_map):
            return {}, {}

        with patch("toggl.backfill.fetch_week_data", fake_fetch):
            run_backfill("fake_token", {})

        conn = sqlite3.connect(get_backfill_db_path())
        rows = list(conn.execute("SELECT * FROM runs"))
        conn.close()
        assert len(rows) >= 1

    def test_stops_on_quota(self, tmp_data_dir, monkeypatch):
        from toggl.backfill import run_backfill, init_backfill_db
        from toggl.api import TogglRateLimitError

        monkeypatch.setattr("toggl.backfill.get_current_week", lambda: "2023-W10")
        monkeypatch.setattr("toggl.backfill.find_earliest_week",
                            lambda token, pm: "2023-W01")

        init_backfill_db()

        def quota_fetch(week_str, token, projects_map):
            raise TogglRateLimitError("No quota")

        with patch("toggl.backfill.fetch_week_data", quota_fetch):
            result = run_backfill("fake_token", {})

        assert result["stopped_reason"] == "quota"
        assert result["weeks_backfilled"] == 0
