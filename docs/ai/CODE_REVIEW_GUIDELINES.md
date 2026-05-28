# Code Review Guidelines (Quality)

Use this after spec compliance is ✅.

## Code quality checklist
1. **Clarity & naming**
   - Functions and variables are explicit and consistent with repo style.

2. **Locality**
   - Changes are localized; helpers live near usage.

3. **Error handling**
   - Explicit handling of missing files, empty data, and parsing errors.

4. **Performance**
   - Avoid repeated CSV reads; use DataCache for aggregation.

5. **Test quality**
   - Tests are deterministic and minimal.
   - No over-mocking.

6. **UI quality**
   - Textual widgets sized/aligned correctly.
   - No layout regressions.

## Output format for reviews
- **Status**: ✅ Approved / ❌ Issues
- **Strengths**: bullet list
- **Issues**: bullet list with severity (Critical/Important/Minor)
