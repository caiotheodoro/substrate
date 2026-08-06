"""Make workspace packages importable regardless of uv's editable .pth state.

uv 0.12.2 intermittently fails to load the `__editable__*.pth` files it
writes (observed across recreations). Rather than depend on them, prepend
every package's `src/` dir to sys.path here — deterministic for both the
workspace-level `uv run pytest` and per-package `cd py/... && uv run pytest`.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

for pkg in sorted(ROOT.joinpath("packages").iterdir()):
    src = pkg / "src"
    if src.is_dir():
        s = str(src)
        if s not in sys.path:
            sys.path.insert(0, s)