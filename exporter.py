"""
exporter.py
===========
Сборка сцены машины и запись в GLB (собственный минимальный writer по спецификации glTF 2.0)
или OBJ+MTL. Текстуры пишутся в PNG в папку ``textures`` рядом с файлом модели.

Состав сцены:
  <id>                    корневой узел
    Parts                 детали из STM (кабина, кузов, стёкла, зеркала ...), по узлу на деталь
    Wheels                колёса: узел на колесо с дочерними шиной и диском (если известны)
    Skeleton              кости (пустышки) с локальными матрицами из STM (необязательно)

Кастомизация (бамперы, глушители ...) пишется отдельным файлом <id>_customization.glb|obj рядом с моделью:
узлы Customization и Cosmetics в тех же осях и с тем же началом координат, что у машины.

Оси: glTF Y-up, +Z - вперёд машины, +X - влево, единицы - метры.
"""

from __future__ import annotations

import json
import logging
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image

import stm_converter as stm
import texture_converter as texc
from pak_reader import PakIndex
from ui_lang import tr
from vehicle_parser import Vehicle, addons_for_vehicle, resolve_wheel_meshes

log = logging.getLogger("export")

ProgressFn = Callable[[float, str], None]


# ------------------------------------------------------------------ параметры и результат

@dataclass
class ExportOptions:
    fmt: str = "glb"                    # 'glb' | 'obj'
    include_wheels: bool = True
    include_skeleton: bool = False      # кости-пустышки; по умолчанию выключены (нужен только транспорт)
    skip_low_lod: bool = True           # не выгружать lp_* при наличии hp_*
    skip_placeholders: bool = True      # меши только с материалом lambert1 (служебные объёмы)
    flip_normal_green: bool = True
    textures: bool = True
    include_customization: bool = False  # бамперы, глушители, шноркели, багажники, краны, рамы и т.д. (без окрасок)
    include_cosmetic: bool = False       # наклейки и мелочи в салоне (стикеры, игрушки, ароматизаторы)
    addon_paths: frozenset | None = None # None - по галочкам выше; набор - только эти детали (пути XML аддонов)
    albedo_only: bool = False            # только цветовые текстуры (для превью, без нормалей и шероховатости)


@dataclass
class ExportResult:
    folder: Path
    model_file: Path
    texture_files: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    custom_file: Path | None = None         # отдельный файл с деталями кастомизации (<id>_customization.glb|obj)
    custom_stats: dict = field(default_factory=dict)


# ------------------------------------------------------------------ сцена

@dataclass
class SMaterial:
    name: str
    albedo: str | None = None
    normal: str | None = None
    orm: str | None = None
    emissive: str | None = None
    blend: bool = False


@dataclass
class SNode:
    name: str
    primitives: list[stm.PrimitiveData] | None = None
    children: list["SNode"] = field(default_factory=list)
    translation: tuple[float, float, float] | None = None
    rotation: tuple[float, float, float, float] | None = None
    scale: tuple[float, float, float] | None = None
    matrix: list[float] | None = None
    extras: dict | None = None


@dataclass
class Scene:
    root: SNode
    materials: dict[str, SMaterial] = field(default_factory=dict)
    images: dict[str, Image.Image] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _safe_name(text: str) -> str:
    return re.sub(r"[^\w.\-]+", "_", text, flags=re.UNICODE).strip("_") or "model"


class _MaterialBuilder:
    """Преобразует материал STM в материал сцены, конвертируя текстуры один раз."""

    def __init__(self, index: PakIndex, scene: Scene, opts: ExportOptions):
        self.index, self.scene, self.opts = index, scene, opts
        self._raw: dict[str, Image.Image | None] = {}
        self._done: dict[tuple, SMaterial] = {}

    def _load(self, tga: str) -> Image.Image | None:
        if tga not in self._raw:
            self._raw[tga] = texc.load_game_texture(self.index, tga)
            if self._raw[tga] is None:
                self.scene.warnings.append(f"текстура не загружена: {tga}")
        return self._raw[tga]

    def build(self, name: str, attrs: dict[str, str] | None) -> SMaterial:
        attrs = attrs or {}
        key = (name, tuple(sorted(attrs.items())))
        if key in self._done:
            return self._done[key]
        mat = SMaterial(name=name, blend=attrs.get("Blending", "").lower() == "alpha")
        if self.opts.textures:
            if attrs.get("AlbedoMap"):
                img = self._load(attrs["AlbedoMap"])
                if img is not None:
                    fn = Path(attrs["AlbedoMap"]).stem + ".png"
                    self.scene.images.setdefault(fn, texc.prepare_albedo(img, mat.blend))
                    mat.albedo = fn
            if attrs.get("NormalMap") and not self.opts.albedo_only:
                img = self._load(attrs["NormalMap"])
                if img is not None:
                    fn = Path(attrs["NormalMap"]).stem + ".png"
                    self.scene.images.setdefault(fn, texc.prepare_normal(img, self.opts.flip_normal_green))
                    mat.normal = fn
            if attrs.get("ShadingMap") and not self.opts.albedo_only:
                img = self._load(attrs["ShadingMap"])
                if img is not None:
                    fn = Path(attrs["ShadingMap"]).stem + "_orm.png"
                    self.scene.images.setdefault(fn, texc.prepare_orm(img))
                    mat.orm = fn
            if attrs.get("EmissiveMap") and not self.opts.albedo_only:
                img = self._load(attrs["EmissiveMap"])
                if img is not None:
                    fn = Path(attrs["EmissiveMap"]).stem + ".png"
                    self.scene.images.setdefault(fn, texc.prepare_albedo(img, False))
                    mat.emissive = fn
        self._done[key] = mat
        # одинаковые имена с разными текстурами (редко) получают суффикс
        final = name
        n = 1
        while final in self.scene.materials and self.scene.materials[final] is not mat:
            n += 1
            final = f"{name}.{n}"
        mat.name = final
        self.scene.materials[final] = mat
        return mat


def _is_placeholder(mesh: stm.StmMesh) -> bool:
    return bool(mesh.material_names) and all(m.lower().startswith("lambert") for m in mesh.material_names)


def _select_meshes(model: stm.StmModel, opts: ExportOptions) -> tuple[list[stm.StmMesh], list[str]]:
    meshes = model.visible_meshes()
    names = {m.name.lower() for m in meshes}
    keep, skipped = [], []
    for m in meshes:
        low = m.name.lower()
        if opts.skip_low_lod and low.startswith("lp_") and ("hp_" + low[3:]) in names:
            skipped.append(f"{m.name} (LOD lp_)")
            continue
        if opts.skip_placeholders and _is_placeholder(m):
            skipped.append(f"{m.name} ({tr('служебный объём')})")
            continue
        if not np.isfinite(m.positions).all():
            skipped.append(f"{m.name} ({tr('NaN в позициях')})")
            continue
        keep.append(m)
    return keep, skipped


def _model_part_nodes(model: stm.StmModel, mb: _MaterialBuilder, opts: ExportOptions, scene: Scene,
                      prefix: str = "") -> list[SNode]:
    nodes: list[SNode] = []
    meshes, skipped = _select_meshes(model, opts)
    for s in skipped:
        log.info("Пропущен узел: %s", s)
    for m in meshes:
        part = stm.mesh_to_part(m)
        for pr in part.primitives:
            attrs = model.materials.get(pr.material_name)
            if attrs is None and pr.material_name.lower().startswith("lambert") is False:
                scene.warnings.append(tr("материал '{m}' не описан в STM", m=pr.material_name))
            pr.material_name = mb.build(pr.material_name, attrs).name      # при совпадении имён получает суффикс
        nodes.append(SNode(prefix + m.name, primitives=part.primitives,
                           extras={"stm_node": m.name, "joints": [model.nodes[j].name for j in m.joints if j < len(model.nodes)]}))
    return nodes


def _skeleton_nodes(model: stm.StmModel) -> list[SNode]:
    """Кости без геометрии; коллизионные cdt_* и узлы с мешами пропускаются."""
    keep: dict[int, SNode] = {}
    parent_of: dict[int, int] = {}
    local: dict[int, np.ndarray] = {}
    for n in model.nodes:
        if n.mesh is not None or n.name.lower().startswith("cdt_") or n.name.lower().startswith("cdt"):
            continue
        keep[n.index] = SNode(n.name, matrix=[float(x) for x in stm.game_to_gltf_matrix(n.matrix).reshape(-1)])
        parent_of[n.index] = n.parent
        local[n.index] = n.matrix.astype(np.float64)
    by_index = {n.index: n for n in model.nodes}
    roots: list[SNode] = []
    for idx, node in keep.items():
        p = parent_of[idx]
        carry = np.eye(4)
        while p in by_index and p not in keep and p >= 0:
            carry = carry @ by_index[p].matrix.astype(np.float64)       # пропущенный предок
            p = by_index[p].parent
        if p in keep:
            if not np.allclose(carry, np.eye(4), atol=1e-4):
                node.matrix = [float(x) for x in stm.game_to_gltf_matrix((local[idx] @ carry).astype(np.float32)).reshape(-1)]
            keep[p].children.append(node)
        else:
            roots.append(node)
    return roots


def _wheel_nodes(index: PakIndex, v: Vehicle, mb: _MaterialBuilder, opts: ExportOptions, scene: Scene) -> list[SNode]:
    if not v.wheels:
        return []
    tire_p, rim_p = resolve_wheel_meshes(index, v)
    if not tire_p and not rim_p:
        scene.warnings.append("колёса по умолчанию не найдены (нет тира/диска в XML колёс)")
        return []
    scale = v.wheel_scale or 0.5
    if not v.wheel_scale:
        scene.warnings.append("масштаб колёс не указан в XML, принят 0.5")
    parts: list[tuple[str, list[stm.PrimitiveData]]] = []
    for label, path in (("tire", tire_p), ("rim", rim_p)):
        if not path:
            continue
        try:
            model = stm.parse_stm(index.read(path), path)
        except (KeyError, stm.StmError) as exc:
            scene.warnings.append(f"колесо {label}: {exc}")
            continue
        prims: list[stm.PrimitiveData] = []
        for m in model.visible_meshes():
            for pr in stm.mesh_to_part(m).primitives:
                mb.build(pr.material_name, model.materials.get(pr.material_name))
                prims.append(pr)
        parts.append((label, prims))
    nodes: list[SNode] = []
    counters = {"left": 0, "right": 0}
    for x, y, z, right in v.wheels:
        side = "right" if right else "left"
        counters[side] += 1
        zz = -z if right else z
        pos = np.array([[x, y, zz]], np.float32)
        gl_pos = stm.game_to_gltf_points(pos)[0]
        # у диска видимая сторона смотрит в -Z (игровые оси), поэтому левые колёса разворачиваем на 180° вокруг вертикали
        rot = (0.0, 1.0, 0.0, 0.0) if not right else (0.0, 0.0, 0.0, 1.0)
        wn = SNode(f"wheel_{side}_{counters[side]}", translation=tuple(float(c) for c in gl_pos), rotation=rot,
                   scale=(scale, scale, scale), extras={"wheel_scale": scale})
        for label, prims in parts:
            wn.children.append(SNode(label, primitives=prims))
        nodes.append(wn)
    return nodes


def _customization_nodes(index: PakIndex, v: Vehicle, opts: ExportOptions, scene: Scene,
                         progress: ProgressFn | None = None) -> list[SNode]:
    """Детали кастомизации: группа на тип гнезда (Bumper, Exhaust ...), в ней узел на каждую деталь.
    Модели аддонов лежат в осях машины, поэтому ставятся без смещения. Все варианты одного гнезда
    накладываются друг на друга: ненужные скрывайте в Blender. У деталей берутся базовые текстуры из материалов
    модели (как у самой машины); окраски и камуфляжи (skins) не выгружаются."""
    mb = _MaterialBuilder(index, scene, opts)
    if opts.addon_paths is not None:
        addons = [a for a in addons_for_vehicle(index, v) if a.path in opts.addon_paths]
    else:
        addons = [a for a in addons_for_vehicle(index, v)
                  if (opts.include_cosmetic if a.cosmetic else opts.include_customization)]
    groups: dict[tuple[bool, str], SNode] = {}
    total = max(len(addons), 1)
    failed = 0
    for i, a in enumerate(addons):
        if progress:
            progress(i / total, f"Деталь: {a.id}")
        try:
            model = stm.parse_stm(index.read(a.stm_path), a.stm_path)
            parts = _model_part_nodes(model, mb, opts, scene)
        except (KeyError, stm.StmError) as exc:
            failed += 1
            log.info("Деталь %s пропущена: %s", a.id, exc)
            continue
        if not parts:
            continue
        sock = a.sockets[0]
        group = groups.get((a.cosmetic, sock))
        if group is None:
            group = groups[(a.cosmetic, sock)] = SNode(sock)
        group.children.append(SNode(a.id, children=parts, extras={"socket": sock, "ui_name": a.ui_name}))
    if failed:
        scene.warnings.append(f"деталей кастомизации не удалось прочитать: {failed}")
    out: list[SNode] = []
    for cosmetic, title in ((False, "Customization"), (True, "Cosmetics")):
        kids = [g for (c, _), g in groups.items() if c == cosmetic]
        if kids:
            out.append(SNode(title, children=kids))
    return out


def build_scene(index: PakIndex, v: Vehicle, opts: ExportOptions, progress: ProgressFn | None = None) -> Scene:
    def tick(f: float, msg: str) -> None:
        if progress:
            progress(f, msg)

    root = SNode(v.id, extras={"vehicle_id": v.id, "source": v.source_label, "axes": "glTF Y-up, +Z forward, meters"})
    scene = Scene(root)
    tick(0.05, "Чтение модели")
    data = index.try_read(v.stm_path)
    if data is None:
        raise stm.StmError(f"файл модели не найден: {v.stm_path}")
    model = stm.parse_stm(data, v.stm_path)
    if not model.visible_meshes():
        raise stm.StmError("в модели нет видимой геометрии")
    mb = _MaterialBuilder(index, scene, opts)
    tick(0.15, "Геометрия и материалы")
    parts = SNode("Parts", children=_model_part_nodes(model, mb, opts, scene))
    root.children.append(parts)
    if opts.include_wheels:
        tick(0.45, "Колёса")
        wheels = _wheel_nodes(index, v, mb, opts, scene)
        if wheels:
            root.children.append(SNode("Wheels", children=wheels))
    if opts.include_skeleton:
        bones = _skeleton_nodes(model)
        if bones:
            root.children.append(SNode("Skeleton", children=bones))
    tick(0.6, "Текстуры")
    return scene


def wants_customization(opts: ExportOptions) -> bool:
    return opts.addon_paths is not None or opts.include_customization or opts.include_cosmetic


def build_customization_scene(index: PakIndex, v: Vehicle, opts: ExportOptions,
                              progress: ProgressFn | None = None) -> Scene | None:
    """Отдельная сцена с деталями кастомизации (узлы Customization и Cosmetics) в тех же осях и координатах,
    что и машина: оба файла импортируются в Blender в одну точку и совпадают. None - деталей нет."""
    root = SNode(f"{v.id}_customization", extras={"vehicle_id": v.id, "source": v.source_label,
                                                   "axes": "glTF Y-up, +Z forward, meters, same origin as the vehicle file"})
    scene = Scene(root)
    root.children.extend(_customization_nodes(index, v, opts, scene, progress))
    return scene if root.children else None


# ------------------------------------------------------------------ GLB

class _GlbBuilder:
    def __init__(self) -> None:
        self.bin = bytearray()
        self.views: list[dict] = []
        self.accessors: list[dict] = []
        self.meshes: list[dict] = []
        self.nodes: list[dict] = []
        self.materials: list[dict] = []
        self.textures: list[dict] = []
        self.images: list[dict] = []
        self._tex_index: dict[tuple[str, bool], int] = {}
        self._mat_index: dict[str, int] = {}

    def view(self, data: bytes, target: int | None = None) -> int:
        while len(self.bin) % 4:
            self.bin.append(0)
        v = {"buffer": 0, "byteOffset": len(self.bin), "byteLength": len(data)}
        if target:
            v["target"] = target
        self.bin += data
        self.views.append(v)
        return len(self.views) - 1

    def accessor(self, arr: np.ndarray, ctype: str, comp: int, target: int, minmax: bool = False) -> int:
        a = {"bufferView": self.view(arr.tobytes(), target), "componentType": comp,
             "count": int(arr.shape[0]), "type": ctype}
        if minmax:
            a["min"] = [float(x) for x in arr.min(axis=0)]
            a["max"] = [float(x) for x in arr.max(axis=0)]
        self.accessors.append(a)
        return len(self.accessors) - 1

    def texture(self, scene: Scene, filename: str, png: dict[str, bytes]) -> int:
        key = (filename, True)
        if key not in self._tex_index:
            self.images.append({"bufferView": self.view(png[filename]), "mimeType": "image/png", "name": filename})
            self.textures.append({"sampler": 0, "source": len(self.images) - 1, "name": filename})
            self._tex_index[key] = len(self.textures) - 1
        return self._tex_index[key]

    def material(self, scene: Scene, m: SMaterial, png: dict[str, bytes]) -> int:
        if m.name in self._mat_index:
            return self._mat_index[m.name]
        pbr: dict = {"metallicFactor": 0.0, "roughnessFactor": 0.8}
        gm: dict = {"name": m.name, "pbrMetallicRoughness": pbr, "doubleSided": m.blend}
        if m.albedo:
            pbr["baseColorTexture"] = {"index": self.texture(scene, m.albedo, png)}
        else:
            pbr["baseColorFactor"] = [0.7, 0.7, 0.7, 1.0]
        if m.orm:
            pbr["metallicRoughnessTexture"] = {"index": self.texture(scene, m.orm, png)}
            pbr["metallicFactor"] = 1.0
            pbr["roughnessFactor"] = 1.0
            gm["occlusionTexture"] = {"index": pbr["metallicRoughnessTexture"]["index"]}
        if m.normal:
            gm["normalTexture"] = {"index": self.texture(scene, m.normal, png)}
        if m.emissive:
            gm["emissiveTexture"] = {"index": self.texture(scene, m.emissive, png)}
            gm["emissiveFactor"] = [1.0, 1.0, 1.0]
        if m.blend:
            gm["alphaMode"] = "BLEND"
        self.materials.append(gm)
        self._mat_index[m.name] = len(self.materials) - 1
        return self._mat_index[m.name]

    def mesh(self, scene: Scene, name: str, prims: list[stm.PrimitiveData], png: dict[str, bytes]) -> int:
        out = []
        for p in prims:
            attrs = {"POSITION": self.accessor(p.positions.astype(np.float32), "VEC3", 5126, 34962, True)}
            if p.normals is not None:
                attrs["NORMAL"] = self.accessor(p.normals.astype(np.float32), "VEC3", 5126, 34962)
            if p.uv0 is not None:
                attrs["TEXCOORD_0"] = self.accessor(p.uv0.astype(np.float32), "VEC2", 5126, 34962)
            if len(p.positions) < 65535:
                idx = self.accessor(p.indices.astype(np.uint16).reshape(-1, 1), "SCALAR", 5123, 34963)
            else:
                idx = self.accessor(p.indices.astype(np.uint32).reshape(-1, 1), "SCALAR", 5125, 34963)
            mat = scene.materials.get(p.material_name)
            prim = {"attributes": attrs, "indices": idx, "mode": 4}
            if mat is not None:
                prim["material"] = self.material(scene, mat, png)
            out.append(prim)
        self.meshes.append({"name": name, "primitives": out})
        return len(self.meshes) - 1

    def node(self, scene: Scene, n: SNode, png: dict[str, bytes]) -> int:
        d: dict = {"name": n.name}
        if n.primitives:
            d["mesh"] = self.mesh(scene, n.name, n.primitives, png)
        if n.matrix is not None:
            d["matrix"] = n.matrix
        if n.translation is not None:
            d["translation"] = list(n.translation)
        if n.rotation is not None and tuple(n.rotation) != (0.0, 0.0, 0.0, 1.0):
            d["rotation"] = list(n.rotation)
        if n.scale is not None:
            d["scale"] = list(n.scale)
        if n.extras:
            d["extras"] = n.extras
        self.nodes.append(d)
        me = len(self.nodes) - 1
        kids = [self.node(scene, c, png) for c in n.children]
        if kids:
            d["children"] = kids
        return me

    def build(self, root: int) -> bytes:
        gltf: dict = {"asset": {"version": "2.0", "generator": "SnowRunner Exporter (personal use)"},
                      "scene": 0, "scenes": [{"name": "Scene", "nodes": [root]}], "nodes": self.nodes,
                      "buffers": [{"byteLength": len(self.bin)}]}
        for key, val in (("meshes", self.meshes), ("materials", self.materials), ("textures", self.textures),
                         ("images", self.images), ("accessors", self.accessors), ("bufferViews", self.views)):
            if val:
                gltf[key] = val
        if self.textures:
            gltf["samplers"] = [{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497}]
        js = json.dumps(gltf, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        js += b" " * (-len(js) % 4)
        binary = bytes(self.bin) + b"\0" * (-len(self.bin) % 4)
        total = 12 + 8 + len(js) + 8 + len(binary)
        return (struct.pack("<III", 0x46546C67, 2, total) + struct.pack("<II", len(js), 0x4E4F534A) + js
                + struct.pack("<II", len(binary), 0x004E4942) + binary)


def write_glb(scene: Scene, path: Path) -> None:
    png = {name: texc.png_bytes(img) for name, img in scene.images.items()}
    b = _GlbBuilder()
    root = b.node(scene, scene.root, png)
    path.write_bytes(b.build(root))


# ------------------------------------------------------------------ OBJ + MTL

def _walk(n: SNode, parent_prefix: str = ""):
    name = f"{parent_prefix}{n.name}"
    if n.primitives:
        yield name, n
    for c in n.children:
        yield from _walk(c, name + ".")


def _node_to_world(n: SNode, vertices: np.ndarray) -> np.ndarray:
    """Применяет TRS узла (для колёс) к вершинам."""
    v = vertices.astype(np.float64)
    if n.scale is not None:
        v = v * np.array(n.scale)
    if n.rotation is not None:
        x, y, z, w = n.rotation
        r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                      [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                      [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
        v = v @ r.T
    if n.translation is not None:
        v = v + np.array(n.translation)
    return v.astype(np.float32)


def write_obj(scene: Scene, obj_path: Path) -> None:
    mtl_path = obj_path.with_suffix(".mtl")
    lines = [f"# SnowRunner Exporter: {scene.root.name}", f"mtllib {mtl_path.name}"]
    base_v = base_t = base_n = 1
    # путь от корня: узлы с TRS-родителем (колёса) переносим вручную
    stack: list[tuple[SNode, SNode | None, str]] = [(scene.root, None, "")]
    entries: list[tuple[str, SNode, SNode | None]] = []
    while stack:
        n, parent, prefix = stack.pop(0)
        name = (prefix + n.name) if prefix else n.name
        if n.primitives and n.name != scene.root.name:
            entries.append((name, n, parent))
        if n.name == "Skeleton":
            continue
        for c in n.children:
            stack.append((c, n, name + "."))
    for name, n, parent in entries:
        lines.append(f"o {name}")
        for i, p in enumerate(n.primitives or []):
            pos = p.positions
            if parent is not None and (parent.translation is not None or parent.scale is not None):
                pos = _node_to_world(parent, pos)
                nrm = None if p.normals is None else _node_to_world(SNode("n", rotation=parent.rotation), p.normals)
            else:
                nrm = p.normals
            lines += ["v %.6f %.6f %.6f" % tuple(r) for r in pos]
            has_t = p.uv0 is not None
            has_n = nrm is not None
            if has_t:
                lines += ["vt %.6f %.6f" % (u, 1.0 - vv) for u, vv in p.uv0]
            if has_n:
                lines += ["vn %.5f %.5f %.5f" % tuple(r) for r in nrm]
            lines.append(f"usemtl {p.material_name}")
            tri = p.indices.reshape(-1, 3).astype(np.int64)
            for a, b, c in tri:
                def ref(k: int) -> str:
                    v = base_v + k
                    if has_t and has_n:
                        return f"{v}/{base_t + k}/{base_n + k}"
                    if has_t:
                        return f"{v}/{base_t + k}"
                    if has_n:
                        return f"{v}//{base_n + k}"
                    return str(v)
                lines.append(f"f {ref(a)} {ref(b)} {ref(c)}")
            base_v += len(pos)
            if has_t:
                base_t += len(pos)
            if has_n:
                base_n += len(pos)
    obj_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    mtl = ["# SnowRunner Exporter"]
    for m in scene.materials.values():
        mtl += [f"newmtl {m.name}", "Ka 1 1 1", "Kd 1 1 1" if m.albedo else "Kd 0.7 0.7 0.7", "Ks 0.2 0.2 0.2", "d 1.0", "illum 2"]
        if m.albedo:
            mtl.append(f"map_Kd textures/{m.albedo}")
            if m.blend:
                mtl.append(f"map_d textures/{m.albedo}")
        if m.normal:
            mtl.append(f"map_Bump textures/{m.normal}")
        if m.emissive:
            mtl += ["Ke 1 1 1", f"map_Ke textures/{m.emissive}"]
        mtl.append("")
    mtl_path.write_text("\n".join(mtl), encoding="utf-8")


# ------------------------------------------------------------------ точка входа

def scene_stats(scene: Scene) -> dict:
    verts = tris = 0
    mins, maxs = np.full(3, np.inf), np.full(3, -np.inf)
    parts = 0

    def rec(n: SNode, parent: SNode | None, extra: bool = False) -> None:
        nonlocal verts, tris, parts, mins, maxs
        if n.primitives:
            parts += 1
            for p in n.primitives:
                pos = _node_to_world(parent, p.positions) if parent is not None and parent.translation is not None else p.positions
                verts += len(pos)
                tris += len(p.indices) // 3
                if not extra:           # габариты считаем по самой машине, без бамперов, кранов и рам
                    mins = np.minimum(mins, pos.min(0))
                    maxs = np.maximum(maxs, pos.max(0))
        for c in n.children:
            rec(c, n, extra or c.name in ("Customization", "Cosmetics"))
    rec(scene.root, None)
    size = (maxs - mins) if parts else np.zeros(3)
    return {"parts": parts, "vertices": verts, "triangles": tris, "materials": len(scene.materials),
            "textures": len(scene.images),
            "bbox_min": [round(float(x), 3) for x in mins], "bbox_max": [round(float(x), 3) for x in maxs],
            "size_xyz_m": [round(float(x), 3) for x in size],
            "nan": bool(not np.isfinite(size).all())}


def _export_fbx_mod(index: PakIndex, v: Vehicle, folder: Path, opts: ExportOptions,
                    progress: ProgressFn | None) -> ExportResult:
    """Моды хранят исходный FBX, а не STM. FBX копируется как есть (Blender открывает его сам),
    текстуры из описания материалов преобразуются в PNG."""
    folder.mkdir(parents=True, exist_ok=True)
    warnings = ["мод хранит исходный FBX: файл скопирован без изменений, материалы назначьте по PNG из папки textures"]
    fbx = folder / f"{_safe_name(v.id)}.fbx"
    fbx.write_bytes(index.read(f"meshes/{v.mesh}.fbx"))
    files: list[Path] = []
    xml = index.try_read(f"meshes/{v.mesh}.xml")
    if xml and opts.textures:
        from vehicle_parser import parse_xml_lenient
        root = parse_xml_lenient(xml)
        done: set[str] = set()
        for m in (root.iter("Material") if root is not None else []):
            for key in ("AlbedoMap", "NormalMap", "ShadingMap", "EmissiveMap"):
                tga = m.get(key)
                if not tga or tga in done:
                    continue
                done.add(tga)
                img = texc.load_game_texture(index, tga)
                if img is None:
                    warnings.append(f"текстура не загружена: {tga}")
                    continue
                if key == "NormalMap":
                    img = texc.prepare_normal(img, opts.flip_normal_green)
                p = folder / "textures" / (Path(tga).stem + ".png")
                texc.save_png(img.convert("RGBA") if key == "AlbedoMap" else img.convert("RGB"), p)
                files.append(p)
    if progress:
        progress(1.0, "Готово")
    return ExportResult(folder, fbx, files, warnings, {"parts": 0, "vertices": 0, "triangles": 0, "materials": 0,
                                                      "textures": len(files), "size_xyz_m": [0, 0, 0]})


def export_vehicle(index: PakIndex, v: Vehicle, out_dir: Path, opts: ExportOptions,
                   progress: ProgressFn | None = None) -> ExportResult:
    """Экспортирует одну машину в out_dir/<id>/. Бросает исключение при невозможности экспорта
    (вызывающий код показывает его пользователю и продолжает работу)."""
    def tick(f: float, msg: str) -> None:
        if progress:
            progress(f, msg)

    folder = Path(out_dir) / _safe_name(v.id)
    if v.stm_path not in index and f"meshes/{v.mesh}.fbx" in index:
        return _export_fbx_mod(index, v, folder, opts, progress)
    folder.mkdir(parents=True, exist_ok=True)
    custom = wants_customization(opts)
    split = 0.5 if custom else 1.0          # доля шкалы прогресса на файл самой машины
    scene = build_scene(index, v, opts, _scaled(progress, 0.0, split))      # build_scene сообщает 0..0.6
    model_file, files = _write_scene(scene, folder, _safe_name(v.id), opts, _scaled(progress, split * 0.6, split))
    res = ExportResult(folder, model_file, files, scene.warnings, scene_stats(scene))
    if custom:
        tick(split, "Кастомизация")
        cscene = build_customization_scene(index, v, opts, _scaled(progress, split, split + (1 - split) * 0.4))
        if cscene is None:
            res.warnings.append("деталей кастомизации для выгрузки не найдено, отдельный файл не создан")
        else:
            cfile, cfiles = _write_scene(cscene, folder, f"{_safe_name(v.id)}_customization", opts,
                                         _scaled(progress, split + (1 - split) * 0.4, 1.0))
            res.custom_file = cfile
            res.texture_files += [p for p in cfiles if p not in res.texture_files]
            res.warnings += cscene.warnings
            res.custom_stats = scene_stats(cscene)
    tick(1.0, "Готово")
    return res


def _scaled(progress: ProgressFn | None, lo: float, hi: float) -> ProgressFn | None:
    """Прогресс части работы (0..1) переносится на отрезок [lo, hi] общей шкалы."""
    if progress is None:
        return None
    return lambda f, msg: progress(lo + (hi - lo) * f, msg)


def _write_scene(scene: Scene, folder: Path, stem: str, opts: ExportOptions,
                 progress: ProgressFn | None) -> tuple[Path, list[Path]]:
    """Текстуры в folder/textures и файл модели folder/<stem>.glb|obj. Прогресс 0..1."""
    def tick(f: float, msg: str) -> None:
        if progress:
            progress(f, msg)

    files: list[Path] = []
    n = len(scene.images)
    for i, (name, img) in enumerate(scene.images.items()):
        tick(0.75 * (i / max(n, 1)), f"PNG: {name}")
        p = folder / "textures" / name
        texc.save_png(img, p)
        files.append(p)
    tick(0.9, "Запись модели")
    model_file = folder / f"{stem}.{'glb' if opts.fmt == 'glb' else 'obj'}"
    if opts.fmt == "glb":
        write_glb(scene, model_file)
    else:
        write_obj(scene, model_file)
    return model_file, files
