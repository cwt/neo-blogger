# Third-party licenses and attribution

Neo-Blogger is MIT-licensed (`LICENSE`). This bundle attributes the
vendored assets and system libraries it ships; the full dependency
inventory lives in `docs/technical-requirements.md` §17.1.

## Vendored in `neoblogger/app/web/static/`

| Asset | Version | License | Source |
|---|---|---|---|
| Pico CSS | 2.1.1 | MIT | https://picocss.com · https://cdn.jsdelivr.net/npm/@picocss/pico@2 |
| EasyMDE | 2.19.0 | MIT (Copyright Jeroen Akkerman) | https://github.com/Ionaru/easy-markdown-editor |
| IBM Plex webfonts (13 families, woff2) | current | SIL OFL 1.1 | Google Fonts css2 + `@ibm/plex-sans-sc` / `@ibm/plex-sans-tc` npm split webfonts; re-vendor with `tools/fetch_fonts.py` |

Icons referenced by EasyMDE font classes render as text-only buttons;
no icon font is shipped.

## Subrepo at `tools/tokenizer/`

| Asset | License | Source |
|---|---|---|
| fts5-icu-tokenizer sources, pinned at tag `v7.2.1` (compiled in the container image by `Containerfile`; pin recorded in `.hgsubstate`) | MIT (Copyright 2025 Chaiwat Suttipongsakul) | git@github.com:cwt/fts5-icu-tokenizer.git |

Cloning this repository must initialize subrepos (`hg clone` fetches
`tools/tokenizer` automatically on update); the `git` executable is
required for that step.

## Deploy-time generated assets

| Asset | Provenance |
|---|---|
| Theme banners (`theme_*.webp`, one per page family, generated once at deploy time by `neoblogger.cli.theme`) | AI-generated with Agnes Image 2.5; Output owned by the operator under Agnes ToS §8.1. The footer credit ("Theme artwork generated with Agnes AI") satisfies the §6.1 AI-content disclosure whenever a theme is active. |

`AGNES_API_KEY` lives in `./.env` (ignored, never committed, never baked
into the image); the running app performs no network calls.

## System libraries (container image)

| Library | License |
|---|---|
| libicu (International Components for Unicode) | ICU License (MIT-equivalent, OSI-approved) |
| Unicode data files | Unicode License v3 / Unicode-TOU |
| SQLite | Public domain |
| Python interpreter + stdlib | PSF-2.0 |

## Runtime Python dependencies

All MIT or MIT-compatible (BSD-2/3, Apache-2.0, MIT-CMU, MIT-0, PSF);
see §17.1 of the technical requirements for the verified table. No
GPL/AGPL/SSPL code enters the image.
