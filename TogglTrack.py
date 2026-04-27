#!/usr/bin/env python3
"""
TogglTrack.py — Toggl Track API → Life Points Calculator (TUI Only)
"""

import sys

from toggl.const import RED, BOLD, RESET
from toggl.config import load_runtime_settings
from toggl.api import TogglRateLimitError, TogglAPIError
from toggl.tui import TogglTUI


def main():
    try:
        load_runtime_settings()
        TogglTUI().run()
    except TogglRateLimitError as e:
        print(f"\n  {RED}{BOLD}{e}{RESET}")
        sys.exit(1)
    except TogglAPIError as e:
        print(f"\n  {RED}{e}{RESET}")
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(0)

if __name__ == "__main__":
    main()
