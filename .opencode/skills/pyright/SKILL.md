---
name: pyright
description: Use when the user mentions "pyright", "type check", "type error", or "type warning". Run pyright on specified directories/files or default to project root, then fix all type errors and warnings.
---

# pyright type checking skill

## When triggered

The user provides destinations (files, directories, or nothing for project root).

## Steps

1. **Run pyright**
   - If the user specified destinations: run `uv run pyright {destinations}` (fallback: `pyright {destinations}`)
   - If no destinations specified: run `uv run pyright .` (fallback: `pyright .`) on the project root.

2. **Analyze and fix all errors/warnings** emitted by pyright. For each issue:

   a. **Fix statically if possible** — correct type annotations, add missing imports, fix incorrect calls, adjust return types, etc.

   b. **If a truly static fix is not possible** (e.g., the user's third-party library has missing stubs, dynamic code patterns, or the fix would require a major refactor outside scope):
      - Add **runtime enforcing** at the narrowest point before the error site: `isinstance` checks, `cast()`, `typing.assert_type()`, `typing.type_check_only` protocols, or `TypedDict` constructors.
      - Then add a `# pyright: ignore[<error-code>]` comment on the offending line with a short reason, e.g.:
        ```python
        result = lib.untyped_function(x)  # pyright: ignore[reportUnknownMemberType] — no stubs for this lib
        ```

3. **Re-run pyright** on the same destinations to confirm all issues are resolved. If new issues appear, repeat step 2.

4. Report: summary of what was fixed and what was silenced with a reason.
