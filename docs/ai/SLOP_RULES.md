# Slop Rules (Anti-Slop)

The goal: concise, precise, and testable output. Avoid verbose or generic text.

## Writing constraints
- **No filler**: remove generic statements like “ensure best practices” or “improve performance.”
- **No over-promising**: only claim what you can verify.
- **No vague verbs**: replace “handle,” “support,” “enable” with concrete actions.
- **Prefer specifics**: file paths, functions, data shapes, exact behavior.
- **One idea per sentence**.

## Implementation constraints
- Avoid speculative changes. Follow the plan and requirements.
- Keep changes minimal and localized.
- Add tests for each new behavior.

## Review constraints
- If you cannot verify, say so explicitly.
- Call out ambiguity rather than guessing.
