"""
texture_converter.py
====================
РўРµРєСЃС‚СѓСЂС‹ РёРіСЂС‹ -> PNG.

Р¤РѕСЂРјР°С‚ .pct (РЅР°Р№РґРµРЅ РЅР° СЂРµР°Р»СЊРЅС‹С… С„Р°Р№Р»Р°С…, РїСЂРѕРІРµСЂРµРЅ СЃСЂР°РІРЅРµРЅРёРµРј СЃ TGA РёР· mod.pak, PSNR 46-53 РґР‘):

    [shared_textures.pak]  [textures]/pct/<РёРјСЏ>.pct          - Р·Р°РіРѕР»РѕРІРѕРє + РІСЃРµ mip-СѓСЂРѕРІРЅРё РїРѕРґСЂСЏРґ
                           [textures]/pct/<РёРјСЏ>.pct_header   - РєРѕРїРёСЏ Р·Р°РіРѕР»РѕРІРєР° (РµРіРѕ РґР»РёРЅР° = СЃРјРµС‰РµРЅРёРµ РґР°РЅРЅС‹С…)
    [shared_textures_base.pak] <РёРјСЏ>.pct_base                - С‚РѕР»СЊРєРѕ РЅРёР¶РЅРёРµ mip-СѓСЂРѕРІРЅРё (128 px), Р·Р°РїР°СЃРЅРѕР№ РІР°СЂРёР°РЅС‚

    Р·Р°РіРѕР»РѕРІРѕРє: ... 'TCIP' (+6)  u32 width (+0x10)  u32 height (+0x14)  ... u8 РєРѕРґ С„РѕСЂРјР°С‚Р° (+0x26)
    РґР°РЅРЅС‹Рµ: BC7 (DXGI 98), РїРµСЂРІС‹Р№ СѓСЂРѕРІРµРЅСЊ - СЃР°РјС‹Р№ Р±РѕР»СЊС€РѕР№, СЃС‚СЂРѕРєРё СЃРІРµСЂС…Сѓ РІРЅРёР·.
    СЂР°Р·РјРµСЂ СѓСЂРѕРІРЅСЏ 0 = width * height Р±Р°Р№С‚.

РљР°РЅР°Р»С‹ РїРѕ СЃСѓС„С„РёРєСЃР°Рј РёРјС‘РЅ: __d - Р°Р»СЊР±РµРґРѕ, __d_a - Р°Р»СЊР±РµРґРѕ + Р°Р»СЊС„Р°, __n_d - РєР°СЂС‚Р° РЅРѕСЂРјР°Р»РµР№ RGB
(Р·РµР»С‘РЅС‹Р№ РєР°РЅР°Р» РёРЅРІРµСЂС‚РёСЂРѕРІР°РЅ РѕС‚РЅРѕСЃРёС‚РµР»СЊРЅРѕ glTF), __sh_d - "shading" (R = РјРµС‚Р°Р»Р»РёС‡РЅРѕСЃС‚СЊ, G = С€РµСЂРѕС…РѕРІР°С‚РѕСЃС‚СЊ,
B = Р·Р°С‚РµРЅРµРЅРёРµ; СЌС‚Рѕ РїСЂРµРґРїРѕР»РѕР¶РµРЅРёРµ РїРѕ СЃС‚Р°С‚РёСЃС‚РёРєРµ, СЃРј. README), __em_d - СЌРјРёСЃСЃРёСЏ.
"""

from __future__ import annotations

import io
import logging
import struct
from pathlib import Path

import numpy as np
from PIL import Image

from pak_reader import PakIndex
from vehicle_parser import texture_vpath

log = logging.getLogger("textures")

DXGI_BC7 = 98


class TextureError(Exception):
    pass


def _dds_wrap(width: int, height: int, payload: bytes, dxgi: int) -> bytes:
    """РћР±РѕСЂР°С‡РёРІР°РµС‚ СЃС‹СЂС‹Рµ Р±Р»РѕРєРё РІ DDS СЃ Р·Р°РіРѕР»РѕРІРєРѕРј DX10, С‡С‚РѕР±С‹ Pillow РґРµРєРѕРґРёСЂРѕРІР°Р» BCn."""
    flags = 0x1 | 0x2 | 0x4 | 0x1000 | 0x80000
    hdr = struct.pack("<4sIIIIIII", b"DDS ", 124, flags, height, width, len(payload), 0, 1)
    hdr += b"\0" * 44
    hdr += struct.pack("<II4sIIIII", 32, 4, b"DX10", 0, 0, 0, 0, 0)
    hdr += struct.pack("<IIIII", 0x1000, 0, 0, 0, 0)
    hdr += struct.pack("<IIIII", dxgi, 3, 0, 1, 0)
    return hdr + payload


def bc7_chain_size(width: int, height: int, mips: int) -> int:
    """Р Р°Р·РјРµСЂ С†РµРїРѕС‡РєРё mip-СѓСЂРѕРІРЅРµР№ BC7 (16 Р±Р°Р№С‚ РЅР° Р±Р»РѕРє 4x4)."""
    total = 0
    for _ in range(max(mips, 1)):
        total += max(1, (width + 3) // 4) * max(1, (height + 3) // 4) * 16
        width, height = max(1, width // 2), max(1, height // 2)
    return total


def decode_pct(data: bytes, header_len: int) -> Image.Image:
    """Р”РµРєРѕРґРёСЂСѓРµС‚ СЃР°РјС‹Р№ Р±РѕР»СЊС€РѕР№ mip-СѓСЂРѕРІРµРЅСЊ .pct (РёР»Рё .pct_base) РІ RGBA."""
    if data[6:10] != b"TCIP":
        raise TextureError("РЅРµС‚ СЃРёРіРЅР°С‚СѓСЂС‹ TCIP: РЅРµРёР·РІРµСЃС‚РЅС‹Р№ РєРѕРЅС‚РµР№РЅРµСЂ")
    width, height = struct.unpack_from("<II", data, 0x10)
    if width == 0 or height == 0 or width % 4 or height % 4:
        raise TextureError(f"РЅРµРїРѕРґРґРµСЂР¶РёРІР°РµРјС‹Р№ СЂР°Р·РјРµСЂ {width}x{height}")
    need = width * height
    avail = len(data) - header_len
    if avail < need:
        raise TextureError(f"РґР°РЅРЅС‹С… {avail} Р±Р°Р№С‚, РѕР¶РёРґР°Р»РѕСЃСЊ РЅРµ РјРµРЅСЊС€Рµ {need}")
    mips = struct.unpack_from("<I", data, 0x30)[0]
    chain = bc7_chain_size(width, height, mips)
    # С„Р°Р№Р» = Р·Р°РіРѕР»РѕРІРѕРє + С†РµРїРѕС‡РєР° mip + 6 СЃР»СѓР¶РµР±РЅС‹С… Р±Р°Р№С‚; РёРЅРѕР№ СЂР°Р·РјРµСЂ - С„РѕСЂРјР°С‚ РЅР°Рј РЅРµРёР·РІРµСЃС‚РµРЅ
    if avail not in (chain, chain + 6):
        raise TextureError(f"РЅРµРёР·РІРµСЃС‚РЅС‹Р№ С„РѕСЂРјР°С‚ РїРёРєСЃРµР»РµР№ (РґР°РЅРЅС‹С… {avail} Р±Р°Р№С‚ РїСЂРё {width}x{height}, mip {mips})")
    payload = data[header_len:header_len + need]
    try:
        img = Image.open(io.BytesIO(_dds_wrap(width, height, payload, DXGI_BC7)))
        img.load()
    except Exception as exc:  # noqa: BLE001 - Pillow Р±СЂРѕСЃР°РµС‚ СЂР°Р·РЅС‹Рµ С‚РёРїС‹
        raise TextureError(f"BC7 РЅРµ РґРµРєРѕРґРёСЂСѓРµС‚СЃСЏ: {exc}") from exc
    return img.convert("RGBA")


def load_game_texture(index: PakIndex, tga_path: str) -> Image.Image | None:
    """Р—Р°РіСЂСѓР¶Р°РµС‚ С‚РµРєСЃС‚СѓСЂСѓ РїРѕ РїСѓС‚Рё РёР· РјР°С‚РµСЂРёР°Р»Р° ('trucks/foo__d.tga').
    РџРѕСЂСЏРґРѕРє РїРѕРёСЃРєР°: .pct РёРіСЂС‹, .pct_base, С„Р°Р№Р» РјРѕРґР° (.tga/.dds/.png). None, РµСЃР»Рё РЅРµ РЅР°Р№РґРµРЅР°."""
    vpath = texture_vpath(tga_path)
    base = vpath[:-4]
    try:
        data = index.try_read(vpath)
        if data is not None:
            hdr = index.try_read(base + ".pct_header")
            if hdr is None:
                raise TextureError("РЅРµС‚ .pct_header")
            return decode_pct(data, len(hdr))
        data = index.try_read(base + ".pct_base")
        if data is not None:
            log.warning("РўРµРєСЃС‚СѓСЂР° %s: РµСЃС‚СЊ С‚РѕР»СЊРєРѕ РЅРёР·РєРѕРµ СЂР°Р·СЂРµС€РµРЅРёРµ (pct_base)", tga_path)
            # Р·Р°РіРѕР»РѕРІРѕРє base - РґРѕ РїРµСЂРІРѕРіРѕ Р±Р»РѕРєР° РґР°РЅРЅС‹С…; РґР»РёРЅСѓ Р±РµСЂС‘Рј РёР· СЂР°Р·РјРµСЂР° С„Р°Р№Р»Р°
            w, h = struct.unpack_from("<II", data, 0x10)
            mips = struct.unpack_from("<I", data, 0x30)[0]
            hdr_len = len(data) - bc7_chain_size(w, h, mips) - 6
            if hdr_len < 32 or hdr_len > 512:
                raise TextureError("РЅРµ СѓРґР°Р»РѕСЃСЊ РѕРїСЂРµРґРµР»РёС‚СЊ РґР»РёРЅСѓ Р·Р°РіРѕР»РѕРІРєР° pct_base")
            return decode_pct(data, hdr_len)
    except TextureError as exc:
        log.warning("РўРµРєСЃС‚СѓСЂР° %s РЅРµ РїСЂРµРѕР±СЂР°Р·РѕРІР°РЅР°: %s", tga_path, exc)
        return None
    # РјРѕРґС‹ С…СЂР°РЅСЏС‚ РёСЃС…РѕРґРЅРёРєРё
    for ext in ("", ".tga", ".dds", ".png"):
        stem = tga_path if not ext else tga_path.rsplit(".", 1)[0] + ext
        for prefix in ("textures/", ""):
            raw = index.try_read(prefix + stem)
            if raw is not None:
                try:
                    im = Image.open(io.BytesIO(raw))
                    im.load()
                    return im.convert("RGBA")
                except Exception as exc:  # noqa: BLE001
                    log.warning("РўРµРєСЃС‚СѓСЂР° РјРѕРґР° %s РЅРµ РѕС‚РєСЂС‹Р»Р°СЃСЊ: %s", stem, exc)
                    return None
    log.warning("РўРµРєСЃС‚СѓСЂР° %s РЅРµ РЅР°Р№РґРµРЅР° РІ Р°СЂС…РёРІР°С…", tga_path)
    return None


# ------------------------------------------------------------------ РѕР±СЂР°Р±РѕС‚РєР° РєР°РЅР°Р»РѕРІ

def prepare_albedo(img: Image.Image, with_alpha: bool) -> Image.Image:
    if with_alpha:
        return img.convert("RGBA")
    return img.convert("RGB")


def prepare_normal(img: Image.Image, flip_green: bool = True) -> Image.Image:
    """РљР°СЂС‚Р° РЅРѕСЂРјР°Р»РµР№ РёРіСЂС‹ С…СЂР°РЅРёС‚ Р·РµР»С‘РЅС‹Р№ РєР°РЅР°Р» РёРЅРІРµСЂС‚РёСЂРѕРІР°РЅРЅРѕ (РїСЂРѕРІРµСЂРєР° РїРѕ РёРЅС‚РµРіСЂРёСЂСѓРµРјРѕСЃС‚Рё
    РіСЂР°РґРёРµРЅС‚РѕРІ: corr(dNx/drow, dNy/dcol) > 0 Сѓ РІСЃРµС… РїСЂРѕРІРµСЂРµРЅРЅС‹С… С‚РµРєСЃС‚СѓСЂ). Р”Р»СЏ glTF (OpenGL) РёРЅРІРµСЂС‚РёСЂСѓРµРј."""
    a = np.asarray(img.convert("RGB")).copy()
    if flip_green:
        a[..., 1] = 255 - a[..., 1]
    return Image.fromarray(a, "RGB")


def prepare_orm(sh: Image.Image) -> Image.Image:
    """РРіСЂРѕРІР°СЏ РєР°СЂС‚Р° shading (R - РјРµС‚Р°Р»Р», G - С€РµСЂРѕС…РѕРІР°С‚РѕСЃС‚СЊ, B - Р·Р°С‚РµРЅРµРЅРёРµ) -> glTF ORM
    (R - Р·Р°С‚РµРЅРµРЅРёРµ, G - С€РµСЂРѕС…РѕРІР°С‚РѕСЃС‚СЊ, B - РјРµС‚Р°Р»Р»)."""
    a = np.asarray(sh.convert("RGB"))
    out = np.empty_like(a)
    out[..., 0] = a[..., 2]
    out[..., 1] = a[..., 1]
    out[..., 2] = a[..., 0]
    return Image.fromarray(out, "RGB")


def save_png(img: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="PNG", optimize=False)


def png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

