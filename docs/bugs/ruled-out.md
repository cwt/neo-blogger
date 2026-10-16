---
type: lessons_learned
title: "Investigated and ruled out (not bugs)"
description: "Areas inspected during the deep codebase audit and confirmed sound."
status: stable
sources:
  - neoblogger/app/wiring.py
  - neoblogger/app/repositories/db.py
  - neoblogger/app/repositories/members.py
  - neoblogger/app/repositories/objects.py
  - neoblogger/app/text/sanitize.py
verified: machine-confirmed
tags: [bugs, audit, false-positive, lessons-learned]
timestamp: 2026-10-16T09:30:00Z
---

# Investigated and ruled out (not bugs)

Checked during the source-level audit and confirmed **not** to be defects, so excluded from the numbered [bug tracker](index.md).

| Concern | Result |
|---|---|
| `ensure_theme_banners()` (`neoblogger/app/wiring.py:88-102`) querying the database on every request when no theme is installed | **Not a bug.** `context.theme_banners` starts as `None`; on the first call with no theme banners, it is assigned `{}` (an empty `dict`, which is not `None`), so `if context.theme_banners is None:` only runs once per worker lifecycle. |
| PEP 758 unparenthesized `except TypeError, ValueError:` syntax in `hashing.py:27`, `sessions.py:61`, and `images.py:202` | **Not a bug.** Valid Python 3.14 syntax (PEP 758), explicitly mandated by [Technical Requirements](../technical-requirements.md) §2 and formatted by `ruff format`. |
| Concurrent first-member registration race in `MemberRepository.create_first_or_member()` (`neoblogger/app/repositories/members.py:73-121`) | **Not a bug.** Uniqueness checks, `count_documents({}) == 0`, insert, and post-insert earliest-`_id` verification all execute inside a single work unit on the `max_workers=1` DB executor. |
| TOCTOU race between checking object existence and downloading in `ObjectRepository.data()` (`neoblogger/app/repositories/objects.py:52-67`) | **Not a bug.** Handled via a single `download_to_stream` call catching `NoFile` inside one executor work unit. |
| Nested executor deadlock (`ThreadPoolExecutor(max_workers=1)`) across repository methods | **Not a bug.** All repository methods submit work from the event loop only (`await self._database.run(...)`); no repository callback invokes `self._database.run()` from inside executor work. |
| XSS via raw HTML or inline `style` attributes in Markdown articles and comments (`neoblogger/app/text/markdown.py`, `neoblogger/app/text/sanitize.py`) | **Not a bug.** `MarkdownIt("default", {"html": False})` escapes raw HTML before `nh3.clean()` applies strict tag/attribute/scheme allowlists and strips `script`/`style` content and all `style` attributes. |
| Stale cookie from a disabled account clearing the shared anonymous `ResponseCache` (`neoblogger/app/wiring.py:266-269, 342-348`) | **Not a bug.** Stale-cookie cleanup sets `g.destroy_session_cookie = True` without setting `g.clear_response_cache = True`, so only explicit `POST /signout` clears the cache (covered by `test_stale_session_keeps_response_cache`). |
