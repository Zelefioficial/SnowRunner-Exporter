"""
gui.py
======
Окно приложения: тёмная скруглённая тема (ui_kit.py), машины по типам,
снежный прогресс в процентах. Тяжёлая работа идёт в фоновом потоке,
результаты передаются в интерфейс через очередь. Язык интерфейса - ui_lang.py.
"""

from __future__ import annotations

import logging
import os
import queue
import re
import subprocess
import sys
import threading
import traceback
from collections import Counter
from dataclasses import replace
from pathlib import Path
import tkinter as tk
from tkinter import filedialog

import app_identity
import game_locator as gl
import paths
import preview
import ui_lang
from about import AboutDialog
from addon_picker import AddonPicker
from hover_preview import HoverPreview
from exporter import ExportOptions, export_vehicle
from pak_reader import PakIndex
from ui_kit import (PALETTE as P, Card, ChipGroup, DropdownButton, RoundButton, RoundEntry, RoundScrollbar, ScrollFrame,
                    SnowBar, Toggle, VehicleList, apply_window_chrome, ui_font)
from ui_lang import tr
from vehicle_parser import CATEGORIES, CATEGORY_LABELS, Vehicle, addons_for_vehicle, get_vehicles, load_strings

CACHE_PATH = gl.APP_DIR / "cache.json"
DEFAULT_OUTPUT = paths.DEFAULT_OUTPUT

# подписи (русские ключи переводятся через tr() при создании интерфейса)
SOURCE_OPTIONS = [("all", "Все"), ("base", "База"), ("dlc", "DLC"), ("mod", "Моды")]
LANG_OPTIONS = [("russian", "RU"), ("english", "EN")]          # язык названий машин, не интерфейса
LANGUI_OPTIONS = [("ru", "Русский"), ("en", "English")]        # язык интерфейса (названия на своих языках)
FORMAT_OPTIONS = [("glb", "GLB (основной)"), ("obj", "OBJ + MTL")]
EXPORT_OPTIONS = [
    ("textures", "Текстуры (PNG)"),
    ("include_wheels", "Колёса"),
    ("include_customization", "Кастомизация"),
    ("include_cosmetic", "Наклейки и мелочи в салоне"),
    ("skip_low_lod", "Без lp_ LOD"),
    ("skip_placeholders", "Без служебных объёмов"),
    ("flip_normal_green", "Инверсия зелёного нормалей"),
]
DEFAULTS = {"textures": True, "include_wheels": True, "include_customization": False, "include_cosmetic": False,
            "skip_low_lod": True, "skip_placeholders": True, "flip_normal_green": True}


def dlc_season(v: Vehicle) -> str | None:
    """Номер DLC: 'DLC dlc_14_1' -> '14', 'dlc_1_2' -> '1'; прочие (trial, ru_08) -> 'other'; не DLC -> None."""
    if v.source != "dlc":
        return None
    m = re.match(r"dlc_(\d+)", v.source_label.removeprefix("DLC ").strip().lower())
    return m.group(1) if m else "other"


def dlc_search_text(v: Vehicle) -> str:
    """Дополнительные слова для поиска: 'dlc 14', 'dlc14', 'dlc_14_1' находят машины DLC №14."""
    if v.source != "dlc":
        return ""
    key = v.source_label.removeprefix("DLC ").strip().lower()
    return f"{key} {key.replace('_', ' ')} {key.replace('_', '')}"


class _QueueHandler(logging.Handler):
    def __init__(self, q: queue.Queue):
        super().__init__()
        self.q = q

    def emit(self, record: logging.LogRecord) -> None:
        self.q.put(("log", record.levelno, f"{record.name}: {tr(record.getMessage())}"))


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("SnowRunner Exporter")
        self.geometry("1280x840")
        self.minsize(980, 640)
        self.configure(bg=P["bg"])
        app_identity.apply_window_icon(self)          # значок колеса в заголовке и панели задач

        self.cfg = gl.load_config()
        ui_lang.set_language(self.cfg.get("ui_language", "ru"))     # до сборки интерфейса
        self.q: queue.Queue = queue.Queue()
        self.index: PakIndex | None = None
        self.vehicles: list[Vehicle] = []
        self.busy = False

        self.search_var = tk.StringVar(value="")
        self.cat_var = tk.StringVar(value="all")
        self.src_var = tk.StringVar(value="all")
        self.dlc_var = tk.StringVar(value="all")
        self.lang_var = tk.StringVar(value=self.cfg.get("language", "russian"))
        self.fmt_var = tk.StringVar(value=self.cfg.get("format", "glb"))
        self.out_var = tk.StringVar(value=self.cfg.get("output_dir", str(DEFAULT_OUTPUT)))
        self.opt_vars = {k: tk.BooleanVar(value=self.cfg.get(k, d)) for k, d in DEFAULTS.items()}
        # выбор конкретных деталей кастомизации: ключ машины -> пути XML выбранных аддонов
        self.addon_choice: dict[str, set[str]] = {k: set(v) for k, v in self.cfg.get("addon_choice", {}).items()
                                                  if isinstance(v, list)}
        self.hover = HoverPreview(self)
        self._picker: AddonPicker | None = None
        self._about_win: AboutDialog | None = None
        self._strings: dict[str, dict[str, str]] = {}

        self._build()
        for var in (self.search_var, self.cat_var, self.src_var, self.dlc_var, self.lang_var):
            var.trace_add("write", lambda *_: self._refresh())

        handler = _QueueHandler(self.q)
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.INFO)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Control-f>", lambda _e: self.search.entry.focus_set())
        self.after(80, self._poll)
        self.after(250, self._startup)
        self.after(200, lambda: apply_window_chrome(self))
        self.after(300, lambda: app_identity.finalize_taskbar(self))   # значок окна и данные для закрепления

    # ------------------------------------------------------------ сборка интерфейса
    def _build(self) -> None:
        root = tk.Frame(self, bg=P["bg"])
        root.pack(fill="both", expand=True, padx=20, pady=18)
        root.columnconfigure(0, weight=1)
        root.columnconfigure(1, minsize=380)
        root.rowconfigure(1, weight=1)

        # шапка
        head = tk.Frame(root, bg=P["bg"])
        head.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 16))
        titles = tk.Frame(head, bg=P["bg"])
        titles.pack(side="left")
        tk.Label(titles, text="SnowRunner Exporter", bg=P["bg"], fg=P["text"],
                 font=ui_font(18, True)).pack(anchor="w")
        tk.Label(titles, text=tr("Экспорт машин SnowRunner в GLB и OBJ для Blender. Файлы игры только читаются."),
                 bg=P["bg"], fg=P["muted"], font=ui_font(9)).pack(anchor="w")
        actions = tk.Frame(head, bg=P["bg"])
        actions.pack(side="right")
        self.game_label = tk.Label(actions, text=tr("Игра не найдена"), bg=P["bg"], fg=P["warn"], font=ui_font(9))
        self.game_label.pack(side="left", padx=(0, 14))
        self.btn_reload = RoundButton(actions, tr("Обновить"), command=self._reload, bg=P["bg"])
        self.btn_reload.pack(side="left", padx=4)
        RoundButton(actions, tr("Папка игры..."), command=self._browse_game, bg=P["bg"]).pack(side="left", padx=4)
        RoundButton(actions, tr("Ярлык"), command=self._make_shortcut, bg=P["bg"]).pack(side="left", padx=4)
        RoundButton(actions, tr("О программе"), command=self._about, bg=P["bg"]).pack(side="left", padx=4)
        # выбор языка интерфейса: выпадающий список, показывает текущий язык
        DropdownButton(actions, LANGUI_OPTIONS, value=ui_lang.LANG, on_change=self._switch_language,
                       bg=P["bg"]).pack(side="left", padx=4)

        # левая колонка: список
        left = Card(root, P["bg"], radius=16, pad=16)
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 16))
        b = left.body

        tk.Label(b, text=tr("Поиск по названию или ID"), bg=P["card"], fg=P["muted"],
                 font=ui_font(9)).pack(anchor="w")
        self.search = RoundEntry(b, bg=P["card"], textvariable=self.search_var, height=38)
        self.search.pack(fill="x", pady=(6, 14))

        head_row = tk.Frame(b, bg=P["card"])
        head_row.pack(fill="x")
        tk.Label(head_row, text=tr("Тип машины"), bg=P["card"], fg=P["muted"], font=ui_font(9)).pack(side="left")
        self.count_label = tk.Label(head_row, text="", bg=P["card"], fg=P["muted"], font=ui_font(9))
        self.count_label.pack(side="right")
        self.cat_group = ChipGroup(b, [("all", tr("Все"))] + [(k, tr(lbl)) for k, lbl in CATEGORIES],
                                   self.cat_var, bg=P["card"])
        self.cat_group.pack(fill="x", pady=(8, 14))

        src_row = tk.Frame(b, bg=P["card"])
        src_row.pack(fill="x", pady=(0, 12))
        self.src_row = src_row
        ChipGroup(src_row, [(k, tr(lbl)) for k, lbl in SOURCE_OPTIONS], self.src_var, bg=P["card"],
                  wrap=False).pack(side="left")
        ChipGroup(src_row, LANG_OPTIONS, self.lang_var, bg=P["card"], wrap=False).pack(side="right")

        # номер DLC: появляется только при фильтре «DLC», чипы создаются после загрузки списка машин
        self.dlc_box = tk.Frame(b, bg=P["card"])
        tk.Label(self.dlc_box, text=tr("Номер DLC"), bg=P["card"], fg=P["muted"], font=ui_font(9)).pack(anchor="w")
        self.dlc_holder = tk.Frame(self.dlc_box, bg=P["card"])
        self.dlc_holder.pack(fill="x", pady=(6, 12))
        self.dlc_group: ChipGroup | None = None
        self._dlc_shown = False

        lst = tk.Frame(b, bg=P["card"])
        lst.pack(fill="both", expand=True)
        self.list = VehicleList(lst, lang=lambda: self.lang_var.get(),
                                on_select=self._on_select, on_activate=self._export, on_hover=self._vehicle_hover)
        sb = RoundScrollbar(lst, command=self.list.yview, bg=P["card"])
        self.list.configure(yscrollcommand=sb.set)
        self.list.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y", padx=(6, 0))

        # правая колонка: сведения и экспорт
        right = ScrollFrame(root, bg=P["bg"])          # правая колонка прокручивается при малой высоте окна
        right.grid(row=1, column=1, sticky="nsew")
        self.right_pane = right

        info = Card(right.inner, P["bg"], radius=16, pad=16, fit=True)
        info.pack(fill="x")
        ib = info.body
        self.info_title = tk.Label(ib, text=tr("Выберите машину"), bg=P["card"], fg=P["text"],
                                   font=ui_font(14, True), anchor="w", justify="left", wraplength=330)
        self.info_title.pack(fill="x")
        self.info_sub = tk.Label(ib, text=tr("Клик - выбрать, Ctrl+клик - несколько, двойной клик - экспорт."),
                                 bg=P["card"], fg=P["muted"], font=ui_font(9), anchor="w", justify="left",
                                 wraplength=330)
        self.info_sub.pack(fill="x", pady=(2, 10))
        grid = tk.Frame(ib, bg=P["card"])
        grid.pack(fill="x")
        self.info_vals: dict[str, tk.Label] = {}
        for i, (key, label) in enumerate([("cat", tr("Тип")), ("src", tr("Источник")),
                                          ("mesh", tr("Модель")), ("wheels", tr("Колёса"))]):
            tk.Label(grid, text=label, bg=P["card"], fg=P["muted"], font=ui_font(9),
                     anchor="w").grid(row=i, column=0, sticky="nw", pady=3, padx=(0, 16))
            val = tk.Label(grid, text="-", bg=P["card"], fg=P["text"], font=ui_font(9), anchor="w",
                           justify="left", wraplength=240)
            val.grid(row=i, column=1, sticky="w", pady=3)
            self.info_vals[key] = val
        grid.columnconfigure(1, weight=1)

        exp = Card(right.inner, P["bg"], radius=16, pad=16, fit=True)
        exp.pack(fill="x", pady=(14, 0))
        eb = exp.body
        tk.Label(eb, text=tr("Экспорт"), bg=P["card"], fg=P["text"], font=ui_font(12, True),
                 anchor="w").pack(fill="x")
        tk.Label(eb, text=tr("Формат"), bg=P["card"], fg=P["muted"], font=ui_font(9),
                 anchor="w").pack(fill="x", pady=(12, 6))
        ChipGroup(eb, [(k, tr(lbl)) for k, lbl in FORMAT_OPTIONS], self.fmt_var, bg=P["card"]).pack(fill="x")
        tk.Label(eb, text=tr("Папка вывода"), bg=P["card"], fg=P["muted"], font=ui_font(9),
                 anchor="w").pack(fill="x", pady=(12, 6))
        orow = tk.Frame(eb, bg=P["card"])
        orow.pack(fill="x")
        RoundEntry(orow, bg=P["card"], textvariable=self.out_var, width=180).pack(side="left", fill="x", expand=True)
        RoundButton(orow, tr("Выбрать..."), command=self._browse_out, bg=P["card"]).pack(side="left", padx=(8, 0))
        tk.Label(eb, text=tr("Что выгружать"), bg=P["card"], fg=P["muted"], font=ui_font(9),
                 anchor="w").pack(fill="x", pady=(12, 6))
        for key, text in EXPORT_OPTIONS:
            if key != "include_customization":
                Toggle(eb, tr(text), self.opt_vars[key], bg=P["card"]).pack(anchor="w", pady=3)
                continue
            # строка «Кастомизация»: галочка слева, кнопка выбора конкретных деталей справа
            crow = tk.Frame(eb, bg=P["card"])
            crow.pack(fill="x", pady=3)
            self.pick_row = crow
            Toggle(crow, tr(text), self.opt_vars[key], bg=P["card"]).pack(side="left")
            RoundButton(crow, tr("Выбрать..."), command=self._pick_addons, bg=P["card"], height=28,
                        font_size=9).pack(side="right")
            self.pick_label = tk.Label(eb, text="", bg=P["card"], fg=P["accent"], font=ui_font(9), anchor="w")
        btns = tk.Frame(eb, bg=P["card"])
        btns.pack(fill="x", pady=(16, 0))
        self.btn_export = RoundButton(btns, tr("Экспортировать"), command=self._export, bg=P["card"],
                                      variant="primary", height=46, font_size=11)
        self.btn_export.pack(fill="x")
        RoundButton(btns, tr("Открыть папку вывода"), command=self._open_out,
                    bg=P["card"]).pack(fill="x", pady=(8, 0))

        # журнал
        logcard = Card(root, P["bg"], fill=P["panel"], radius=14, pad=10, height=134)
        logcard.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(16, 0))
        lb = logcard.body
        self.log_text = tk.Text(lb, height=6, wrap="word", bg=P["panel"], fg=P["text"], relief="flat", bd=0,
                                highlightthickness=0, padx=8, pady=4, font=("Consolas", 9), state="disabled",
                                insertbackground=P["accent"], selectbackground=P["accent"])
        lsb = RoundScrollbar(lb, command=self.log_text.yview, bg=P["panel"])
        self.log_text.configure(yscrollcommand=lsb.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        lsb.pack(side="right", fill="y", padx=(6, 0))
        self.log_text.tag_configure("warn", foreground=P["warn"])
        self.log_text.tag_configure("err", foreground=P["err"])
        self.log_text.tag_configure("ok", foreground=P["ok"])

        # строка состояния со снежным прогрессом
        status = tk.Frame(root, bg=P["bg"])
        status.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        self.status_label = tk.Label(status, text=tr("Ожидание"), bg=P["bg"], fg=P["muted"], font=ui_font(10),
                                     anchor="w", width=44)
        self.status_label.pack(side="left")
        self.snow = SnowBar(status, bg=P["bg"], height=40)
        self.snow.pack(side="left", fill="x", expand=True, padx=(16, 0))

        self._refresh()

    # ------------------------------------------------------------ служебное
    def _log(self, text: str, tag: str | None = None) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n", tag or ())
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.btn_export.set_enabled(not busy)
        self.btn_reload.set_enabled(not busy)

    def _set_game_label(self, text: str, color: str) -> None:
        if len(text) > 44:                      # длинный путь не должен вытеснять кнопки шапки
            text = text[:14] + "..." + text[-27:]
        self.game_label.configure(text=text, fg=color)

    def _save_cfg(self) -> None:
        self.cfg.update(language=self.lang_var.get(), format=self.fmt_var.get(),
                        output_dir=self.out_var.get(), **{k: v.get() for k, v in self.opt_vars.items()})
        self.cfg["addon_choice"] = {k: sorted(v) for k, v in self.addon_choice.items()}
        gl.save_config(self.cfg)

    def _on_close(self) -> None:
        self.hover.hide()
        self._save_cfg()
        self.destroy()

    def _switch_language(self, target: str) -> None:
        """Сохраняет выбранный язык ('ru' или 'en') и перезапускает приложение:
        интерфейс собирается один раз при старте."""
        if target == ui_lang.LANG:
            return
        if self.busy:
            self._log(tr("Дождитесь окончания текущей операции."), "warn")
            return
        self.cfg["ui_language"] = target
        self._save_cfg()
        env = os.environ.copy()
        if paths.FROZEN:
            cmd = [sys.executable]
            # exe в одном файле (PyInstaller) запускает сам себя. Без сброса дочерний процесс наследует
            # служебные переменные родителя и берёт его временную папку _MEIxxxx, которую родитель удалит
            # при выходе («Failed to import encodings module», «Failed to remove temporary directory»).
            for key in list(env):
                if key.startswith(("_PYI", "_MEIPASS")):
                    del env[key]
            env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        else:
            cmd = [app_identity._pythonw(), str(Path(__file__).resolve().parent / "main.py")]
        flags = 0x00000008 if sys.platform == "win32" else 0       # DETACHED_PROCESS: новое окно не связано с этим
        subprocess.Popen(cmd, close_fds=True, creationflags=flags, env=env)
        self.hover.hide()
        self.destroy()

    def _about(self) -> None:
        if self._about_win is not None:
            try:
                self._about_win.lift()
                self._about_win.focus_set()
                return
            except tk.TclError:
                self._about_win = None
        self._about_win = AboutDialog(self)

    def _make_shortcut(self) -> None:
        try:
            path = app_identity.create_desktop_shortcut()
        except Exception as exc:  # noqa: BLE001
            self._log(tr("Не удалось создать ярлык: {exc}", exc=exc), "err")
            return
        self._log(tr("Ярлык создан: {path}. Закрепить: правая кнопка по ярлыку, «Закрепить на панели задач».",
                     path=path), "ok")

    # ------------------------------------------------------------ загрузка игры
    def _startup(self) -> None:
        game = gl.resolve_game_dir(self.cfg)
        if game:
            self._load(game)
        else:
            self._set_game_label(tr("Игра не найдена"), P["warn"])
            self.status_label.configure(text=tr("Укажите папку игры кнопкой «Папка игры»"))
            self._log(tr("SnowRunner не найден автоматически. Укажите папку игры."), "warn")

    def _browse_game(self) -> None:
        path = filedialog.askdirectory(title=tr("Папка установки SnowRunner"), mustexist=True)
        if not path:
            return
        game = gl.normalize_game_dir(path)
        if not game:
            self._log(tr("В выбранной папке нет preload\\paks\\client\\initial.pak. Выберите корень SnowRunner."),
                      "err")
            return
        self._load(game)

    def _reload(self) -> None:
        saved = self.cfg.get("game_dir")
        game = gl.normalize_game_dir(saved) if saved else None
        if not game:
            self._log(tr("Папка игры не задана."), "err")
            return
        self._load(game)

    def _load(self, game: Path) -> None:
        if self.busy:
            return
        self._set_busy(True)
        self.cfg["game_dir"] = str(game)
        gl.save_config(self.cfg)
        self._set_game_label(tr("Игра: {game}", game=game), P["ok"])
        self._log(tr("Игра: {game}", game=game))
        self.snow.set(0, busy=True)

        def work() -> None:
            try:
                idx = PakIndex()
                idx.add_game(gl.paks_dir(game), lambda f, m: self.q.put(("progress", f * 60, m)))
                mods = gl.list_mod_archives(gl.find_mods_dir())
                if mods:
                    self.q.put(("log", logging.INFO, tr("Найдено модов: {n}", n=len(mods))))
                idx.add_mods(mods, lambda f, m: self.q.put(("progress", 60 + f * 5, m)))
                vehicles = get_vehicles(idx, CACHE_PATH, lambda f, m: self.q.put(("progress", 65 + f * 35, m)))
                self.q.put(("loaded", idx, vehicles))
            except Exception as exc:  # noqa: BLE001 - показываем в логе, приложение не падает
                self.q.put(("load_error", f"{exc}\n{traceback.format_exc()}"))

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------ фильтры и список
    def _refresh(self) -> None:
        lang = self.lang_var.get()
        text = self.search_var.get().strip().lower()
        src = self.src_var.get()
        cat = self.cat_var.get()
        by_src = [v for v in self.vehicles
                  if (src == "all" or v.source == src)
                  and (not text or text in " ".join([v.id, *v.names.values(), dlc_search_text(v)]).lower())]
        want_dlc = src == "dlc" and self.dlc_group is not None
        if want_dlc != self._dlc_shown:
            self._dlc_shown = want_dlc
            if want_dlc:
                self.dlc_box.pack(fill="x", after=self.src_row)
            else:
                self.dlc_box.pack_forget()
        base = by_src
        if want_dlc:
            season_counts = Counter(dlc_season(v) for v in by_src)
            labels = {"all": f"{tr('Все DLC')} ({len(by_src)})"}
            labels.update({s: f"{self._season_title(s)} ({n})" for s, n in season_counts.items()})
            self.dlc_group.set_labels(labels)
            self.dlc_group.set_visible({"all"} | set(season_counts))
            season = self.dlc_var.get()
            if season != "all" and season not in season_counts:
                self.dlc_var.set("all")          # трассировка перерисует список
                return
            if season != "all":
                base = [v for v in by_src if dlc_season(v) == season]
        counts = Counter(v.category for v in base)
        labels = {"all": f"{tr('Все')} {len(base)}"}
        labels.update({key: f"{tr(label)} {counts.get(key, 0)}" for key, label in CATEGORIES})
        self.cat_group.set_labels(labels)
        # пустые типы скрываем, чтобы не было одиноких чипов в отдельной строке
        visible = {"all"} | {key for key, _ in CATEGORIES if counts.get(key, 0)}
        self.cat_group.set_visible(visible)
        if cat not in visible:
            self.cat_var.set("all")          # сбросится в «Все», и список обновится через трассировку
            return

        shown = [v for v in base if cat == "all" or v.category == cat]
        groups = []
        for key, label in CATEGORIES:
            items = sorted((v for v in shown if v.category == key), key=lambda v: v.display_name(lang).lower())
            if items:
                groups.append((key, label, items))
        self.list.set_groups(groups)
        self.count_label.configure(text=tr("показано {shown} из {total}", shown=len(shown), total=len(self.vehicles)))
        self._on_select(self.list.selected_vehicles())

    @staticmethod
    def _season_title(season: str) -> str:
        return tr("Прочие") if season == "other" else season

    def _rebuild_dlc_chips(self) -> None:
        """Чипы с номерами DLC по загруженному списку машин (1, 2, ... 19, прочие)."""
        seasons = sorted({s for s in map(dlc_season, self.vehicles) if s},
                         key=lambda s: (s == "other", int(s) if s.isdigit() else 0))
        if self.dlc_group is not None:
            self.dlc_group.destroy()
        options = [("all", tr("Все DLC"))] + [(s, self._season_title(s)) for s in seasons]
        self.dlc_group = ChipGroup(self.dlc_holder, options, self.dlc_var, bg=P["card"])
        self.dlc_group.pack(fill="x")

    # ------------------------------------------------------------ превью и выбор деталей
    def _vehicle_hover(self, v: Vehicle | None, x_root: int, y_root: int) -> None:
        """Наведение на строку списка: через паузу показывается картинка машины."""
        if v is None or self.index is None:
            self.hover.hide()
            return
        index = self.index
        sub = f"{v.id}  |  {v.type_label()}  |  {tr(v.source_label)}"
        self.hover.show(f"vehicle:{v.key}", v.display_name(self.lang_var.get()), sub,
                        lambda: preview.vehicle_preview_png(index, v), x_root, y_root)

    def _ui_strings(self) -> dict[str, str]:
        lang = self.lang_var.get()
        if lang not in self._strings and self.index is not None:
            self._strings[lang] = load_strings(self.index, lang)
        return self._strings.get(lang, {})

    def _current_vehicle(self) -> Vehicle | None:
        sel = self.list.selected_vehicles()
        return sel[-1] if sel else None

    def _update_pick_label(self) -> None:
        v = self._current_vehicle()
        if v is not None and v.key in self.addon_choice:
            self.pick_label.configure(text=tr("Выбрано деталей: {n}", n=len(self.addon_choice[v.key])))
            self.pick_label.pack(fill="x", padx=(50, 0), after=self.pick_row)
        else:
            self.pick_label.pack_forget()

    def _pick_addons(self) -> None:
        v = self._current_vehicle()
        if v is None or self.index is None:
            self._log(tr("Выберите машину в списке, затем нажмите «Выбрать...»."), "warn")
            return
        if self._picker is not None:
            try:
                self._picker.destroy()
            except tk.TclError:
                pass
        addons = addons_for_vehicle(self.index, v)
        if not addons:
            self._log(tr("{id}: деталей кастомизации не найдено.", id=v.id), "warn")
            return
        if v.key in self.addon_choice:
            selected = set(self.addon_choice[v.key])
        else:           # без своего выбора окно открывается с тем, что включено галочками
            selected = {a.path for a in addons
                        if (self.opt_vars["include_cosmetic"] if a.cosmetic
                            else self.opt_vars["include_customization"]).get()}

        def apply(chosen: set[str]) -> None:
            self.addon_choice[v.key] = chosen
            self._update_pick_label()
            self._save_cfg()
            self._log(tr("{id}: для экспорта выбрано деталей кастомизации: {n}", id=v.id, n=len(chosen)))

        def reset() -> None:
            self.addon_choice.pop(v.key, None)
            self._update_pick_label()
            self._save_cfg()

        self._picker = AddonPicker(self, self.hover, self.index, v, addons, self._ui_strings(), selected, apply, reset)

    def _on_select(self, vehicles: list[Vehicle]) -> None:
        self._update_pick_label()
        if not vehicles:
            self.info_title.configure(text=tr("Выберите машину"))
            for lbl in self.info_vals.values():
                lbl.configure(text="-")
            return
        v = vehicles[-1]
        if len(vehicles) == 1:
            self.info_title.configure(text=v.display_name(self.lang_var.get()))
            self.info_sub.configure(text=v.id)
        else:
            self.info_title.configure(text=tr("Выбрано машин: {n}", n=len(vehicles)))
            self.info_sub.configure(text=tr("Сведения ниже - для «{name}»",
                                            name=v.display_name(self.lang_var.get())))
        self.info_vals["cat"].configure(text=v.type_label())
        self.info_vals["src"].configure(text=tr(v.source_label))
        self.info_vals["mesh"].configure(text=v.mesh)
        self.info_vals["wheels"].configure(
            text=f"{len(v.wheels)} {tr('шт.')}" if v.wheels else tr("нет данных"))

    # ------------------------------------------------------------ экспорт
    def _browse_out(self) -> None:
        path = filedialog.askdirectory(title=tr("Папка вывода"))
        if path:
            self.out_var.set(path)

    def _open_out(self) -> None:
        p = Path(self.out_var.get().strip() or DEFAULT_OUTPUT)
        p.mkdir(parents=True, exist_ok=True)
        os.startfile(p)  # noqa: S606 - только Windows

    def _export(self) -> None:
        if self.busy:
            self._log(tr("Дождитесь окончания текущей операции."), "warn")
            return
        if self.index is None:
            self._log(tr("Список машин ещё не загружен."), "warn")
            return
        sel = self.list.selected_vehicles()
        if not sel:
            self._log(tr("Выберите машину в списке."), "warn")
            return
        out = Path(self.out_var.get().strip() or DEFAULT_OUTPUT)
        try:
            out.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._log(tr("Не удалось создать папку вывода: {exc}", exc=exc), "err")
            return
        opts = ExportOptions(fmt=self.fmt_var.get(), **{k: v.get() for k, v in self.opt_vars.items()})
        self._save_cfg()
        self._set_busy(True)
        self.snow.set(0, busy=True)
        index = self.index
        choice = {k: set(v) for k, v in self.addon_choice.items()}
        total = len(sel)

        def work() -> None:
            ok = fail = 0
            for n, v in enumerate(sel):
                self.q.put(("log", logging.INFO, f"=== {v.display_name('english')} ({v.id}) ==="))

                def on_progress(f: float, msg: str, n=n, v=v) -> None:
                    self.q.put(("progress", (n + f) / total * 100, f"{v.id}: {msg}"))
                try:
                    v_opts = replace(opts, addon_paths=frozenset(choice[v.key])) if v.key in choice else opts
                    res = export_vehicle(index, v, out, v_opts, on_progress)
                    s = res.stats
                    self.q.put(("done", tr("Готово: {file}  ({parts} деталей, {vertices} вершин, {triangles} треугольников, габариты {x} x {z} x {y} м, текстур {n})",
                                           file=res.model_file, parts=s["parts"], vertices=s["vertices"],
                                           triangles=s["triangles"], x=s["size_xyz_m"][0],
                                           z=s["size_xyz_m"][2], y=s["size_xyz_m"][1],
                                           n=len(res.texture_files))))
                    if res.custom_file:
                        cs = res.custom_stats
                        self.q.put(("done", tr("Кастомизация отдельным файлом: {file}  ({parts} деталей, {tris} треугольников)",
                                               file=res.custom_file, parts=cs.get("parts", 0),
                                               tris=cs.get("triangles", 0))))
                    for w in res.warnings:
                        self.q.put(("log", logging.WARNING, f"{v.id}: {tr(w)}"))
                    ok += 1
                except Exception as exc:  # noqa: BLE001 - ошибка одной машины не останавливает остальные
                    fail += 1
                    self.q.put(("fail", tr("{id}: не удалось экспортировать: {exc}", id=v.id, exc=exc)))
                    logging.getLogger("gui").debug(traceback.format_exc())
            self.q.put(("finished", ok, fail))

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------ очередь сообщений
    def _poll(self) -> None:
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "log":
                    lvl = msg[1]
                    tag = "err" if lvl >= logging.ERROR else "warn" if lvl >= logging.WARNING else None
                    self._log(msg[2], tag)
                elif kind == "progress":
                    self.snow.set(msg[1], busy=True)
                    self.status_label.configure(text=tr(msg[2])[:70])
                elif kind == "loaded":
                    self.index, self.vehicles = msg[1], msg[2]
                    self._set_busy(False)
                    self.snow.set(100, busy=False)
                    self.status_label.configure(text=tr("Готово: машин {n}", n=len(self.vehicles)))
                    self._log(tr("Найдено машин: {n} (записей в индексе: {m})",
                                 n=len(self.vehicles), m=len(self.index)), "ok")
                    self._rebuild_dlc_chips()
                    self._refresh()
                elif kind == "load_error":
                    self._set_busy(False)
                    self.snow.set(0, busy=False)
                    self.status_label.configure(text=tr("Ошибка чтения архивов"))
                    self._log(f"{tr('Ошибка чтения архивов')}: {msg[1]}", "err")
                elif kind == "done":
                    self._log(msg[1], "ok")
                elif kind == "fail":
                    self._log(msg[1], "err")
                elif kind == "finished":
                    self._set_busy(False)
                    self.snow.set(100, busy=False)
                    self.status_label.configure(text=tr("Экспорт: успешно {ok}, с ошибками {fail}",
                                                        ok=msg[1], fail=msg[2]))
                    if msg[2]:
                        self._log(tr("Экспорт завершён: успешно {ok}, с ошибками {fail}.", ok=msg[1], fail=msg[2]),
                                  "warn")
        except queue.Empty:
            pass
        self.after(80, self._poll)


def run() -> None:
    App().mainloop()
