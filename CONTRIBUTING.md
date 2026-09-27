# Contributing

Use Python 3.12+ and [uv](https://docs.astral.sh/uv/). From this directory:

```sh
uv sync --dev
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pip-audit
```

Keep the `src/` layout, add focused tests for behavior changes, and do not add
cloud or network dependencies to unit tests. Database schema changes require an
Alembic revision. Use conventional, imperative commit messages and update the
README for public API or configuration changes.
