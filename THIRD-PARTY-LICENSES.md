# Third-party licenses and attribution

Neo-Blogger is MIT-licensed (`LICENSE`). This bundle attributes the
vendored assets and system libraries it ships; the full dependency
inventory lives in `docs/technical-requirements.md` §17.1.

## Vendored in `neoblogger/app/web/static/`

| Asset | Version | License | Source |
|---|---|---|---|
| Pico CSS | 2.1.1 | MIT | https://picocss.com · https://cdn.jsdelivr.net/npm/@picocss/pico@2 |
| EasyMDE | 2.19.0 | MIT (Copyright Jeroen Akkerman) | https://github.com/Ionaru/easy-markdown-editor |

Icons referenced by EasyMDE font classes render as text-only buttons;
no icon font is shipped.

## Vendored in `tools/tokenizer/`

| Asset | License | Source |
|---|---|---|
| fts5-icu-tokenizer sources (compiled in the container image by `Containerfile`) | MIT (Copyright 2025 Chaiwat Suttipongsakul) | the `fts5-icu-tokenizer` project |

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
