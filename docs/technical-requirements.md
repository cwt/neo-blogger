# Technical Requirements — Neo-Blogger (Clean-Slate Build)

Status: draft v0.1 (Solutions Architect)
Date: 2026-10-02
Companion document: `docs/requirements.md` (functional specification). This document records *how* the platform is built. It must be read together with the functional spec; whenever the two conflict, the functional spec wins and this document must be amended.

---

## 1. Architecture Decision Record (summary)

| # | Decision | Choice | Rationale | Alternatives rejected |
|---|---|---|---|---|
| A1 | Language / runtime | **Python 3.14** (use current modern syntax throughout) | User directive; spec's "small and readable" principle | Node/TS, Go |
| A2 | Web framework | **Quart** (asyncio, Flask-compatible API) | User directive; async-first; Jinja2 templating built in | Django (too heavy) |
| A3 | ASGI runtime | **Gunicorn (process manager) + Uvicorn ASGI worker** running the Quart app in production; Hypercorn for development | Gunicorn natively provides worker recycling (`max_requests`) and fork-time hooks (pre-warm), satisfying spec §19.1/§19.4 without custom code | Hypercorn multi-worker (no request-bounded recycling) |
| A4 | Database engine | **NeoSQLite** (embedded, single-file document store) used **directly in-process** — no wire-protocol server; `repositories/` wraps the synchronous engine in a thin async facade (single-thread DB executor). **NX-27017 + PyMongo `AsyncMongoClient`** remain the documented fallback route if the facade proves problematic | User directive; satisfies spec §12 (document model, self-generated opaque IDs) and §1 (no external DB service); single process, lowest latency; NX-27017 itself dispatches sync NeoSQLite calls via `asyncio.to_thread`, so the direct route executes identically minus the socket/BSON hop | Wire server as primary (extra process, runtime coupling, per-op BSON overhead); standalone MongoDB (external service, violates spec §1) |
| A5 | Container base | **fedora:44**, run **rootless Podman** on a RHEL-based host | User directive | — |
| A6 | Markup syntax | **CommonMark** via `markdown-it-py` | Mature parser + sanitizer ecosystem; covers headings/emphasis/lists/links/images/tables/fenced code | Custom syntax (we own the parser + sanitization risk) |
| A7 | Sanitizer | **nh3** (Rust ammonia bindings), strict allowlist | Fast, maintained, allowlist-native (spec §15.3) | bleach (deprecated) |
| A8 | Frontend | **Server-rendered Jinja2 + vanilla JS**, no SPA, no build step for core assets | Spec §14/§17 performance + accessibility targets; CSP friendliness | HTMX, SPA |
| A9 | CSS | **Pico CSS**, vendored locally (no CDN), extended with a small custom layer for the distinctive typographic identity | User suggestion; classless-first, strong accessible defaults; keeps CSP `self`-only | Bootstrap (generic look), Tailwind (build step) |
| A10 | Password KDF | **Argon2id** via `argon2-cffi` | "Well-established KDF with large iteration count" (spec §15.1); memory-hard | bcrypt, PBKDF2 (allowed only as documented fallback for legacy data) |
| A11 | Config format | **TOML**, parsed with stdlib `tomllib` | Spec §18 "labeled sections of key–value pairs"; stdlib, human-readable | INI (no types), YAML (extra dep) |
| A12 | Sessions | **Signed cookie** (`itsdangerous`) carrying member internal ID + CSRF token; server re-resolves member from DB on every request | Spec §13 (visibility), Appendix B D4 (stable internal ID), zero server-side session storage | Server-side session table (unnecessary complexity for v1) |
| A13 | Source control | **Mercurial** (project convention) | Workspace convention | — |

---

## 2. Language and Python-version policy

Python 3.14 features must be used where they improve clarity:

- **Exception handling without parentheses (PEP 758)**: multiple exception types in `except` clauses may omit parentheses (`except TypeError, ValueError:`). `ruff format` standardizes on this form for Python 3.14 targets.
- **Deferred annotations (PEP 649/749)**: annotate everything; no forward-reference quotes needed.
- **Template strings / t-strings (PEP 750)**: permitted for building small dynamic HTML fragments in Python where a Jinja template would be overkill; never used with raw user data (t-string interpolation must route through the sanitizer pipeline).
- **`asyncio.TaskGroup` + `asyncio.timeout()`**: all structured concurrency (e.g. dashboard statistics, parallel repository reads) must use TaskGroups.
- **Structural pattern matching**: for config parsing and request-dispatch enums.
- **Typing**: `TypedDict` (with `NotRequired`) for all document shapes; `TypeAlias`, `TypeIs` where appropriate. A `py.typed` marker ships with the package.
- **`tomllib`** for configuration; **`secrets`** for all randomness; no third-party utility needed for those roles.
- **Free-threaded build (PEP 779)**: out of scope for v1; the code must not depend on the GIL for correctness, but must be built and tested against the standard build.

Style rules (hard gates, see §18):

- No `lambda`; use named `def` functions (workspace convention).
- Line length 88 (ruff default); `ruff format` is the formatter of record.
- Every route is `async def`; blocking work must never run on the event loop (see §5.6).

---

## 3. Application architecture

### 3.1 Layering (enforced; spec §20 "Maintainability")

Three strict layers; imports may only point downward:

```
blueprints/  (thin controllers: parse request, authorize, call service, render response)
   ↓
services/    (business rules: visibility, moderation, workflows, cache invalidation)
   ↓
   repositories/  (all database access: NeoSQLite direct; no HTTP concepts leak in)
```

Side-layer modules (no dependency on the layers): `text/` (markdown, sanitize, highlight), `security/` (hashing, sessions, CSRF), `web/` (templates, static assets).

### 3.2 Package layout

```
neoblogger/
  app/
    __init__.py        # create_app() application factory
    blueprints/        # auth, profile, blog, comments, images, tags, search, admin, core
    services/          # accounts, articles, comments, objects, moderation, search, cache, seo
    repositories/      # db (connection factory + DB executor facade), members, articles, comments, objects, meta
    text/              # markdown.py, sanitize.py, highlight.py
    security/          # hashing.py, sessions.py, csrf.py, headers.py, ratelimit.py, proxy.py
    web/templates/     # Jinja2 templates
    web/static/        # vendored CSS/JS/fonts/icons (self-hosted; CSP 'self')
  cli/                 # maintenance scripts (secret gen, index rebuild, backfills, user management, theme artwork generation)
  tests/               # unit / web / e2e
  neo-blogger.toml      # example configuration
  Containerfile
  pyproject.toml
```

Blueprints are **thin controllers**: no business rules, no storage access. Rule: a blueprint function is short enough to review at a glance.

### 3.3 Request lifecycle (every request)

1. Resolve session cookie → member by **internal ID** (Appendix B D4). If the member is disabled or deleted, destroy the cookie immediately and treat as anonymous (spec §4.3, §15.7).
2. Validate CSRF token on all mutating methods (POST/PUT/DELETE) (spec §15.2).
3. Route handler runs (async).
4. Response cache lookup/insert for anonymous GET pages, excluding search and tag pages (spec §14).
5. `after_request` pipeline: security headers (§12), cache-control policy, HTML minification (§11), session refresh (sliding expiry).

### 3.4 Startup sequence (application factory)

1. Load config: TOML file (path from env `NEOBLOGGER_CONFIG`, default `./neo-blogger.toml`); every omitted key falls back to documented defaults; nothing crashes on missing values (spec §18).
2. Production-mode detection (HTTPS flag) → require `secret_key` non-empty and strong; refuse to boot in production with a missing/weak secret (spec §15.9).
3. Start the DB executor (`ThreadPoolExecutor(max_workers=1)`) and open the single `neosqlite.Connection` on it (WAL; tokenizer libraries passed via the engine's `tokenizers=...` kwarg when configured, §5.1).
4. Create indexes idempotently (§5.4); run automatic backfills (§5.7); self-heal single-administrator publisher status (spec §2). All of these deliver through the repo facade.
5. Clear response cache; pre-warm home-feed page 1 for anonymous visitors and warm the database handle — executed **per worker at fork time** via Gunicorn `post_fork` hook (spec §14, §19.4).
6. Done: the app is the only process in the container (§15.3).

---

## 4. Web layer details

- Framework: Quart; Jinja2 templates with autoescape on; strict-undefined mode in development.
- URL scheme (public surface): home `/`, article `/{slug-or-id}` (id-based; confirm with data model §5.1), tag `/tag/{name}`, search `/search?q=...&page=N`, auth pages, profile `/profile`, write `/write`, upload `/upload`, admin `/admin`, review `/admin/unpublished`, images `/images/{id}.{ext}`, sitemap `/sitemap.xml`, robots `/robots.txt`, health `/healthz`.
- All state-changing routes require an authenticated, active member and CSRF token (spec §13).
- Rate limiting: fixed-window counter keyed by (client IP, normalized email) on the sign-in and password-recovery endpoints (spec Appendix B D5); counters live in-process, never fatal on failure.
- Proxy trust: parse `X-Forwarded-For`, `X-Forwarded-Proto`, `X-Forwarded-Host` **only** from the adjacent hop; trusted-hop allowlist configurable, default loopback (spec §15.8). Canonical URLs and rate-limit keys use the reconstructed client address/scheme.
- Error handlers for 404, 403, 500 render branded pages; log full traceback server-side (spec §3.11, §19.5).

---

## 5. Data layer

### 5.1 Engine and access

- Engine: **NeoSQLite** (embedded, single-file document store, self-generated opaque unique IDs — spec §12), used **directly** — no wire-protocol server in v1.
- Execution model: NeoSQLite is a synchronous library. `repositories/db.py` owns the only blocking hop: a process-wide `ThreadPoolExecutor(max_workers=1)` ("the DB executor"); repository methods are `async def` and hand their sync work to it via `loop.run_in_executor`. This mirrors exactly what NX-27017 does internally (`asyncio.to_thread` over a per-database `RLock`, see `packages/nx_27017/src/nx_27017/server.py`), minus the socket and BSON encode/decode per operation. The request path stays fully async; nothing blocking runs on the event loop (§5.6).
- Thread-safety contract (taken from the engine's own threaded usage in `nx_27017/handler.py`): the single `Connection` is opened on the DB executor thread; if it must be created on the main thread instead, pass `check_same_thread=False` — the engine forwards kwargs to `sqlite3.connect` — and route all use through the executor. One connection per worker process; no shared cursors across threads. SQLite remains single-writer; writes serialize inside SQLite itself.
- Executor-discipline rule (proven by Spike S1-4b): repository code must **never** submit to the DB executor from within executor work — a nested submit on `max_workers=1` self-deadlocks. All submits originate from the event loop only.
- ID policy (proven by Spike S2): documents keep their engine-generated ObjectId `_id`; linkage fields (`article_id` etc.) are stored as plain **hex strings** (`str(_id)`), never as `ObjectId` instances — the engine's equality translation does not handle ObjectId-typed ordinary fields, while hex strings work for `find`/`count` and join correctly against an ObjectId `_id` in `$lookup`. Repository methods normalize `_id` to hex strings at the boundary (aggregation outputs — `$facet`, `$lookup` subdocs — already arrive stringified).
- **Fallback route (documented contingency, not implemented in v1):** switch to PyMongo `AsyncMongoClient` + the NX-27017 wire server. NX-27017 passes 372/372 PyMongo API-compatibility tests against MongoDB 8.x behavior, so parity is established; because every DB access already lives behind the facade in `repositories/`, the swap touches one layer only. Trigger this only if the executor facade shows real problems (e.g. long-running queries starving the single worker under load, unexpected thread interactions).
- PyPI package `neosqlite` — consumed from PyPI, version pinned in `uv.lock` (1.17.1); the local working copy at `../neosqlite/` is no longer needed at runtime and only remains whitelisted for spike reproduction (`tools/spikes/`).
- The database file lives on a persistent volume; never on container scratch (spec §19.2). WAL is the engine default. Concurrent Gunicorn workers each hold their own `Connection` to the same file — readers proceed under WAL, writers serialize at the file level.

### 5.2 Collections (documents are `TypedDict`-typed in code)

| Collection | Fields |
|---|---|
| `members` | display_name (unique), email, password_hash, security_question_code, security_answer_hash, active=True, administrator=False, publisher=False |
| `articles` | title, subtitle, body (markup), cover_url, author (display name), created (ISO 8601 string), tags: list[str], status: `draft`\|`published` |
| `comments` | text (markup), author (display name), article_id (hex string of the article `_id`), created (ISO string) |
| `objects` | GridFS-style registry: id, stored filename, length, chunk_size, upload_date, checksum, metadata {owner, original_filename, alt_text, upload_time, content_type} |
| `chunks` | binary payloads referenced by `objects` (GridFS contract) |
| `meta` | key–value: `content_version` counter (cache versioning), bookkeeping |

ISO 8601 timestamps sort correctly as strings in SQLite; date-keyed indexes therefore index the raw string — no type coercion needed (verify in Spike S2).

### 5.3 Queries that must run inside the engine (spec §14 "Database efficiency")

- Feed listing + count in **one round trip**: aggregation `$match` → `$sort` → `$facet`/`$group` combined pipeline.
- Article page: article + active-member comments in one joined query (`$lookup`, or equivalent supported by the engine).
- Related tags: `$match` (published, tag present, visibility filter) → `$unwind` tags → `$group` co-occurrence count → `$sort` → `$limit` 10, excluding the current tag — single pipeline, no application-side loops (spec §8).
- Dashboard statistics: minimal round trips via grouped pipelines (spec §11.1).

### 5.4 Indexes (declared at connection time, idempotent — spec §12.2)

- `articles`: created, author, tags, cover_url, status; compound `(status, created desc)`; compound `(author, status, created desc)`.
- `comments`: created, article_id, author; compound `(article_id, created desc)`.
- `members`: **unique** on display_name; index on email; index on `(administrator, publisher, active)` role-flag tuple.
- Full-text: per-field FTS indexes on article title, subtitle, body (§6).

### 5.5 Image objects (spec §10)

Storage follows the GridFS contract (registry + chunked payload); NeoSQLite ships a modern `GridFSBucket` API plus legacy `GridFS` compatibility — use it directly rather than hand-rolling chunking. API notes verified by Spike S3: construct the bucket on the **raw sqlite handle** (`GridFSBucket(conn.db)`; engines' `Connection` object itself is not accepted), tables materialize as `fs_files`/`fs_chunks`, chunk rows link via the internal integer `fs_files.id`, checksums arrive in the `md5` field (ETag source for spec §10.4), metadata round-trips as a dict, and `GridOut`-style cursors iterate with plain `list()` (no `.to_list()`).

### 5.6 Blocking-work policy

- All database work runs through the single-thread DB executor via the repository facade (§5.1) — never ad-hoc `asyncio.to_thread` calls against the raw `Connection`, so ordering and write serialization stay predictable.
- Pillow image conversion/decoding is CPU-bound → always run via a **separate** executor (or TaskGroup offload); a big conversion must not queue behind DB work.
- Nothing blocking may run inside an `async def` route directly.

### 5.7 Automatic backfills at startup (spec §19.6)

Idempotent, at every start: articles missing `tags` → `[]`; articles missing `status` → infer/set; first-member promotion; single-administrator publisher self-heal. No migration framework in v1; standalone CLI scripts for exceptional conversions (legacy ID migration, metadata backfill, admin repair) and member management (`neoblogger.cli.users`) under `cli/`.

### 5.8 Library verification checklist (spikes — EXECUTED 2026-10-02, all passed)

Executed against the local NeoSQLite working copy on the Fedora 44 workstation (same distro as the container base). Scripts live in `tools/spikes/` (`spike_s1.py`…`spike_s5.py`; run with `PYTHONPATH=/home/cwt/Projects/neosqlite python3 spike_sN.py`). Results:

- **S1 — executor facade sanity: PASS (12 checks).** Connection opened on the executor thread; WAL default; 3 000-doc bulk insert 0.05 s; 200 concurrent facade tasks at 1 741 ops/s with zero faults; find latency p50 0.1 ms / p95 0.4 ms; GridFS 2 MB round trip 7 ms. Two contract rules discovered and recorded: (a) nested executor submits deadlock (S1-4b, negative test) → event-loop-only submits; (b) `check_same_thread=False` works for a main-thread-created connection.
- **S2 — aggregations: PASS (8 checks).** Feed + count in one `$facet` round trip (3.3 ms); `$lookup` article+comments join verified; related-tags pipeline ($match → $unwind → $group → $sort → $limit) matches Python-computed ground truth; dashboard `$facet`; standalone `$count`; ISO-string pagination truth. Findings recorded as ID policy above (ObjectId stringification; hex-string linkage; pipeline-style `$lookup` unsupported — not needed).
- **S3 — GridFS: PASS (14 checks).** Multi-chunk upload (3.5 MB @ 256 KiB), md5 checksum equals hashlib, metadata subdocument round-trips, metadata-filtered find, `upload_from_stream_with_id` + rename + delete-by-name, legacy `GridFS` OK. API trap recorded: bucket must be built on `conn.db`.
- **S4 — indexes & tokenizer: PASS (11 checks).** Single/compound/nested + unique index (duplicate rejected with `sqlite3.IntegrityError` naming the index); default FTS + `$text` works; **real ICU tokenizer** (`fts5-icu v7.1.1` prebuilt `.so`) loaded via the engine's `tokenizers=[("icu", path)]` kwarg — implicit entrypoint derivation from the file name works; Thai and Chinese `$text` queries match after segmentation; per-locale `icu_th` library verified. Findings: missing tokenizer `.so` raises `sqlite3.OperationalError` at connect → app-owned fallback (catch, warn, reconnect without tokenizer) implements spec §12.2; two-word `TOKENIZE=icu th` clause unsupported (upstream quoting fix possible) → v1 config uses single-name tokenizers only.
- **S5 — platform: PASS (9 checks).** Fedora 44 host: Python 3.14.7, SQLite 3.51.2 with FTS5 + extension loading verified by behavior, libicu 77.1 (+devel), zig 0.16.0, ICU `.so` loadable on the stdlib `sqlite3` module.
- **S6 — boolean round-trip (app-side probe, 2026-10-02):** `insert_one` preserves Python `bool`; **`$set` stores booleans as integers** (`True` reads back `1`); queries with `True`/`False` match stored values correctly in both cases. Consequence: repositories normalize boolean fields to `bool` at the read boundary, exactly like the `_id` hex-string policy (§5.1).
- **S7 — visibility coherence (implementation finding, 2026-10-02):** feed/search visibility (spec §13) needs member flags against article-author *names*; pipeline joins are unsupported, so articles and comments carry **denormalized author-state snapshots** (`author_active`, `author_publisher`, `author_active` on comments): stamped inside the atomic save work unit, resynced on every role/account toggle (§11.2), recomputed idempotently at startup (§19.6). Feed/search filters stay single-round-trip indexed matches (§14). First-member promotion and uniqueness checks run inside the same executor work unit as the insert — check-then-write across separate units is racy.
- **S8 — read-boundary round-trip is asymmetric (implementation finding, 2026-10-03):** `find()`/`find_one()` return `_id` (and hex-string-shaped ordinary values) as **`ObjectId` instances** even when the app stored plain hex strings — so *every* repository read must apply the §5.1 normalization (`document_id` + boolean coercion), not just the insert path. A missing normalization silently poisoned linkage fields with ObjectId instances, which then broke equality (the exact S2 trap). Corollary confirmed: `delete_many`/`update_many` with hex-string linkage keys work only when the stored linkage values are hex strings.

**Deferred to the fallback route only (do not spike unless adopted):** NX-27017 wire-route verification (PyMongo `AsyncMongoClient` interop; the server's start command and loopback binding). The wire route is referenced in A4 and §5.1 as the contingency.

---

## 6. Full-text search

- FTS indexes on title, subtitle, body, each with a **pluggable tokenizer** (spec §12.2). Target tokenizer: **ICU-based segmentation** (Thai/CJK capable) — candidate source: the `fts5-icu-tokenizer` extension project; compiled into the container image (spec §19.3).
- If the configured tokenizer cannot load at startup: log a warning, fall back to the default tokenizer; never fail boot (spec §12.2).
- If the FTS index is unavailable at query time: fall back to case-insensitive substring match across title/subtitle/body (spec §9).
- Ranking: engine's relevance ordering over the three field indexes.
- Admin-triggered **full index rebuild** (title/subtitle/body) in the admin panel, required after tokenizer changes (spec §11.4).
- Query validation (spec §9) as a dedicated, unit-tested service: reject URLs, markup/script tags, code/shell patterns, file paths, and excessive special-character proportion in longer input; on rejection flash "please use only text" and redirect home.

---

## 7. Content pipeline

- **Parsing**: `markdown-it-py` (CommonMark), with tables enabled.
- **Sanitization**: every rendered fragment passes through **nh3** with an explicit allowlist — elements (headings, p, em/strong, ul/ol/li, a, img, table/thead/tbody/tr/th/td, pre, code, blockquote, hr, br, span) and safe attributes (href, src, alt, title, class limited to code-language classes). Inline CSS is completely disallowed (the style property allowlist is empty, stripping all `style` attributes) for defense-in-depth and CSP compatibility. Raw user HTML must never bypass the pipeline (spec §15.3).
- **Syntax highlighting**: **Pygments** server-side into `<pre>` blocks; CSS self-hosted; a copy button attached per block by a small vanilla-JS module (spec §6).
- **Links**: relative URLs allowed; `rel="noopener noreferrer"` added to external targets during sanitization.
- **Markdown editor**: vendored EasyMDE (toolbar, live preview) for the article body; a minimal lightweight toolbar for comments (same pipeline, smaller button set). The editor's image button uploads via `fetch` to the image endpoint and inserts the returned URL at the cursor (spec §5.1, §10.1).
- **Cover picker**: the editor's cover field offers the member's recent uploads (48) in a collapsible thumbnail gallery; one click fills the field, and without JS the printed URLs are copied by hand (spec §5.1).
- All editor/JS libraries are vendored into `web/static/` — no runtime CDN dependency; CSP stays `self` (§12.1).

---

## 8. Sessions, authentication, CSRF

- **Password hashing**: Argon2id (`argon2-cffi`), parameters at least the library defaults, recorded in the hash string; plaintext never stored or logged (spec §4.1, §15.1).
- **Security answer**: normalized to lowercase, hashed with Argon2id as well; never displayed back (spec §4.1).
- **Sessions**: signed cookie (`itsdangerous` URL-safe serializer) with payload `{member_id, session_version, csrf_token}`; `max_age` 24 h **sliding** — re-signed on every authenticated response; `HttpOnly`, `SameSite=Lax`, `Secure` when production flag is set (spec §4.3). `session_version` is tracked on the member document and incremented on credential rotation (password recovery and profile updates), invalidating existing sessions.
- Sign-out clears the cookie and clears/bumps the response cache (spec §4.3).
- **CSRF**: per-session random token (stored inside the signed cookie payload); rendered as a hidden input in every mutating form and as `<meta name="csrf-token">` for client scripts; enforced by middleware on all POST/PUT/DELETE (spec §15.2).
- Password recovery: explicit "no account found" message retained (accepted trade-off, spec Appendix B D2) **plus** rate limiting (§4). Disabled accounts cannot recover via this flow.

---

## 9. Images

- **Upload**: extension allowlist (jpg/jpeg/png/webp/gif) **plus** content decoding verification (Pillow must actually decode; spoofing rejected); request body cap from config (default 16 MB, enforced at both server and app level) (spec §10.2, §15.6).
- **Conversion at save time**: convert to **WebP, quality 85**; transparency flattened onto white; stored payload is the converted one (spec §10.2).
- **Stored filename**: `owner_displayname + "_" + sanitized_original_name + "_" + random_suffix` (spec §10.2).
- **Registry metadata**: owner, original filename, **alt text seeded from the original filename**, upload time, content type (spec §10.2).
- **Serving route** `/images/{id}.{ext}`: public (no login); `Cache-Control` max-age 1 year, `ETag` (from checksum), `Last-Modified`; conditional `304` support (spec §10.4).
- **Legacy variant**: requesting `.jpg`/`.png` triggers on-the-fly conversion of the stored WebP (flattened white, conversion capped at ~20 MB objects), same caching policy; used for link-preview scrapers and emitted in preview metadata (spec §10.4, §16).
- **Gallery**: 12 per page; inline alt-text editing via a dedicated authorized request (owner or admin) that only touches alt text (spec §10.3); members see own images, admins see all labeled with owner.
- **Deletion guard**: owner or admin may delete **unless** the object is a current article cover → conflict response listing the using articles (spec §10.5). Automated-tested (spec §20).

---

## 10. Frontend

- Server-rendered Jinja2; **Pico CSS vendored** + a small custom layer (`custom.css`) providing the typographic identity, card/feed design, banner backgrounds, and size-matched font-fallback stack (spec §17).
- Vanilla JS ES modules, no bundler: nav collapse, back-to-top (IntersectionObserver), copy-to-clipboard with visual feedback, `<dialog>`-based confirmation modals, editor wiring, alt-text inline save.
- Progressive enhancement: every function works without JS where feasible (forms fall back to full-page posts).
- **Accessibility**: alt text everywhere, accessible names on icon-only controls, sequential heading hierarchy, visible focus, contrast — audited to ≥ 95/100 (spec §17, §20).
- Performance practices: explicit `width`/`height` on feed images, lazy-loading except first card, high fetch-priority cover on article pages, per-page banner preload hints (spec §6).
- Fonts: self-hosted woff2 with `font-display` swap and size-matched fallback definitions to avoid CLS (spec §17). Exact typeface pairing is a pending design decision (see §19 Open items).
- **Theme artwork (deploy-time, optional)**: one 21:9 banner per page family (home, article, tag, search, auth, profile, write, upload, admin, error), generated once with Agnes Image 2.5 by `neoblogger.cli.theme generate` (key from `AGNES_API_KEY` env or `./.env`, never committed; in containers via `podman run --rm -v ... -e AGNES_API_KEY=... --entrypoint neoblogger-theme` or `podman exec`) and stored as ordinary `theme`-owned image objects; the app resolves the set once at startup and serves it through `/images/`, so runtime stays offline. Without a generated set every page renders the themeless default. An article's own cover wins over its page banner. Output ownership (operator, Agnes ToS §8.1) is recorded in `THIRD-PARTY-LICENSES.md`; the footer credit satisfies the §6.1 AI-content disclosure whenever a theme is active.

---

## 11. Caching and performance

- **Response cache** (optional, config-gated): rendered anonymous-visitor pages keyed by `(path, page, per_page, global_content_version)`; any content change (article CRUD, comment add/delete, account/role change, sign-out) bumps `meta.content_version` or deletes affected keys (spec §14).
- Storage modes: `memory` (default) or `file` (multi-worker coherence; directory on persistent volume). Configurable expiry (default 300 s), size cap (default 100 MB), oldest-eviction, opportunistic sweeping; cache failures logged, never fatal (spec §14).
- Signed-in responses are never served from cache and carry `Cache-Control: no-store`; search and tag responses explicitly no-cache (spec §14).
- **Pre-warm** home-feed page 1 for anonymous visitors in each worker at fork time (spec §14, §19.4).
- **HTML minification**: conservative post-render whitespace trimming that preserves single blank lines and `<pre>`/`<code>` content (spec §14).
- Feed/listing queries run as single-round-trip aggregations (§5.3); hot paths covered by §5.4 indexes.

---

## 12. Security hardening

Response headers on every response (spec §15.4):

| Header | Value |
|---|---|
| `Content-Security-Policy` | `default-src 'self'; script-src 'self' 'nonce-<request-nonce>'; style-src 'self'; img-src 'self' data: blob: https:; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'` (W3C CSP Level 2/3 does not exempt `<script type="application/ld+json">` from `script-src`; a per-request nonce permits the JSON-LD block) |
| `X-Content-Type-Options` | `nosniff` |
| `X-XSS-Protection` | `1; mode=block` (legacy filter, per spec) |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains; preload` (production) |
| `Cross-Origin-Opener-Policy` | `same-origin` |

Also: CSRF enforcement (§8), upload hardening (§9), per-request member re-resolution (§3.3), proxy-trust rules (§4), sign-in and recovery rate limiting (§4), session invalidation on credential rotation via `session_version` (§8), mandatory production secret (§3.4).

---

## 13. SEO and social sharing

- Canonical link on every page from configured `base_url` (trailing-slash normalized), falling back to the request URL (spec §16).
- Article pages: description (derived from body text), author meta, keywords = tags, published-time, Open Graph article metadata with cover image — **preview metadata references the legacy-format image variant** (spec §16).
- JSON-LD structured data: Article schema on article pages (headline, author, date, description, cover, keywords, site as publisher organization with logo); WebSite schema elsewhere (spec §16).
- Dynamic `/sitemap.xml` (publicly visible articles + home, last-modified dates) and `/robots.txt` advertising the absolute sitemap URL (spec §16); footer links to the sitemap.
- Readable dates: "Month DD, YYYY at HH:MM", date-only at midnight (spec §16).

---

## 14. Configuration (TOML)

Location from env `NEOBLOGGER_CONFIG` (essential for container volumes); defaults for every omitted key; missing values never crash (spec §18). A **missing or unreadable configuration file is a fault, not a silent default** (recorded 2026-10-02): a lost volume mount must fail loudly rather than boot with defaults — silently booting with `https=false` and an empty secret would look like a passing deployment while it is unsafe. Example skeleton:

```toml
[application]
secret_key = ""          # REQUIRED in production; generated by CLI script
bind = "0.0.0.0"
port = 8000
site_title = "Neo-Blogger"
site_author = ""
site_description = ""
base_url = ""            # https://example.com/ — normalized with trailing slash
https = false            # production flag: Secure cookies + HSTS (must be true in production even when TLS terminates at proxy)

[database]
path = "neo-blogger.db"
tokenizer = ""           # optional tokenizer name; empty = default.
                         # single name only in v1 (e.g. "icu", "icu_th") —
                         # two-word locale-override form unsupported (Spike S4)
tokenizer_library = ""   # optional .so path; missing file = app-owned fallback (§12.2)

[caching]
enabled = false
timeout_seconds = 300
storage = "memory"       # "memory" | "file"
directory = "cache"
max_size_mb = 100

[posts]
per_page = 10
max_per_page = 50

[uploads]
max_body_bytes = 16777216

[proxy]
trusted_proxies = ["127.0.0.1", "::1"]  # adjacent hops whose X-Forwarded-* headers are honored (§4, §15.8)
```

A CLI script generates a strong random `secret_key` (`secrets.token_urlsafe(32)`); the procedure is documented (spec §15.9).

---

## 15. Deployment and operations

1. **Runtime shape**: rootless Podman container on a RHEL-based host; Gunicorn + Uvicorn worker running the Quart app; `--workers N` (small count); `--max-requests` bounded recycling + jitter; `post_fork` hook pre-warms per-worker state (spec §19.1, §19.4).
2. **Container image** (`Containerfile`, base `fedora:44`): install Python ≥ 3.14 + libicu; compile the FTS ICU tokenizer extension into the image; install Pillow-enabled image support so uploads/conversions work out of the box (spec §19.3). Reproducible build (pinned dnf packages + lockfile).
3. **Single-process container**: the Quart app (Gunicorn + Uvicorn worker) is the only process — no wire-protocol server to supervise, no readiness wait, no inter-process trap. Entrypoint `exec`s Gunicorn with signal forwarding for clean shutdown; `/healthz` used by the Podman healthcheck (spec §19).
4. **Volumes** (persistent, never scratch): database file (+WAL) and, when used, the file-cache directory (spec §19.2). RHEL/SELinux: volumes labeled for container use (`:Z` or `container_file_t`). The container runtime sets `WORKDIR /data` so relative paths (`neo-blogger.db`, `cache/`) resolve onto the persistent volume.
5. **Rootless specifics**: app binds an unprivileged port (8000) inside the container; host TLS termination by the existing reverse proxy (nginx/Caddy on the metal); `PublishPort 127.0.0.1:8000:8000`. Even though TLS terminates at the reverse proxy, production installations must set `https = true` in the configuration so session cookies receive the `Secure` attribute and HSTS headers are emitted.
6. **systemd Quadlet**: `~/.config/containers/systemd/neo-blogger.container` user unit for rootless autostart/restart; documented in the deployment guide.
7. **Observability**: access logs (with request duration) and error logs to stdout at info level; errors logged with full traces, users see branded pages only (spec §19.5).
8. **Platform portability**: no platform-specific service as a hard requirement; VPS + proxy and container-platforms-with-volumes both supported (spec §19.7).

---

## 16. Quality gates

- **Tests** (offline, runnable, must pass — spec §20): `pytest` + `pytest-asyncio`; Quart test client for web-level tests; a real NeoSQLite instance (temp DB file) for repository/e2e tests. Minimum coverage: search-input protections, visibility rules (§13 of functional spec), draft lifecycle, image deletion guard; E2E for register → write → publish → comment → search → moderate.
- **Static quality (hard gate)**: `ruff check` + `ruff format --check`; `mypy --strict` over `app/` and `cli/` (templates excluded); `py.typed` shipped.
- **Performance/SEO budgets** (spec §20): Lighthouse — Performance ≥ 85, Accessibility ≥ 95, Best Practices ≥ 95, SEO = 100.
- **Robustness**: every failure path flashes a human-readable message and redirects sensibly; cache/tokenizer failures degrade gracefully (spec §20).

---

## 17. Dependency manifest

Runtime (versions pinned in lockfile at implementation time):

| Package | Role |
|---|---|
| `quart` | async web framework |
| `gunicorn` + `uvicorn` | production process manager + ASGI worker |
| `hypercorn` | development ASGI server |
| `pymongo` + `nx-27017` | **fallback only** — wire-route contingency (A4); NOT installed in the v1 runtime image |
| `neosqlite` | embedded document DB engine (direct, in-process) |
| `markdown-it-py` | CommonMark parser |
| `nh3` | HTML sanitizer (allowlist) |
| `pygments` | syntax highlighting |
| `pillow` | image decode/convert (WebP) |
| `argon2-cffi` | Argon2id hashing |
| `itsdangerous` | signed session cookies |

Standard library roles: `tomllib` (config), `secrets` (tokens/keys), `hashlib` (checksums/ETags), `zipfile`-free — no others required for v1.

Dev: `pytest`, `pytest-asyncio`, `ruff`, `mypy`, lockfile tooling.

### 17.1 License inventory (verified 2026-10-02 — project may be MIT)

Verified against current upstream data (vendor notices, PyPI/GitHub metadata). Verdict: **every runtime and build dependency is MIT-compatible; no GPL/AGPL/SSPL code enters the image**.

**Clean-room provenance (2026-10-02).** This rebuild exists to avoid license contamination: the author's previous blogging platform tree (`../neo-bloggy/`) is license-encumbered and is **permanently excluded from local research** — it must never be opened, read, searched, copied, or explored by any agent or tool in this project. The local-research whitelist is exactly `../neosqlite/` and `../fts5-icu-tokenizer/` (AGENTS.md §3). All functional truth for this build derives from `docs/requirements.md` alone; any spec reference to a "reference implementation" is implemented from the spec text only.

| Component | License |
|---|---|
| neosqlite, nx-27017, quart, hypercorn, gunicorn, markdown-it-py, nh3 (+ammonia dual), ruff, mypy, Pico CSS, EasyMDE, fts5-icu-tokenizer, pygments (BSD-2), argon2-cffi(-bindings) | MIT |
| IBM Plex fonts (Sans, Mono, Sans Thai Looped, Sans Hebrew/Arabic/Devanagari/JP/KR/SC/TC) | SIL Open Font License 1.1 |
| pymongo | Apache-2.0 |
| uvicorn, itsdangerous, pytest-dev (pytest: MIT; pytest-asyncio: Apache-2.0) | BSD-3 / Apache-2.0 |
| cffi | MIT-0 |
| pillow | MIT-CMU (HPND) |
| Python stdlib + interpreter | PSF-2.0 |
| SQLite | Public domain |
| ICU (libicu) | ICU License (MIT-equivalent, OSI-approved) |
| Unicode data files | Unicode License v3 / Unicode-TOU (permissive) |
| Zig toolchain (build-time only) | MIT (Expat) |

Vendored assets (Pico CSS, EasyMDE) and any shipped/system ICU libraries require attribution: ship a `THIRD-PARTY-LICENSES`/`NOTICE` bundle in the repo and container image. The SSPL trap is avoided by construction — the MongoDB *server* (SSPL/AGPL) is never shipped; NX-27017 replaces it entirely.

---

## 18. Traceability (functional spec → this document)

| Functional § | Technical § |
|---|---|
| 3 (pages), 6 (reading) | §4, §10 |
| 4 (accounts) | §8 |
| 5 (writing) | §7, §10 |
| 8 (tags), 9 (search) | §6 |
| 10 (images) | §9 |
| 11 (moderation) | §5.3, §4 |
| 12 (data model) | §5 |
| 13 (visibility) | §3.3, services layer |
| 14 (caching/perf) | §11 |
| 15 (security) | §12, §8, §9 |
| 16 (SEO) | §13 |
| 17 (a11y/responsive) | §10 |
| 18 (config) | §14 |
| 19 (deployment) | §15 |
| 20 (quality) | §16 |

---

## 19. Open items (decisions still pending)

1. **Typeface pairing** (§10) — **DECIDED 2026-10-04: IBM Plex family** per user directive. Sans (Latin/Cyrillic/Greek), Mono (code), Sans Thai Looped, plus Sans Hebrew/Arabic/Devanagari/SC/TC/JP/KR per the site's language coverage (§12.2 scripts). Self-hosted woff2, `font-display: swap`; **conditional loading is native**: per-script families carry only their native-block unicode-range faces (GF subsets dropped for those families), IBM SC/TC come from `@ibm/plex-sans-sc|tc` npm split webfonts (Google Fonts does not host them); `tools/fetch_fonts.py` re-vendors. A page never downloads a script's faces unless the page renders characters inside their ranges. Default CJK order favors Simplified Chinese; `html[lang=ja|zh-Hant|ko]` overrides re-order the stack. Weight axis: Plex Sans is variable on GF (one file covers 100-700). OFL noted in §17.1 and `THIRD-PARTY-LICENSES.md`.
2. **Security-question list** — **DECIDED 2026-10-02: seven codes** (`first-pet`, `elementary-school`, `birth-city`, `mothers-maiden-name`, `favorite-book`, `favorite-food`, `first-car`): the Appendix A count (7) wins over the eight-item parenthetical in §4.1; `favorite-sport` is the dropped candidate.
2. **Article URL shape** — **DECIDED 2026-10-02: identifier-based**. Public article URLs carry the opaque document id (`/{article-id}`), per S2-verified query support and the safe-default rationale. No slug column in v1; slug support may be layered on later as a backward-compatible addition without touching linkage fields.
3. ~~**Confirm NeoSQLite capabilities** via spikes S1–S5 (§5.8)~~ — **DONE 2026-10-02, all passed**; discovered constraints and the data-model ID policy are recorded in §5.1/§5.5/§5.8. The NX-27017/PyMongo route stays as the documented contingency if the executor facade proves inadequate.
4. **Lighthouse verification tooling** for the CI runner (headless Chrome availability on the build host).
5. **Upstream metadata nit**: `neosqlite/__init__.py` reports `__version__ = 1.5.0` while `pyproject.toml` is at 1.17.1 (stale constant — harmless at runtime; report/fix upstream when convenient).
6. **Inline CSS policy** (§7) — **DECIDED 2026-10-12: completely disallowed**. Rendered user markup strips all `style` attributes via an empty nh3 style allowlist; deny-by-default eliminates style-injection and CSS-based data exfiltration vectors while keeping CSP strict (`'self'`).
7. **Admin draft visibility scope on discovery pages** (§13, Appendix B D3) — **DECIDED 2026-10-12**: Per spec §13 and Appendix B D3, search results for administrators omit drafts to preserve relevance ordering (drafts surface in the dedicated `/admin/unpublished` review view per D3), while tag pages retain administrator draft visibility per §13.
8. **CLI operator management powers** (§11.2, CLI) — **DECIDED 2026-10-12**: The `neoblogger-users` CLI tool is an out-of-band host operator tool, not subject to the peer-administrator constraints of the web UI (§11.2). Operators may demote or disable non-sole administrators from the CLI, but the sole-administrator invariant is strictly enforced across all surfaces.
