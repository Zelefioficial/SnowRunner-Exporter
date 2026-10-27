"""
ui_lang.py
==========
Язык интерфейса: 'ru' (по умолчанию) или 'en'. Выбор хранится в config.json как ui_language.

tr("русская фраза") возвращает английский текст из словаря EN, если выбран английский,
иначе саму фразу. Ключ словаря - точная русская строка из кода. Непереведённая строка остаётся
русской и ничего не ломает. Подстановки пишутся так: tr("Игра: {game}", game=path).

PREFIXES - для динамических сообщений (прогресс, журнал), где в конце стоит значение:
"Читаю C:\\...\\x.pak" -> "Reading C:\\...\\x.pak".
"""

from __future__ import annotations

LANG = "ru"


def set_language(code: str) -> None:
    global LANG
    LANG = "en" if str(code).lower() in ("en", "english") else "ru"


def tr(text: str, **kw) -> str:
    if LANG != "en":
        out = text
    else:
        out = EN.get(text)
        if out is None:
            out = text
            for ru, en in PREFIXES:
                if text.startswith(ru):
                    out = en + text[len(ru):]
                    break
    return out.format(**kw) if kw else out


PREFIXES: list[tuple[str, str]] = [
    ("PNG: ", "PNG: "),
    ("Деталь: ", "Part: "),
    ("Читаю ", "Reading "),
    ("Мод: ", "Mod: "),
    ("Машин найдено: ", "Vehicles found: "),
    ("Деталей кастомизации в архивах: ", "Customization parts in archives: "),
    ("Найдена Steam-установка: ", "Steam installation found: "),
    ("Найдена установка Epic Games: ", "Epic Games installation found: "),
    ("Пропущен узел: ", "Skipped node: "),
    ("текстура не загружена: ", "texture not loaded: "),
    ("деталей кастомизации не удалось прочитать: ", "customization parts could not be read: "),
]

EN: dict[str, str] = {
    # --- типы машин и источники
    "Легковая (Scout)": "Light (Scout)",
    "Шоссейник": "Highway",
    "Внедорожник": "Off-road",
    "Тяжёлый": "Heavy",
    "Сверхтяжёлый": "Heavy duty",
    "Прицепы": "Trailers",
    "Прочее": "Other",
    "Все": "All",
    "База": "Base",
    "Моды": "Mods",
    "БАЗА": "BASE",
    "МОД": "MOD",
    "Все DLC": "All DLC",
    "Прочие": "Other",
    "Номер DLC": "DLC number",
    "Тип машины": "Vehicle type",
    "Поиск по названию или ID": "Search by name or ID",
    "показано {shown} из {total}": "showing {shown} of {total}",
    "Машин: {n}, пропущено служебных/пустых: {m}": "Vehicles: {n}, skipped service/empty: {m}",
    "Пропущено {v}: нет модели {m}": "Skipped {v}: model {m} not found",
    "Машин найдено: {n}": "Vehicles found: {n}",
    # --- шапка
    "Экспорт машин SnowRunner в GLB и OBJ для Blender. Файлы игры только читаются.":
        "Export SnowRunner vehicles to GLB and OBJ for Blender. Game files are read-only.",
    "Обновить": "Refresh",
    "Папка игры...": "Game folder...",
    "Ярлык": "Shortcut",
    "О программе": "About",
    "Игра не найдена": "Game not found",
    "Игра: {game}": "Game: {game}",
    "Укажите папку игры кнопкой «Папка игры»": "Set the game folder with the «Game folder» button",
    "SnowRunner не найден автоматически. Укажите папку игры.": "SnowRunner was not found automatically. Set the game folder.",
    "Папка установки SnowRunner": "SnowRunner install folder",
    "В выбранной папке нет preload\\paks\\client\\initial.pak. Выберите корень SnowRunner.":
        "The selected folder has no preload\\paks\\client\\initial.pak. Choose the SnowRunner root folder.",
    "Папка игры не задана.": "Game folder is not set.",
    "Найдено модов: {n}": "Mods found: {n}",
    "Ошибка чтения архивов": "Archive read error",
    "Найдено машин: {n} (записей в индексе: {m})": "Vehicles found: {n} (index entries: {m})",
    "Готово: машин {n}": "Done: {n} vehicles",
    "Экспорт: успешно {ok}, с ошибками {fail}": "Export: {ok} succeeded, {fail} failed",
    "Экспорт завершён: успешно {ok}, с ошибками {fail}.": "Export finished: {ok} succeeded, {fail} failed.",
    "Дождитесь окончания текущей операции.": "Wait for the current operation to finish.",
    "Список машин ещё не загружен.": "The vehicle list is not loaded yet.",
    "Выберите машину в списке.": "Select a vehicle in the list.",
    "Не удалось создать папку вывода: {exc}": "Could not create the output folder: {exc}",
    "Не удалось создать ярлык: {exc}": "Could not create the shortcut: {exc}",
    "Ярлык создан: {path}. Закрепить: правая кнопка по ярлыку, «Закрепить на панели задач».":
        "Shortcut created: {path}. To pin it, right-click the shortcut and choose «Pin to taskbar».",
    # --- список
    "Клик - выбрать, Ctrl+клик - несколько, двойной клик - экспорт.":
        "Click to select, Ctrl+click for several, double-click to export.",
    "Выберите машину": "Select a vehicle",
    "Тип": "Type",
    "Источник": "Source",
    "Модель": "Model",
    "Колёса": "Wheels",
    "шт.": "pcs.",
    "нет данных": "no data",
    "Выбрано машин: {n}": "Vehicles selected: {n}",
    "Сведения ниже - для «{name}»": "Details below are for «{name}»",
    # --- экспорт
    "Экспорт": "Export",
    "Формат": "Format",
    "GLB (основной)": "GLB (main)",
    "Папка вывода": "Output folder",
    "Выбрать...": "Select...",
    "Что выгружать": "What to export",
    "Текстуры (PNG)": "Textures (PNG)",
    "Кастомизация": "Customization",
    "Наклейки и мелочи в салоне": "Stickers and small cabin items",
    "Без lp_ LOD": "Skip lp_ LOD",
    "Без служебных объёмов": "Skip service volumes",
    "Инверсия зелёного нормалей": "Invert green normal channel",
    "Выбрано деталей: {n}": "Parts selected: {n}",
    "Выберите машину в списке, затем нажмите «Выбрать...».": "Select a vehicle in the list, then click «Select...».",
    "{id}: деталей кастомизации не найдено.": "{id}: no customization parts found.",
    "{id}: для экспорта выбрано деталей кастомизации: {n}": "{id}: customization parts selected for export: {n}",
    "Экспортировать": "Export",
    "Открыть папку вывода": "Open output folder",
    "Ожидание": "Waiting",
    "Готово: {file}  ({parts} деталей, {vertices} вершин, {triangles} треугольников, габариты {x} x {z} x {y} м, текстур {n})":
        "Done: {file}  ({parts} parts, {vertices} vertices, {triangles} triangles, size {x} x {z} x {y} m, textures {n})",
    "Кастомизация отдельным файлом: {file}  ({parts} деталей, {tris} треугольников)":
        "Customization as a separate file: {file}  ({parts} parts, {tris} triangles)",
    "{id}: не удалось экспортировать: {exc}": "{id}: export failed: {exc}",
    # --- прогресс (сообщения из модулей)
    "Разбор описаний машин": "Parsing vehicle descriptions",
    "Список из кэша": "Loaded from cache",
    "Поиск деталей кастомизации": "Searching customization parts",
    "Архивы прочитаны": "Archives read",
    "Деталей кастомизации в архивах: {n}": "Customization parts in archives: {n}",
    "Чтение модели": "Reading model",
    "Геометрия и материалы": "Geometry and materials",
    "Текстуры": "Textures",
    "Запись модели": "Writing model",
    "Готово": "Done",
    # --- предупреждения экспорта
    "колёса по умолчанию не найдены (нет тира/диска в XML колёс)":
        "default wheels not found (no tire or rim in the wheel XML)",
    "масштаб колёс не указан в XML, принят 0.5": "wheel scale is not set in the XML, 0.5 used",
    "деталей кастомизации для выгрузки не найдено, отдельный файл не создан":
        "no customization parts to export, separate file not created",
    "мод хранит исходный FBX: файл скопирован без изменений, материалы назначьте по PNG из папки textures":
        "mods store the original FBX: the file was copied unchanged, assign materials from the PNGs in the textures folder",
    "материал '{m}' не описан в STM": "material '{m}' is not described in STM",
    "служебный объём": "service volume",
    "NaN в позициях": "NaN in positions",
    # --- подсказки
    "Загрузка превью...": "Loading preview...",
    "Превью недоступно": "Preview unavailable",
    # --- категории деталей кастомизации
    "Бампер": "Bumper",
    "Передний бампер": "Front bumper",
    "Задний бампер": "Rear bumper",
    "Глушитель": "Exhaust",
    "Шноркель": "Snorkel",
    "Сигнал": "Horn",
    "Сигналы": "Horns",
    "Сигналы малые": "Small horns",
    "Багажник на крышу": "Roof rack",
    "Прожекторы": "Spotlights",
    "Фары": "Headlights",
    "Маяк": "Beacon",
    "Маяк передний": "Front beacon",
    "Габаритные огни": "Marker lights",
    "Запасное колесо": "Spare wheel",
    "Запасное колесо 2": "Spare wheel 2",
    "Козырёк": "Visor",
    "Пороги": "Side skirts",
    "Крылья": "Fenders",
    "Багаж": "Trunk items",
    "Седло": "Saddle",
    "Большой кран": "Large crane",
    "Лесовозные коники": "Log bunks",
    "Ароматизаторы": "Air fresheners",
    "Игрушки на панели": "Dashboard toys",
    # --- окно выбора деталей
    "Детали кастомизации": "Customization parts",
    "Детали кастомизации: {id}": "Customization parts: {id}",
    "Отметьте, что выгружать. Наведите указатель на деталь, чтобы увидеть, как она выглядит. "
    "Варианты одного гнезда в Blender лежат друг на друге.":
        "Tick what to export. Hover over a part to see how it looks. "
        "Variants of the same slot overlap each other in Blender.",
    "Все": "All",
    "Ничего": "None",
    "Только тюнинг": "Tuning only",
    "Применить": "Apply",
    "Отмена": "Cancel",
    "Сбросить выбор": "Reset selection",
    "Выбрано: {n} из {m}": "Selected: {n} of {m}",
    "(наклейки и мелочи)": "(stickers and small items)",
    "ничего": "none",
    "все": "all",
    # --- окно «О программе»
    "Закрыть": "Close",
    "Экспорт машин SnowRunner в GLB и OBJ для Blender": "Export SnowRunner vehicles to GLB and OBJ for Blender",
}
