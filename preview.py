"""
preview.py
==========
Превью машин и деталей кастомизации без OpenGL: программная отрисовка треугольников
(метод художника) с цветом из уменьшенной текстуры. Используется для подсказок при наведении.

Готовые картинки лежат в DATA_DIR/previews/<версия>_<подпись архивов>/*.png, поэтому второй раз
превью открывается сразу. Функции thread-safe в части файлов: разные ключи - разные файлы.
"""

from __future__ import annotations

import hashlib
import io
import logging
import math
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

import exporter as ex
import paths
import stm_converter as stm
from pak_reader import PakIndex
from vehicle_parser import Addon, Vehicle

log = logging.getLogger("preview")

PREVIEW_VERSION = 2
VEHICLE_SIZE = (420, 270)
ADDON_SIZE = (320, 230)
BG = (60, 65, 74)                    # PALETTE["card_hi"]
_SS = 2                              # суперсэмплинг: рисуем в 2x и уменьшаем
_FALLBACK = (156, 164, 178)          # цвет детали без текстуры
_THUMB = 32


@dataclass
class _Item:
    pos: np.ndarray                  # (N, 3) мировые оси glTF
    idx: np.ndarray                  # (T, 3)
    uv: np.ndarray | None
    thumb: np.ndarray | None         # (h, w, 3) uint8


# ------------------------------------------------------------------ сцена -> элементы

def _collect(scene: ex.Scene) -> list[_Item]:
    """Плоский список примитивов с учётом поворота и масштаба узлов (колёса). Стёкла (blend) пропускаются."""
    thumbs: dict[str, np.ndarray] = {}

    def thumb_of(fn: str | None) -> np.ndarray | None:
        if not fn or fn not in scene.images:
            return None
        if fn not in thumbs:
            img = scene.images[fn].convert("RGB").resize((_THUMB, _THUMB), Image.BOX)
            thumbs[fn] = np.asarray(img, dtype=np.uint8)
        return thumbs[fn]

    out: list[_Item] = []

    def rec(n: ex.SNode, parent: ex.SNode | None) -> None:
        for p in n.primitives or []:
            mat = scene.materials.get(p.material_name)
            if mat is not None and mat.blend:
                continue
            pos = p.positions
            if parent is not None and (parent.translation is not None or parent.scale is not None
                                       or parent.rotation is not None):
                pos = ex._node_to_world(parent, pos)
            out.append(_Item(pos.astype(np.float32), p.indices.reshape(-1, 3).astype(np.int64),
                             p.uv0, thumb_of(mat.albedo if mat else None)))
        for c in n.children:
            rec(c, n)

    rec(scene.root, None)
    return out


# ------------------------------------------------------------------ рисование

def _render(items: list[_Item], size: tuple[int, int], az: float = 38.0, el: float = 17.0,
            gamma: float = 0.75, lift: float = 6.0) -> Image.Image | None:
    items = [it for it in items if len(it.idx)]
    if not items:
        return None
    W, H = size
    w, h = W * _SS, H * _SS
    a, e = math.radians(az), math.radians(el)
    zv = np.array([math.sin(a) * math.cos(e), math.sin(e), math.cos(a) * math.cos(e)])   # к камере
    xv = np.cross([0.0, 1.0, 0.0], zv)
    xv /= np.linalg.norm(xv)
    yv = np.cross(zv, xv)
    light = zv * 0.55 + np.array([0.0, 0.8, 0.0]) - xv * 0.45
    light /= np.linalg.norm(light)

    allp = np.concatenate([it.pos for it in items]).astype(np.float64)
    sx, sy = allp @ xv, allp @ yv
    x0, x1 = float(sx.min()), float(sx.max())
    y0, y1 = float(sy.min()), float(sy.max())
    margin = 0.07 * min(w, h)
    scale = min((w - 2 * margin) / max(x1 - x0, 1e-6), (h - 2 * margin) / max(y1 - y0, 1e-6))
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2

    polys, depths, colors = [], [], []
    for it in items:
        p3 = it.pos.astype(np.float64)[it.idx]                       # (T, 3, 3)
        n = np.cross(p3[:, 1] - p3[:, 0], p3[:, 2] - p3[:, 0])
        ln = np.linalg.norm(n, axis=1)
        ok = (ln > 1e-12) & (n @ zv > 0)                             # лицевые грани
        if not ok.any():
            continue
        p3, n, ln = p3[ok], n[ok], ln[ok]
        idx = it.idx[ok]
        X = (p3 @ xv - cx) * scale + w / 2
        Y = h / 2 - (p3 @ yv - cy) * scale
        area = 0.5 * np.abs((X[:, 1] - X[:, 0]) * (Y[:, 2] - Y[:, 0]) - (X[:, 2] - X[:, 0]) * (Y[:, 1] - Y[:, 0]))
        keep = area > 0.15
        if not keep.any():
            continue
        X, Y, n, ln, idx, p3 = X[keep], Y[keep], n[keep], ln[keep], idx[keep], p3[keep]
        nn = n / ln[:, None]
        shade = 0.38 + 0.62 * np.clip(nn @ light, 0.0, 1.0)
        if it.thumb is not None and it.uv is not None:
            uvc = it.uv[idx].mean(axis=1)
            th, tw = it.thumb.shape[:2]
            tx = (np.mod(uvc[:, 0], 1.0) * (tw - 1)).astype(np.int64)
            ty = (np.mod(uvc[:, 1], 1.0) * (th - 1)).astype(np.int64)
            base = it.thumb[ty, tx].astype(np.float64)
            base = 255.0 * (base / 255.0) ** gamma                   # базовые текстуры тёмные: осветляем
        else:
            base = np.tile(np.array(_FALLBACK, np.float64), (len(idx), 1))
        col = np.clip(base * shade[:, None] * 1.1 + lift, 0, 255).astype(np.uint8)
        polys.append(np.stack([X, Y], axis=2).reshape(-1, 6))
        depths.append((p3 @ zv).mean(axis=1))
        colors.append(col)
    if not polys:
        return None
    poly = np.concatenate(polys)
    depth = np.concatenate(depths)
    col = np.concatenate(colors)
    order = np.argsort(depth)                                         # от дальних к ближним
    img = Image.new("RGB", (w, h), BG)
    draw = ImageDraw.Draw(img)
    for pts, c in zip(poly[order].tolist(), map(tuple, col[order].tolist())):
        draw.polygon(pts, fill=c)
    return img.resize((W, H), Image.LANCZOS)


# ------------------------------------------------------------------ кэш на диске

def _cache_dir(index: PakIndex) -> Path:
    sig = hashlib.md5(index.signature().encode("utf-8")).hexdigest()[:8]
    d = paths.DATA_DIR / "previews" / f"v{PREVIEW_VERSION}_{sig}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _file_for(index: PakIndex, kind: str, key: str) -> Path:
    safe = re.sub(r"[^\w.\-]+", "_", key)[-80:]
    return _cache_dir(index) / f"{kind}_{safe}_{hashlib.md5(key.encode('utf-8')).hexdigest()[:6]}.png"


def _to_png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=False)
    return buf.getvalue()


def _cached(index: PakIndex, kind: str, key: str, make) -> bytes | None:
    """PNG-байты превью: с диска или из make() -> PIL.Image | None. При неудаче None (и пустой файл не пишется)."""
    path = _file_for(index, kind, key)
    try:
        if path.is_file():
            return path.read_bytes()
    except OSError:
        pass
    img = make()
    if img is None:
        return None
    data = _to_png(img)
    try:
        path.write_bytes(data)
    except OSError:
        pass
    return data


# ------------------------------------------------------------------ публичные функции

def vehicle_preview_png(index: PakIndex, v: Vehicle) -> bytes | None:
    def make() -> Image.Image | None:
        opts = ex.ExportOptions(textures=True, albedo_only=True, include_wheels=True)
        try:
            scene = ex.build_scene(index, v, opts)
        except (stm.StmError, KeyError, ValueError) as exc:
            log.info("Превью %s недоступно: %s", v.id, exc)
            return None
        return _render(_collect(scene), VEHICLE_SIZE)

    return _cached(index, "vehicle", v.key, make)


def addon_preview_png(index: PakIndex, a: Addon) -> bytes | None:
    def make() -> Image.Image | None:
        opts = ex.ExportOptions(textures=True, albedo_only=True)
        scene = ex.Scene(ex.SNode(a.id))
        try:
            model = stm.parse_stm(index.read(a.stm_path), a.stm_path)
            mb = ex._MaterialBuilder(index, scene, opts)
            scene.root.children = ex._model_part_nodes(model, mb, opts, scene)
        except (stm.StmError, KeyError, ValueError) as exc:
            log.info("Превью детали %s недоступно: %s", a.id, exc)
            return None
        return _render(_collect(scene), ADDON_SIZE, az=142.0 if "rear" in a.sockets[0].lower() else 38.0,    # задние детали смотрим сзади
                       gamma=0.55, lift=26.0)

    return _cached(index, "addon", a.path, make)
