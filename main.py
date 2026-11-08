#!/usr/bin/env python3
"""Location-independent portable Texypad source launcher."""
from __future__ import annotations

import runpy
import sys
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parent
    program_dir = root / "texypad"
    entry_point = program_dir / "app.py"
    if not entry_point.is_file():
        raise SystemExit(
            "Texypad's program folder is incomplete: "
            f"{entry_point} was not found. Keep main.py beside the texypad folder."
        )
    sys.path.insert(0, str(root))
    if "--version" in sys.argv[1:]:
        from texypad import APP_NAME, APP_VERSION
        print(f"{APP_NAME} {APP_VERSION}")
        return
    runpy.run_path(str(entry_point), run_name="__main__")


if __name__ == "__main__":
    main()
