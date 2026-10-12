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
uv run pytest               # tests must be green with zero warnings
uv run ruff check           # linting must be clean
uv run mypy                 # strict typing must be clean
uv run ruff format          # format before committing
```

Configuration lives in a TOML file; its location is overridden by the `NEOBLOGGER_CONFIG`
environment variable, and every omitted key degrades to a documented default (`docs/requirements.md` §18).

## Deployment

The production artifact is a rootless-Podman container (tech-req §15):

```sh
podman build -t localhost/neo-blogger:latest .
mkdir -p ~/neo-blogger/data        # database file + file-cache directory
cp neo-blogger.toml ~/neo-blogger/data/
uv run python -m neoblogger.cli.secret  # put the value into secret_key (https = true)
podman run -d --name neo-blogger \
  -v "$HOME/neo-blogger/data:/data:Z" \
  -p 127.0.0.1:8000:8000 \
  localhost/neo-blogger:latest
curl http://127.0.0.1:8000/healthz
```

The container runs Gunicorn + Uvicorn workers with bounded recycling; worker startup
pre-warms the database handle and the anonymous home page into the response cache.
TLS termination belongs to the reverse proxy of the metal (`PublishPort` is loopback-only).

For autostart: copy `deploy/neo-blogger.container` to `~/.config/containers/systemd/`
and run `systemctl --user daemon-reload && systemctl --user start neo-blogger`.

Maintenance scripts (offline, idempotent): `uv run python -m neoblogger.cli.secret |
python -m neoblogger.cli.reindex | python -m neoblogger.cli.admin_repair <display-name>`.

Optional theme artwork (deploy-time, once): put `AGNES_API_KEY` in `./.env`
(never committed), then `uv run python -m neoblogger.cli.theme generate`.
Without a generated set every page renders the themeless default.
