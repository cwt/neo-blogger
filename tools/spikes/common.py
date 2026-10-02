"""Shared helpers for Neo-Blogger spikes S1-S4."""

import os
import sys

sys.path.insert(0, "/home/cwt/Projects/neosqlite")

import neosqlite  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {name}{(' - ' + detail) if detail else ''}")


def finish(code: str) -> None:
    failed = [r for r in RESULTS if not r[1]]
    print()
    if failed:
        print(f"{code} FAILED: {len(failed)}/{len(RESULTS)} checks failing")
        for r in failed:
            print("  FAIL:", r[0])
        sys.exit(1)
    print(f"{code} PASSED ({len(RESULTS)} checks)")
    sys.exit(0)


def fresh_db(path: str) -> str:
    if os.path.exists(path):
        os.remove(path)
    for suffix in ("-wal", "-shm"):
        if os.path.exists(path + suffix):
            os.remove(path + suffix)
    return path
