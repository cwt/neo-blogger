# Neo-Blogger

Self-hosted, article-first, long-form publishing platform — a clean-room rebuild specified in
`docs/requirements.md` (WHAT) and `docs/technical-requirements.md` (HOW).

## Status

Specification and spike verification are complete; implementation proceeds phase by phase,
one clean commit per phase.

## Development

The platform requires **Python 3.14+** (`requires-python = ">=3.14,<3.15"` in `pyproject.toml`).

> [!NOTE]
> **Python 3.14 syntax (PEP 758):** This codebase utilizes native Python 3.14 syntax, including [PEP 758](https://peps.python.org/pep-0758/) which permits multiple exception types in `except` clauses without parentheses (e.g. `except TypeError, ValueError:`). This syntax is standard in Python 3.14 and is automatically formatted by `ruff format`. Reviewing agents or external tooling configured with pre-3.14 assumptions must not misidentify this modern syntax as a Python 2 regression.

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
# generate secret_key using the built image (or: uv run python -m neoblogger.cli.secret)
podman run --rm --entrypoint neoblogger-secret localhost/neo-blogger:latest
# put the generated value into secret_key in ~/neo-blogger/data/neo-blogger.toml (https = true)
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

See [Maintenance (CLI)](#maintenance-cli) for the offline scripts (secret,
users, admin repair, search reindex, theme artwork).

## Maintenance (CLI)

All commands target the configured database (`-c/--config`, else `$NEOBLOGGER_CONFIG`
or `./neo-blogger.toml`; `reindex` and `admin_repair` take the config path as an
optional positional argument instead). Installed console scripts (`neoblogger-users`,
`neoblogger-admin-repair`, `neoblogger-reindex`, `neoblogger-secret`,
`neoblogger-theme`) mirror the `python -m` forms below.

When deploying via container, any of these commands can be run via:

```sh
# Offline against the persistent data volume:
podman run --rm -it -v "$HOME/neo-blogger/data:/data:Z" --entrypoint <command> localhost/neo-blogger:latest [args...]

# Or on a running container instance:
podman exec -it neo-blogger <command> [args...]
```

- `python -m neoblogger.cli.secret` — print a strong random `secret_key` (§15.9).
- `python -m neoblogger.cli.users <subcommand>` — member administration, where
  `<id>` is a display name, email address, or 24-character hex id:
  - `list [--status all|active|disabled] [--role all|admin|publisher|author] [--json]`
  - `show <id> [--json]` — details plus contribution statistics.
  - `create <name> <email> [--password/-p] [--question/-q] [--answer/-a] [--admin/--no-admin] [--publisher/--no-publisher]` — prompts for omitted secrets; the first member becomes administrator and publisher.
  - `enable <id>` / `disable <id>` — the sole administrator cannot be disabled.
  - `set-role <id> [--admin/--no-admin] [--publisher/--no-publisher]` — the sole administrator cannot be demoted.
  - `set-password <id> [--password/-p]` and `set-email <id> <new-email>`.
- `python -m neoblogger.cli.admin_repair <display-name> [config]` — promote a
  member to administrator and publisher; for multi-member databases with no
  administrator (startup only auto-promotes a lone member).
- `python -m neoblogger.cli.reindex [config]` — drop and rebuild the
  title/subtitle/body full-text indexes (required after tokenizer changes).
- `python -m neoblogger.cli.theme generate [-c CONFIG] [--force]` — one-time
  theme artwork, see below.

### Theme artwork (optional, deploy-time)

One 21:9 banner per page family (home, article, tag, search, auth, profile,
write, upload, admin, error), generated with Agnes Image 2.5 and stored as
ordinary `theme`-owned gallery images.

#### Local development

```sh
printf 'AGNES_API_KEY=...\n' > .env   # never committed, never baked into the image
uv run python -m neoblogger.cli.theme generate
```

#### Container deployment (Podman / Docker)

When running the platform in a container, pass the Agnes API key via an environment variable or `--env-file`. Never bake the API key into the image.

**Option 1: One-off container against the persistent volume** (recommended before starting the service or while stopped):

```sh
podman run --rm \
  -v "$HOME/neo-blogger/data:/data:Z" \
  -e AGNES_API_KEY="your-api-key" \
  --entrypoint neoblogger-theme \
  localhost/neo-blogger:latest generate
```

Or pass a temporary `.env` file from the host:

```sh
printf 'AGNES_API_KEY=...\n' > ~/neo-blogger/data/.env
podman run --rm \
  -v "$HOME/neo-blogger/data:/data:Z" \
  --env-file ~/neo-blogger/data/.env \
  --entrypoint neoblogger-theme \
  localhost/neo-blogger:latest generate
rm ~/neo-blogger/data/.env
```

**Option 2: On a running container**:

```sh
podman exec -e AGNES_API_KEY="your-api-key" neo-blogger neoblogger-theme generate
podman restart neo-blogger
```

> **Note**: The application resolves and caches the theme banner mapping once at startup. If generated against an active container instance, restart the container (`podman restart neo-blogger`) so the new banners take effect.

The set generates once: a complete set is refused without `--force`, a partial
run resumes on retry. Without a generated set every page renders the themeless
default; an article's own cover always wins over its page banner. AI-generated
output belongs to the operator (Agnes ToS §8.1); the footer credit satisfies
the AI-content disclosure whenever a theme is active.
