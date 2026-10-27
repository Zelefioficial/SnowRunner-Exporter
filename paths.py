"""
paths.py
========
Папки приложения. Из исходников всё лежит рядом с кодом. В собранном .exe (PyInstaller --onefile)
код распаковывается во временную папку, которая стирается при выходе, поэтому настройки, кэш,
журнал и значок хранятся в %LOCALAPPDATA%\\SnowRunnerExporter, а готовые модели - в Документах.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))


def _data_dir() -> Path:
    if not FROZEN:
        return Path(__file__).resolve().parent
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Local"
    path = root / "SnowRunnerExporter"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        path = Path(sys.executable).resolve().parent
    return path


DATA_DIR = _data_dir()
DEFAULT_OUTPUT = (Path.home() / "Documents" / "SnowRunner Exporter" / "output") if FROZEN else DATA_DIR / "output"
