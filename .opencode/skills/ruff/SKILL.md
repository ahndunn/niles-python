---
name: ruff
description: Use when the user mentions "ruff", "lint", "format", "ruff check", "ruff format", or "linter". Run ruff format + ruff check + ruff format on specified files/directories or project root, then fix all lint errors.
---

# ruff linting and formatting skill

## When triggered

The user provides destinations (files, directories, or nothing for project root).

## Steps

1. **Run ruff in order** on the specified destinations (default: `.` for project root):
   ```
   uv run ruff format {destinations}    (fallback: ruff format {destinations})
   uv run ruff check {destinations}     (fallback: ruff check {destinations})
   uv run ruff format {destinations}    (fallback: ruff format {destinations})
   ```

2. **Analyze and fix all errors/warnings** emitted by `ruff check`. For each issue:

   a. **Fix statically if possible** — apply the correct lint rule fix (rename symbols, remove unused imports, fix syntax, simplify logic, etc.).

   b. **If the issue genuinely cannot be fixed** (e.g., the rule flags a legitimate pattern that can't be rewritten without breaking semantics, or the fix would require a refactor outside scope):
      - Add a `# noqa: <rule-code>` comment on the offending line with a brief justification.
      - For broader suppressions, add a `# ruff: noqa: <rule-code>` at the top of the file.

3. **Re-run `ruff check`** on the same destinations to confirm zero remaining errors. If new issues appear, repeat step 2.

4. Report: summary of what was auto-fixed and what was suppressed with a reason.
