"""
pak_reader.py
=============
Единый индекс "виртуальный путь -> (архив, запись)" по всем .pak игры и модам.

.pak - обычный ZIP. Архивы читаются через zipfile, на диск ничего не
распаковывается. Пути приводятся к нижнему регистру и прямым слэшам.
Приоритет: архивы добавляются по порядку, более поздний перекрывает ранний
(база < DLC-архивы < моды).
"""

from __future__ import annotations

import logging
import threading
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Iterator

log = logging.getLogger("pak")

# Эти архивы не содержат ни машин, ни моделей, ни текстур машин - пропускаем,
# чтобы не читать огромные оглавления (editor.pak - 14 ГБ, звук - 5 ГБ).
SKIP_PREFIXES = ("level_", "shared_sound", "editor", "gfx", "boot", "shader", "ref_")


def norm(path: str) -> str:
    return path.replace("\\", "/").lower()


@dataclass(frozen=True)
class PakEntry:
    pak: Path
    name: str          # имя записи внутри архива (как есть)
    size: int
    source: str        # 'base' | 'dlc' | 'mod'
    pak_label: str     # имя архива для отображения


class PakIndex:
    def __init__(self) -> None:
        self._entries: dict[str, PakEntry] = {}
        self._zips: dict[Path, zipfile.ZipFile] = {}
        self._locks: dict[Path, threading.Lock] = {}
        self._lock = threading.Lock()
        self.loaded_paks: list[Path] = []

    # ------------------------------------------------------------ построение
    def add_pak(self, path: Path, source: str = "base") -> int:
        """Добавляет архив в индекс. Возвращает число записей или -1 при ошибке."""
        try:
            z = zipfile.ZipFile(path)
        except (zipfile.BadZipFile, OSError) as exc:
            log.warning("Архив %s пропущен: %s", path.name, exc)
            return -1
        with self._lock:
            self._zips[path] = z
            self._locks[path] = threading.Lock()
        count = 0
        for info in z.infolist():
            if info.is_dir():
                continue
            self._entries[norm(info.filename)] = PakEntry(path, info.filename, info.file_size, source, path.name)
            count += 1
        self.loaded_paks.append(path)
        return count

    def add_game(self, paks_dir: Path, progress: Callable[[float, str], None] | None = None) -> None:
        """Добавляет нужные архивы игры: сначала базовые, затем dlc_*.pak.
        progress(доля 0..1, текст) вызывается перед чтением каждого архива."""
        all_paks = sorted(paks_dir.glob("*.pak"), key=lambda p: p.name.lower())
        base, dlc = [], []
        for p in all_paks:
            n = p.name.lower()
            if n.startswith("dlc_") or n.startswith("dlc"):
                dlc.append(p)
            elif not n.startswith(SKIP_PREFIXES):
                base.append(p)
        # initial.pak должен идти первым - остальные его перекрывают только при совпадении путей
        base.sort(key=lambda p: (p.name.lower() != "initial.pak", p.name.lower()))
        order = base + dlc
        for i, p in enumerate(order):
            if progress:
                progress(i / max(len(order), 1), f"Читаю {p.name}")
            # mod.pak - шаблон мода из набора редактора, а не базовая игра
            source = "dlc" if p in dlc else ("mod" if p.name.lower() == "mod.pak" else "base")
            self.add_pak(p, source)
        if progress:
            progress(1.0, "Архивы прочитаны")

    def add_mods(self, archives: Iterable[Path], progress: Callable[[float, str], None] | None = None) -> None:
        archives = list(archives)
        for i, p in enumerate(archives):
            if progress:
                progress(i / max(len(archives), 1), f"Мод: {p.name}")
            self.add_pak(p, "mod")

    # ------------------------------------------------------------ доступ
    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, vpath: str) -> bool:
        return norm(vpath) in self._entries

    def entry(self, vpath: str) -> PakEntry | None:
        return self._entries.get(norm(vpath))

    def read(self, vpath: str) -> bytes:
        """Читает файл в память. KeyError, если пути нет в индексе."""
        e = self._entries.get(norm(vpath))
        if e is None:
            raise KeyError(vpath)
        with self._locks[e.pak]:
            return self._zips[e.pak].read(e.name)

    def try_read(self, vpath: str) -> bytes | None:
        try:
            return self.read(vpath)
        except (KeyError, zipfile.BadZipFile, OSError, RuntimeError) as exc:
            if not isinstance(exc, KeyError):
                log.warning("Не удалось прочитать %s: %s", vpath, exc)
            return None

    def paths(self, prefix: str = "", suffix: str = "") -> Iterator[str]:
        """Виртуальные пути (в нижнем регистре) с заданным началом и концом."""
        prefix, suffix = norm(prefix), norm(suffix)
        for k in self._entries:
            if k.startswith(prefix) and k.endswith(suffix):
                yield k

    def signature(self) -> str:
        """Подпись набора архивов (для инвалидации кэша)."""
        parts = []
        for p in self.loaded_paks:
            try:
                st = p.stat()
                parts.append(f"{p.name}:{st.st_size}:{int(st.st_mtime)}")
            except OSError:
                parts.append(p.name)
        return "|".join(parts)

    def close(self) -> None:
        for z in self._zips.values():
            try:
                z.close()
            except Exception:  # noqa: BLE001
                pass
        self._zips.clear()
