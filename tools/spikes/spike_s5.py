"""S5: Fedora 44 platform check — Python, SQLite+FTS5, ICU, zig.
Executed on the host itself, which is Fedora 44 = the container base image,
so the findings transfer 1:1 to the build environment."""

import os
import platform
import shutil
import sqlite3
import subprocess
import sys

sys.dont_write_bytecode = True

from common import check, finish  # noqa: E402


def pkg_version(pkg: str) -> str:
    try:
        return subprocess.check_output(
            ["rpm", "-q", "--qf", "%{VERSION}", pkg],
            stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:  # noqa: BLE001
        return "?"


os_rel = ""
try:
    with open("/etc/os-release") as f:
        for line in f:
            if line.startswith("PRETTY_NAME"):
                os_rel = line.split("=", 1)[1].strip().strip('"')
            elif line.startswith("VERSION="):
                pass
except OSError:
    pass

py = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
check("S5-1 Fedora 44 detected", "Fedora Linux" in os_rel
      and " 44 " in " " + os_rel + " ", os_rel)
check("S5-2 Python >= 3.14", (sys.version_info.major,
                              sys.version_info.minor) >= (3, 14), py)
check("S5-2b python3 package matches",
      pkg_version("python3").startswith("3.14"),
      pkg_version("python3"))

sq = sqlite3.sqlite_version
conn = sqlite3.connect(":memory:")
fts5 = conn.execute(
    "SELECT sqlite_compileoption_used('ENABLE_FTS5')").fetchone()[0] == 1
loadable = hasattr(sqlite3.Connection, "enable_load_extension")
if loadable:
    probe = sqlite3.connect(":memory:")
    try:
        probe.enable_load_extension(True)
        probe.execute("SELECT load_extension(?)",
                      ("/home/cwt/Projects/fts5-icu-tokenizer/zig-out/"
                       "lib/libfts5_icu.so",))
        ver = probe.execute("SELECT fts5_icu_version()").fetchone()[0]
        loadable = bool(ver)
    except Exception as e:  # noqa: BLE001
        loadable = False
        detail = f"{type(e).__name__}: {e}"
    else:
        detail = f"ICU loaded on stdlib sqlite ({ver})"
    probe.close()
else:
    detail = "no enable_load_extension API"
check("S5-3b extension loading works (by behavior)", loadable, detail)

icu_ver = pkg_version("libicu")
icu_dev = pkg_version("libicu-devel")
check("S5-4 libicu present", icu_ver not in ("?", ""), f"libicu {icu_ver}")
check("S5-4b libicu-devel present (tokenizer compilation)", icu_dev not in ("?", ""),
      f"libicu-devel {icu_dev}")
query = fr"file-text"  # placeholder to keep imports tidy
icu_pc = ""
try:
    icu_pc = subprocess.check_output(
        ["pkg-config", "--modversion", "icu-uc"], text=True).strip()
except Exception:  # noqa: BLE001
    pass
check("S5-4c pkg-config icu-uc", bool(icu_pc), f"icu-uc {icu_pc}")

zig = shutil.which("zig")
zig_ver = ""
if zig:
    try:
        zig_ver = subprocess.check_output([zig, "version"], text=True).strip()
    except Exception:  # noqa: BLE001
        zig_ver = "?"
check("S5-5 zig available (build tokenizer in image)",
      zig is not None and zig_ver.startswith("0.16"), f"zig {zig_ver}")

libc_pub = arch = platform.machine()
check("S5-6 prebuilt ICU .so already present",
      os.path.exists(
          "/home/cwt/Projects/fts5-icu-tokenizer/zig-out/lib/libfts5_icu.so"),
      f"arch={libc_pub}")

finish("S5")
