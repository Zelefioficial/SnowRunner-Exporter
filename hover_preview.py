"""
hover_preview.py
================
Всплывающая подсказка с картинкой при наведении. Картинка создаётся в фоновом потоке
(по одной за раз, сначала самая свежая заявка), в окне до этого стоит «Загрузка...».
Окно не принимает мышь: оно смещено от указателя и не перехватывает события списка.
"""

from __future__ import annotations

import io
import logging
import queue
import threading
import tkinter as tk
from collections import OrderedDict, deque
from typing import Callable

from PIL import Image, ImageTk

from ui_kit import PALETTE as P, ui_font
from ui_lang import tr

log = logging.getLogger("hover")

Loader = Callable[[], "bytes | None"]


class HoverPreview:
    DELAY_MS = 380
    CACHE_MAX = 80

    def __init__(self, root: tk.Misc):
        self.root = root
        self._win: tk.Toplevel | None = None
        self._img_label: tk.Label | None = None
        self._cache: OrderedDict[str, ImageTk.PhotoImage | None] = OrderedDict()
        self._key: str | None = None
        self._title = ""
        self._sub = ""
        self._pos = (0, 0)
        self._timer: str | None = None
        self._jobs: deque[tuple[str, Loader]] = deque()
        self._results: queue.Queue = queue.Queue()
        self._cv = threading.Condition()
        self._thread: threading.Thread | None = None
        self._polling = False

    # ------------------------------------------------------------ API
    def show(self, key: str, title: str, sub: str, loader: Loader, x_root: int, y_root: int) -> None:
        """Показать подсказку для key через небольшую паузу; повторный вызов с тем же key только двигает окно."""
        self._pos = (x_root, y_root)
        if key == self._key and (self._win is not None or self._timer is not None):
            self._place()
            return
        self.hide()
        self._key, self._title, self._sub = key, title, sub
        self._timer = self.root.after(self.DELAY_MS, lambda: self._open(key, loader))

    def hide(self) -> None:
        if self._timer is not None:
            try:
                self.root.after_cancel(self._timer)
            except tk.TclError:
                pass
            self._timer = None
        self._key = None
        if self._win is not None:
            try:
                self._win.destroy()
            except tk.TclError:
                pass
            self._win = None
            self._img_label = None

    # ------------------------------------------------------------ окно
    def _open(self, key: str, loader: Loader) -> None:
        self._timer = None
        if self._key != key:
            return
        self._build_window()
        if key in self._cache:
            self._cache.move_to_end(key)
            self._set_image(self._cache[key])
            return
        self._set_image("loading")
        self._enqueue(key, loader)
        self._start_poll()

    def _build_window(self) -> None:
        win = tk.Toplevel(self.root)
        win.withdraw()
        win.overrideredirect(True)
        try:
            win.attributes("-topmost", True)
        except tk.TclError:
            pass
        frame = tk.Frame(win, bg=P["card"], highlightbackground=P["accent"], highlightthickness=1)
        frame.pack()
        tk.Label(frame, text=self._title, bg=P["card"], fg=P["text"], font=ui_font(10, True), anchor="w",
                 justify="left", wraplength=400).pack(fill="x", padx=12, pady=(10, 0))
        if self._sub:
            tk.Label(frame, text=self._sub, bg=P["card"], fg=P["muted"], font=ui_font(8), anchor="w",
                     justify="left", wraplength=400).pack(fill="x", padx=12)
        self._img_label = tk.Label(frame, bg=P["card"], fg=P["muted"], font=ui_font(9), width=40, height=10)
        self._img_label.pack(padx=10, pady=10)
        self._win = win

    def _set_image(self, photo) -> None:
        if self._win is None or self._img_label is None:
            return
        if photo == "loading":
            self._img_label.configure(image="", text=tr("Загрузка превью..."), width=40, height=10)
        elif photo is None:
            self._img_label.configure(image="", text=tr("Превью недоступно"), width=40, height=4)
        else:
            self._img_label.configure(image=photo, text="", width=photo.width(), height=photo.height())
            self._img_label.image = photo
        self._place()
        self._win.deiconify()

    def _place(self) -> None:
        if self._win is None:
            return
        self._win.update_idletasks()
        w, h = self._win.winfo_reqwidth(), self._win.winfo_reqheight()
        sw, sh = self._win.winfo_screenwidth(), self._win.winfo_screenheight()
        x, y = self._pos[0] + 22, self._pos[1] + 18
        if x + w > sw - 8:
            x = max(8, self._pos[0] - w - 22)
        if y + h > sh - 48:
            y = max(8, sh - 48 - h)
        self._win.geometry(f"+{x}+{y}")

    # ------------------------------------------------------------ фоновая загрузка
    def _enqueue(self, key: str, loader: Loader) -> None:
        with self._cv:
            self._jobs.append((key, loader))
            if self._thread is None:
                self._thread = threading.Thread(target=self._work, daemon=True)
                self._thread.start()
            self._cv.notify()

    def _work(self) -> None:
        while True:
            with self._cv:
                while not self._jobs:
                    self._cv.wait()
                key, loader = self._jobs.pop()          # самая свежая заявка; остальные неактуальны
                self._jobs.clear()
            try:
                png = loader()
            except Exception:  # noqa: BLE001 - превью не должно ломать приложение
                log.exception("Не удалось построить превью %s", key)
                png = None
            self._results.put((key, png))

    def _start_poll(self) -> None:
        if not self._polling:
            self._polling = True
            self.root.after(60, self._poll)

    def _poll(self) -> None:
        try:
            while True:
                key, png = self._results.get_nowait()
                photo = None
                if png:
                    try:
                        photo = ImageTk.PhotoImage(Image.open(io.BytesIO(png)))
                    except Exception:  # noqa: BLE001
                        photo = None
                self._cache[key] = photo
                while len(self._cache) > self.CACHE_MAX:
                    self._cache.popitem(last=False)
                if key == self._key and self._win is not None:
                    self._set_image(photo)
        except queue.Empty:
            pass
        waiting = self._key is not None and self._key not in self._cache
        if waiting or not self._results.empty():
            self.root.after(60, self._poll)
        else:
            self._polling = False
