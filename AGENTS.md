# AGENTS.md — working instructions for coding agents in this repository

Project: **Neo-Blogger** — a self-hosted, article-first, long-form publishing platform.
Current phase: implementation complete; production hardening and security fixes.

## 1. Where the truth lives — read before writing code

Read **both**, in this order:

1. `docs/requirements.md` — clean-room functional specification (WHAT the platform does).
   It deliberately names no technology; never "fix" perceived gaps in it by naming tech.
2. `docs/technical-requirements.md` — Solutions-architect document (HOW the platform is built):
   the ADR (§1), layering/package layout (§3.1–3.2), data layer incl. verified spike results (§5),
   per-domain rules (§6–§13), deployment (§15), quality gates (§16), dependencies (§17),
   license inventory (§17.1), open decisions (§19).

Rules of engagement:
- If docs and code disagree, **docs win** and code gets fixed — or, if the decision is
  justified, amend the doc *first*, then the code.
- When a session discovers a new constraint, trap, or finding about the stack: **record it in
  `docs/technical-requirements.md` immediately** (usually §5, or a new ADR row). Session knowledge
  that is not in the docs is assumed lost.
- Pending product/design decisions are tracked in §19. Do not silently pick one; if forced,
  take the doc-declared default and note the deviation there.

## 2. Source control

- **Mercurial** (project convention; hg-git for GitHub sync). Use the `hg-mcp` server tools,
  not raw shell VCS commands.
- The repo may not be initialized yet — if `.hg/` is absent, first act of a new session is
  `hg init`, then `hg add` + commit the existing tree before any change.
- Small, atomic commits; imperative messages; no secrets.
- Before pushing: `hg outgoing` > 5 changesets → confirm with the user.

## 3. License containment (hard rule)

The project must remain releasable under **MIT**. License inventory and verdict: §17.1.

- Local research scope is restricted to: `../neosqlite/` and `../fts5-icu-tokenizer/`.
  **Do not open, read, or copy from any other local project** — this prevents license contamination.
- Internet research is allowed, but every candidate dependency/asset must have its license
  checked against §17.1 before adoption; update the inventory table when adding one.
- Vendored frontend assets (Pico CSS, EasyMDE, …) go into `app/web/static/` (no CDN at runtime,
  CSP stays `'self'`) and must be added to the attribution/NOTICE bundle list.

## 4. Coding standards (hard gates, mirrored from §2 and §16)

- **Python 3.14** syntax where it improves clarity; no features requiring < 3.14 assumptions.
  Embraces PEP 758 (unparenthesized `except A, B:`), which `ruff format` standardizes on for Python 3.14.
- **No `lambda`** — always named `def` functions (workspace convention).
- Line length 88; `ruff format` is the formatter of record; `ruff check` + `mypy --strict`
  over `app/` and `cli/` are hard gates before committing anything substantive.
- Every route is `async def`. Blocking work never runs on the event loop:
  DB work only via the repo facade (`run_in_executor` on the single-thread DB executor),
  Pillow on the separate image executor (§5.6).
- Comments: keep them out unless they encode a spec reference (§) or spike finding;
  prefer self-explanatory code that names intent.

## 5. Known stack traps (from executed spikes — do not re-discover)

Details and evidence: `docs/technical-requirements.md` §5.1/§5.2/§5.5/§5.8; scripts: `tools/spikes/`.

- **Executor discipline**: never submit to the DB executor from inside executor work
  (a nested submit on `max_workers=1` deadlocks — proven in S1-4b). Submits originate only
  from the event loop; one `neosqlite.Connection` per worker, opened on the executor thread
  (or `check_same_thread=False`).
- **ID policy**: linkage fields (`article_id`, …) are plain hex strings (`str(_id)`), never
  `ObjectId` instances — engine equality does not support ObjectId-typed ordinary fields.
  Repositories normalize `_id` to hex strings at the boundary.
- **GridFS**: build buckets on the raw sqlite handle — `GridFSBucket(conn.db)` (the
  `neosqlite.Connection` object itself is not accepted); registry is relational
  (`fs_files.id` ↔ `fs_chunks.files_id`); checksum from `md5`; iterate cursors with `list()`.
- **Tokenizers**: engine accepts single-name tokenizer only; a missing `.so` raises
  `sqlite3.OperationalError` at connect → the app owns the fallback (catch → warn →
  reconnect without tokenizer) per spec §12.2.
- **Fallback route** (not implemented in v1): if the executor facade proves inadequate,
  switch `repositories/` to PyMongo `AsyncMongoClient` + NX-27017 wire server; nothing else
  may change layers.

## 6. Verification workflow

- After touching the data layer, run the spikes:
  `PYTHONPATH=/home/cwt/Projects/neosqlite python3 spike_sN.py` from `tools/spikes/`
  (all five must pass; they exit non-zero on failure and print `[FAIL]` lines).
- Runtime tests (once the app exists): `pytest` + `pytest-asyncio`, offline, with a real
  NeoSQLite temp-DB instance; minimum coverage per §16 (search-input protections, visibility
  rules, draft lifecycle, image deletion guard, e2e register→publish→comment→search→moderate).
- Quality/perf budgets (§16/§20 of functional spec): Lighthouse Performance ≥ 85,
  Accessibility ≥ 95, Best Practices ≥ 95, SEO = 100.

## 7. Environment notes

- Host is Fedora 44 (Workstation) — same distro as the container base (`fedora:44`), so
  local verification transfers 1:1 to container builds (S5).
- Container runtime target: **rootless Podman**; find it in `PATH` on the host.
- Working directory layout today: `docs/` (specification), `tools/spikes/` (executed spikes).
  When scaffolding, follow the package layout in technical-requirements §3.2 exactly
  (`neoblogger/` with the three strict layers — `blueprints/` → `services/` → `repositories/`,
  plus side-layer `text/`, `security/`, `web/`).

## 8. Communication

- Be concise; prefer showing the changed file/section over prose.
- Mercurial IDs are change-set references; user-facing numbers stay hex strings.
- Thai language is a first-class deployment target (ICU tokenizer required); docs are English.
