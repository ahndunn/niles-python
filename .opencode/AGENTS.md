# Python coding rules

## Functional programming

- Favor pure functions — same input always produces same output, no side effects.
- Prefer immutable data: use `tuple`, `frozenset`, `dataclass(frozen=True)`, or `Mapping`/`Sequence` type annotations over mutable counterparts.
- Use `map`, `filter`, `functools.reduce` over explicit `for` loops where readability is preserved.
- Compose small functions with `functools.partial`, `toolz.functoolz`, or plain function chaining.
- Avoid mutable default arguments — use `None` + `if arg is None: arg = ...` pattern.
- Avoid classes that exist solely to hold state; use standalone functions or frozen dataclasses instead.
- Prefer returning new values over mutating inputs in place.
- Avoid `global` and `nonlocal` mutations.

## Naming conventions

### Exceptions
- Must end with `Error` suffix: e.g. `ConfigError`, `ValidationError`, `DispatchError`.

### Classes
- Named as an actor — something that performs an action.
- Examples: `Parser`, `Dispatcher`, `Router`, `Builder`, `Runner`, `Handler`, `Factory`, `Validator`, `Collector`, `Transformer`.
- Avoid noun-only names that don't convey action (e.g. `Configuration`, `Data`, `Manager`).

### Methods / functions
- Describe an action or verb: `def parse()`, `def dispatch()`, `def validate()`.
- Methods that return `bool` and take **only** `self` → prefix with `is_`: `def is_valid(self) -> bool`.
- Methods/functions that return `bool` and take parameters beyond `self` → prefix with `check_`: `def check_permission(user) -> bool`, `def check_exists(self, key) -> bool`.

### Modules and submodules
- Named in a resource-based manner (like RESTful API endpoints): `niles/configs/`, `niles/discord/channels/`, `niles/utils/parsing.py`.
- Children module names **must not** overlap with their parent's name.
  - Correct: `niles/configs/loader.py` (parent is `configs`, child is `loader`).
  - Incorrect: `niles/configs/configs.py` (child overlaps).
  - Incorrect: `niles/utils/utils.py`.
- The root package (`niles/`) uses the project name. Everything underneath is a resource.

## Protocols before implementations

- Define `typing.Protocol` classes before writing concrete implementations.
- A Protocol captures the interface contract; concrete types then implement it.
- This enables loose coupling, easy testing, and future scalability without refactoring call sites.
- Example:
  ```python
  class Parser[T](Protocol):
      def parse(self, data: str) -> T: ...

  class JsonParser:
      def parse(self, data: str) -> dict: ...
  ```

## Reuse check

- Before defining a new Protocol, search the codebase for an existing one that already covers the interface you need.
- Before writing a utility function, check if `functools`, `itertools`, or stdlib already provides it.
- Before adding a dependency, check if the language stdlib already solves the problem.

## Post-coding workflow

After making changes, run these three commands **only on the changed files**, in order, stopping if any fails:

```shell
uv run pyright {changed_files}  ||  pyright {changed_files}
uv run ruff check {changed_files}  ||  ruff check {changed_files}
uv run ruff format {changed_files}  ||  ruff format {changed_files}
```

Try `uv run` first (uses the project's `.venv`). If that fails, fall back to the bare command from `PATH`.

## Discord input modal design

- Prioritize dropdown lists and auto-completion whenever feasible, especially when input options are finite.
- Break input flow into small ephemeral input tasks to enhance UX, filtering out unreachable options of the current input task given previous input task selections.
