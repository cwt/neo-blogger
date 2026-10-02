# Neo-Blogger

Self-hosted, article-first, long-form publishing platform — a clean-room rebuild specified in
`docs/requirements.md` (WHAT) and `docs/technical-requirements.md` (HOW).

## Status

Specification and spike verification are complete; implementation proceeds phase by phase,
one clean commit per phase.

## Development

The toolchain is [`uv`](https://docs.astral.sh/uv/)-managed:

```sh
uv sync                     # creates .venv, installs project + dev group, writes uv.lock
uv pip install -e ../neosqlite   # optional: co-development install of the engine
uv run pytest               # tests must be green with zero warnings
uv run ruff check           # linting must be clean
uv run mypy                 # strict typing must be clean
uv run ruff format          # format before committing
```

Configuration lives in a TOML file; its location is overridden by the `NEOBLOGGER_CONFIG`
environment variable, and every omitted key degrades to a documented default (`docs/requirements.md` §18).
