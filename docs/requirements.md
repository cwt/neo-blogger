# Requirements Specification — Clean-Slate Long-Form Publishing Platform

Status: seed specification for a from-scratch build. This document is intentionally written as a clean-room functional specification. It describes *what the platform does*, not *how it is implemented*. It deliberately avoids naming any product, library, framework, or service, and contains no sample code. Everything a builder needs to recreate the platform from zero must be derivable from this document alone.

---

## 1. Purpose and Vision

The product is a self-hosted, article-first publishing platform for amateur writers: people who want to read and share new perspectives on any topic without running a full-blown commercial service. The reading experience should resemble a long-form publishing site: a bold welcome banner, a card-based home feed with cover images, generous typography, tags, comments, and full-text search.

Three principles govern the whole specification:

1. **Standalone by design.** The platform must run from a single installation with no external database service, no third-party sign-in providers, and no dependency on any hosted backend. All state — accounts, articles, comments, and uploaded images — lives in one place that can be copied with a file copy.
2. **Small and readable.** The feature set is deliberately focused: accounts, writing, reading, commenting, discovery, image management, and light moderation. Anything not listed here is out of scope for version 1 (see Future Considerations).
3. **Safe by default.** All user-supplied content is treated as untrusted. Rendering, searching, uploading, and moderating must be built around explicit allowlists and server-side validation.

---

## 2. Users and Roles

The platform recognizes the following role concepts. Flags are stored per member; a member may hold several at once.

- **Visitor** — anyone browsing without signing in. Sees the public face of the site only.
- **Member** — a registered, signed-in person. Can write, comment, upload images, and manage their own profile.
- **Author** — any member who has written at least one article (not a stored flag; implied by content).
- **Publisher** — a member whose articles may appear in public surfaces (home feed, search, tags, site map). This is an *approval* gate, granted by an administrator. Any member can write immediately; only approved publishers reach the public feed.
- **Administrator** — a member who can moderate accounts and content, manage publisher status, and rebuild search indexes.
- **Disabled member** — a member whose account has been switched off by an administrator. Disabled members cannot sign in or act, and their content disappears from public view while remaining in storage for auditing.

Two seed rules make the system self-configuring:

- The **first member to register automatically becomes an administrator and a publisher**.
- If there is exactly one administrator and that administrator is not yet a publisher, the platform quietly grants publisher status to them at startup (self-healing for legacy data).

---

## 3. Page Inventory (narrative)

The site consists of the following page types. Every page shares a common frame: a fixed top navigation bar with the site logo, a search box, role-aware links, and a footer with social sharing links, a copyright line whose year updates automatically, and a link to the site map. Every page shows a breadcrumb trail beneath the banner. Every page carries a floating "back to top" button that appears after scrolling.

1. **Home feed** — welcome banner ("read and share new perspectives"), then a paginated list of article cards: cover image, title, subtitle, up to three tags with a "+N more" indicator, human-readable publication date, and author name.
2. **Article page** — a full-width cover banner (title, subtitle, author, date, tags) over a rendered article body, followed by the comment area.
3. **Sign-up page**, **sign-in page**, **password recovery page**.
4. **Profile page** — the member's own workspace: statistics cards, and one table listing drafts first (badged) then published articles, with edit and delete actions per row.
5. **Edit profile page**.
6. **Write/edit article page** — a rich plain-text editor.
7. **Upload image page** — a gallery of the member's uploaded images with inline alt-text editing.
8. **Tag page** — home-style feed filtered to one tag, with related-tag suggestions.
9. **Search results page** — home-style feed filtered by a query.
10. **Admin panel** and **unpublished articles review page**.
11. **Error pages** — friendly, branded pages for "not found", "access denied", and "server error"; users must never see raw stack traces.

---

## 4. Member Accounts

### 4.1 Registration

Sign-up collects: **email address**, **password**, **display name**, and a **security question with answer**. Rules:

- The email must be unique. If already registered, the visitor is told to sign in instead.
- The display name must be unique and is case-stable as typed; it is the public identity used on articles, comments, and profile links. It is **not changeable later** (see deviation note D1 in Appendix B), because articles and comments reference the author by this name.
- The password is stored only as a salted, iterated one-way hash from a well-established key-derivation scheme with a large iteration count. Plaintext passwords are never stored or logged.
- The security question is chosen from a fixed, predefined list of seven everyday questions (first pet, elementary school, birth city, mother's maiden name, favorite book, favorite food, first car, favorite sport). The answer is normalized to lowercase and stored as a salted one-way hash, never in plaintext and never redisplayed.
- On success the new member is signed in immediately (a persistent session is created), sees a success flash message, and is taken to their profile. If no administrator exists yet, they are promoted to administrator and publisher with a congratulatory notice.

### 4.2 Sign-in

Sign-in requires the email and password. Wrong combinations produce a single generic failure notice that does not reveal which field was wrong. A disabled account is refused with a "contact an administrator" notice. Successful sign-in creates a persistent session and lands on the member's profile.

### 4.3 Sessions and sign-out

- Sessions persist for **24 hours** and are refreshed on every request (sliding expiry).
- The session cookie must be `HttpOnly`, `SameSite=Lax`, and marked `Secure` in production; production mode is detected from configuration or environment (see Configuration).
- Every request re-resolves the current member from storage. If the account has been disabled or deleted meanwhile, the session is destroyed on the spot — a disabled member cannot keep acting with an old cookie.
- Sign-out clears all session data and, when caching is enabled, clears the response cache so no cached page can show a signed-in state to the next visitor.

### 4.4 Password recovery

A public recovery page asks for the email, then the previously chosen security question and its answer. If all three match (the stored answer is compared case-insensitively against the normalized input), the member sets a new password, which is hashed like any other. Disabled accounts may not recover access this way. Incorrect answers get a clear failure notice without leaking whether the email exists — wait, it does say "no account found with that email address" in the reference behavior; the new build should keep the explicit message but this is an accepted trade-off (deviation note D2). After a successful reset the member is sent to the sign-in page with a success notice.

### 4.5 Profile page

Profiles are **private to their owner**: signed-in members may view only their own profile; attempting to view another member's profile redirects with a notice. The profile shows:

- **Statistics cards**: number of published articles, number of drafts, total comments written, and a combined "contributions" figure (published + drafts + comments).
- **"Your Posts" table**: drafts listed first, each marked with a visible "Draft" badge, followed by published articles, newest first. Each row shows a thumbnail (or a "No image" placeholder), title with the "Draft" badge when applicable, subtitle when present, and the formatted timestamp. Each row offers **Edit** and **Delete**; deletion asks for confirmation in a modal dialog before performing it.

### 4.6 Profile editing

The edit page allows changing the email (uniqueness enforced against other members), setting a new password (optional), and re-entering a security question and answer (mandatory rotation each save, since answers are unreadable). The display name is not editable. Saving keeps the session alive and returns to the profile with a success notice.

---

## 5. Writing and Publishing

### 5.1 Creating an article

Only signed-in members can open the write page. The form contains:

- **Title** (required) and **Subtitle** (required).
- **Cover image URL** — optional while drafting, **required to publish**.
- **Body** — a long text field written in a lightweight plain-text formatting syntax supporting headings, emphasis, lists, links, images, tables, and fenced code blocks. The editing interface is a full toolbar editor with formatting buttons, live preview, and an **image button** that uploads a picture (see Image Management) and inserts its URL at the cursor.
- **Tags** — a single comma-separated field; whitespace is trimmed and empty entries dropped; stored as an array.
- Two submit actions: **Save as Draft** and **Publish**. Saving a draft keeps the member on their own profile flow; publishing redirects to the home feed with a success notice.

On save, the platform records the author (by display name), the current local timestamp (ISO format), the tag array, and the status (`draft` or `published`).

### 5.2 Drafts

- Drafts are never visible on the home feed, search results, tag pages, or the site map — to anyone except their author, who sees them badged at the top of their own profile.
- A draft may omit the cover image.
- To publish a draft, the author opens it in the editor and chooses Publish; a cover image must then be supplied. An article can also be *re-drafted* from published state by saving it with the draft action.

### 5.3 Editing

Only the article's author or an administrator may edit an article. The editor is pre-filled from the stored document (tags re-joined as comma-separated text). Disabled members may not edit anything. After saving, a published article returns to its article page; a re-drafted article returns to the profile. Cache entries for the article are invalidated immediately.

### 5.4 Deleting

Only the author or an administrator may delete an article, after confirming in a modal. Deleting an article **also deletes all of its comments** (cascade). The home feed cache is version-bumped so all cached feed pages refresh. Deleting a draft is a separate, author-only action that does not touch comments (drafts cannot accumulate comments from other viewers anyway).

---

## 6. Reading Experience

- **Article rendering.** The stored markup is converted to HTML on the fly, then **sanitized against an explicit allowlist** of elements, attributes, and a small set of inline CSS properties. Unsafe content must never reach the browser. Fenced code blocks are rendered with syntax highlighting and a small "copy" affordance attached to each block.
- **Article header.** Cover image as the banner background, large title, horizontal rule, subtitle, "Posted by *author* on *date*", and the tag list (each tag linking to its tag page). When an administrator views an article whose author is not a publisher, a warning badge explains that the article is not visible to regular users.
- **Comments area.** A comment form for signed-in members (with its own lightweight editor toolbar), then the comment list newest first. Each comment shows author and date, renders sanitized markup, and offers a delete action (with confirmation modal) to its author or an administrator.
- **Imagery quality.** Cover images are preloaded with high fetch priority on the article page; feed card images carry explicit width and height (to avoid layout shift) and lazy-load except the first card, which is fetched with high priority for the largest-paint metric. Page-specific banner backgrounds (home, sign-in, sign-up, write, upload, profile) are preloaded per page type.
- **Navigation aids.** Breadcrumbs on every page; a fixed navigation bar with a collapsible mobile menu; a floating back-to-top button.

---

## 7. Comments

- Only signed-in members may comment. Anonymous visitors see the comment list but are prompted to sign in to comment.
- Comment text uses the same lightweight formatting syntax and the same sanitization rules as articles.
- Comments are attached to their article by reference and stored with author and timestamp.
- Visible comments are limited to those whose authors are still active members; content from disabled members stays in storage but is filtered out of every public render.
- A comment may be deleted by its author or by an administrator, with a confirmation modal; the article's cache entry is purged immediately.

---

## 8. Tags and Discovery

- Articles carry zero or more tags, entered as comma-separated text and normalized (trimmed, de-duplicated by emptiness) on save.
- Each tag has a public tag page listing matching articles (visibility rules apply). The page header announces the tag and suggests **related tags** — tags that frequently co-occur with the current one across matching articles, ranked by co-occurrence frequency, excluding the current tag, limited to ten. Related tags are computed by the database in a single pass, not by application-side loops.
- Feed cards show the first three tags plus a "+N more" marker when there are more.

---

## 9. Search

- A single search box lives in the navigation bar on every page. Submitting it redirects to a **shareable, bookmarkable results URL** that carries the query text and pagination parameters.
- Results respect the consolidated visibility rules (Section 13), are **ranked by relevance** using the database's full-text engine (field indexes on title, subtitle, and body), and are paginated with the same controls as the home feed. Search responses are never cached.
- If the full-text index is unavailable for any reason, the platform falls back to a **case-insensitive substring match** across the same three fields so that search keeps working.
- **Query validation:** queries containing web addresses, markup/script tags, code or shell-command patterns, file paths, or (for longer input) an excessive proportion of special characters are rejected with a "please use only text" notice and redirect home. Automated tests must cover these protections.

---

## 10. Image Management

Uploaded images are **stored as in-database objects**, not as files on disk: the database holds an object registry plus the binary payload split into chunks. This keeps the whole installation in one file and lets the platform serve images without any filesystem storage requirement.

### 10.1 Upload paths

Two upload paths exist, both requiring sign-in:

1. **From the editor toolbar** (image button while writing an article or comment): the file is uploaded in the background and the returned URL is inserted into the text at the cursor.
2. **The Upload Image page**: a web form; after upload the page shows the copied-ready URL in a success banner with a **Copy button** (one-click clipboard copy with visual feedback).

### 10.2 Upload rules

- Only common raster image formats are accepted (allowlist by extension), and the payload must genuinely decode as an image — extension spoofing is rejected by content verification.
- The request body size is capped (configurable; default **16 MB**).
- Every upload is **converted to a modern, efficient image format** (quality 85) at save time; transparency is flattened onto white.
- The stored filename is `owner_displayname + "_" + sanitized original name + "_" + random suffix`, ensuring uniqueness and traceability.
- The object registry records metadata: owner display name, original filename, **alt text seeded from the original filename**, upload time, and content type.

### 10.3 Gallery and metadata editing

The Upload Image page doubles as a gallery: twelve images per page (paginated), each showing a thumbnail, display name, an **editable alt-text field with a Save button**, and a Copy-URL button. Regular members see only their own images; administrators see all images, labeled with their owner. Updating alt text is a dedicated authorized request (owner or administrator) and must never return the stored answer of anything sensitive — only the alt text itself.

### 10.4 Serving and compatibility

- Images are served by their identifier through a public route (no login needed, since images appear on public pages).
- Responses carry **long-lived cache headers (one year)**, an ETag, `Last-Modified`, and support conditional `304 Not Modified` responses.
- Because some link-preview scrapers do not support the modern format, requesting the image with an **older-format file extension** triggers an on-the-fly conversion (transparent backgrounds flattened to white; conversion capped at roughly **20 MB** objects); both variants share the same long-lived caching policy.

### 10.5 Deletion guard

An image may be deleted by its owner or an administrator — **unless it is currently used as an article cover**. In that case the deletion is refused with a conflict response listing the articles that use it, so covers never silently break.

---

## 11. Moderation and Administration

The admin panel (administrators only; reachable via a link shown only to them) provides:

### 11.1 Dashboard statistics

Stat cards computed server-side in a minimal number of database round trips: **members** (total, active, administrators, publishers) and **content** (total articles, published articles, drafts, total comments).

### 11.2 Member management

A table of all other members with three per-row actions, each a single toggle-style request with a confirmation flash message:

- **Enable/disable account.** Disabling prevents sign-in and action-taking immediately (see Sessions). An administrator can never disable another administrator.
- **Promote to administrator** (one-way in v1; no demotion).
- **Grant/revoke publisher status.** Granting makes the member's articles eligible for all public surfaces; revoking hides them again.

Every account or role change clears the response cache.

### 11.3 Unpublished articles review

A dedicated page lists **all articles by non-publisher members** (regardless of active status), newest first, each labeled with the author's current publisher status, so administrators can review content before approving its author. This page exists to support the approval workflow described in Roles.

### 11.4 Search index maintenance

An administrator-triggered **rebuild of all full-text indexes** (title, subtitle, body). This is required after switching to a pluggable word-segmentation tokenizer (see below), because existing index entries must be regenerated under the new segmentation rules.

---

## 12. Data Model

Storage is a **document-based NoSQL database** embedded in the installation — self-contained, zero-configuration, addressed by a single file path. Documents are JSON-like structures retrieved with flexible query operators (membership tests, array element matching, pattern matching, existence checks, set membership) and may be combined with joins and grouped analytics inside the database engine itself. Every document carries a unique, opaque, self-generated identifier that any instance can create without coordination.

### 12.1 Collections

- **Members.** Display name (unique), email, password hash, security question code, security answer hash, and three boolean flags: active (default true), administrator (default false), publisher (default false).
- **Articles.** Title, subtitle, body markup, cover image URL, author display name, creation timestamp (ISO string), tags (array of strings), and status (`draft` or `published`).
- **Comments.** Comment text markup, author display name, parent article reference, and timestamp.
- **Object store.** A registry of uploaded objects — identifier, stored filename, byte length, chunk size, upload timestamp, checksum, and a metadata subdocument (owner, original filename, alt text, upload time, content type) — plus the chunked binary payloads themselves.

### 12.2 Indexes

Declared at connection time, idempotently:

- Articles: single-field indexes on timestamp (as a date), author, tags, cover URL, and status; **compound indexes** on (status, timestamp descending) for the public feed and (author, status, timestamp descending) for profiles and draft management.
- Comments: timestamp, parent article, author, and compound (parent article, timestamp descending).
- Members: **unique** index on display name, plus indexes on email and on the role-flag pairs used for authorization checks.
- Full-text: per-field full-text indexes on article title, subtitle, and body, each with an optional **pluggable tokenizer** supporting languages whose words are not separated by spaces (Thai, Chinese, Japanese, Korean, and similar). If a configured tokenizer cannot be loaded, the platform logs a warning and falls back to the default tokenizer rather than failing to start.

---

## 13. Visibility Rules (consolidated)

These rules apply uniformly across home feed, tag pages, search, article pages, and the site map.

| Viewer | Sees |
|---|---|
| Anonymous visitor | Published articles by **publisher** members only |
| Signed-in member | Published articles by **active** members only |
| Administrator | Everything from everyone (including drafts, via search and tag pages) |
| Author (self) | Their own drafts and published articles on their profile, regardless of publisher status |
| Disabled member's content | Hidden from all of the above **except administrators** |

Additional rules:

- Drafts never appear on public surfaces for anyone, ever; they surface only on the author's profile.
- A non-publisher's article page is viewable **only by its author and administrators** — not by other members — even though other members can generally browse the work of active members. (For consistency, the feed for signed-in members should filter to publishers as well; see deviation note D2.)
- Disabled members: attempting to view a hidden article yields a neutral "not available" message and a redirect — never an explanation that could leak the account's state.
- All state-changing actions (create/edit/delete content, role toggles, uploads, metadata updates) require an authenticated, active member, except where explicitly administrative.

---

## 14. Performance and Caching

- **Response cache (optional).** When enabled by configuration, fully rendered anonymous-visitor pages (notably the home feed) are cached under a key that includes the page number and page size plus a **global content version**; any content change (article create/edit/delete, comment add/delete, account or role change, sign-out) bumps the version or deletes the affected key, so stale pages never persist past the next request.
- The cache supports two storage modes — **in-process memory** and **file-backed** (for installations running several concurrent worker processes that must share the cache) — with a configurable expiry (default **300 seconds**), a configurable size cap (default **100 MB**), and eviction of the oldest entries when full. Expired entries are swept opportunistically; cache failures are logged but never fatal.
- On startup the platform clears the cache, then **pre-warms** it by rendering the first home-feed page for anonymous visitors, so the first request of the day is already fast.
- **Signed-in requests are never served from cache** and carry no-store cache-control headers; search and tag responses are explicitly no-cache.
- **HTML minification.** Rendered HTML is whitespace-trimmed (preserving single blank lines needed by the markup converter) before being sent.
- **Database efficiency.** Listing and counting happen in a single round trip via grouped analytics pipelines; article pages fetch the article and its active-member comments in one joined query; tag analytics run server-side. All hot query paths are covered by the indexes listed in the Data Model.
- **Image efficiency.** Uploads are converted to an efficient modern format at save time and served with one-year cache headers plus conditional requests.

---

## 15. Security

1. **Passwords and answers** are hashed with a salted, iterated key-derivation scheme; low-effort legacy hashes should be re-hashed opportunistically at verify time (see Future Considerations).
2. **Cross-site request forgery:** every state-changing form carries a per-session token; a token is also exposed as a meta tag for client-side scripts. Token validation is enforced on all POST/PUT/DELETE routes.
3. **Output safety:** all user content is rendered through a strict sanitizer with an explicit allowlist of elements, attributes, and inline CSS properties before display. The markup conversion pipeline must never pass raw user HTML through.
4. **Security response headers** are set on every response: prevent MIME-type sniffing, forbid framing (`frame-ancestors: none`), enable the legacy XSS filter, send a strict referrer policy, enforce transport security for one year including subdomains with preload, isolate browsing contexts (`same-origin` opener policy), and send a **content security policy** whose default source is `self` and whose script/style sources are limited to `self` and an explicit allowlist of trusted content-delivery origins; images may come from `self`, data, blob, and any HTTPS origin; object embedding is disabled; base URIs and form actions are restricted to `self`.
5. **Search abuse protection:** query validation as specified in Search, with automated tests.
6. **Upload hardening:** extension allowlist plus content decoding verification; size caps; sanitized filenames; images only (no executables, no documents).
7. **Account state enforcement:** the current member is re-fetched from storage on every request and a disabled or deleted account's session is destroyed immediately.
8. **Proxy trust:** when running behind a reverse proxy, the platform trusts forwarded headers (client address, scheme, host, prefix) from the adjacent hop only, so rate-limit-relevant addresses and redirect/canonical URLs are correct.
9. **Secrets:** the session-signing secret is mandatory in production; a documented procedure generates a strong random value. A missing secret must never silently use a weak default in production (see Configuration).

---

## 16. Search Engine Optimization and Social Sharing

- **Canonical URLs** are emitted on every page, derived from the configured external base URL when set (with a graceful fallback to the request's own URL).
- **Per-article metadata:** description, author, keywords including the article's tags, publication time, and article-type link-preview metadata with the cover image; tags are also emitted as article topic markers.
- **Site-wide metadata:** site title, author, and description on non-article pages, with website-type structured data.
- **Structured data:** article pages embed machine-readable structured data (headline, author, publication date, description, cover image, tag keywords, and the site as publishing organization with its logo); non-article pages embed the equivalent site-level structured data.
- **Link-preview compatibility:** when the cover image is stored in the modern efficient format, preview metadata references an older-format variant of the same image so shared links render correctly on scrapers that lack modern-format support.
- **Site map:** a dynamically generated XML site map listing every publicly visible article (publisher authors, non-draft) with its last-modified date, plus the home page; linked from the footer.
- **Crawler directives:** a dynamically generated crawler-permissions document that advertises the absolute site-map URL.
- **Readable dates:** publication dates are rendered in long human form ("Month DD, YYYY at HH:MM", falling back to date-only when the time is midnight).

---

## 17. Accessibility and Responsive Design

- **Accessibility targets:** audit scores of at least **95/100** at launch (reference implementation: 98), moving toward **WCAG 2.1 AA** (see Future Considerations). Current required practices: alt text on every meaningful image (editable, seeded from the filename), accessible names on all icon-only controls, sequential heading hierarchy on every page, visible focus treatment, and sufficient text contrast.
- **Responsive behavior:** the layout adapts from small phones to desktops; the navigation collapses behind a toggle; profile action buttons adapt to narrow screens; tables remain usable with horizontal scrolling where necessary.
- **Visual identity:** a distinctive typographic identity with graceful fallback metrics (custom font-family stack with size-matched fallback definitions to avoid layout shift while web fonts load), plus icon set and banner photography; all page types share one coherent frame.

---

## 18. Configuration

All runtime configuration lives in **one human-readable, structured configuration file** organized as labeled sections of key–value pairs, loaded at startup with sensible defaults for every omitted value:

- **Application section:** session-signing secret (required in production), bind address, port, site title, site author, site description, external base URL (with trailing-slash normalization; required for correct shared-image and preview URLs in production), and an HTTPS/production flag.
- **Database section:** database file path (default: a named file in the project directory), optional tokenizer name and tokenizer library path.
- **Caching section:** enabled flag, timeout seconds, storage type (`memory` or `file`), cache directory, and maximum cache size in MB.
- **Posts section:** default articles per page (10) and maximum allowed per page (50).
- **Uploads section:** maximum request body size in bytes (default 16 MB).

The configuration file's location may be overridden by an environment variable (essential for containerized deployments where the file lives on a mounted volume). Missing values never crash the platform; each subsystem degrades to its documented default.

---

## 19. Deployment and Operations

1. **Runtime shape.** The platform runs as a long-lived application behind a standard reverse proxy that terminates TLS. In production it must run under a production-grade application server with a small number of concurrent worker processes; workers recycle after a bounded number of requests to keep memory in check, and request-line/header limits are enforced for hardening.
2. **State on persistent storage.** The database file (which includes all in-database image objects) and, if used, the file-cache directory must live on persistent storage — mounted volumes in container deployments — never on ephemeral container scratch space.
3. **Containerized builds.** A reproducible container image build is required; the build compiles optional native extensions (the pluggable word-segmentation tokenizer for Asian-language search) and includes image-format support so uploads and conversions work out of the box.
4. **Multi-worker coherence.** When several worker processes serve traffic, they must share the cache through the file-backed mode, and each worker pre-warms its state at fork time so the platform is fast from the first request after deployment or restart.
5. **Observability.** Access logs (including request duration) and error logs stream to standard output at info level; errors are logged with full traces while users see only friendly messages.
6. **Database evolution.** Version 1 relies on **automatic backfills at startup** (ensuring every article has tags and a status) rather than a migration framework, plus a small set of standalone command-line maintenance scripts for exceptional one-time conversions (e.g., legacy identifier migration, attachment metadata backfill, first-admin promotion repair). All migrations must be idempotent.
7. **Platform portability.** Deployment must be feasible on a virtual private server, container platforms with persistent volumes, and any host that supports a long-running application process behind a proxy. No platform-specific service may be a hard requirement.

---

## 20. Quality Attributes and Verification

- **Correctness.** A runnable, offline-capable automated test suite must exist and pass, covering at minimum the search-input protections, the visibility rules in Section 13, the draft lifecycle, and the image deletion guard. Critical user flows (register → write → publish → comment → search → moderate) need end-to-end coverage.
- **Static quality.** The codebase must pass linting and type checking as a hard gate.
- **Performance.** PageSpeed-style audits at launch must reach at least: Performance **85+** (reference: 84; goal is to beat it with responsive images implemented), Accessibility **95+**, Best Practices **95+**, SEO **100**.
- **Robustness.** Every failure path flashes a human-readable message and redirects to a sensible page; nothing crashes, nothing leaks internals. Cache or tokenizer failures degrade gracefully.
- **Maintainability.** The architecture separates request handling from business logic and from storage access, so each concern can be tested independently.

---

## 21. Future Considerations (explicitly out of v1 scope)

Ordered by usefulness; none may block the version-1 release.

1. **Related articles** — suggest articles sharing tags with the one being read, computed in the database.
2. **Comment moderation queue** — a dashboard joining comments, articles, and members for bulk review.
3. **Reading lists** — members bookmark articles into named reading lists.
4. **Responsive images** — serve multiple generated sizes with width descriptors; server-side resizing/compression profiles.
5. **Session hardening** — rotate session identifiers on sign-in and privilege changes; re-hash weak legacy password hashes at verify time; stricter content security policy via nonces or hashes where the deployment allows it (removing inline-script permissions); additional isolation headers (resource and embedder policies) and a permissions policy.
6. **Accessibility depth** — skip-navigation links, ARIA landmarks, screen-reader testing, formal WCAG 2.1 AA certification.
7. **Author analytics** — monthly publication counts and per-author performance metrics.
8. **Storage hygiene** — report and clean up unused image objects.
9. **Developer documentation** — API documentation, deployment guides, and contribution guidelines.

---

## Appendix A — Defaults and Limits

| Parameter | Default |
|---|---|
| Articles per page (feed/search/tags) | 10 |
| Maximum articles per page | 50 |
| Session lifetime | 24 hours, sliding |
| Maximum upload size | 16 MB |
| Converted image quality | 85 |
| Image cache lifetime | 1 year (with conditional 304s) |
| Gallery page size | 12 images |
| On-the-fly image conversion cap | 20 MB |
| Cache expiry | 300 seconds |
| Cache size cap | 100 MB |
| Related tags returned | 10 |
| Recent articles on profile | 5 |
| Security questions offered | 7 |
| First member | Administrator + publisher |

## Appendix B — Deliberate Deviations from the Reference Behavior

Fixes for spec-level inconsistencies observed in the working platform; the new build should implement the *corrected* rules below rather than replicating the quirks.

1. **Display name is immutable** to keep author references stable. (The reference allowed removing the field from the edit form but articles reference authors by name.)
2. **Feed consistency for signed-in members:** the signed-in home feed must apply the same publisher filter as the public feed; otherwise members see cards for non-publisher articles whose pages then refuse them. Admins keep their broader search/tag visibility.
3. **Search scope for administrators** should include drafts only in dedicated admin surfaces, not mixed silently into public search results ordering.
4. **Sessions should identify members by stable internal ID** rather than display name, so any future renaming capability does not orphan sessions.
5. **Password recovery messaging:** keep the explicit "no account with that email" message (useful for self-hosted communities) but rate-limit the endpoint to blunt enumeration.
6. **Comment deletion** should not require the client to pass the parent article id around; derive it from the comment itself.
