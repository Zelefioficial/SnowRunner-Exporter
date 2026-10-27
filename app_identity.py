"""
app_identity.py
===============
Значок приложения (снежинка), идентификатор для панели задач Windows и ярлык.

* значок (снежинка) рисуется в Pillow и сохраняется в assets/app.ico и assets/app.png;
* SetCurrentProcessExplicitAppUserModelID - окно не группируется под Python,
  в панели задач показывается наш значок;
* свойства окна RelaunchCommand / RelaunchIconResource / RelaunchDisplayNameResource - если закрепить
  запущенное окно в панели задач, закреплённый значок остаётся нашим и запускает приложение;
* create_desktop_shortcut() - ярлык с тем же идентификатором (его тоже можно закрепить).

Всё, что связано с Windows, выполняется через ctypes без внешних зависимостей и при ошибке
молча отключается (приложение работает и без этого).
"""

from __future__ import annotations

import ctypes
import math
import sys
import uuid
from ctypes import byref, c_int, c_long, c_ubyte, c_ulong, c_ushort, c_void_p, c_wchar_p
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

APP_ID = "SnowRunner.Exporter.Personal"
APP_NAME = "SnowRunner Exporter"
from paths import DATA_DIR as APP_DIR, FROZEN

ASSETS = APP_DIR / "assets"
ICO_PATH = ASSETS / "app.ico"
PNG_PATH = ASSETS / "app.png"
ICO_SIZES = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)]

_FMTID_APPUSERMODEL = "{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}"
_PID_RELAUNCH_COMMAND, _PID_RELAUNCH_ICON, _PID_RELAUNCH_NAME, _PID_APP_ID = 2, 3, 4, 5
_IID_PROPERTY_STORE = "{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}"
_CLSID_SHELL_LINK = "{00021401-0000-0000-C000-000000000046}"
_IID_SHELL_LINK_W = "{000214F9-0000-0000-C000-000000000046}"
_IID_PERSIST_FILE = "{0000010B-0000-0000-C000-000000000046}"
_FOLDERID_DESKTOP = "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}"
_VT_LPWSTR = 31


# ------------------------------------------------------------------ значок

ICON_VERSION = "snowflake-3"            # при смене рисунка значок пересоздаётся сам
VERSION_PATH = ASSETS / "app.version"


def _flake_segments(bold: bool = False) -> list[tuple[float, float, float, float, float]]:
    """Отрезки снежинки в условных единицах (центр в нуле, 1024 = ширина значка): x1, y1, x2, y2, толщина.
    bold=True - упрощённый жирный вариант для маленьких размеров (16-32 px)."""
    m = 1.7 if bold else 1.0
    branches = ((165, 150, 62), (290, 104, 56)) if bold else ((150, 132, 48), (262, 96, 44), (372, 70, 40))
    segs: list[tuple[float, float, float, float, float]] = []
    for i in range(6):
        a = math.radians(i * 60 - 90)
        ux, uy = math.cos(a), math.sin(a)
        segs.append((0.0, 0.0, ux * 372, uy * 372, 64 * m))                # главный луч
        # боковые веточки (расстояние от центра, длина, толщина), на конце луча - развилка
        for dist, length, width in branches:
            px, py = ux * dist, uy * dist
            for side in (-1, 1):
                b = a + side * math.radians(58 if dist < 372 else 42)
                segs.append((px, py, px + math.cos(b) * length, py + math.sin(b) * length, width))
    return segs


def draw_icon(master: int = 2048, bold: bool = False) -> Image.Image:
    """Снежинка на скруглённой графитовой плитке: ледяное свечение, белые лучи, шестигранная ступица."""
    k = master / 1024.0
    c = master / 2.0
    img = Image.new("RGBA", (master, master), (0, 0, 0, 0))

    # плитка с вертикальным градиентом и скруглёнными углами
    tile = Image.new("RGBA", (master, master))
    td = ImageDraw.Draw(tile)
    top, bottom = (66, 79, 96), (26, 30, 37)
    for y in range(master):
        t = y / (master - 1)
        td.line([(0, y), (master, y)], fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)) + (255,))
    mask = Image.new("L", (master, master), 0)
    ImageDraw.Draw(mask).rounded_rectangle((int(24 * k), int(24 * k), int(1000 * k), int(1000 * k)),
                                           radius=int(232 * k), fill=255)
    img.paste(tile, (0, 0), mask)

    def paint(layer: Image.Image, color: tuple, extra: float = 0.0) -> None:
        d = ImageDraw.Draw(layer)
        for x1, y1, x2, y2, w in _flake_segments(bold):
            wk = (w + extra) * k
            p, q = (c + x1 * k, c + y1 * k), (c + x2 * k, c + y2 * k)
            d.line([p, q], fill=color, width=int(wk))
            for cx, cy in (p, q):                                         # скруглённые концы
                d.ellipse((cx - wk / 2, cy - wk / 2, cx + wk / 2, cy + wk / 2), fill=color)

    def hexagon(layer: Image.Image, radius: float, color: tuple) -> None:
        pts = [(c + radius * k * math.cos(math.radians(i * 60 - 90)),
                c + radius * k * math.sin(math.radians(i * 60 - 90))) for i in range(6)]
        ImageDraw.Draw(layer).polygon(pts, fill=color)

    # свечение: те же линии ледяным цветом, размытые и подложенные под снежинку
    glow = Image.new("RGBA", (master, master), (0, 0, 0, 0))
    paint(glow, (109, 208, 247, 255), extra=26)
    hexagon(glow, 150 if bold else 120, (109, 208, 247, 255))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=30 * k))
    glow.putalpha(glow.getchannel("A").point(lambda v: int(v * 0.75)))
    img = Image.alpha_composite(img, glow)

    flake = Image.new("RGBA", (master, master), (0, 0, 0, 0))
    paint(flake, (238, 247, 253, 255))
    hexagon(flake, 128 if bold else 104, (109, 208, 247, 255))
    hexagon(flake, 74 if bold else 58, (255, 255, 255, 255))
    # снежинка не должна выходить за плитку
    clipped = Image.new("RGBA", (master, master), (0, 0, 0, 0))
    clipped.paste(flake, (0, 0), mask)
    return Image.alpha_composite(img, clipped)


def ensure_icon() -> Path:
    """Создаёт assets/app.ico и app.png, если их нет или рисунок обновился. Возвращает путь к .ico."""
    current = VERSION_PATH.read_text(encoding="utf-8").strip() if VERSION_PATH.is_file() else ""
    if ICO_PATH.is_file() and PNG_PATH.is_file() and current == ICON_VERSION:
        return ICO_PATH
    ASSETS.mkdir(parents=True, exist_ok=True)
    master = draw_icon(2048)
    bold = draw_icon(1024, bold=True)        # для 16-32 px: жирный упрощённый рисунок
    frames = {s: (bold if s[0] <= 32 else master).resize(s, Image.LANCZOS) for s in ICO_SIZES}
    base = frames[(256, 256)]
    base.save(ICO_PATH, format="ICO", sizes=ICO_SIZES,
              append_images=[f for s, f in frames.items() if s != (256, 256)])
    base.save(PNG_PATH, format="PNG")
    VERSION_PATH.write_text(ICON_VERSION, encoding="utf-8")
    return ICO_PATH


def apply_window_icon(root) -> None:
    """Значок в заголовке окна и в панели задач."""
    try:
        ico = ensure_icon()
    except Exception:  # noqa: BLE001 - значок не должен ломать запуск
        return
    try:
        root.iconbitmap(default=str(ico))
    except Exception:  # noqa: BLE001
        try:
            import tkinter as tk
            root._icon_ref = tk.PhotoImage(file=str(PNG_PATH))
            root.iconphoto(True, root._icon_ref)
        except Exception:  # noqa: BLE001
            pass


# ------------------------------------------------------------------ COM через ctypes

class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", c_ushort), ("Data3", c_ushort), ("Data4", c_ubyte * 8)]


class _PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", c_ulong)]


def _guid(text: str) -> _GUID:
    return _GUID.from_buffer_copy(uuid.UUID(text).bytes_le)


def _pkey(pid: int) -> _PROPERTYKEY:
    pk = _PROPERTYKEY()
    pk.fmtid = _guid(_FMTID_APPUSERMODEL)
    pk.pid = pid
    return pk


def _vcall(obj: c_void_p, index: int, argtypes: list, *args) -> int:
    """Вызов метода COM-объекта по индексу в таблице виртуальных функций."""
    vtbl = ctypes.cast(ctypes.cast(obj, ctypes.POINTER(c_void_p))[0], ctypes.POINTER(c_void_p))
    fn = ctypes.WINFUNCTYPE(c_long, c_void_p, *argtypes)(vtbl[index])
    return fn(obj, *args)


def _string_variant(text: str):
    """PROPVARIANT типа VT_LPWSTR: 2 байта vt, указатель на строку со смещения 8."""
    buf = ctypes.create_unicode_buffer(text)
    pv = (c_ubyte * (8 + 2 * ctypes.sizeof(c_void_p)))()
    c_ushort.from_buffer(pv, 0).value = _VT_LPWSTR
    c_void_p.from_buffer(pv, 8).value = ctypes.addressof(buf)
    return pv, buf


def _set_string(store: c_void_p, pid: int, text: str) -> None:
    pv, _keep = _string_variant(text)
    hr = _vcall(store, 6, [c_void_p, c_void_p], byref(_pkey(pid)), byref(pv))     # IPropertyStore::SetValue
    if hr != 0:
        raise OSError(f"SetValue({pid}) вернул {hr:#x}")


def _get_string(store: c_void_p, pid: int) -> str | None:
    pv = (c_ubyte * (8 + 2 * ctypes.sizeof(c_void_p)))()
    hr = _vcall(store, 5, [c_void_p, c_void_p], byref(_pkey(pid)), byref(pv))     # IPropertyStore::GetValue
    if hr != 0:
        return None
    vt = c_ushort.from_buffer(pv, 0).value
    ptr = c_void_p.from_buffer(pv, 8).value
    text = ctypes.wstring_at(ptr) if vt == _VT_LPWSTR and ptr else None
    ctypes.windll.ole32.PropVariantClear(byref(pv))
    return text


def _pythonw() -> str:
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    return str(pyw if pyw.is_file() else exe)


def _launch_args() -> str:
    """Аргументы запуска: у собранного .exe их нет, из исходников это main.py."""
    return "" if FROZEN else f'"{Path(__file__).resolve().parent / "main.py"}"'


def relaunch_command() -> str:
    args = _launch_args()
    return f'"{_pythonw()}" {args}'.strip()


# ------------------------------------------------------------------ панель задач

_native_icons: list[int] = []        # дескрипторы значков живут до конца работы приложения


def set_native_icon(root) -> bool:
    """Задаёт значок самому окну (WM_SETICON): большой для панели задач и Alt+Tab,
    малый для заголовка. Размеры берутся из системных метрик, поэтому работает при любом масштабе экрана."""
    if sys.platform != "win32":
        return False
    try:
        ensure_icon()
        user32 = ctypes.windll.user32
        user32.LoadImageW.restype = c_void_p
        user32.LoadImageW.argtypes = [c_void_p, c_wchar_p, ctypes.c_uint, c_int, c_int, ctypes.c_uint]
        user32.SendMessageW.restype = c_void_p
        user32.SendMessageW.argtypes = [c_void_p, ctypes.c_uint, c_void_p, c_void_p]
        hwnd = int(root.wm_frame(), 16)
        big = user32.LoadImageW(None, str(ICO_PATH), 1, user32.GetSystemMetrics(11), user32.GetSystemMetrics(12), 0x10)
        small = user32.LoadImageW(None, str(ICO_PATH), 1, user32.GetSystemMetrics(49), user32.GetSystemMetrics(50), 0x10)
        if not big or not small:
            return False
        _native_icons.extend([big, small])
        user32.SendMessageW(hwnd, 0x0080, 1, big)        # WM_SETICON, ICON_BIG
        user32.SendMessageW(hwnd, 0x0080, 0, small)      # WM_SETICON, ICON_SMALL
        return True
    except Exception:  # noqa: BLE001
        return False


def finalize_taskbar(root) -> bool:
    """Значок окна + свойства для закрепления. Вызывать, когда окно уже создано."""
    icon_ok = set_native_icon(root)
    id_ok = register_window_identity(root)
    return icon_ok and id_ok


def set_process_app_id() -> bool:
    """Вызывать до создания окна: окно получает собственную группу в панели задач."""
    if sys.platform != "win32":
        return False
    try:
        return ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(c_wchar_p(APP_ID)) == 0
    except Exception:  # noqa: BLE001
        return False


def register_window_identity(root) -> bool:
    """Свойства окна для панели задач: идентификатор, команда перезапуска, значок и имя.
    Благодаря им закрепление запущенного окна даёт закреплённый значок приложения."""
    if sys.platform != "win32":
        return False
    try:
        ensure_icon()
        hwnd = int(root.wm_frame(), 16)
        shell32 = ctypes.windll.shell32
        shell32.SHGetPropertyStoreForWindow.argtypes = [c_void_p, c_void_p, c_void_p]
        shell32.SHGetPropertyStoreForWindow.restype = c_long
        store = c_void_p()
        if shell32.SHGetPropertyStoreForWindow(hwnd, byref(_guid(_IID_PROPERTY_STORE)), byref(store)) != 0 or not store:
            return False
        try:
            _set_string(store, _PID_APP_ID, APP_ID)
            _set_string(store, _PID_RELAUNCH_COMMAND, relaunch_command())
            _set_string(store, _PID_RELAUNCH_ICON, f"{ICO_PATH},0")
            _set_string(store, _PID_RELAUNCH_NAME, APP_NAME)
            _vcall(store, 7, [])                                                   # Commit
        finally:
            _vcall(store, 2, [])                                                   # Release
        return True
    except Exception:  # noqa: BLE001
        return False


def read_window_identity(root) -> dict[str, str | None]:
    """Читает свойства окна обратно (для проверки)."""
    hwnd = int(root.wm_frame(), 16)
    shell32 = ctypes.windll.shell32
    shell32.SHGetPropertyStoreForWindow.argtypes = [c_void_p, c_void_p, c_void_p]
    shell32.SHGetPropertyStoreForWindow.restype = c_long
    store = c_void_p()
    if shell32.SHGetPropertyStoreForWindow(hwnd, byref(_guid(_IID_PROPERTY_STORE)), byref(store)) != 0:
        return {}
    try:
        return {"id": _get_string(store, _PID_APP_ID), "command": _get_string(store, _PID_RELAUNCH_COMMAND),
                "icon": _get_string(store, _PID_RELAUNCH_ICON), "name": _get_string(store, _PID_RELAUNCH_NAME)}
    finally:
        _vcall(store, 2, [])


# ------------------------------------------------------------------ ярлык

def desktop_dir() -> Path:
    try:
        buf = c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(byref(_guid(_FOLDERID_DESKTOP)), 0, None, byref(buf)) == 0:
            path = Path(buf.value)
            ctypes.windll.ole32.CoTaskMemFree(buf)
            return path
    except Exception:  # noqa: BLE001
        pass
    return Path.home() / "Desktop"


def create_shortcut(lnk_path: Path) -> Path:
    """Ярлык на main.py со значком колеса и тем же идентификатором, что у окна.
    Закреплённый ярлык и запущенное окно попадают в одну кнопку панели задач."""
    ensure_icon()
    ole32 = ctypes.windll.ole32
    hr_init = ole32.CoInitialize(None)
    link, store, persist = c_void_p(), c_void_p(), c_void_p()
    try:
        hr = ole32.CoCreateInstance(byref(_guid(_CLSID_SHELL_LINK)), None, 1, byref(_guid(_IID_SHELL_LINK_W)), byref(link))
        if hr != 0:
            raise OSError(f"CoCreateInstance вернул {hr:#x}")
        for idx, value in ((20, _pythonw()), (11, _launch_args()), (9, str(Path(_pythonw()).parent if FROZEN else APP_DIR)), (7, APP_NAME)):
            _vcall(link, idx, [c_wchar_p], c_wchar_p(value))                      # SetPath / SetArguments / SetWorkingDirectory / SetDescription
        _vcall(link, 17, [c_wchar_p, c_int], c_wchar_p(str(ICO_PATH)), 0)         # SetIconLocation
        if _vcall(link, 0, [c_void_p, c_void_p], byref(_guid(_IID_PROPERTY_STORE)), byref(store)) == 0:
            _set_string(store, _PID_APP_ID, APP_ID)
            _vcall(store, 7, [])
        if _vcall(link, 0, [c_void_p, c_void_p], byref(_guid(_IID_PERSIST_FILE)), byref(persist)) != 0:
            raise OSError("у ярлыка нет IPersistFile")
        lnk_path = lnk_path.absolute()                  # IPersistFile::Save требует полный путь
        lnk_path.parent.mkdir(parents=True, exist_ok=True)
        hr = _vcall(persist, 6, [c_wchar_p, c_int], c_wchar_p(str(lnk_path)), 1)  # IPersistFile::Save
        if hr != 0:
            raise OSError(f"Save вернул {hr:#x}")
        return lnk_path
    finally:
        for obj in (persist, store, link):
            if obj:
                _vcall(obj, 2, [])
        if hr_init >= 0:
            ole32.CoUninitialize()


def read_shortcut_app_id(lnk_path: Path) -> str | None:
    """Идентификатор приложения, записанный в ярлык (для проверки)."""
    ole32 = ctypes.windll.ole32
    hr_init = ole32.CoInitialize(None)
    link, persist, store = c_void_p(), c_void_p(), c_void_p()
    try:
        ole32.CoCreateInstance(byref(_guid(_CLSID_SHELL_LINK)), None, 1, byref(_guid(_IID_SHELL_LINK_W)), byref(link))
        _vcall(link, 0, [c_void_p, c_void_p], byref(_guid(_IID_PERSIST_FILE)), byref(persist))
        if _vcall(persist, 5, [c_wchar_p, c_int], c_wchar_p(str(Path(lnk_path).absolute())), 0) != 0:   # IPersistFile::Load
            return None
        _vcall(link, 0, [c_void_p, c_void_p], byref(_guid(_IID_PROPERTY_STORE)), byref(store))
        return _get_string(store, _PID_APP_ID)
    finally:
        for obj in (store, persist, link):
            if obj:
                _vcall(obj, 2, [])
        if hr_init >= 0:
            ole32.CoUninitialize()


def create_desktop_shortcut() -> Path:
    return create_shortcut(desktop_dir() / f"{APP_NAME}.lnk")
