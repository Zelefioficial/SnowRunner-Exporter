"""
addon_picker.py
===============
Окно выбора деталей кастомизации для одной машины: группы по типу гнезда (бампер, глушитель, ...),
галочка на каждой детали, при наведении на строку - картинка, как деталь выглядит.
Результат - набор путей XML выбранных аддонов (по ним экспортёр узнаёт, что выгружать).
"""

from __future__ import annotations

import re
import tkinter as tk
from typing import Callable

import preview
from hover_preview import HoverPreview
from ui_kit import PALETTE as P, RoundButton, ScrollFrame, Toggle, apply_window_chrome, ui_font
from ui_lang import tr
from vehicle_parser import Addon, Vehicle

# Названия гнёзд: ключ - имя гнезда без префикса машины, в нижнем регистре, без разделителей.
# Значения - русские ключи для tr(); перевод на английский в ui_lang.py.
SOCKET_TITLES = {
    "bumper": "Бампер", "frontbumper": "Передний бампер", "rearbumper": "Задний бампер",
    "exhaust": "Глушитель", "snorkel": "Шноркель", "horn": "Сигнал", "horns": "Сигналы",
    "roofrack": "Багажник на крышу", "rooftoptrunk": "Багажник на крышу", "spotlight": "Прожекторы",
    "headlamp": "Фары", "beacon": "Маяк", "beaconfront": "Маяк передний", "gabarite": "Габаритные огни",
    "sparewheel": "Запасное колесо", "sparewheel2": "Запасное колесо 2", "visor": "Козырёк",
    "threshold": "Пороги", "fender": "Крылья", "trunkstuff": "Багаж", "wheeladdon": "Запасное колесо",
    "saddlehigh": "Седло", "saddlehigh1": "Седло", "bigcrane": "Большой кран", "bunklog": "Лесовозные коники",
    "addonhorns": "Сигналы", "addonhornssmall": "Сигналы малые",
    "stuffairfreshener": "Ароматизаторы", "stuffdashboard": "Игрушки на панели",
}


def _tokens(text: str) -> list[str]:
    out: list[str] = []
    for part in re.split(r"_+", text):
        out += [t for t in re.split(r"(?<=[a-z0-9])(?=[A-Z])", part) if t]
    return out


def socket_title(sock: str, v: Vehicle) -> str:
    """'Kolob74760Bumper' -> 'Бампер', 'InternationalScout800FrontBumper' -> 'Передний бампер'."""
    idn = v.id.replace("_", "").lower()
    toks = _tokens(sock)
    acc, i = "", 0
    while i < len(toks) and len(acc) < len(idn) and idn.startswith(acc + toks[i].lower()):
        acc += toks[i].lower()
        i += 1
    rest = toks[i:] if i and acc == idn else toks
    key = "".join(rest).lower()
    if key in SOCKET_TITLES:
        return tr(SOCKET_TITLES[key])
    if sock.lower() in SOCKET_TITLES:
        return tr(SOCKET_TITLES[sock.lower()])
    return " ".join(rest) or sock


class AddonPicker(tk.Toplevel):
    def __init__(self, app: tk.Tk, hover: HoverPreview, index, vehicle: Vehicle, addons: list[Addon],
                 strings: dict[str, str], selected: set[str], on_apply: Callable[[set[str]], None],
                 on_reset: Callable[[], None]):
        super().__init__(app)
        self.hover, self.index, self.v = hover, index, vehicle
        self.addons, self.strings = addons, strings
        self.on_apply, self.on_reset = on_apply, on_reset
        self.title(tr("Детали кастомизации: {id}", id=vehicle.id))
        self.configure(bg=P["bg"])
        self.geometry("640x740")
        self.minsize(520, 480)
        self.transient(app)
        self.vars = {a.path: tk.BooleanVar(value=a.path in selected) for a in addons}
        self.count_label: tk.Label
        self._groups: list[dict] = []
        self._build()
        for var in self.vars.values():
            var.trace_add("write", lambda *_: self._update_count())
        self._update_count()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.bind("<MouseWheel>", lambda _e: self.hover.hide(), add="+")
        self.after(150, lambda: apply_window_chrome(self))

    # ------------------------------------------------------------ интерфейс
    def _build(self) -> None:
        outer = tk.Frame(self, bg=P["bg"])
        outer.pack(fill="both", expand=True, padx=18, pady=16)
        tk.Label(outer, text=tr("Детали кастомизации"), bg=P["bg"], fg=P["text"], font=ui_font(15, True),
                 anchor="w").pack(fill="x")
        tk.Label(outer, text=tr("Отметьте, что выгружать. Наведите указатель на деталь, чтобы увидеть, как она выглядит. "
                                "Варианты одного гнезда в Blender лежат друг на друге."),
                 bg=P["bg"], fg=P["muted"], font=ui_font(9), anchor="w", justify="left",
                 wraplength=580).pack(fill="x", pady=(2, 10))

        bar = tk.Frame(outer, bg=P["bg"])
        bar.pack(fill="x", pady=(0, 10))
        RoundButton(bar, tr("Все"), command=lambda: self._set_all(True), bg=P["bg"], height=32,
                    font_size=9).pack(side="left", padx=(0, 6))
        RoundButton(bar, tr("Ничего"), command=lambda: self._set_all(False), bg=P["bg"], height=32,
                    font_size=9).pack(side="left", padx=(0, 6))
        RoundButton(bar, tr("Только тюнинг"), command=self._only_tuning, bg=P["bg"], height=32,
                    font_size=9).pack(side="left")
        self.count_label = tk.Label(bar, text="", bg=P["bg"], fg=P["muted"], font=ui_font(9))
        self.count_label.pack(side="right")

        self.scroll = ScrollFrame(outer, bg=P["bg"])
        self.scroll.pack(fill="both", expand=True)

        foot = tk.Frame(outer, bg=P["bg"])
        foot.pack(fill="x", pady=(12, 0))
        RoundButton(foot, tr("Применить"), command=self._apply, bg=P["bg"], variant="primary", height=42,
                    font_size=10).pack(side="right")
        RoundButton(foot, tr("Отмена"), command=self._close, bg=P["bg"], height=42).pack(side="right", padx=8)
        RoundButton(foot, tr("Сбросить выбор"), command=self._reset, bg=P["bg"], height=42).pack(side="left")

        by_group: dict[tuple[bool, str], list[Addon]] = {}
        for a in self.addons:
            by_group.setdefault((a.cosmetic, a.sockets[0]), []).append(a)
        for (cosmetic, sock), items in by_group.items():
            self._add_group(sock, items, cosmetic)

    def _add_group(self, sock: str, items: list[Addon], cosmetic: bool) -> None:
        box = tk.Frame(self.scroll.inner, bg=P["bg"])
        box.pack(fill="x", pady=(0, 8))
        head = tk.Frame(box, bg=P["card"], cursor="hand2")
        head.pack(fill="x")
        title = socket_title(sock, self.v) + (f" {tr('(наклейки и мелочи)')}" if cosmetic else "")
        arrow = tk.Label(head, text="", bg=P["card"], fg=P["accent"], font=ui_font(10, True), width=2)
        arrow.pack(side="left", padx=(10, 0), pady=8)
        name = tk.Label(head, text=f"{title}  ({len(items)})", bg=P["card"], fg=P["accent"], font=ui_font(10, True),
                        anchor="w")
        name.pack(side="left", pady=8)
        for text, value in ((tr("ничего"), False), (tr("все"), True)):
            RoundButton(head, text, command=lambda it=items, val=value: self._set_group(it, val), bg=P["card"],
                        height=26, font_size=8).pack(side="right", padx=(0, 8), pady=4)
        body = tk.Frame(box, bg=P["bg"])
        group = {"items": items, "body": body, "arrow": arrow, "built": False, "open": False}
        self._groups.append(group)
        for w in (head, arrow, name):
            w.bind("<Button-1>", lambda _e, g=group: self._toggle_group(g))
        self._toggle_group(group, force=not cosmetic)

    def _toggle_group(self, g: dict, force: bool | None = None) -> None:
        g["open"] = (not g["open"]) if force is None else force
        g["arrow"].configure(text="v" if g["open"] else ">")
        if g["open"]:
            if not g["built"]:                      # строки создаются при первом раскрытии (наклеек много)
                for a in g["items"]:
                    self._add_row(g["body"], a)
                g["built"] = True
            g["body"].pack(fill="x", pady=(4, 0))
        else:
            g["body"].pack_forget()

    def _add_row(self, parent: tk.Frame, a: Addon) -> None:
        row = tk.Frame(parent, bg=P["row"])
        row.pack(fill="x", pady=2)
        Toggle(row, self._label_for(a), self.vars[a.path], bg=P["row"]).pack(side="left", padx=10, pady=6)
        tk.Label(row, text=a.id, bg=P["row"], fg=P["muted"], font=ui_font(8)).pack(side="right", padx=10)
        title, sub = self._label_for(a), f"{a.id}  |  {socket_title(a.sockets[0], self.v)}"
        self._bind_hover(row, a, title, sub)

    def _label_for(self, a: Addon) -> str:
        text = self.strings.get(a.ui_name, "") if a.ui_name else ""
        return text or a.id.replace("_", " ")

    def _bind_hover(self, row: tk.Widget, a: Addon, title: str, sub: str) -> None:
        key = f"addon:{a.path}"

        def loader(a=a) -> bytes | None:
            return preview.addon_preview_png(self.index, a)

        def move(e: tk.Event) -> None:
            self.hover.show(key, title, sub, loader, e.x_root, e.y_root)

        def leave(e: tk.Event) -> None:
            w = row.winfo_containing(e.x_root, e.y_root)
            if w is None or not str(w).startswith(str(row)):
                self.hover.hide()

        def attach(w: tk.Widget) -> None:
            w.bind("<Motion>", move, add="+")
            w.bind("<Enter>", move, add="+")
            w.bind("<Leave>", leave, add="+")
            w.bind("<Button-1>", lambda _e: self.hover.hide(), add="+")
            for c in w.winfo_children():
                attach(c)

        attach(row)

    # ------------------------------------------------------------ выбор
    def _set_all(self, value: bool) -> None:
        for var in self.vars.values():
            var.set(value)

    def _only_tuning(self) -> None:
        for a in self.addons:
            self.vars[a.path].set(not a.cosmetic)

    def _set_group(self, items: list[Addon], value: bool) -> None:
        for a in items:
            self.vars[a.path].set(value)

    def _update_count(self) -> None:
        n = sum(1 for var in self.vars.values() if var.get())
        self.count_label.configure(text=tr("Выбрано: {n} из {m}", n=n, m=len(self.vars)))

    def _chosen(self) -> set[str]:
        return {path for path, var in self.vars.items() if var.get()}

    def _apply(self) -> None:
        self.on_apply(self._chosen())
        self._close()

    def _reset(self) -> None:
        self.on_reset()
        self._close()

    def _close(self) -> None:
        self.hover.hide()
        self.destroy()
