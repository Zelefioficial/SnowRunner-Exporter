"""
stm_converter.py
================
Чтение компилированных моделей SnowRunner (формат "STM", в архивах лежит как
``[meshes]/<имя>`` без расширения) и преобразование в наборы мешей для экспорта.

Формат восстановлен по реальным файлам игры (см. README.md, раздел "Формат STM").
Кратко (все числа little-endian):

    u32  xml_len
    char xml[xml_len]            <CombineXMesh> - материалы, скины, точки привязки
    --- бинарная часть ("blob") ---
    u32  magic/version (0x0133EF63)
    u32  44
    f32  bbox[6]                 min xyz, max xyz всей модели
    u32  число "корневых" записей (в разборе не нужно)
    node*:                       узлы (кости и меши) подряд
        i16 parent, u16 index, u32 kind
        u32 name_len, char name[name_len]   (с завершающим нулём)
        f32 matrix[16]           4x4, строки, перенос в последней строке
        kind != 0  ->  u32 0 (кость/пустышка, данных геометрии нет)
        kind == 0  ->  блок меша (см. parse_mesh_block)

Игровые оси: X - вперёд, Y - вверх, Z - влево (левосторонняя система).
Для glTF/Blender: (x, y, z)_game -> (z, y, x)_gltf, порядок вершин в
треугольнике меняется на обратный. Единицы - метры.
"""

from __future__ import annotations

import logging
import re
import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import numpy as np

log = logging.getLogger("stm")


class StmError(Exception):
    """Файл не удалось разобрать как STM."""


# ---------------------------------------------------------------- структуры

@dataclass
class SubMesh:
    material_index: int
    first_tri: int
    tri_count: int
    first_vtx: int
    vtx_count: int
    palette: list[int]            # индексы в список joints меша


@dataclass
class StmMesh:
    node_index: int
    name: str                     # имя узла, например "hp_cab"
    mesh_name: str                # внутреннее имя, например "mesh_hp_cab"
    material_names: list[str]
    joints: list[int]             # индексы узлов-костей, на которые навешен меш
    inv_bind: np.ndarray          # (K, 4, 4) float32, как в файле
    submeshes: list[SubMesh]
    bbox: tuple[float, ...]
    positions: np.ndarray         # (N, 3) float32, игровые оси
    normals: np.ndarray | None    # (N, 3) float32
    uv0: np.ndarray | None        # (N, 2) float32
    weights: np.ndarray | None    # (N, 4) float32
    bone_idx: np.ndarray | None   # (N, 4) uint8
    indices: np.ndarray           # (T, 3) uint32
    is_collision: bool = False    # "cdt_*" - упрощённая геометрия коллизий


@dataclass
class StmNode:
    index: int
    parent: int
    kind: int
    name: str
    matrix: np.ndarray            # (4, 4) float32, как в файле (строки)
    mesh: StmMesh | None = None


@dataclass
class StmModel:
    source_name: str
    xml: ET.Element | None
    bbox: tuple[float, ...]
    nodes: list[StmNode]
    materials: dict[str, dict[str, str]] = field(default_factory=dict)
    skins: list[dict[str, str]] = field(default_factory=list)
    sockets: dict[str, tuple[float, float, float]] = field(default_factory=dict)

    @property
    def meshes(self) -> list[StmMesh]:
        return [n.mesh for n in self.nodes if n.mesh is not None]

    def visible_meshes(self) -> list[StmMesh]:
        return [m for m in self.meshes if not m.is_collision]


# ---------------------------------------------------------------- разбор

# в именах бывают не-ASCII символы (кириллическая "С" в "BoneСabinTwist_cdt"), запрещаем только управляющие
_NAME_RE = re.compile(rb"[^\x00-\x1f\x7f]+")
_ELEMENT_SIZE = {1: 8, 2: 12, 3: 16, 5: 4, 8: 4}   # тип элемента вершины -> байт
# usage: 0 - позиция/UV0, 1 - нормаль, 2 - касательная, 4 - веса, 5 - индексы костей, 6 - UV1


def _parse_vec(text: str) -> tuple[float, ...]:
    return tuple(float(x) for x in text.strip("() ").split(";"))


def _parse_xml(xml_text: str) -> tuple[ET.Element | None, dict, list, dict]:
    materials: dict[str, dict[str, str]] = {}
    skins: list[dict[str, str]] = []
    sockets: dict[str, tuple[float, float, float]] = {}
    try:
        root = ET.fromstring(xml_text.strip("\x00 \r\n\t"))
    except ET.ParseError:
        # в некоторых файлах у <Material> повторяются атрибуты (недопустимо для XML):
        # разбираем теги регулярками, при повторе берётся первое значение
        log.info("STM: XML с повторяющимися атрибутами, разбор вручную")
        attr_re = re.compile(r'([A-Za-z_][\w.\-]*)\s*=\s*"([^"]*)"')
        for tag, bucket in (("Material", None), ("MaterialOverride", skins)):
            for m in re.finditer(r"<%s\b([^>]*?)/?>" % tag, xml_text, re.S):
                attrs: dict[str, str] = {}
                for k, v in attr_re.findall(m.group(1)):
                    attrs.setdefault(k, v)
                if bucket is None:
                    if attrs.get("Name"):
                        materials[attrs["Name"]] = attrs
                else:
                    bucket.append(attrs)
        for m in re.finditer(r"<SocketPoint\b([^>]*?)/?>", xml_text, re.S):
            a = dict(attr_re.findall(m.group(1)))
            try:
                v = _parse_vec(a.get("Pos", "(0;0;0)"))
                sockets[a.get("Name", "")] = (v[0], v[1], v[2])
            except (ValueError, IndexError):
                pass
        return None, materials, skins, sockets
    for m in root.iter("Material"):
        name = m.get("Name")
        if name:
            materials[name] = dict(m.attrib)
    for m in root.iter("MaterialOverride"):
        skins.append(dict(m.attrib))
    for s in root.iter("SocketPoint"):
        try:
            v = _parse_vec(s.get("Pos", "(0;0;0)"))
            sockets[s.get("Name", "")] = (v[0], v[1], v[2])
        except ValueError:
            pass
    return root, materials, skins, sockets


class _Reader:
    def __init__(self, data: bytes):
        self.d = data

    def u32(self, o: int) -> int:
        return struct.unpack_from("<I", self.d, o)[0]

    def u16(self, o: int) -> int:
        return struct.unpack_from("<H", self.d, o)[0]

    def string(self, o: int) -> tuple[str, int]:
        ln = self.u32(o)
        if ln == 0 or ln > 512 or o + 4 + ln > len(self.d):
            raise StmError(f"некорректная строка по смещению {o:#x}")
        raw = self.d[o + 4:o + 4 + ln]
        return raw.rstrip(b"\x00").decode("utf-8", "replace"), o + 4 + ln

    def matrices(self, o: int, count: int) -> np.ndarray:
        if count == 0:
            return np.zeros((0, 4, 4), np.float32)
        return np.frombuffer(self.d, "<f4", count * 16, o).reshape(count, 4, 4).copy()


def _looks_like_node(d: bytes, q: int, expect_index: int) -> bool:
    if q < 0 or q + 16 > len(d):
        return False
    parent, index, kind, ln = struct.unpack_from("<hHII", d, q)
    if index != expect_index or kind > 64 or not 2 <= ln <= 96:
        return False
    if q + 12 + ln + 64 > len(d):
        return False
    raw = d[q + 12:q + 12 + ln]
    return raw.endswith(b"\x00") and _NAME_RE.fullmatch(raw[:-1]) is not None


def _find_next_node(d: bytes, start: int, expect_index: int, window: int = 1 << 16) -> int:
    """Ищет заголовок следующего узла (за блоком коллизий может лежать
    блоб неизвестной длины, поэтому границу находим по сигнатуре узла)."""
    pat = re.compile(
        rb".{2}" + re.escape(struct.pack("<H", expect_index)) + rb"[\x00-\x40]\x00\x00\x00[\x02-\x60]\x00\x00\x00[^\x00-\x1f]",
        re.S,
    )
    end = min(len(d), start + window)
    pos = start
    while True:
        m = pat.search(d, pos, end)
        if not m:
            return -1
        if _looks_like_node(d, m.start(), expect_index):
            return m.start()
        pos = m.start() + 1


def _decode_vertices(raw: np.ndarray, decl: list[tuple[int, int, int]], count: int):
    """raw: (count, stride) uint8. Возвращает позиции, нормали, uv0, веса, индексы костей."""
    pos = normals = uv0 = weights = bone_idx = None
    for off, typ, usage in decl:
        size = _ELEMENT_SIZE.get(typ)
        if size is None:
            log.warning("STM: неизвестный тип элемента вершины %d", typ)
            continue
        chunk = np.ascontiguousarray(raw[:, off:off + size])
        if typ == 2 and usage == 0:
            pos = chunk.view("<f4").reshape(count, 3).astype(np.float32)
        elif typ == 1 and usage == 0:
            uv0 = chunk.view("<f4").reshape(count, 2).astype(np.float32)
        elif typ == 8 and usage == 1:
            n = chunk[:, :3].astype(np.float32) / 255.0 * 2.0 - 1.0
            ln = np.linalg.norm(n, axis=1, keepdims=True)
            normals = (n / np.maximum(ln, 1e-8)).astype(np.float32)
        elif typ == 8 and usage == 4:
            weights = chunk.astype(np.float32) / 255.0
        elif typ == 5 and usage == 5:
            bone_idx = chunk.copy()
    if pos is None:
        raise StmError("в вершинах нет позиций")
    return pos, normals, uv0, weights, bone_idx


def _parse_mesh_block(r: _Reader, o3: int, node_index: int, node_name: str):
    """o3 - смещение сразу за матрицей узла. Возвращает (StmMesh, конец_данных)."""
    d = r.d
    vc, tc = r.u32(o3), r.u32(o3 + 4)
    mesh_name, o4 = r.string(o3 + 8)
    n_a, n_mat, _zero = r.u32(o4), r.u32(o4 + 4), r.u32(o4 + 8)
    o5 = o4 + 12
    if n_mat > 64:
        raise StmError(f"{node_name}: слишком много материалов ({n_mat})")
    mat_names = []
    for _ in range(n_mat):
        s, o5 = r.string(o5)
        mat_names.append(s)
    k = r.u32(o5)
    if k > 256:
        raise StmError(f"{node_name}: слишком много костей ({k})")
    inv_bind = r.matrices(o5 + 4, k)
    o6 = o5 + 4 + 64 * k
    n_joint = max(k, 1)

    submeshes: list[SubMesh] = []
    if k == 0:
        # жёсткая геометрия без костей, один подмеш.
        # [u16 узел][bbox] и затем либо [1,0,0,tc,0,vc] (видимые меши), либо [u32 0] (коллизии cdt_*)
        # [u16 узел][bbox][u32 n][запись подмеша * n][n_decl]; у коллизий n == 0
        joints = [r.u16(o6)]
        bbox_o = o6 + 2
        p = bbox_o + 24
        n_rec = r.u32(p)
        if n_rec > 64:
            raise StmError(f"{node_name}: неверное число подмешей {n_rec}")
        p += 4
        for i in range(n_rec):
            mat, ft, tcnt, fv, vcnt = struct.unpack_from("<5I", d, p)
            p += 20
            submeshes.append(SubMesh(mat, ft, tcnt, fv, vcnt, [0]))
        if not submeshes:
            submeshes.append(SubMesh(0, 0, tc, 0, vc, [0]))
        n_decl = r.u32(p)
        p += 4
    else:
        # [A][nSub][nb * nSub] { [mat][first_tri][tri_count][first_vtx][vtx_count][palette * nb] } * nSub
        n_sub = r.u32(o6 + 4)
        if not 1 <= n_sub <= 64:
            raise StmError(f"{node_name}: неверное число подмешей {n_sub}")
        q = o6 + 8
        nb = [r.u32(q + 4 * i) for i in range(n_sub)]
        q += 4 * n_sub
        for i in range(n_sub):
            mat, ft, tcnt, fv, vcnt = struct.unpack_from("<5I", d, q)
            q += 20
            pal = [r.u32(q + 4 * j) for j in range(nb[i])]
            q += 4 * nb[i]
            submeshes.append(SubMesh(mat, ft, tcnt, fv, vcnt, pal))
        joints = [r.u16(q + 2 * j) for j in range(k)]
        bbox_o = q + 2 * k
        p = bbox_o + 24
        # [1][0][0][tc][0][vc] - повтор счётчиков
        if struct.unpack_from("<6I", d, p) != (1, 0, 0, tc, 0, vc):
            raise StmError(f"{node_name}: не совпала сигнатура счётчиков геометрии")
        p += 24
        n_decl = r.u32(p)
        p += 4
    bbox = struct.unpack_from("<6f", d, bbox_o)
    if not 1 <= n_decl <= 16:
        raise StmError(f"{node_name}: неверное число элементов вершины ({n_decl})")
    decl = []
    for _ in range(n_decl):
        _stream, off, typ, _flag, usage = struct.unpack_from("<HHHBB", d, p)
        decl.append((off, typ, usage))
        p += 8
    last = max(decl, key=lambda e: e[0])
    size = _ELEMENT_SIZE.get(last[1])
    if size is None:
        raise StmError(f"{node_name}: неизвестный тип элемента {last[1]}")
    stride = last[0] + size
    p += 8                                            # [0xFF][0x11] - не используется
    if p + vc * stride > len(d):
        raise StmError(f"{node_name}: вершинный буфер выходит за файл")
    raw = np.frombuffer(d, np.uint8, vc * stride, p).reshape(vc, stride)
    pos, nrm, uv0, wts, bix = _decode_vertices(raw, decl, vc)
    iv = p + vc * stride
    isz = 2 if vc <= 0x10000 else 4
    idx_dtype = "<u2" if isz == 2 else "<u4"
    if iv + tc * 3 * isz > len(d):
        raise StmError(f"{node_name}: индексный буфер выходит за файл")
    idx = np.frombuffer(d, idx_dtype, tc * 3, iv).reshape(tc, 3).astype(np.uint32)
    if len(idx) and int(idx.max()) >= vc:
        raise StmError(f"{node_name}: индекс {int(idx.max())} за пределами {vc} вершин")
    mesh = StmMesh(
        node_index=node_index, name=node_name, mesh_name=mesh_name, material_names=mat_names,
        joints=joints[:n_joint], inv_bind=inv_bind, submeshes=submeshes, bbox=bbox,
        positions=pos, normals=nrm, uv0=uv0, weights=wts, bone_idx=bix, indices=idx,
        is_collision=node_name.lower().startswith("cdt_") or mesh_name.lower() == "cdt_mesh",
    )
    return mesh, iv + tc * 3 * isz


def parse_stm(data: bytes, source_name: str = "") -> StmModel:
    """Разбирает файл STM целиком. Бросает StmError при неизвестной структуре."""
    if len(data) < 64:
        raise StmError("файл слишком мал")
    xml_len = struct.unpack_from("<I", data, 0)[0]
    if xml_len > len(data) - 4 or data[4:5] != b"<":
        raise StmError("нет XML-заголовка: это не STM или неизвестная версия")
    xml_text = data[4:4 + xml_len].decode("utf-8", "replace")
    xml_root, materials, skins, sockets = _parse_xml(xml_text)
    d = data[4 + xml_len:]
    r = _Reader(d)
    model_bbox = struct.unpack_from("<6f", d, 8)
    nodes: list[StmNode] = []
    o = 36
    expect = 0
    while _looks_like_node(d, o, expect):
        parent, index, kind = struct.unpack_from("<hHI", d, o)
        name, o2 = r.string(o + 8)
        matrix = np.frombuffer(d, "<f4", 16, o2).reshape(4, 4).copy()
        o3 = o2 + 64
        node = StmNode(index, parent, kind, name, matrix)
        nodes.append(node)
        # кость/пустышка: за матрицей идёт u32 0 и сразу следующий узел.
        # У меша на этом месте число вершин (> 0). Поле kind для этого не годится.
        if r.u32(o3) == 0:
            o = o3 + 4
            expect += 1
            continue
        try:
            mesh, end = _parse_mesh_block(r, o3, index, name)
        except (StmError, struct.error, ValueError) as exc:
            raise StmError(f"узел '{name}': {exc}") from exc
        node.mesh = mesh
        expect += 1
        o = _find_next_node(d, end, expect)
        if o < 0:
            break
    if not nodes:
        raise StmError("в файле не найдено ни одного узла")
    return StmModel(source_name, xml_root, model_bbox, nodes, materials, skins, sockets)


# ---------------------------------------------------------------- преобразование осей

_P = np.array([[0, 0, 1], [0, 1, 0], [1, 0, 0]], np.float32)   # (x,y,z)->(z,y,x)


def game_to_gltf_points(p: np.ndarray) -> np.ndarray:
    """Игровые оси (X вперёд, Y вверх, Z влево) -> glTF (Y вверх, Z вперёд, X влево)."""
    return np.ascontiguousarray(p[:, [2, 1, 0]])


def game_to_gltf_matrix(m: np.ndarray) -> np.ndarray:
    """4x4 (строки, перенос в последней строке) -> то же в осях glTF.
    Область памяти совпадает с column-major матрицей glTF."""
    p4 = np.eye(4, dtype=np.float64)
    p4[:3, :3] = _P
    return (p4 @ m.astype(np.float64) @ p4).astype(np.float32)


@dataclass
class PrimitiveData:
    """Один примитив (подмеш с одним материалом) в осях glTF."""
    material_name: str
    positions: np.ndarray
    normals: np.ndarray | None
    uv0: np.ndarray | None
    indices: np.ndarray           # (3T,) uint32


@dataclass
class PartData:
    """Деталь машины = один узел STM с мешем."""
    name: str
    primitives: list[PrimitiveData]
    node_index: int


def mesh_to_part(mesh: StmMesh) -> PartData:
    """Режет меш на примитивы по материалам и переводит в оси glTF."""
    pos = game_to_gltf_points(mesh.positions)
    nrm = game_to_gltf_points(mesh.normals) if mesh.normals is not None else None
    prims: list[PrimitiveData] = []
    for sub in mesh.submeshes:
        tris = mesh.indices[sub.first_tri:sub.first_tri + sub.tri_count]
        if len(tris) == 0:
            continue
        # индексы в таблице относятся к вершинам всего меша; берём только используемые
        used, inverse = np.unique(tris.reshape(-1), return_inverse=True)
        tri = inverse.reshape(-1, 3)[:, [0, 2, 1]]          # зеркало осей -> разворот обхода
        mat = (mesh.material_names[sub.material_index]
               if sub.material_index < len(mesh.material_names) else "default")
        prims.append(PrimitiveData(
            material_name=mat,
            positions=pos[used],
            normals=nrm[used] if nrm is not None else None,
            uv0=mesh.uv0[used] if mesh.uv0 is not None else None,
            indices=tri.reshape(-1).astype(np.uint32),
        ))
    return PartData(mesh.name, prims, mesh.node_index)
