---
type: index
title: "Bug Tracker — Neo-Blogger"
description: "One file per bug (#1–#24) covering functional bugs, security/validation gaps, unoptimized algorithms, dead code, and duplication, plus ruled-out concerns and verification."
status: draft
sources:
  - docs/bugs/
  - docs/requirements.md
  - docs/technical-requirements.md
verified: machine-confirmed
tags: [bugs, tracker, index, issues, audit]
timestamp: 2026-10-16T09:30:00Z
---

# Bugs — Neo-Blogger

Deep source-level audit findings for Neo-Blogger (Python 3.14 / Quart / NeoSQLite), cross-referenced against [Functional Requirements](../requirements.md) and [Technical Requirements](../technical-requirements.md). Each finding is documented in its own file (`001.md`–`024.md`) with root-cause analysis, code references, impact, and suggested fix.

- [Investigated and ruled out (not bugs)](ruled-out.md)
- [Verification history](verification.md)
- [Minor notes (style and hardening, unnumbered)](minor-notes.md)

## Severity legend

- **HIGH** — correctness, concurrency/event-loop blocking, data-integrity, or security validation defect that degrades availability or corrupts state/metadata under realistic conditions.
- **MEDIUM** — functional specification gap, edge-case flaw, deployment reproducibility issue, or algorithmic bottleneck with measurable runtime cost.
- **LOW** — minor algorithmic inefficiency, dead code, or unfactored duplication with maintenance impact.

## Summary by category and severity

| Category | Bugs | Severity | Status |
|---|---|---|---|
| Concurrency, Data Integrity, Validation & SEO Bugs | [#1](001.md)–[#5](005.md) | HIGH | Open |
| Caching, Auth, CLI, Spec UI/SEO & Deployment Bugs | [#6](006.md)–[#12](012.md) | MEDIUM | Open |
| Unoptimized Algorithms & Database Bottlenecks | [#13](013.md)–[#16](016.md) | MEDIUM | Open |
| Minor Algorithmic & Query Optimizations | [#17](017.md)–[#20](020.md) | LOW | Open |
| Dead Code & Duplicated Code | [#21](021.md)–[#24](024.md) | LOW | Open |

| Severity | Count |
|---|---:|
| HIGH | 5 |
| MEDIUM | 11 |
| LOW | 8 |
| **Total** | **24** |

## All Bugs

| # | Title | Category | Severity | Status |
|---|---|---|---|---|
| [1](001.md) | CPU-bound Argon2id hashing runs synchronously on the event loop | Bug / Concurrency | HIGH | Open |
| [2](002.md) | Re-drafting a published article and deleting it leaks orphaned comments; drafts accept comments | Bug / Data Integrity | HIGH | Open |
| [3](003.md) | Missing server-side input validation on articles, comments, cover URLs, and emails | Bug / Validation | HIGH | Open |
| [4](004.md) | Startup `backfill_author_snapshots` omits `comments.author_active` | Bug / Data Integrity | HIGH | Open |
| [5](005.md) | Broken `og:image` and JSON-LD image URL generation on article pages | Bug / SEO | HIGH | Open |
| [6](006.md) | File-backed `ResponseCache` runs blocking disk I/O on the event loop and skips startup cache clear | Bug / Caching | MEDIUM | Open |
| [7](007.md) | Deploy-time theme banners leak into the Admin Upload Gallery & Cover Picker and break `context.theme_banners` if deleted | Bug / Theme & Gallery | MEDIUM | Open |
| [8](008.md) | Password recovery double-counts rate limit attempts and misreports empty answer / password errors | Bug / Auth | MEDIUM | Fixed |
| [9](009.md) | `neoblogger-users set-role` can revoke `publisher` from the sole administrator | Bug / CLI Invariant | MEDIUM | Fixed |
| [10](010.md) | Missing UI and SEO elements required by specification (`<dialog>` modals, Copy-URL, comment toolbar, review link, total articles card, `keywords`/`article:tag`) | Bug / Spec Compliance | MEDIUM | Open |
| [11](011.md) | `Containerfile` ignores `uv.lock` in runtime stage and omits `LICENSE` / `THIRD-PARTY-LICENSES.md` | Bug / Deployment & License | MEDIUM | Open |
| [12](012.md) | Weak scalar validation in `config.py` accepts booleans as ints, non-positive limits, and unknown cache storage modes | Bug / Configuration | MEDIUM | Fixed |
| [13](013.md) | Listing queries, `/profile`, and `/sitemap.xml` fetch full article `body` content unnecessarily | Unoptimized Algorithm | MEDIUM | Open |
| [14](014.md) | Full-text search materializes up to 500 full documents in memory per query | Unoptimized Algorithm | MEDIUM | Open |
| [15](015.md) | Sequential DB executor round-trips on `/admin`, `/<article_id>`, `/tag/<name>`, and `/profile` | Unoptimized Algorithm | MEDIUM | Open |
| [16](016.md) | Missing database indexes on hot filter fields (`author_active`, `author_publisher`, `metadata.owner`) | Unoptimized Algorithm | MEDIUM | Open |
| [17](017.md) | `GridFSBucket` re-instantiated on every object store operation | Unoptimized Algorithm | LOW | Open |
| [18](018.md) | N+1 query in `neoblogger-users list --role author` | Unoptimized Algorithm | LOW | Fixed |
| [19](019.md) | $O(N)$ per-member `update_many` loop at startup in `backfill_author_snapshots` | Unoptimized Algorithm | LOW | Open |
| [20](020.md) | $O(N)$ linear scans on every `ResponseCache` memory access and eviction | Unoptimized Algorithm | LOW | Open |
| [21](021.md) | Dead repository methods in `ArticleRepository` and `MemberRepository` | Dead Code | LOW | Open |
| [22](022.md) | Dead service classes, methods, constants, and unused `poetry.lock` | Dead Code | LOW | Open |
| [23](023.md) | Unfactored code duplication across repositories, services, blueprints, and CLI | Duplicated Code | LOW | Open |
| [24](024.md) | Duplicated test fixtures and helpers across `tests/` (with missing rate-limiter reset) | Duplicated Code | LOW | Open |
