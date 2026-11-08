"""Runtime path discovery for portable and packaged Texypad builds."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from texypad import APP_ID, ORGANIZATION_NAME


def _program_root() -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    return Path(frozen_root).resolve() if frozen_root else Path(__file__).resolve().parent


def _config_root() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        return base / ORGANIZATION_NAME / "Texypad"
    raw = os.environ.get("XDG_CONFIG_HOME", "").strip()
    base = Path(raw).expanduser() if raw and Path(raw).expanduser().is_absolute() else Path.home() / ".config"
    return base / ORGANIZATION_NAME / APP_ID


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    package_root: Path
    config_root: Path
    config_path: Path
    icon_path: Path

    @classmethod
    def detect(cls) -> "RuntimePaths":
        package_root = _program_root()
        config_root = _config_root()
        return cls(
            package_root=package_root,
            config_root=config_root,
            config_path=config_root / f"{APP_ID}.json",
            icon_path=package_root / "assets" / "icons" / "texypad.png",
        )
