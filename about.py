"""
about.py
========
Окно «О программе»: что делает приложение, как им пользоваться и что означает каждая настройка.
Текст есть на русском и английском, выбор по ui_lang.LANG.
"""

from __future__ import annotations

import tkinter as tk

import ui_lang
from ui_kit import PALETTE as P, RoundButton, ScrollFrame, apply_window_chrome, ui_font
from ui_lang import tr

# (заголовок раздела, [(жирное начало, обычный текст), ...])
SECTIONS_RU: list[tuple[str, list[tuple[str, str]]]] = [
    ("Что делает приложение", [
        ("", "SnowRunner Exporter берёт 3D-модели машин и прицепов из вашей копии SnowRunner и сохраняет их в файлы "
             "GLB или OBJ с текстурами PNG. Такие файлы открываются в Blender и других 3D-редакторах."),
        ("", "Игра на диске только читается: ничего не распаковывается целиком и не изменяется. В выходную папку "
             "попадает только то, что вы выбрали."),
        ("", "Приложение рассчитано на личное использование с легально купленной копией игры."),
    ]),
    ("Как пользоваться", [
        ("1. Игра. ", "Папку SnowRunner приложение находит само (Steam, Epic). Если не нашло, нажмите «Папка игры...»."),
        ("2. Машина. ", "Выберите машину в списке. Поиск работает по названию и ID, также по номеру DLC "
                        "(например, «dlc 14»). Фильтры: тип, источник (База, DLC, Моды), номер DLC. "
                        "Наведите указатель на машину, чтобы увидеть её картинку. Ctrl+клик выбирает несколько машин."),
        ("3. Формат и папка. ", "GLB - один файл с текстурами внутри (основной вариант). OBJ + MTL - классический "
                                "формат с текстурами рядом."),
        ("4. Что выгружать. ", "Отметьте нужные параметры (описаны ниже)."),
        ("5. Экспорт. ", "Нажмите «Экспортировать» или дважды кликните по машине. Результат лежит в "
                         "<папка вывода>\\<ID машины>\\."),
    ]),
    ("Какие файлы получаются", [
        ("<ID>.glb ", "сама машина: кабина, кузов, стёкла, зеркала и колёса."),
        ("<ID>_customization.glb ", "кастомизация отдельным файлом: бамперы, глушители, шноркели, багажники и т.д. "
                                    "Файл создаётся, только если кастомизация включена. Детали стоят в тех же "
                                    "координатах, что и машина: импортируйте оба файла в одну сцену Blender, и "
                                    "они совпадут."),
        ("textures\\ ", "текстуры PNG (цвет, нормали, шероховатость и металличность, свечение)."),
    ]),
    ("Настройки «Что выгружать»", [
        ("Текстуры (PNG). ", "Сохранять базовые текстуры. Без них файлы намного легче, материалы будут серыми."),
        ("Колёса. ", "Добавить колёса комплектации по умолчанию."),
        ("Кастомизация. ", "Выгрузить все детали кастомизации машины отдельным файлом. Кнопка «Выбрать...» "
                           "открывает список, где можно отметить только нужные детали; при наведении на деталь "
                           "показывается, как она выглядит. Если выбор сделан, он важнее галочки."),
        ("Наклейки и мелочи в салоне. ", "Добавить в файл кастомизации стикеры, игрушки на панели и ароматизаторы."),
        ("Без lp_ LOD. ", "Не выгружать упрощённые копии деталей (lp_), если есть полные (hp_)."),
        ("Без служебных объёмов. ", "Не выгружать невидимые игровые объёмы (например, _cockpit)."),
        ("Инверсия зелёного нормалей. ", "Приводит карты нормалей к формату Blender (OpenGL). "
                                         "Включено по умолчанию."),
    ]),
    ("Что не выгружается и ограничения", [
        ("", "Окраски и камуфляжи, анимации, привязка к костям (скиннинг), груз. Колёса берутся только "
             "по умолчанию для машины."),
        ("", "Базовые текстуры игры тёмные: окраска в игре накладывается поверх них, поэтому многие машины "
             "в Blender выглядят тёмными."),
        ("", "Экспорт тяжёлой машины занимает до минуты, а с кастомизацией и текстурами файлы весят сотни мегабайт."),
        ("", "Моды в формате FBX копируются как есть, без материалов."),
        ("", "Картинки при наведении строятся самим приложением: это приблизительный вид, а не рендер игры."),
    ]),
]

SECTIONS_EN: list[tuple[str, list[tuple[str, str]]]] = [
    ("What the app does", [
        ("", "SnowRunner Exporter takes 3D models of vehicles and trailers from your copy of SnowRunner and saves "
             "them as GLB or OBJ files with PNG textures. These files open in Blender and other 3D editors."),
        ("", "The game files are only read: nothing is unpacked in full and nothing is changed. Only what you "
             "select goes into the output folder."),
        ("", "The app is meant for personal use with a legally purchased copy of the game."),
    ]),
    ("How to use it", [
        ("1. Game. ", "The app finds the SnowRunner folder itself (Steam, Epic). If it doesn't, click «Game folder...»."),
        ("2. Vehicle. ", "Select a vehicle in the list. Search works by name and ID, and also by DLC number "
                         "(for example, «dlc 14»). Filters: type, source (Base, DLC, Mods), DLC number. "
                         "Hover over a vehicle to see its picture. Ctrl+click selects several vehicles."),
        ("3. Format and folder. ", "GLB is a single file with textures inside (the main option). OBJ + MTL is the "
                                   "classic format with textures next to it."),
        ("4. What to export. ", "Tick the options you need (described below)."),
        ("5. Export. ", "Click «Export» or double-click a vehicle. The result goes to "
                        "<output folder>\\<vehicle ID>\\."),
    ]),
    ("Which files you get", [
        ("<ID>.glb ", "the vehicle itself: cabin, body, glass, mirrors and wheels."),
        ("<ID>_customization.glb ", "customization as a separate file: bumpers, exhausts, snorkels, roof racks and so on. "
                                    "The file is created only when customization is on. The parts use the same "
                                    "coordinates as the vehicle: import both files into one Blender scene and "
                                    "they line up."),
        ("textures\\ ", "PNG textures (colour, normals, roughness and metalness, glow)."),
    ]),
    ("Options under «What to export»", [
        ("Textures (PNG). ", "Save the base textures. Without them files are much lighter, but materials will be grey."),
        ("Wheels. ", "Add the default wheels of the vehicle."),
        ("Customization. ", "Export all customization parts of the vehicle as a separate file. The «Select...» button "
                            "opens a list where you can tick only the parts you need; hovering over a part shows "
                            "how it looks. If you made a selection, it overrides the checkbox."),
        ("Stickers and small cabin items. ", "Add stickers, dashboard toys and air fresheners to the customization file."),
        ("Skip lp_ LOD. ", "Do not export simplified copies of parts (lp_) when full ones (hp_) exist."),
        ("Skip service volumes. ", "Do not export invisible game volumes (for example _cockpit)."),
        ("Invert green normal channel. ", "Converts normal maps to the Blender (OpenGL) format. "
                                          "On by default."),
    ]),
    ("What is not exported, and limits", [
        ("", "Paint jobs and camouflage, animations, bone skinning, cargo. Wheels are only the default ones "
             "for each vehicle."),
        ("", "The game's base textures are dark: the paint is applied on top of them, so many vehicles look "
             "dark in Blender."),
        ("", "A heavy vehicle takes up to a minute to export, and with customization and textures the files "
             "reach hundreds of megabytes."),
        ("", "FBX mods are copied as they are, without materials."),
        ("", "The pictures shown on hover are made by the app itself: they are an approximate view, not a game render."),
    ]),
]


class AboutDialog(tk.Toplevel):
    def __init__(self, app: tk.Tk):
        super().__init__(app)
        self.title(tr("О программе"))
        self.configure(bg=P["bg"])
        self.geometry("640x720")
        self.minsize(480, 420)
        self.transient(app)
        outer = tk.Frame(self, bg=P["bg"])
        outer.pack(fill="both", expand=True, padx=18, pady=16)
        tk.Label(outer, text="SnowRunner Exporter", bg=P["bg"], fg=P["text"], font=ui_font(16, True),
                 anchor="w").pack(fill="x")
        tk.Label(outer, text=tr("Экспорт машин SnowRunner в GLB и OBJ для Blender"), bg=P["bg"], fg=P["muted"],
                 font=ui_font(10), anchor="w").pack(fill="x", pady=(2, 12))
        scroll = ScrollFrame(outer, bg=P["bg"])
        scroll.pack(fill="both", expand=True)
        sections = SECTIONS_EN if ui_lang.LANG == "en" else SECTIONS_RU
        for title, items in sections:
            box = tk.Frame(scroll.inner, bg=P["card"], highlightbackground=P["border"], highlightthickness=1)
            box.pack(fill="x", pady=(0, 10))
            tk.Label(box, text=title, bg=P["card"], fg=P["accent"], font=ui_font(11, True),
                     anchor="w").pack(fill="x", padx=14, pady=(10, 4))
            for head, text in items:
                self._paragraph(box, head, text)
            tk.Frame(box, bg=P["card"], height=6).pack()
        RoundButton(outer, tr("Закрыть"), command=self.destroy, bg=P["bg"], variant="primary",
                    height=40).pack(anchor="e", pady=(12, 0))
        self.after(150, lambda: apply_window_chrome(self))

    @staticmethod
    def _paragraph(parent: tk.Frame, head: str, text: str) -> None:
        """Абзац с жирным началом: две подписи в одной строке не умеют переноситься вместе, поэтому используем Text."""
        t = tk.Text(parent, wrap="word", bg=P["card"], fg=P["text"], relief="flat", bd=0, highlightthickness=0,
                    padx=14, pady=2, font=ui_font(10), height=1, cursor="arrow")
        t.tag_configure("b", font=ui_font(10, True), foreground=P["text"])
        t.tag_configure("n", foreground=P["muted"])
        if head:
            t.insert("end", head, "b")
        t.insert("end", text, "n")
        t.configure(state="disabled")
        t.pack(fill="x")

        def fit(_e=None) -> None:
            """Высота по числу строк после переноса."""
            t.update_idletasks()
            lines = t.count("1.0", "end", "displaylines")
            t.configure(height=max(1, (lines[0] if lines else 1)))

        t.bind("<Configure>", fit)
