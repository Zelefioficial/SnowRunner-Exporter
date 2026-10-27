# SnowRunner Exporter

[Русская версия](README.ru.md)

A personal Windows tool that finds your installed SnowRunner, shows the vehicle list (base game, DLC, mods) and exports the selected vehicle to **GLB** (main format) or **OBJ + MTL** with PNG textures. The result opens in Blender (File > Import > glTF 2.0). Game files are only read; nothing is unpacked to disk as a whole.

## Requirements

* Windows 10 or 11.
* Python 3.14 (tested with it). Packages: numpy and Pillow from `requirements.txt`. tkinter is included in the standard Python installer from python.org.
* SnowRunner installed (Steam or Epic Games) with its game data. The game is required for export: the program reads its archives and does not change them.

## Running

```powershell
cd "path\to\SnowRunner Exporter"
pip install -r requirements.txt        # numpy, Pillow (tkinter is included in Python)
python main.py
```

1. The game is found automatically (Steam registry, `libraryfolders.vdf`, Epic manifests and typical Epic paths). If it is not found, click "Game folder..." and select the SnowRunner root folder (the one containing `preload\paks\client\initial.pak`). The path is saved to `config.json`.
2. Vehicles are grouped by type, as in the game: Light (Scout), Highway, Off-road, Heavy, Heavy duty, Trailers. Click a group header to collapse it. Filters: search (Ctrl+F), type, source (Base / DLC / Mods), vehicle name language RU/EN. Select a vehicle (Ctrl+click for several), choose the format and output folder, then click "Export". Progress is shown as a percentage: the bar fills with snow.
3. Output: `<output folder>\<vehicle id>\<id>.glb` (or `.obj` + `.mtl`) and `textures\*.png`. Double-clicking a vehicle also starts the export.

**Icon and taskbar.** The app has its own icon (a snowflake on a graphite tile) in the window title bar and on the taskbar, so the window is not grouped under Python. You can pin it in two ways: right-click the running app's taskbar button and choose "Pin to taskbar" (the pinned icon stays a snowflake and launches `main.py` without a console), or click "Shortcut" in the header: it creates a desktop shortcut with the same icon and app identifier, which you can also pin. Icon files are in `assets\` and are recreated automatically if deleted.

An error in one vehicle is written to the log and does not stop the others. The technical log is also written to `exporter.log`.
The vehicle list is cached in `cache.json` (updated when the archives change). Example of checking the result in Blender without the interface:

```powershell
blender --background --python tools\blender_check.py -- output\international_scout_800\international_scout_800.glb preview.png
```

## Modules

| file | purpose |
|---|---|
| `game_locator.py` | game search, mods folder, `config.json` |
| `pak_reader.py` | single index "virtual path -> (archive, entry)", reading into memory |
| `vehicle_parser.py` | vehicle XML, localization, wheels, `cache.json` |
| `stm_converter.py` | STM format parsing, axes and scale for glTF |
| `texture_converter.py` | `.pct` (BC7) and mod TGA/DDS -> PNG |
| `exporter.py` | scene, own GLB writer, OBJ+MTL |
| `gui.py`, `ui_kit.py`, `main.py` | interface (dark rounded theme, snow progress), widgets, startup |
| `app_identity.py` | snowflake icon (`assets/app.ico`, drawn with Pillow), Windows taskbar icon, pinning, shortcut |
| `tools/blender_check.py` | import check in Blender in background mode |
| `build/pyinstaller/SnowRunner_Exporter.spec` | exe build recipe (PyInstaller) |
| `assets/` | app icon (`app.ico`, `app.png`) and icon version |

## Findings from a real installation

* Archives: `preload\paks\client\*.pak` are regular ZIP files. Needed: `initial.pak` (XML, strings), `shared.pak` (models), `shared_textures.pak`, `shared_textures_base.pak`, `main_menu_textures.pak` (part of the wheel textures), `mod.pak` (mod template from the editor kit). This installation has no separate `dlc_*.pak` files.
* **DLC is inside `initial.pak`** in `[media]/_dlc/<name>/classes/trucks/`, while their models and textures are in the shared `shared*.pak` files. That is why the "DLC source" is determined from the XML path. The app cannot tell whether a DLC is owned: the files are present for everyone.
* Descriptions: `[media]/classes/trucks/<id>.xml` (base), `.../trailers/<id>.xml` (trailers). A file contains two root elements (`<_templates>` and `<Truck>`), so the parser wraps the text in `<root>`.
* Links: `PhysicsModel/@Mesh="trucks/<id>"` -> `[meshes]/trucks_<id>` (STM, no extension); `GameData/UiDesc/@UiName` -> a string in `[strings]/strings_<language>.str` (UTF-16LE, `KEY<TAB>"text"`); wheels: `TruckData/Wheels/@DefaultWheelType/DefaultTire/DefaultRim` -> `classes/wheels/<type>.xml` -> `[meshes]/wheels_<tire|rim>_...`; wheel positions are `Wheel/@Pos`, scale is `CompatibleWheels/@Scale` for the default type.
* Materials are described in the XML inside the STM itself: `AlbedoMap`, `NormalMap`, `ShadingMap`, `EmissiveMap`, `Blending="alpha"`. The path `trucks/x__d.tga` corresponds to `[textures]/pct/trucks_x__d.pct`.
* 190 vehicles found (121 trucks, 69 trailers): 62 base, 127 DLC, 1 from `mod.pak`. On this PC the mods folder `Documents\My Games\SnowRunner\base\Mods` is missing or empty, but support is there (`.pak`/`.zip`, paths like `classes/trucks/...`, `meshes/...`).

## STM format (reconstructed from data, little-endian)

```
u32  xml_len                                    XML length
     xml                                        <CombineXMesh>: <Material .../>, <MaterialOverride .../>, <SocketPoint .../>
--- binary part ---
u32  0x0133EF63, u32 44                         signature/version (meaning not determined)
f32  bbox[6]                                    min xyz, max xyz of the whole model
u32  root count (13 for Scout; not needed for reading)
node * N:
  i16 parent (-2 for root), u16 index (0,1,2...), u32 kind (not used in parsing)
  u32 name_len, name (null-terminated; some non-ASCII characters occur: the game has a Cyrillic «С» in BoneСabinTwist_cdt)
  f32 matrix[16]                                4x4 row-wise, translation in the last row, local to parent
  if the next u32 == 0:  bone/dummy; followed by another u32 0 (4 bytes total), no geometry
  otherwise - a mesh block:
    u32 vertex_count, u32 triangle_count
    u32 len + mesh_name
    u32 a, u32 n_materials, u32 0
    n_materials * (u32 len + material name)
    u32 K                                       number of bones (0 = rigid mesh)
    K * f32[16]                                 inverse bind matrices; K[j] == inverse(world matrix of bone joints[j]) (verified, difference 0.0)
    if K > 0:  u32 A (1 - all rigid, 2 - skinning present), u32 nSub, u32 nb[nSub]
               for each submesh: u32 mat, first_tri, tri_count, first_vtx, vtx_count; then nb[i] palette indices
               u16 joints[K]                    indices of bone nodes
               f32 bbox[6]
               u32 1,0,0,tri_count,0,vertex_count   (repeated counts)
    if K == 0: u16 joint, f32 bbox[6], u32 n; n * (5 u32 as above) - submesh table (n == 0 for cdt_* collisions)
    u32 n_decl; n_decl * {u16 stream, u16 offset, u16 type, u8 flag, u8 usage}
    u32 0xFF, u32 0x11                          (meaning not determined)
    vertex_count * stride bytes                 stride = offset of the last element + its size
    triangle_count * 3 * u16 indices            (u32 if vertices > 65536; never seen in the data)
    block of unknown length (collision physics, in cdt_* nodes) - skipped by searching for the next node header
```

Vertex element types: `2` = float3 (usage 0: position), `1` = float2 (usage 0: UV0; usage 6: second UVs, lightmap, not used), `8` = 4 bytes (usage 1: normal, usage 2: tangent, usage 4: bone weights, unorm8), `5` = 4 bytes (usage 5: bone indices, u8). Typical stride is 44. Normal: `n = byte/255*2 - 1`.

Verified on real data, not assumed:

* positions are already in model space (bind pose), with no bone transforms; each mesh bbox lies inside the file bbox;
* 14,252 of 14,280 STM files from `shared.pak` were parsed (all vehicle, trailer, addon and wheel models); 28 were not: they are landmark buildings (`landmarks_*_hut_*`) and `animesh_*`, which are not vehicles; there is no NaN in the positions;
* all 189 vehicles with an STM are assembled into a scene without errors;
* triangle winding matches the normals in the file for 100 % of faces after the axis conversion (checked in Blender).

**Axes.** In the game X is forward, Y is up, Z is left (a left-handed system: `mirror_left` and the steering wheel of US vehicles lie in +Z). For glTF: `(x,y,z) -> (z,y,x)`, and the vertex order in each triangle is reversed. Units are meters. Dimensions of the exported Scout 800: 1.83 x 3.95 x 1.84 m (W x L x H).

## Textures (`.pct`)

Header `... 'TCIP' ...`, width/height at offsets `0x10`/`0x14`, mip count at `0x30`. Data: **BC7** (DXGI 98). Level 0 is the largest and comes right after the header (its length equals the `.pct_header` size), followed by the full mip chain and 6 trailing bytes. Decoding was verified by comparing with the original TGA files from `mod.pak` (11 textures, PSNR 46-53 dB, rows not flipped). Decoder: Pillow (BC7 via a DX10 DDS wrapper); there is no custom decoder.

* `__d`, `__d_a` - albedo (alpha is kept only for `Blending="alpha"` materials; otherwise the channel is dropped);
* `__n_d` - normal map, RGB. The green channel is **inverted**: by gradient integrability (`corr(dNx/drow, dNy/dcol) > 0` for all 7 checked maps) the game stores normals in the DirectX convention. Disable it with the "Invert green normal channel" checkbox;
* `__sh_d` - packed into a glTF ORM: R = occlusion (game B), G = roughness (game G), B = metallic (game R). **This is an assumption** based on statistics (glass: R=0, G~55, B=255; bumpers: high B); there is no format documentation;
* `__em_d` - emission.

If a full `.pct` is missing, `.pct_base` (128 px) is used and noted in the log. Unsupported formats (for example 4 textures whose size is not a multiple of 4, or 8-bit `__sh_s`) are written to the log, and the export continues.

## Export contents

`Parts` (parts: cab, body, glass, mirrors, roof...), `Wheels` (`wheel_left_N`/`wheel_right_N` wheels with the default tire and rim, positions from the XML), `Skeleton` (bones as empty objects with local matrices). Not exported: `lp_*` (simplified LOD when `hp_*` exists), service volumes with the `lambert1` material (`_cockpit`), collisions `cdt_*`. All of these can be turned on and off with checkboxes.

## Customization

The "Customization" checkbox exports parts to a **separate file** `<id>_customization.glb` (or `.obj`) next to `<id>.glb`; the vehicle file stays clean. In the customization file there is a `Customization` node: a group per mount type (`Kolob74760Bumper`, `Kolob74760Exhaust`, `...Snorkel`, cranes, frames, roof racks), and in it a node for each part. "Stickers and small cabin items" puts stickers, toys and air fresheners into a `Cosmetics` node in the same file. Both files share the same origin: import them into one Blender scene and the parts line up. The textures of both files are in the shared `textures` folder.

* A part fits a vehicle if the addon's `<InstallSocket Type>` matches `<Socket Names>` in the vehicle's `<AddonSockets>`. Variants such as `front_bumper_1` take the mount and model from `<_parent File>`.
* Addon models are in the vehicle's axes, so they are placed without an offset. All variants of the same mount overlap: hide the extra ones in Blender.
* Parts export their base textures (controlled by the general "Textures (PNG)" checkbox). Paint jobs and camouflage are not exported. The files are heavy: Kenworth 963 with full customization is about 500 MB and takes about 2 minutes to export.
* Dimensions in the log are computed from the vehicle itself, without customization parts.
* The "Select..." button opens the parts list of the selected vehicle grouped by category (bumper, exhaust, snorkel, etc.). Checked parts are exported regardless of the checkboxes; the selection is remembered for each vehicle (`addon_choice` in `config.json`), and "Reset selection" hands control back to the checkboxes. Stickers and small items are collapsed in the list.

## About (window in the app)

The "About" button in the header opens a help window: what the app does, the workflow, which files are produced, what each checkbox means, and the limitations. The text is in `about.py` (`SECTIONS`).

## Hover preview

Hovering over a vehicle in the list or a part in the selection window shows a picture after 0.4 s. The archives do not contain ready-made icons, so `preview.py` builds the picture: software drawing of triangles (front-left-top view) with colors taken from a downscaled base texture; glass is skipped. It is an approximate view, not a render from the game. Results are stored on disk in `previews\` next to `config.json` (in the exe: `%LOCALAPPDATA%\SnowRunnerExporter\previews`), so they open instantly next time; the folder can be deleted.

## DLC number search

The "DLC" filter shows a row of numbers: 1, 2, ... 19 and "Other" (trial, ru_08). Each number groups all its sub-releases (14 includes dlc_14, dlc_14_1, dlc_14_2). Search queries `dlc 14`, `dlc14` and `dlc_14_1` work.

## Verified vehicles (Blender 5.1.2, `--background`, import without errors, all textures loaded, dimensions correct)

| vehicle | source | dimensions W x L x H, m | parts / textures |
|---|---|---|---|
| International Scout 800 (light) | base | 1.83 x 3.95 x 1.84 | 19 / 24 |
| Kolob 74760 (heavy) | base | 3.41 x 9.74 x 3.89 | 27 / 28 |
| Kenworth 963 | DLC dlc_10 | 4.25 x 13.19 x 3.95 | 25 / 32 |
| TUZ 16 Actaeon | DLC dlc_1_1 | 2.55 x 5.53 x 2.72 | 16 / 22 |
| Scout flatbed trailer 1 (trailer) | base | 2.69 x 5.81 x 1.66 | 1 / 7 |

OBJ+MTL was verified on Scout 800 (same dimensions, 100 % normal consistency). The second argument of `tools\blender_check.py` sets the PNG preview rendered with Blender Workbench.

## Supported

* automatic game search, manual selection, `config.json`; archives are read without unpacking; priority base < DLC archives < mods;
* list of 190 vehicles with names in Russian/English (switchable), search by name and ID, source filter, cache;
* export of geometry, normals, UVs, materials and part hierarchy; GLB with textures embedded and PNG files alongside, OBJ+MTL;
* batch export of several vehicles in a background thread; an error in one vehicle does not stop the app.

## Not supported / not decoded

* **Animations**: none found in STM. **Skinning weights** are read (usage 4/5) but not exported: parts are exported in bind pose without bone binding, and bones are exported as separate empty objects.
* **Paint jobs (skins)**: `MaterialOverride` with `TintMap` (`__cc__d`) and `wt` variants are not applied; the base albedo is exported. That is why many vehicles look dark or gray. This is the content of the textures, not a decoding error.
* **Customization** is exported via checkboxes (see "Customization" above); paint schemes are not supported; wheels are only the default configuration. Some trailers have no default wheels defined in the XML (a warning is written to the log).
* **Mods with FBX** (the `mod_scout` template from `mod.pak`): the FBX is copied as is, textures are converted to PNG, and materials must be assigned manually.
* Meaning of some fields: node `kind`, signature `0x0133EF63`, the `0xFF/0x11` pair before the vertices, the physics block structure in `cdt_*`, tangents (usage 2) are not used.
* The wheel scale (`CompatibleWheels/@Scale` of the first matching type) and the rotation of left wheels (the visible side of the rim faces -Z) were derived from data (tire radius in the mesh = 1, width matches the real one) but were not checked against the game.

## Known issues

* The first export of a heavy vehicle takes 15-25 s (BC7 decoding in Pillow); the GLB is 50-120 MB because of the PNGs inside.
* The assumptions about ORM and green-channel inversion were verified only indirectly (by statistics); if the relief looks inverted, untick the inversion checkbox.
* Console encoding: the log in the window and `exporter.log` use UTF-8. When started from a console, Russian messages may show up as garbled characters on Windows (the files are not affected).

## Files the app creates

These are not part of the repository (see `.gitignore`) and are created during use:

* `config.json` - game path, language, selected options, part selection per vehicle;
* `cache.json` - vehicle list; `addons.json` - list of customization parts;
* `exporter.log` - work log;
* `previews\` - hover preview pictures.

When run from source they are placed next to the code; in the built exe they go to `%LOCALAPPDATA%\SnowRunnerExporter`. Deleting these files is safe: the app recreates them.

## Building the exe

```powershell
python -m pip install pyinstaller
python -m PyInstaller --noconfirm build\pyinstaller\SnowRunner_Exporter.spec
```

Result: `dist\SnowRunner_Exporter.exe` (about 33 MB). Run the command from the project folder: the paths in the `.spec` file are relative. The build was verified with PyInstaller 6.22.3. The exe is not digitally signed, so Windows SmartScreen may show a warning on first launch.

## License

The project is distributed under the MIT License, see the `LICENSE` file. Author: Zelefi.

## Disclaimer

This project is not affiliated with Saber Interactive or Focus Home Interactive. SnowRunner and related names belong to their owners. The repository contains no game files: export requires your own installed copy of SnowRunner. The program is intended for personal use with a legally purchased game.
