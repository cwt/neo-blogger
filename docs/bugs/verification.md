---
type: attested_computation
title: "Verification history"
description: "Baseline test, linter, type-check, and spike verification results recorded for the Neo-Blogger bug tracker."
status: stable
sources:
  - pyproject.toml
  - tests/
  - tools/spikes/
verified: machine-confirmed
tags: [bugs, verification, testing, quality-gates]
timestamp: 2026-10-16T09:30:00Z
---

# Verification history

Recorded per audit pass for the [bug tracker](index.md). Re-run `pytest`, `ruff check`, `ruff format --check`, and `mypy` after any change to `neoblogger/` or `tests/`.

## Baseline audit pass (2026-10-16 — Bugs #1–#24 filed)

- **Test suite (`.venv/bin/pytest -q`):** `249 passed in 13.24s` (zero failures, zero warnings).
- **Linter (`.venv/bin/ruff check`):** `All checks passed!`
- **Type checker (`.venv/bin/mypy`):** `Success: no issues found in 49 source files` (`strict = true` on Python 3.14).
- **Spikes (`tools/spikes/spike_s1.py`–`spike_s5.py`):** 54/54 checks passing (executor facade, `$facet`/`$lookup`/related-tags aggregations, GridFS chunking/MD5, FTS5 + ICU tokenizer fallback, Fedora 44 platform).

## Pending regression coverage for open bugs

Each bug in [All Bugs](index.md) (#1–#24) is currently **Open** and awaiting fix + dedicated regression test coverage:

- **High severity:** [Bug 1](001.md) through [Bug 5](005.md)
- **Medium severity:** [Bug 6](006.md) through [Bug 16](016.md)
- **Low severity:** [Bug 17](017.md) through [Bug 24](024.md)
