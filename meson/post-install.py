#!/usr/bin/env python3
"""Refresh the desktop caches after installation.

Skipped when DESTDIR is set: a staged install is being packaged, and the
caches belong to the machine the package is installed on, not the build host.
"""

import os
import shutil
import subprocess
import sys

if os.environ.get("DESTDIR"):
    print("post-install: staged build, leaving caches to the package manager")
    sys.exit(0)

prefix = os.environ.get("MESON_INSTALL_PREFIX", "/usr/local")
datadir = os.path.join(prefix, "share")

TASKS = (
    ("glib-compile-schemas", [os.path.join(datadir, "glib-2.0", "schemas")]),
    ("update-desktop-database", ["-q", os.path.join(datadir, "applications")]),
    ("update-mime-database", [os.path.join(datadir, "mime")]),
    ("gtk4-update-icon-cache", ["-q", "-t", "-f", os.path.join(datadir, "icons", "hicolor")]),
)

for tool, arguments in TASKS:
    executable = shutil.which(tool)
    if executable is None:
        print(f"post-install: {tool} not found, skipping")
        continue
    result = subprocess.run([executable, *arguments], check=False)
    status = "ok" if result.returncode == 0 else f"failed ({result.returncode})"
    print(f"post-install: {tool} {status}")
