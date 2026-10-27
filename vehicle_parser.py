"""
vehicle_parser.py
=================
Список машин: разбор XML ``classes/trucks/*.xml`` (база, DLC из ``_dlc/<имя>/``,
моды), локализация названий, колёса, кэш в cache.json.

Структура, найденная на реальной установке:
  * [media]/classes/trucks/<id>.xml                 - машины базовой игры
  * [media]/_dlc/<dlc>/classes/trucks/<id>.xml      - машины DLC
  * .../classes/trucks/trailers/<id>.xml            - прицепы
  * <PhysicsModel Mesh="trucks/<id>">               -> [meshes]/trucks_<id> (STM в shared.pak)
  * <GameData><UiDesc UiName="UI_..._NAME">         -> строка в [strings]/strings_<язык>.str
  * <Wheels DefaultWheelType=... DefaultTire=... DefaultRim=...> -> classes/wheels/<тип>.xml
"""

from __future__ import annotations

import json
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pak_reader import PakIndex, norm
from ui_lang import tr

log = logging.getLogger("vehicles")

CACHE_VERSION = 3

_VEHICLE_RE = re.compile(r"(?:^|/)(?:_dlc/([^/]+)/)?classes/trucks/(trailers/)?([^/]+)\.xml$")

# Категории как в игре: ключ, подпись, соответствие TruckType из XML
CATEGORIES = [
    ("scout", "Легковая (Scout)"),
    ("highway", "Шоссейник"),
    ("offroad", "Внедорожник"),
    ("heavy", "Тяжёлый"),
    ("heavy_duty", "Сверхтяжёлый"),
    ("trailer", "Прицепы"),
    ("other", "Прочее"),
]
CATEGORY_LABELS = dict(CATEGORIES)
TRUCK_TYPE_TO_CATEGORY = {
    "SCOUT": "scout",
    "HIGHWAY": "highway",
    "OFFROAD": "offroad",
    "HEAVY": "heavy",
    "HEAVY_DUTY": "heavy_duty",
}


@dataclass
class Vehicle:
    id: str
    kind: str                       # 'truck' | 'trailer'
    truck_type: str                 # SCOUT / HEAVY / ...
    source: str                     # 'base' | 'dlc' | 'mod'
    source_label: str               # 'База', 'DLC dlc_3', 'Мод: x.pak'
    xml_path: str
    mesh: str                       # значение PhysicsModel/@Mesh
    ui_name_key: str = ""
    names: dict[str, str] = field(default_factory=dict)
    wheel_type: str = ""
    default_tire: str = ""
    default_rim: str = ""
    wheel_scale: float = 0.0
    wheels: list[list] = field(default_factory=list)      # [[x, y, z, right_side(bool)], ...]

    def display_name(self, language: str = "russian") -> str:
        return self.names.get(language) or self.names.get("english") or self.id

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.id}"

    @property
    def category(self) -> str:
        if self.kind == "trailer":
            return "trailer"
        return TRUCK_TYPE_TO_CATEGORY.get(self.truck_type, "other")

    def type_label(self) -> str:
        return tr(CATEGORY_LABELS[self.category])

    @property
    def stm_path(self) -> str:
        return "[meshes]/" + self.mesh.replace("/", "_")


# ------------------------------------------------------------------ локализация

_STR_LINE = re.compile(r'^([^\t\r\n]+)\t+"(.*)"\s*$')


def parse_str(data: bytes) -> dict[str, str]:
    """Формат .str: UTF-16LE с BOM, строки вида  KEY<TAB>...<TAB>"значение"."""
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        text = data.decode("utf-16", "replace")
    else:
        text = data.decode("utf-8-sig", "replace")
    out: dict[str, str] = {}
    for line in text.splitlines():
        m = _STR_LINE.match(line)
        if m:
            out[m.group(1)] = m.group(2).replace('\\"', '"')
    return out


def load_strings(index: PakIndex, language: str) -> dict[str, str]:
    """Строки игры; строки модов перекрывают игровые."""
    result: dict[str, str] = {}
    data = index.try_read(f"[strings]/strings_{language}.str")
    if data:
        result.update(parse_str(data))
    for path in index.paths(suffix=f"texts/strings_{language}.str"):
        data = index.try_read(path)
        if data:
            result.update(parse_str(data))
    return result


# ------------------------------------------------------------------ XML

def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16", "cp1251"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return data.decode("latin1", "replace")


_BAD_AMP = re.compile(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_DECL = re.compile(r"^\s*<\?xml[^>]*\?>", re.S)


def parse_xml_lenient(data: bytes) -> ET.Element | None:
    """Файлы классов содержат несколько корневых элементов (<_templates> и <Truck>),
    поэтому оборачиваем в <root>. Битые символы и & исправляем."""
    text = _CTRL.sub("", _DECL.sub("", _decode(data)))
    for attempt in (text, _BAD_AMP.sub("&amp;", text)):
        try:
            return ET.fromstring("<root>" + attempt + "</root>")
        except ET.ParseError:
            continue
    return None


def _vec(text: str | None) -> list[float] | None:
    if not text:
        return None
    try:
        return [float(x) for x in text.strip("() ").split(";")]
    except ValueError:
        return None


def _regex_fallback(text: str) -> dict:
    """Если XML не разобрался - достаём главное регулярками."""
    out = {}
    for key, rx in (("mesh", r'<PhysicsModel[^>]*\sMesh="([^"]+)"'), ("ui", r'UiName="([^"]+)"'),
                    ("type", r'TruckType="([^"]+)"')):
        m = re.search(rx, text)
        if m:
            out[key] = m.group(1)
    return out


def _parse_vehicle_xml(data: bytes, vid: str) -> dict | None:
    root = parse_xml_lenient(data)
    info: dict = {"wheels": []}
    if root is None:
        fb = _regex_fallback(_decode(data))
        if "mesh" not in fb:
            return None
        info.update(mesh=fb["mesh"], ui=fb.get("ui", ""), type=fb.get("type", ""))
        return info
    truck = root.find("Truck")
    if truck is None:
        return None
    pm = truck.find("PhysicsModel")
    mesh = pm.get("Mesh") if pm is not None else None
    if not mesh:
        return None
    info["mesh"] = mesh
    td = truck.find("TruckData")
    info["type"] = td.get("TruckType", "") if td is not None else ""
    ui = truck.find("GameData/UiDesc")
    info["ui"] = ui.get("UiName", "") if ui is not None else ""
    wheels = td.find("Wheels") if td is not None else None
    if wheels is not None:
        info["wheel_type"] = wheels.get("DefaultWheelType", "")
        info["tire"] = wheels.get("DefaultTire", "")
        info["rim"] = wheels.get("DefaultRim", "")
        for w in wheels.findall("Wheel"):
            pos = _vec(w.get("Pos"))
            if pos and len(pos) == 3:
                info["wheels"].append([pos[0], pos[1], pos[2], w.get("RightSide", "false").lower() == "true"])
    if td is not None and info.get("wheel_type"):
        for cw in td.findall("CompatibleWheels"):
            if cw.get("Type") == info["wheel_type"]:
                try:
                    info["scale"] = float(cw.get("Scale", "0"))
                except ValueError:
                    pass
                break
    return info


# ------------------------------------------------------------------ сканирование

def _source_of(path_norm: str, entry_source: str, pak_label: str) -> tuple[str, str]:
    m = _VEHICLE_RE.search(path_norm)
    dlc = m.group(1) if m else None
    if entry_source == "mod":
        return "mod", f"Мод: {pak_label}"
    if dlc or entry_source == "dlc":
        return "dlc", f"DLC {dlc or pak_label}"
    return "base", "База"


def scan_vehicles(index: PakIndex, languages: tuple[str, ...] = ("english", "russian"),
                  progress=None) -> list[Vehicle]:
    """Читает все XML машин. Служебные и пустые записи (без модели или названия) отбрасываются.
    progress(доля 0..1, текст) - по числу просмотренных XML."""
    strings = {lang: load_strings(index, lang) for lang in languages}
    found: dict[str, Vehicle] = {}
    skipped = 0
    candidates = [p for p in index.paths(suffix=".xml") if _VEHICLE_RE.search(p)]
    total = max(len(candidates), 1)
    for done, vpath in enumerate(candidates, 1):
        if progress and done % 50 == 0:
            progress(done / total, "Разбор описаний машин")
        m = _VEHICLE_RE.search(vpath)
        entry = index.entry(vpath)
        data = index.try_read(vpath)
        if entry is None or data is None:
            continue
        vid = m.group(3)
        info = _parse_vehicle_xml(data, vid)
        if not info or not info.get("ui"):
            skipped += 1
            continue
        mesh = info["mesh"]
        stm_ok = f"[meshes]/{mesh.replace('/', '_')}" in index
        fbx_ok = f"meshes/{mesh}.fbx" in index
        if not (stm_ok or fbx_ok):
            skipped += 1
            log.info(tr("Пропущено {v}: нет модели {m}", v=vid, m=mesh))
            continue
        source, label = _source_of(vpath, entry.source, entry.pak_label)
        v = Vehicle(
            id=vid, kind="trailer" if m.group(2) else "truck", truck_type=info.get("type", ""),
            source=source, source_label=label, xml_path=entry.name, mesh=mesh, ui_name_key=info["ui"],
            names={lang: strings[lang].get(info["ui"], "") for lang in languages},
            wheel_type=info.get("wheel_type", ""), default_tire=info.get("tire", ""),
            default_rim=info.get("rim", ""), wheel_scale=info.get("scale", 0.0), wheels=info["wheels"],
        )
        if v.names.get("english", "") == "" and v.names.get("russian", "") == "":
            v.names = {}
        key = f"{v.kind}:{vid}"
        found[key] = v          # более поздний (DLC, мод) перекрывает ранний
    if progress:
        progress(1.0, f"Машин найдено: {len(found)}")
    log.info(tr("Машин: {n}, пропущено служебных/пустых: {m}", n=len(found), m=skipped))
    return sorted(found.values(), key=lambda v: (v.source != "base", v.source_label, v.display_name("english").lower()))


# ------------------------------------------------------------------ кэш

def load_cache(path: Path, signature: str) -> list[Vehicle] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if raw.get("version") != CACHE_VERSION or raw.get("signature") != signature:
        return None
    try:
        return [Vehicle(**item) for item in raw["vehicles"]]
    except (TypeError, KeyError):
        return None


def save_cache(path: Path, signature: str, vehicles: list[Vehicle]) -> None:
    try:
        path.write_text(json.dumps({"version": CACHE_VERSION, "signature": signature,
                                    "vehicles": [asdict(v) for v in vehicles]}, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    except OSError as exc:
        log.warning("Не удалось записать кэш: %s", exc)


def get_vehicles(index: PakIndex, cache_path: Path, progress=None, force: bool = False) -> list[Vehicle]:
    sig = index.signature()
    if not force:
        cached = load_cache(cache_path, sig)
        if cached is not None:
            if progress:
                progress(1.0, "Список из кэша")
            return cached
    vehicles = scan_vehicles(index, progress=progress)
    save_cache(cache_path, sig, vehicles)
    return vehicles


# ------------------------------------------------------------------ кастомизация (аддоны)
#
# Бамперы, глушители, багажники, шноркели, краны, рамы и т.д. описаны в classes/trucks/**.xml
# корневым элементом <TruckAddon>. Деталь ставится в гнездо: <InstallSocket Type="..."/> у аддона
# совпадает с <Socket Names="..."/> в <AddonSockets> машины. Варианты (front_bumper_1..5) наследуют
# описание через <_parent File="..."/>. Геометрия аддона лежит сразу в осях машины.

ADDON_CACHE_VERSION = 1


@dataclass
class Addon:
    id: str
    path: str
    sockets: list[str]
    mesh: str
    ui_name: str = ""
    cosmetic: bool = False          # наклейки и мелочи в салоне (стикеры, игрушки, ароматизаторы)

    @property
    def stm_path(self) -> str:
        return "[meshes]/" + self.mesh.replace("/", "_")


_COSMETIC_HINTS = ("sticker", "airfreshener", "dashboard")


def _is_cosmetic(sockets: list[str], stem: str) -> bool:
    low = [s.lower() for s in sockets]
    return (any(s.startswith("stuff") or any(h in s for h in _COSMETIC_HINTS) for s in low)
            or stem.lower().startswith(("stuff_", "sticker_")))


_SOCKET_RE = re.compile(r"<Socket\s[^>]*?\bNames\s*=\s*\"([^\"]*)\"", re.S)


def _split_names(text: str | None) -> list[str]:
    return [p for p in re.split(r"[,;\s]+", text or "") if p]


def _addon_raw(data: bytes) -> dict | None:
    root = parse_xml_lenient(data)
    if root is None:
        return None
    a = root.find("TruckAddon")
    if a is None:
        return None
    parent = root.find("_parent")
    pm = a.find("PhysicsModel")
    ui = a.find("GameData/UiDesc")
    sockets: list[str] = []
    for s in a.iter("InstallSocket"):
        sockets += _split_names(s.get("Type"))
    return {"parent": parent.get("File", "") if parent is not None else "",
            "mesh": (pm.get("Mesh") or "") if pm is not None else "",
            "ui": (ui.get("UiName") or "") if ui is not None else "",
            "sockets": sockets}


def scan_addons(index: PakIndex, progress=None) -> list[Addon]:
    raw: dict[str, dict] = {}
    by_stem: dict[str, list[str]] = {}
    paths = [p for p in index.paths(suffix=".xml") if "classes/trucks/" in p]
    total = max(len(paths), 1)
    for done, p in enumerate(paths, 1):
        if progress and done % 200 == 0:
            progress(done / total, "Поиск деталей кастомизации")
        data = index.try_read(p)
        if not data or b"<TruckAddon" not in data:
            continue
        info = _addon_raw(data)
        if info:
            raw[p] = info
            by_stem.setdefault(p.rsplit("/", 1)[-1][:-4].lower(), []).append(p)

    def resolve(path: str, depth: int = 0) -> dict:
        info = dict(raw[path])
        name = info["parent"].lower()
        if name and depth < 6 and (not info["mesh"] or not info["sockets"] or not info["ui"]):
            folder = path.rsplit("/", 1)[0]
            cands = by_stem.get(name[:-4] if name.endswith(".xml") else name, [])
            same = [c for c in cands if c.rsplit("/", 1)[0] == folder]
            target = (same or cands or [None])[0]
            if target and target != path:
                up = resolve(target, depth + 1)
                for key in ("mesh", "ui", "sockets"):
                    if not info[key]:
                        info[key] = up[key]
        return info

    out: list[Addon] = []
    for p in raw:
        info = resolve(p)
        if not info["mesh"] or not info["sockets"]:
            continue
        stem = p.rsplit("/", 1)[-1][:-4]
        out.append(Addon(id=stem, path=p, sockets=info["sockets"], mesh=info["mesh"], ui_name=info["ui"],
                         cosmetic=_is_cosmetic(info["sockets"], stem)))
    log.info("Деталей кастомизации в архивах: %d", len(out))
    return out


def get_addons(index: PakIndex, progress=None) -> list[Addon]:
    """Список аддонов; считается один раз за запуск и хранится в addons.json рядом с cache.json."""
    memo = getattr(index, "_addons_memo", None)
    if memo is not None:
        return memo
    import paths as app_paths
    cache = app_paths.DATA_DIR / "addons.json"
    sig = index.signature()
    addons: list[Addon] | None = None
    try:
        raw = json.loads(cache.read_text(encoding="utf-8"))
        if raw.get("version") == ADDON_CACHE_VERSION and raw.get("signature") == sig:
            addons = [Addon(**item) for item in raw["addons"]]
    except (OSError, ValueError, TypeError, KeyError):
        addons = None
    if addons is None:
        addons = scan_addons(index, progress)
        try:
            cache.write_text(json.dumps({"version": ADDON_CACHE_VERSION, "signature": sig,
                                         "addons": [asdict(a) for a in addons]}, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            log.warning("Не удалось записать addons.json: %s", exc)
    index._addons_memo = addons
    return addons


def vehicle_sockets(index: PakIndex, v: Vehicle) -> set[str]:
    """Имена гнёзд <Socket Names="..."> из XML машины. Читаем регулярным выражением: часть файлов
    (например ford_f750) не разбирается как XML, но гнёзда в них есть."""
    data = index.try_read(v.xml_path)
    names: set[str] = set()
    if data:
        for m in _SOCKET_RE.finditer(_decode(data)):
            names.update(n.lower() for n in _split_names(m.group(1)))
    return names


def addons_for_vehicle(index: PakIndex, v: Vehicle, progress=None) -> list[Addon]:
    """Все детали, которые игра может поставить на эту машину (по гнёздам), с существующей моделью."""
    sockets = vehicle_sockets(index, v)
    if not sockets:
        return []
    found = [a for a in get_addons(index, progress)
             if any(s.lower() in sockets for s in a.sockets) and a.stm_path in index]
    found.sort(key=lambda a: (a.cosmetic, a.sockets[0].lower(), a.id.lower()))
    return found


# ------------------------------------------------------------------ колёса

def find_wheel_xml(index: PakIndex, wheel_type: str) -> str | None:
    """Ищет classes/wheels/<тип>.xml в базе, DLC и модах."""
    wt = wheel_type.lower()
    best = None
    for p in index.paths(suffix=f"classes/wheels/{wt}.xml"):
        best = p
        if "/_dlc/" not in p:
            break
    return best


def resolve_wheel_meshes(index: PakIndex, v: Vehicle) -> tuple[str | None, str | None]:
    """Возвращает (виртуальный путь шины, виртуальный путь диска) для колёс по умолчанию."""
    if not v.wheel_type:
        return None, None
    path = find_wheel_xml(index, v.wheel_type)
    if not path:
        return None, None
    data = index.try_read(path)
    root = parse_xml_lenient(data) if data else None
    if root is None:
        return None, None
    tire = rim = None
    for t in root.iter("TruckTire"):
        if t.get("Name") == v.default_tire and t.get("Mesh"):
            tire = t.get("Mesh")
    for r in root.iter("TruckRim"):
        if r.get("Name") == v.default_rim and r.get("Mesh"):
            rim = r.get("Mesh")
    tire_p = f"[meshes]/{tire.replace('/', '_')}" if tire else None
    rim_p = f"[meshes]/{rim.replace('/', '_')}" if rim else None
    return (tire_p if tire_p and tire_p in index else None), (rim_p if rim_p and rim_p in index else None)


def texture_vpath(tga_path: str) -> str:
    """'trucks/foo__d.tga' -> '[textures]/pct/trucks_foo__d.pct'."""
    base = tga_path.replace("\\", "/")
    base = re.sub(r"\.(tga|dds|png)$", "", base, flags=re.I)
    return "[textures]/pct/" + base.replace("/", "_") + ".pct"
