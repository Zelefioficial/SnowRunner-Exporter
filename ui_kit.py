"""
ui_kit.py
=========
Тёмная скруглённая тема для tkinter. Только стандартная библиотека.

Все скруглённые элементы нарисованы на Canvas (сглаженные полигоны), поэтому
выглядят одинаково на любой версии Windows. Иконок-эмодзи нет: стрелки и
индикаторы нарисованы фигурами. Контраст текста на фонах не ниже 4.5:1
(правило UI UX Pro Max: dark mode, visible focus, contrast).
"""

from __future__ import annotations

import random
import sys
import tkinter as tk
from tkinter import font as tkfont

from PIL import Image, ImageDraw, ImageTk

from ui_lang import tr

# Нейтральный графит (светлее прежнего тёмно-синего) и ледяной акцент.
# Контраст muted на card_hi, row и row_sel не ниже 4.5:1.
PALETTE = {
    "bg": "#23262B",
    "panel": "#2A2D33",
    "card": "#30343B",
    "card_hi": "#3C414A",
    "card_sel": "#4A505B",
    "row": "#383C44",
    "row_hover": "#434852",
    "row_sel": "#3D5666",
    "border": "#4B515C",
    "text": "#F4F6F9",
    "muted": "#BCC2CD",
    "accent": "#6DD0F7",
    "accent_hi": "#93E0FF",
    "accent_text": "#06222F",
    "ok": "#7FE3AB",
    "warn": "#F7C275",
    "err": "#FF8E9C",
    "snow": "#EFF7FD",
    "track": "#1B1D21",
    "thumb": "#6A7180",
}

# значки источника: (подпись, фон, текст)
SOURCE_BADGE = {
    "base": ("БАЗА", "#2C5F8D", "#E6F2FD"),
    "dlc": ("DLC", "#5B4B9B", "#F1ECFF"),
    "mod": ("МОД", "#8B5A20", "#FFEBD3"),
}

FONT = "Segoe UI"


def ui_font(size: int = 10, bold: bool = False) -> tuple:
    return (FONT, size, "bold" if bold else "normal")


_SS = 6                                   # суперсэмплинг для сглаживания краёв
_CORNERS: dict[tuple, ImageTk.PhotoImage] = {}
_OVALS: dict[tuple, ImageTk.PhotoImage] = {}


def _rgb(hex_color: str) -> tuple[int, int, int]:
    return int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)


def _corner_image(r: int, fill: str, outline: str, ow: int, corner: str) -> ImageTk.PhotoImage:
    """Один скруглённый угол r x r со сглаживанием (альфа-канал). Рисуется в масштабе _SS
    и уменьшается, поэтому край получается плавным, а не «лесенкой»."""
    key = (r, fill, outline, ow, corner)
    img = _CORNERS.get(key)
    if img is not None:
        return img
    s = r * _SS
    border = bool(outline and ow)
    base = _rgb(outline if border else (fill or "#000000"))      # цвет прозрачных пикселей = цвет края, без тёмной каймы
    big = Image.new("RGBA", (2 * s, 2 * s), base + (0,))
    d = ImageDraw.Draw(big)
    if border:
        d.ellipse((0, 0, 2 * s - 1, 2 * s - 1), fill=_rgb(outline) + (255,))
        inner = ow * _SS
        if fill:
            d.ellipse((inner, inner, 2 * s - 1 - inner, 2 * s - 1 - inner), fill=_rgb(fill) + (255,))
    elif fill:
        d.ellipse((0, 0, 2 * s - 1, 2 * s - 1), fill=_rgb(fill) + (255,))
    box = {"nw": (0, 0, s, s), "ne": (s, 0, 2 * s, s), "sw": (0, s, s, 2 * s), "se": (s, s, 2 * s, 2 * s)}[corner]
    photo = ImageTk.PhotoImage(big.crop(box).resize((r, r), Image.LANCZOS))
    _CORNERS[key] = photo
    return photo


def aa_oval(canvas: tk.Canvas, x1: float, y1: float, x2: float, y2: float, fill: str, tags=()):
    """Сглаженный круг/эллипс (картинка с альфа-каналом)."""
    w, h = max(1, round(x2 - x1)), max(1, round(y2 - y1))
    key = (w, h, fill)
    photo = _OVALS.get(key)
    if photo is None:
        big = Image.new("RGBA", (w * _SS, h * _SS), _rgb(fill) + (0,))
        ImageDraw.Draw(big).ellipse((0, 0, w * _SS - 1, h * _SS - 1), fill=_rgb(fill) + (255,))
        photo = ImageTk.PhotoImage(big.resize((w, h), Image.LANCZOS))
        _OVALS[key] = photo
    return canvas.create_image(round(x1), round(y1), image=photo, anchor="nw", tags=tags)


def rrect(canvas: tk.Canvas, x1: float, y1: float, x2: float, y2: float, r: float, **kw) -> None:
    """Скруглённый прямоугольник с плавными углами.

    Прямые участки - обычные прямоугольники Tk (Tk рисует их как [x1, x2) x [y1, y2)),
    углы - сглаженные картинки с альфа-каналом. Параметры как у create_polygon:
    fill, outline, width, tags."""
    fill = kw.get("fill") or ""
    outline = kw.get("outline") or ""
    ow = int(kw.get("width", 0) or 0) if outline else 0
    tags = kw.get("tags", ())
    x1, y1, x2, y2 = (int(round(v)) for v in (x1, y1, x2, y2))
    w, h = x2 - x1, y2 - y1
    if w <= 0 or h <= 0:
        return
    r = int(max(0, min(round(r), w // 2, h // 2)))

    def rect(a: int, b: int, c: int, d: int, color: str) -> None:
        if c > a and d > b and color:
            canvas.create_rectangle(a, b, c, d, fill=color, outline="", width=0, tags=tags)

    if r < 2:
        rect(x1, y1, x2, y2, outline or fill)
        if outline:
            rect(x1 + ow, y1 + ow, x2 - ow, y2 - ow, fill)
        return
    # тело: центральная полоса на всю высоту и боковые полосы между углами (с нахлёстом 1 px под углы)
    rect(x1 + r - 1, y1, x2 - r + 1, y2, fill)
    rect(x1, y1 + r - 1, x1 + r, y2 - r + 1, fill)
    rect(x2 - r, y1 + r - 1, x2, y2 - r + 1, fill)
    if ow:
        rect(x1 + r - 1, y1, x2 - r + 1, y1 + ow, outline)
        rect(x1 + r - 1, y2 - ow, x2 - r + 1, y2, outline)
        rect(x1, y1 + r - 1, x1 + ow, y2 - r + 1, outline)
        rect(x2 - ow, y1 + r - 1, x2, y2 - r + 1, outline)
    for corner, (cx, cy) in (("nw", (x1, y1)), ("ne", (x2 - r, y1)), ("sw", (x1, y2 - r)), ("se", (x2 - r, y2 - r))):
        canvas.create_image(cx, cy, image=_corner_image(r, fill, outline, ow, corner), anchor="nw", tags=tags)


def apply_window_chrome(root: tk.Tk) -> None:
    """Windows 11: тёмная строка заголовка и скруглённые углы окна через DWM.
    На других системах и при ошибке ничего не делает (окно остаётся обычным)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        dwm = ctypes.windll.dwmapi
        dwm.DwmSetWindowAttribute.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
        dwm.DwmSetWindowAttribute.restype = ctypes.c_long
        hwnd = int(root.wm_frame(), 16)

        def put(attr: int, value: int) -> int:
            v = ctypes.c_int(value)
            return dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))

        def colorref(hex_color: str) -> int:
            r, g, b = int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)
            return r | (g << 8) | (b << 16)

        if put(20, 1) != 0:          # DWMWA_USE_IMMERSIVE_DARK_MODE (старые сборки Win10 - атрибут 19)
            put(19, 1)
        put(33, 2)                   # DWMWA_WINDOW_CORNER_PREFERENCE = DWMWCP_ROUND
        put(35, colorref(PALETTE["bg"]))     # DWMWA_CAPTION_COLOR
        put(36, colorref(PALETTE["text"]))   # DWMWA_TEXT_COLOR
    except Exception:  # noqa: BLE001 - косметика, не должна ломать запуск
        pass


# ------------------------------------------------------------------ карточка

class Card(tk.Canvas):
    """Скруглённая карточка. Содержимое кладётся в ``card.body`` (обычный tk.Frame).
    fit=True - высота карточки подстраивается под содержимое."""

    def __init__(self, master, bg, fill=None, radius: int = 14, pad: int = 14, fit: bool = False,
                 height: int | None = None):
        self._fill = fill or PALETTE["card"]
        self._r = radius
        self._pad = pad
        self._fit = fit
        self._fit_h: int | None = None
        super().__init__(master, bg=bg, highlightthickness=0, bd=0, width=200, height=height or 120)
        self.body = tk.Frame(self, bg=self._fill)
        self._win = self.create_window(pad, pad, anchor="nw", window=self.body)
        self.bind("<Configure>", self._on_resize)
        self.body.bind("<Configure>", self._on_body)

    def _on_resize(self, e: tk.Event) -> None:
        self.delete("bg")
        rrect(self, 1, 1, e.width - 1, e.height - 1, self._r, fill=self._fill,
              outline=PALETTE["border"], width=1, tags="bg")
        self.tag_lower("bg")
        self.itemconfigure(self._win, width=max(1, e.width - 2 * self._pad),
                           height=max(1, e.height - 2 * self._pad))

    def _on_body(self, _e: tk.Event) -> None:
        if self._fit:
            want = self.body.winfo_reqheight() + 2 * self._pad
            if want != self._fit_h:
                self._fit_h = want
                self.configure(height=want)


# ------------------------------------------------------------------ кнопка

class RoundButton(tk.Canvas):
    """Кнопка-таблетка. variant: 'primary' (акцент), 'ghost' (обычная), 'chip' (переключатель)."""

    def __init__(self, master, text: str, command=None, bg: str | None = None, variant: str = "ghost",
                 height: int = 38, radius: int = 999, font_size: int = 10):
        # radius=999 - полностью скруглённая «таблетка» (радиус ограничивается высотой / 2)
        self._text = text
        self._command = command
        self._variant = variant
        self._hover = self._down = self._active = self._focus = False
        self._enabled = True
        self._radius = radius
        self._font = tkfont.Font(family=FONT, size=font_size)
        self._font_b = tkfont.Font(family=FONT, size=font_size, weight="bold")
        super().__init__(master, width=self._want_width(), height=height, bg=bg or PALETTE["bg"],
                         highlightthickness=0, bd=0, cursor="hand2", takefocus=1)
        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<FocusIn>", lambda _e: self._set_focus(True))
        self.bind("<FocusOut>", lambda _e: self._set_focus(False))
        self.bind("<Return>", self._on_key)
        self.bind("<space>", self._on_key)

    def _want_width(self) -> int:
        pad = {"primary": 52, "chip": 28}.get(self._variant, 36)
        font = self._font_b if self._variant == "primary" else self._font
        return int(font.measure(self._text)) + pad

    def _colors(self) -> tuple[str, str]:
        p = PALETTE
        if not self._enabled:
            return p["border"], p["muted"]
        if self._variant == "primary":
            fill = p["accent_hi"] if self._hover else p["accent"]
            return fill, p["accent_text"]
        if self._variant == "chip" and self._active:
            fill = p["accent_hi"] if self._hover else p["accent"]
            return fill, p["accent_text"]
        fill = p["card_sel"] if self._hover else p["card_hi"]
        if self._down:
            fill = p["border"]
        fg = p["muted"] if (self._variant == "chip" and not self._hover) else p["text"]
        return fill, fg

    def _draw(self) -> None:
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w <= 2:
            return
        fill, fg = self._colors()
        kw = {"fill": fill}
        if self._focus:
            kw.update(outline=PALETTE["accent_hi"], width=2)
        rrect(self, 1, 1, w - 1, h - 1, min(self._radius, h / 2), **kw)
        font = self._font_b if self._variant == "primary" else self._font
        self.create_text(w / 2, h / 2, text=self._text, fill=fg, font=font)

    def _on_enter(self, _e) -> None:
        self._hover = True
        self._draw()

    def _on_leave(self, _e) -> None:
        self._hover = self._down = False
        self._draw()

    def _on_press(self, _e) -> None:
        if self._enabled:
            self._down = True
            self.focus_set()
            self._draw()

    def _on_release(self, _e) -> None:
        was_down = self._down
        self._down = False
        self._draw()
        if was_down and self._hover and self._enabled and self._command:
            self._command()

    def _on_key(self, _e) -> None:
        if self._enabled and self._command:
            self._command()

    def _set_focus(self, on: bool) -> None:
        self._focus = on
        self._draw()

    def set_text(self, text: str) -> None:
        self._text = text
        self.configure(width=self._want_width())
        self._draw()

    def set_active(self, on: bool) -> None:
        self._active = bool(on)
        self._draw()

    def set_enabled(self, on: bool) -> None:
        self._enabled = bool(on)
        self.configure(cursor="hand2" if on else "arrow")
        self._draw()


# ------------------------------------------------------------------ выпадающий список

class DropdownButton(tk.Canvas):
    """Кнопка-выпадающий список: показывает текущий вариант и стрелку вниз.
    По клику открывается меню под кнопкой. Мышь: выбор кликом, уход из меню кликом мимо.
    Клавиатура: Вниз/Вверх - выбор, Enter - применить, Esc - закрыть."""

    def __init__(self, master, options: list[tuple[str, str]], value: str, on_change=None,
                 bg: str | None = None, height: int = 38, font_size: int = 10):
        self._opts = list(options)              # имя _options занято самим tkinter
        self._value = value
        self._on_change = on_change
        self._hover = self._focus = False
        self._pop: tk.Toplevel | None = None
        self._pop_rows: list[tk.Label] = []
        self._mi = 0
        self._font = tkfont.Font(family=FONT, size=font_size)
        self._pad_l = 18
        self._arrow_room = 62                   # место под стрелку справа, текст до неё не доходит
        width = max(self._font.measure(lbl) for _, lbl in self._opts) + self._pad_l + self._arrow_room
        super().__init__(master, width=width, height=height, bg=bg or PALETTE["bg"],
                         highlightthickness=0, bd=0, cursor="hand2", takefocus=1)
        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", lambda _e: (self.focus_set(), self._toggle()))
        self.bind("<Return>", lambda _e: self._toggle())
        self.bind("<space>", lambda _e: self._toggle())
        self.bind("<Down>", lambda _e: self._open() if self._pop is None else None)
        self.bind("<FocusIn>", lambda _e: self._set_focus(True))
        self.bind("<FocusOut>", lambda _e: self._set_focus(False))

    def _label(self, value: str) -> str:
        return next((lbl for v, lbl in self._opts if v == value), value)

    def _draw(self) -> None:
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w <= 2:
            return
        p = PALETTE
        fill = p["card_sel"] if (self._hover or self._pop is not None) else p["card_hi"]
        kw = {"fill": fill, "outline": p["accent"] if self._hover or self._pop is not None else p["border"],
              "width": 1}
        if self._focus:
            kw.update(outline=p["accent_hi"], width=2)
        rrect(self, 1, 1, w - 1, h - 1, min(999, h / 2), **kw)
        self.create_text(self._pad_l, h / 2, text=self._label(self._value), anchor="w",
                         fill=p["text"], font=self._font)
        # разделитель и стрелка вниз (две линии-уголка, толщиной 2 px)
        sx = w - self._arrow_room + 8
        self.create_line(sx, h * 0.28, sx, h * 0.72, fill=p["border"], width=1)
        cx, cy = sx + (self._arrow_room - 8) / 2, h / 2
        self.create_line(cx - 6, cy - 2, cx, cy + 3, cx + 6, cy - 2, fill=p["accent"], width=2,
                         capstyle="round", joinstyle="round")

    def _set_focus(self, on: bool) -> None:
        self._focus = on
        self._draw()

    def _on_enter(self, _e) -> None:
        self._hover = True
        self._draw()

    def _on_leave(self, _e) -> None:
        self._hover = False
        self._draw()

    def set_value(self, value: str) -> None:
        self._value = value
        self._draw()

    # --- меню
    def _toggle(self) -> None:
        if self._pop is None:
            self._open()
        else:
            self._close()

    def _open(self) -> None:
        self.update_idletasks()
        menu = tk.Toplevel(self)
        menu.withdraw()
        menu.overrideredirect(True)
        menu.configure(bg=PALETTE["border"])
        frame = tk.Frame(menu, bg=PALETTE["panel"], padx=4, pady=4)
        frame.pack(padx=1, pady=1)
        self._pop = menu
        self._pop_rows = []
        current = next((i for i, (v, _) in enumerate(self._opts) if v == self._value), 0)
        for i, (val, lbl) in enumerate(self._opts):
            row = tk.Label(frame, text=lbl, anchor="w", font=ui_font(10), padx=16, pady=7, cursor="hand2")
            row.pack(fill="x")
            row.bind("<Enter>", lambda _e, i=i: self._highlight(i))
            row.bind("<Button-1>", lambda _e, v=val: self._choose(v))
            self._pop_rows.append(row)
        self._highlight(current)
        menu.update_idletasks()
        w = max(self.winfo_width(), menu.winfo_reqwidth())
        h = menu.winfo_reqheight()
        x, y = self.winfo_rootx(), self.winfo_rooty() + self.winfo_height() + 4
        menu.geometry(f"{w}x{h}+{x}+{y}")
        menu.bind("<Escape>", lambda _e: self._close())
        menu.bind("<Up>", lambda _e: self._move(-1))
        menu.bind("<Down>", lambda _e: self._move(1))
        menu.bind("<Return>", lambda _e: self._choose(self._opts[self._mi][0]))
        menu.bind("<Button-1>", self._on_menu_click)
        menu.deiconify()
        menu.focus_force()
        self._draw()
        self.after(30, self._capture)          # захват мыши: клик мимо меню закрывает его

    def _capture(self) -> None:
        if self._pop is None:
            return
        try:
            self._pop.grab_set()
        except tk.TclError:
            pass

    def _highlight(self, i: int) -> None:
        self._mi = i
        for k, row in enumerate(self._pop_rows):
            on = k == i
            is_current = self._opts[k][0] == self._value
            row.configure(bg=PALETTE["row_hover"] if on else PALETTE["panel"],
                          fg=PALETTE["accent"] if is_current else PALETTE["text"])

    def _move(self, step: int) -> None:
        if self._pop_rows:
            self._highlight((self._mi + step) % len(self._opts))

    def _on_menu_click(self, e: tk.Event) -> None:
        m = self._pop
        if m is None:
            return
        inside = (m.winfo_rootx() <= e.x_root < m.winfo_rootx() + m.winfo_width()
                  and m.winfo_rooty() <= e.y_root < m.winfo_rooty() + m.winfo_height())
        if not inside:
            self._close()

    def _choose(self, value: str) -> None:
        self._close()
        if value != self._value:
            self._value = value
            self._draw()
            if self._on_change:
                self._on_change(value)

    def _close(self) -> None:
        m = self._pop
        if m is None:
            return
        self._pop = None
        self._pop_rows = []
        try:
            m.grab_release()
        except tk.TclError:
            pass
        try:
            m.destroy()
        except tk.TclError:
            pass
        self._draw()


# ------------------------------------------------------------------ поле ввода

class RoundEntry(tk.Canvas):
    """Поле ввода в скруглённой рамке: tk.Entry встроен внутрь Canvas."""

    def __init__(self, master, bg: str, textvariable: tk.StringVar | None = None,
                 height: int = 38, width: int = 200):
        super().__init__(master, height=height, width=width, bg=bg, highlightthickness=0, bd=0)
        self._focus = False
        self.entry = tk.Entry(self, textvariable=textvariable, bg=PALETTE["card_hi"], fg=PALETTE["text"],
                              insertbackground=PALETTE["accent"], relief="flat", bd=0, highlightthickness=0,
                              font=ui_font(10), selectbackground=PALETTE["accent"],
                              selectforeground=PALETTE["accent_text"])
        self._win = self.create_window(14, height / 2, anchor="w", window=self.entry)
        self.entry.bind("<FocusIn>", lambda _e: self._set_focus(True))
        self.entry.bind("<FocusOut>", lambda _e: self._set_focus(False))
        self.bind("<Configure>", self._on_resize)
        self.bind("<Button-1>", lambda _e: self.entry.focus_set())

    def _set_focus(self, on: bool) -> None:
        self._focus = on
        self._draw()

    def _on_resize(self, e: tk.Event) -> None:
        self._draw()
        self.itemconfigure(self._win, width=max(40, e.width - 28))
        self.coords(self._win, 14, e.height / 2)

    def _draw(self) -> None:
        self.delete("bg")
        w, h = self.winfo_width(), self.winfo_height()
        if w <= 2:
            return
        rrect(self, 1, 1, w - 1, h - 1, 10, fill=PALETTE["card_hi"],
              outline=PALETTE["accent"] if self._focus else PALETTE["border"],
              width=2 if self._focus else 1, tags="bg")
        self.tag_lower("bg")


# ------------------------------------------------------------------ переключатель

class Toggle(tk.Frame):
    """Переключатель-пилюля с подписью. Клик по подписи тоже переключает."""

    def __init__(self, master, text: str, variable: tk.BooleanVar, bg: str):
        super().__init__(master, bg=bg)
        self._var = variable
        self._cv = tk.Canvas(self, width=40, height=22, bg=bg, highlightthickness=0, bd=0, cursor="hand2")
        self._cv.pack(side="left", padx=(0, 10))
        self._lbl = tk.Label(self, text=text, bg=bg, fg=PALETTE["text"], font=ui_font(10), cursor="hand2")
        self._lbl.pack(side="left")
        for w in (self._cv, self._lbl):
            w.bind("<Button-1>", self._toggle)
        variable.trace_add("write", lambda *_: self._draw())
        self._draw()

    def _toggle(self, _e=None) -> None:
        self._var.set(not self._var.get())

    def _draw(self) -> None:
        cv = self._cv
        cv.delete("all")
        on = bool(self._var.get())
        rrect(cv, 1, 1, 39, 21, 10, fill=PALETTE["accent"] if on else PALETTE["card_hi"],
              outline=PALETTE["accent"] if on else PALETTE["border"], width=1)
        cx = 30 if on else 10
        aa_oval(cv, cx - 7, 4, cx + 7, 18, PALETTE["accent_text"] if on else PALETTE["muted"])


# ------------------------------------------------------------------ выбор из набора

class ChipGroup(tk.Frame):
    """Одиночный выбор из набора кнопок-пилюль. wrap=True - перенос строк по ширине."""

    ROW_H = 30
    GAP = 8

    def __init__(self, master, options: list[tuple[str, str]], variable: tk.StringVar, bg: str,
                 wrap: bool = True, on_change=None):
        super().__init__(master, bg=bg)
        self._var = variable
        self._wrap = wrap
        self._on_change = on_change
        self._buttons: dict[str, RoundButton] = {}
        self._visible: set[str] | None = None      # None - показывать все
        for value, label in options:
            self._buttons[value] = RoundButton(self, label, command=lambda v=value: self._pick(v), bg=bg,
                                               variant="chip", height=self.ROW_H, radius=self.ROW_H // 2,
                                               font_size=9)
        self.bind("<Configure>", lambda _e: self._layout())
        variable.trace_add("write", lambda *_: self._sync())
        self._sync()
        self._layout()

    def _pick(self, value: str) -> None:
        self._var.set(value)
        if self._on_change:
            self._on_change(value)

    def _sync(self) -> None:
        for value, b in self._buttons.items():
            b.set_active(value == self._var.get())

    def set_labels(self, labels: dict[str, str]) -> None:
        for value, text in labels.items():
            if value in self._buttons:
                self._buttons[value].set_text(text)
        self._layout()

    def set_visible(self, values: set[str]) -> None:
        """Показывает только перечисленные варианты (остальные скрыты, без пустых «хвостов»)."""
        self._visible = set(values)
        self._layout()

    def _layout(self) -> None:
        if self._wrap:
            width = self.winfo_width() or 520
        else:
            width = 10 ** 6
        x = y = 0
        used = 0
        for value, b in self._buttons.items():
            if self._visible is not None and value not in self._visible:
                b.place_forget()
                continue
            bw = int(b.cget("width"))
            if x and x + bw > width:
                x = 0
                y += self.ROW_H + self.GAP
            b.place(x=x, y=y)
            x += bw + self.GAP
            used = max(used, x - self.GAP)
        height = y + self.ROW_H
        if self._wrap:
            self.configure(height=height)
        else:
            self.configure(height=height, width=used)


# ------------------------------------------------------------------ снежный прогресс

class SnowBar(tk.Canvas):
    """Прогресс-бар, который заполняется снегом. Сверху падают снежинки,
    по центру - проценты. Двигается плавно к заданному значению."""

    TICK_MS = 40

    def __init__(self, master, bg: str, height: int = 38):
        super().__init__(master, height=height, width=300, bg=bg, highlightthickness=0, bd=0)
        self._shown = 0.0
        self._target = 0.0
        self._busy = False
        self._flakes: list[list[float]] = []   # [x, y, скорость, радиус]
        self.bind("<Configure>", lambda _e: self._draw())
        self.after(self.TICK_MS, self._tick)

    def set(self, pct: float, busy: bool | None = None) -> None:
        self._target = max(0.0, min(100.0, float(pct)))
        if busy is not None:
            self._busy = bool(busy)

    def _tick(self) -> None:
        try:
            d = self._target - self._shown
            self._shown += d * 0.25 if abs(d) > 0.2 else d
            w, h = self.winfo_width(), self.winfo_height()
            if w > 8 and h > 8:
                x_end = 2 + (w - 4) * self._shown / 100.0
                if self._busy and self._shown > 0.5:
                    for _ in range(2):
                        self._flakes.append([random.uniform(4, max(5.0, x_end - 2)), 1.0,
                                             random.uniform(0.6, 1.6), random.uniform(1.0, 2.2)])
                alive = []
                for f in self._flakes:
                    f[1] += f[2]
                    f[0] += random.uniform(-0.2, 0.2)
                    if f[1] < h - 4:
                        alive.append(f)
                self._flakes = alive[-150:]
            self._draw()
            self.after(self.TICK_MS, self._tick)
        except tk.TclError:
            return  # окно закрыто

    def _draw(self) -> None:
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w <= 8:
            return
        rrect(self, 1, 1, w - 1, h - 1, (h - 2) / 2, fill=PALETTE["track"], outline=PALETTE["border"], width=1)
        fw = (w - 4) * self._shown / 100.0
        if fw >= 4:
            r = min((h - 4) / 2, fw / 2)
            rrect(self, 2, 2, 2 + fw, h - 2, r, fill=PALETTE["snow"])
            x = 8.0
            while x < 2 + fw - 6:                    # снежные «шапки» по верхнему краю
                rad = 3 + (int(x) % 3) * 0.6
                self.create_oval(x - rad, 3 - rad * 0.5, x + rad, 3 + rad, fill="#FFFFFF", outline="")
                x += 13
        for x, y, _vy, rad in self._flakes:
            self.create_oval(x - rad, y - rad, x + rad, y + rad, fill="#FFFFFF", outline="")
        fg = PALETTE["accent_text"] if self._shown > 50 else PALETTE["text"]
        self.create_text(w / 2, h / 2, text=f"{self._shown:.0f}%", fill=fg, font=ui_font(10, True))


# ------------------------------------------------------------------ полоса прокрутки

class RoundScrollbar(tk.Canvas):
    """Тонкая скруглённая полоса прокрутки. Совместима с yscrollcommand / yview у Canvas и Text."""

    MIN_THUMB = 28

    def __init__(self, master, command, bg: str | None = None, width: int = 12):
        super().__init__(master, width=width, bg=bg or PALETTE["card"], highlightthickness=0, bd=0)
        self._command = command
        self._first = 0.0
        self._last = 1.0
        self._drag: float | None = None
        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._move)
        self.bind("<ButtonRelease-1>", self._release)

    def set(self, first, last) -> None:
        """Вызывается виджетом (yscrollcommand): доли видимой части 0..1."""
        self._first, self._last = float(first), float(last)
        self._draw()

    def _thumb(self) -> tuple[float, float]:
        h = self.winfo_height()
        top = h * self._first
        bottom = min(h, max(top + self.MIN_THUMB, h * self._last))
        return top, bottom

    def _draw(self) -> None:
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4 or h < 4:
            return
        rrect(self, 1, 1, w - 1, h - 1, (w - 2) / 2, fill=PALETTE["panel"])
        if self._last - self._first >= 0.999:
            return                                   # всё помещается - ползунок не нужен
        top, bottom = self._thumb()
        rrect(self, 3, top + 2, w - 3, bottom - 2, (w - 6) / 2, fill=PALETTE["thumb"])

    def _press(self, e: tk.Event) -> None:
        top, bottom = self._thumb()
        if top <= e.y <= bottom:
            self._drag = e.y - top
        else:
            self._drag = None
            self._command("scroll", -1 if e.y < top else 1, "pages")

    def _move(self, e: tk.Event) -> None:
        if self._drag is None:
            return
        h = max(1, self.winfo_height())
        frac = max(0.0, min(1.0, (e.y - self._drag) / h))
        self._command("moveto", str(frac))

    def _release(self, _e: tk.Event) -> None:
        self._drag = None


# ------------------------------------------------------------------ прокручиваемая область

class ScrollFrame(tk.Frame):
    """Область с вертикальной прокруткой. Содержимое (``.inner``) сдвигается через place()
    внутри обрезающей рамки ``.view``. Без Canvas: встроенные виджеты при прокрутке
    не оставляют артефактов. Полоса появляется только когда места не хватает."""

    STEP = 30

    def __init__(self, master, bg: str):
        super().__init__(master, bg=bg)
        self.view = tk.Frame(self, bg=bg)
        self.view.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.view, bg=bg)
        self.bar = RoundScrollbar(self, command=self._command, bg=bg)
        self._off = 0
        self._bar_shown = False
        self.view.bind("<Configure>", lambda _e: self._apply())
        self.inner.bind("<Configure>", lambda _e: self._apply())
        self.bind_all("<MouseWheel>", self._on_wheel, add="+")

    def _content_h(self) -> int:
        return max(1, self.inner.winfo_reqheight())

    def _view_h(self) -> int:
        return max(1, self.view.winfo_height())

    def _max_off(self) -> int:
        return max(0, self._content_h() - self._view_h())

    def _apply(self) -> None:
        self._off = max(0, min(int(self._off), self._max_off()))
        need = self._max_off() > 0
        if need != self._bar_shown:
            if need:
                self.bar.pack(side="right", fill="y", padx=(8, 0), before=self.view)
            else:
                self.bar.pack_forget()
            self._bar_shown = need
        self.inner.place(x=0, y=-self._off, width=max(1, self.view.winfo_width()))
        ch, vh = self._content_h(), self._view_h()
        self.bar.set(self._off / ch, min(1.0, (self._off + vh) / ch))

    def _command(self, *args) -> None:
        """Команды от полосы прокрутки: ('moveto', доля) или ('scroll', n, 'pages'|'units')."""
        ch, vh = self._content_h(), self._view_h()
        if args and args[0] == "moveto":
            self._off = float(args[1]) * ch
        elif args and args[0] == "scroll":
            n = int(args[1])
            self._off += n * (vh if len(args) > 2 and args[2] == "pages" else self.STEP)
        self._apply()

    def _on_wheel(self, e: tk.Event) -> None:
        """Колесо прокручивает область, только если указатель над ней."""
        try:
            w = self.winfo_containing(e.x_root, e.y_root)
        except (KeyError, tk.TclError):
            return
        if w is None:
            return
        path, me = str(w), str(self)
        if (path == me or path.startswith(me + ".")) and self._bar_shown:
            self._off -= int(e.delta / 120) * self.STEP
            self._apply()


# ------------------------------------------------------------------ список машин

class VehicleList(tk.Canvas):
    """Прокручиваемый список машин, сгруппированный по типам (сворачивается кликом по заголовку).
    Клик - выбрать, Ctrl+клик - добавить к выбору, двойной клик - действие on_activate."""

    ROW_H = 60
    HEAD_H = 40

    def __init__(self, master, lang, on_select=None, on_activate=None, on_hover=None):
        super().__init__(master, bg=PALETTE["card"], highlightthickness=0, bd=0)
        self.on_hover = on_hover               # (машина | None, x_root, y_root): указатель над строкой / ушёл
        self._lang = lang                      # функция -> 'russian' | 'english'
        self._groups: list[tuple[str, str, list]] = []
        self._by_key: dict[str, object] = {}
        self._collapsed: set[str] = set()
        self.selected: list[str] = []
        self._hover: str | None = None
        self._rows: list[tuple[float, float, str, str]] = []
        self.on_select = on_select
        self.on_activate = on_activate
        self.bind("<Configure>", lambda _e: self.redraw())
        self.bind("<Button-1>", self._click)
        self.bind("<Double-Button-1>", self._double)
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", self._leave)
        self.bind("<MouseWheel>", self._wheel)

    # --- данные
    def set_groups(self, groups: list[tuple[str, str, list]]) -> None:
        self._groups = groups
        self._by_key = {v.key: v for _, _, items in groups for v in items}
        self.selected = [k for k in self.selected if k in self._by_key]
        self.redraw()

    def selected_vehicles(self) -> list:
        return [self._by_key[k] for k in self.selected if k in self._by_key]

    def select_only(self, key: str) -> None:
        self.selected = [key]
        self.redraw()
        self._notify()

    # --- отрисовка
    def redraw(self) -> None:
        self.delete("all")
        width = self.winfo_width()
        if width < 50:
            return
        lang = self._lang()
        top = self.canvasy(0)
        bottom = top + self.winfo_height()
        self._rows = []
        y = 6
        for key, label, items in self._groups:
            is_open = key not in self._collapsed
            if y + self.HEAD_H >= top - 4 and y <= bottom + 4:        # рисуем только видимое
                self._draw_head(width, y, label, len(items), is_open)
            self._rows.append((y, y + self.HEAD_H, "head", key))
            y += self.HEAD_H
            if is_open:
                for v in items:
                    if y + self.ROW_H >= top - 4 and y <= bottom + 4:
                        self._draw_item(width, y, v, lang)
                    self._rows.append((y, y + self.ROW_H, "item", v.key))
                    y += self.ROW_H
                y += 6
        self.configure(scrollregion=(0, 0, width, max(y + 8, self.winfo_height())))

    def yview(self, *args):
        """Прокрутка (в том числе от полосы прокрутки) с перерисовкой видимой части."""
        result = super().yview(*args)
        if args:
            self.redraw()
        return result

    def _draw_head(self, width: int, y: float, label: str, count: int, is_open: bool) -> None:
        cy = y + self.HEAD_H / 2
        if is_open:
            pts = [14, cy - 3, 26, cy - 3, 20, cy + 4]        # стрелка вниз
        else:
            pts = [16, cy - 6, 16, cy + 6, 23, cy]            # стрелка вправо
        self.create_polygon(pts, fill=PALETTE["accent"], outline="")
        self.create_text(34, cy, text=tr(label), anchor="w", fill=PALETTE["accent"], font=ui_font(10, True))
        self.create_text(width - 18, cy, text=str(count), anchor="e", fill=PALETTE["muted"], font=ui_font(9))

    def _draw_item(self, width: int, y: float, v, lang: str) -> None:
        sel = v.key in self.selected
        hov = self._hover == v.key
        y0, y1 = y + 4, y + self.ROW_H - 4
        if sel:
            fill, outline, lw = PALETTE["row_sel"], PALETTE["accent"], 1
        elif hov:
            fill, outline, lw = PALETTE["row_hover"], "", 0
        else:
            fill, outline, lw = PALETTE["row"], "", 0
        rrect(self, 10, y0, width - 12, y1, 10, fill=fill, outline=outline, width=lw)
        self.create_text(24, y0 + 16, text=v.display_name(lang), anchor="w", fill=PALETTE["text"],
                         font=ui_font(10, True), width=max(120, width - 190))
        self.create_text(24, y0 + 37, text=f"{v.id}   ·   {tr(v.source_label)}", anchor="w",
                         fill=PALETTE["muted"], font=ui_font(8))
        label, badge_bg, badge_fg = SOURCE_BADGE.get(v.source, (v.source.upper(), PALETTE["card_hi"], PALETTE["text"]))
        bw = 52
        bx2 = width - 26
        cy = (y0 + y1) / 2
        rrect(self, bx2 - bw, cy - 10, bx2, cy + 10, 10, fill=badge_bg)
        self.create_text(bx2 - bw / 2, cy, text=tr(label), fill=badge_fg, font=ui_font(8, True))

    # --- события
    def _item_at(self, event: tk.Event) -> tuple[str | None, str | None]:
        cy = self.canvasy(event.y)
        for y0, y1, kind, key in self._rows:
            if y0 <= cy < y1:
                return kind, key
        return None, None

    def _click(self, e: tk.Event) -> None:
        kind, key = self._item_at(e)
        if self.on_hover:
            self.on_hover(None, 0, 0)
        if kind == "head":
            if key in self._collapsed:
                self._collapsed.discard(key)
            else:
                self._collapsed.add(key)
            self.redraw()
            return
        if kind != "item":
            return
        if e.state & 0x0004:                               # Ctrl
            if key in self.selected:
                self.selected.remove(key)
            else:
                self.selected.append(key)
        else:
            self.selected = [key]
        self.redraw()
        self._notify()

    def _double(self, e: tk.Event) -> None:
        kind, key = self._item_at(e)
        if kind != "item":
            return
        if key not in self.selected:
            self.select_only(key)
        if self.on_activate:
            self.on_activate()

    def _motion(self, e: tk.Event) -> None:
        kind, key = self._item_at(e)
        new = key if kind == "item" else None
        if new != self._hover:
            self._hover = new
            self.redraw()
        if self.on_hover:
            self.on_hover(self._by_key.get(new) if new else None, e.x_root, e.y_root)

    def _leave(self, _e: tk.Event) -> None:
        if self._hover is not None:
            self._hover = None
            self.redraw()
        if self.on_hover:
            self.on_hover(None, 0, 0)

    def _wheel(self, e: tk.Event) -> None:
        if self.on_hover:
            self.on_hover(None, 0, 0)
        self.yview_scroll(int(-e.delta / 120) * 3, "units")
        self.redraw()

    def _notify(self) -> None:
        if self.on_select:
            self.on_select(self.selected_vehicles())
