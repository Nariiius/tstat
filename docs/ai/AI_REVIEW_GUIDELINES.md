# AI Review Guidelines (Spec Compliance)

Use this for spec compliance reviews after each task.

## Checklist
1. **Scope match**
   - Does the change implement exactly what the task asked for?
   - Anything missing? Anything extra?

2. **Behavior verification**
   - Is behavior observable via tests or the TUI?
   - Are success and failure cases covered?

3. **Data integrity**
   - CSV schemas respected?
   - No destructive writes without explicit requirement?

4. **User interaction**
   - Navigation keys and view changes match requirements?
   - Status/tooltip messaging accurate?

5. **Errors & quotas**
   - Toggl rate limits handled where relevant?
   - Backfill stops on low quota if required?

## Output format for reviews
- **Status**: ✅ Compliant / ❌ Non-compliant
- **Findings**: bullet list with file/line references
- **Required fixes**: bullet list (only when non-compliant)
