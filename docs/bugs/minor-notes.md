---
type: lessons_learned
title: "Minor notes (style and hardening, unnumbered)"
description: "Additional style, hardening, and operational observations from the deep codebase audit."
status: stable
sources:
  - neoblogger/app/wiring.py
  - neoblogger/app/blueprints/images.py
  - neoblogger/app/services/articles.py
  - gunicorn.conf.py
verified: machine-confirmed
tags: [bugs, style, hardening, notes]
timestamp: 2026-10-16T09:30:00Z
---

# Minor notes (style and hardening, unnumbered)

Observations kept alongside the [bug tracker](index.md) that do not warrant separate numbered bug entries:

- **Anonymous CSRF cookie is unsigned (`neoblogger/app/wiring.py:273-286`):**
  Authenticated sessions store the CSRF token inside the `itsdangerous`-signed `neoblogger_session` cookie, whereas anonymous forms (`/signin`, `/signup`, `/recover`) use a raw unsigned `neoblogger_csrf` double-submit cookie. Signing or binding the anonymous CSRF token with `SessionCodec` (or an HMAC) prevents cookie-tossing from sibling subdomains on shared parent domains.
- **`POST /signout` omits `Cache-Control: no-store` (`neoblogger/app/wiring.py:342-358`):**
  In `_finalize()`, `Cache-Control: no-store` is only set in the `elif getattr(g, "set_session_cookie", None):` and `elif member is not None and session is not None:` branches. Because `drop_session()` clears `g.member` and `g.session`, the sign-out redirect response does not receive `Cache-Control: no-store`.
- **`Last-Modified` header assumes naive `upload_time` is GMT (`neoblogger/app/blueprints/images.py:198-204`):**
  `ObjectsService.upload()` records `datetime.datetime.now().isoformat(timespec="seconds")` (local naive time), while `_http_date()` formats it with `"%a, %d %b %Y %H:%M:%S GMT"`. Using `datetime.now(UTC)` (or `email.utils.format_datetime(..., usegmt=True)`) ensures RFC 9110-compliant UTC timestamps regardless of host timezone.
- **On-the-fly legacy image conversion (`neoblogger/app/blueprints/images.py:140-149`) is uncached:**
  Requesting `/images/<id>.jpg` or `.png` decodes the stored WebP and re-encodes JPEG/PNG via Pillow on every request that does not send a matching `If-None-Match` ETag (e.g., social preview crawlers from multiple IPs).
- **Tag deduplication in `_parse_tags()` (`neoblogger/app/services/articles.py:17-24`):**
  Uses `if tag and tag not in tags:` ($O(T^2)$ list membership check); `list(dict.fromkeys(t for e in raw.split(",") if (t := e.strip())))` is $O(T)$ and preserves insertion order.
- **`gunicorn.conf.py` worker class (`gunicorn.conf.py:4`):**
  Uses `worker_class = "uvicorn.workers.UvicornWorker"`. Since `Containerfile:38` installs `uvicorn-worker`, `uvicorn_worker.UvicornWorker` is the canonical non-deprecated import path in `uvicorn >= 0.30`.
