"""
game_locator.py
===============
Поиск установки SnowRunner (Steam, Epic Games), папки модов и работа с config.json.
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import re
from ctypes import wintypes
from pathlib import Path

log = logging.getLogger("locator")

from paths import DATA_DIR as APP_DIR

CONFIG_PATH = APP_DIR / "config.json"

# Папки с .pak внутри установки игры
PAKS_SUBDIR = Path("preload") / "paks" / "client"


# ------------------------------------------------------------------ config.json

def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_config(cfg: dict) -> None:
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        log.warning("Не удалось сохранить config.json: %s", exc)


# ------------------------------------------------------------------ проверка папки

def normalize_game_dir(path: str | os.PathLike) -> Path | None:
    """Принимает корень игры, папку paks/client или любую папку выше/ниже.
    Возвращает корень установки или None."""
    p = Path(path)
    candidates = [p]
    # пользователь мог выбрать preload, paks или client
    for _ in range(4):
        candidates.append(candidates[-1].parent)
    for c in candidates:
        if (c / PAKS_SUBDIR / "initial.pak").is_file():
            return c
    sub = p / "SnowRunner"
    if (sub / PAKS_SUBDIR / "initial.pak").is_file():
        return sub
    return None


def paks_dir(game_dir: Path) -> Path:
    return game_dir / PAKS_SUBDIR


# ------------------------------------------------------------------ Steam / Epic

def _steam_paths() -> list[Path]:
    roots: list[Path] = []
    try:
        import winreg
        for hive, key, value in (
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
        ):
            try:
                with winreg.OpenKey(hive, key) as k:
                    roots.append(Path(winreg.QueryValueEx(k, value)[0]))
            except OSError:
                continue
    except ImportError:
        pass
    roots += [Path(r"C:\Program Files (x86)\Steam"), Path(r"C:\Program Files\Steam")]
    libs: list[Path] = []
    for root in roots:
        libs.append(root)
        vdf = root / "steamapps" / "libraryfolders.vdf"
        try:
            text = vdf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in re.finditer(r'"path"\s+"([^"]+)"', text):
            libs.append(Path(m.group(1).replace("\\\\", "\\")))
    seen, out = set(), []
    for p in libs:
        key = str(p).lower()
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def _epic_paths() -> list[Path]:
    out: list[Path] = []
    manifests = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
    try:
        for item in manifests.glob("*.item"):
            try:
                data = json.loads(item.read_text(encoding="utf-8", errors="replace"))
            except ValueError:
                continue
            if "snowrunner" in str(data.get("DisplayName", "")).lower() or "snowrunner" in str(data.get("InstallLocation", "")).lower():
                out.append(Path(data.get("InstallLocation", "")))
    except OSError:
        pass
    for base in (r"C:\Program Files\Epic Games", r"D:\Epic Games", r"C:\Program Files (x86)\Epic Games"):
        out.append(Path(base) / "SnowRunner")
    return out


def find_game_dir() -> Path | None:
    """Автопоиск установки. Возвращает корень игры или None."""
    for lib in _steam_paths():
        found = normalize_game_dir(lib / "steamapps" / "common" / "SnowRunner")
        if found:
            log.info("Найдена Steam-установка: %s", found)
            return found
    for p in _epic_paths():
        found = normalize_game_dir(p)
        if found:
            log.info("Найдена установка Epic Games: %s", found)
            return found
    return None


def resolve_game_dir(cfg: dict) -> Path | None:
    """Путь из config.json, иначе автопоиск."""
    saved = cfg.get("game_dir")
    if saved:
        found = normalize_game_dir(saved)
        if found:
            return found
    return find_game_dir()


# ------------------------------------------------------------------ папка модов

def _documents_dir() -> Path:
    """Папка 'Документы' с учётом перенаправления (OneDrive и т.п.)."""
    try:
        buf = ctypes.c_wchar_p()
        # FOLDERID_Documents = {FDD39AD0-238F-46AF-ADB4-6C85480369C7}
        class GUID(ctypes.Structure):
            _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD), ("d", ctypes.c_ubyte * 8)]
        g = GUID(0xFDD39AD0, 0x238F, 0x46AF, (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7))
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(buf)) == 0:
            path = Path(buf.value)
            ctypes.windll.ole32.CoTaskMemFree(buf)
            return path
    except Exception:  # noqa: BLE001 - запасной вариант ниже
        pass
    return Path.home() / "Documents"


def find_mods_dir() -> Path | None:
    p = _documents_dir() / "My Games" / "SnowRunner" / "base" / "Mods"
    return p if p.is_dir() else None


def list_mod_archives(mods_dir: Path | None) -> list[Path]:
    """.pak и .zip в папке модов (включая один уровень вложенности)."""
    if not mods_dir:
        return []
    found: list[Path] = []
    try:
        for p in sorted(mods_dir.rglob("*")):
            if p.is_file() and p.suffix.lower() in (".pak", ".zip") and len(p.relative_to(mods_dir).parts) <= 3:
                found.append(p)
    except OSError:
        pass
    return found
