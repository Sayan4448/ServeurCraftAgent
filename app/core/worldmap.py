"""Mini-carte top-down du monde (sans plugin) : rendu des régions .mca
autour d'une position, avec marqueur du joueur (croix + direction du regard).

Lit les chunks directement dans les fichiers région (format Anvil :
en-tête de localisation + données zlib), puis prend le premier bloc non-air
de chaque colonne en partant du haut (heightmap WORLD_SURFACE si dispo).
"""
import io
import math
import zlib
from pathlib import Path

import nbtlib
from PIL import Image, ImageDraw

# ---------------------------------------------------------------- couleurs

# nom de bloc -> (r,g,b). Heuristiques en dessous pour le reste.
COLORS = {
    "grass_block": (94, 157, 62), "short_grass": (94, 157, 62),
    "grass": (94, 157, 62), "tall_grass": (94, 157, 62), "fern": (80, 140, 60),
    "dirt": (134, 96, 67), "coarse_dirt": (119, 85, 60), "mud": (87, 64, 56),
    "podzol": (129, 89, 57), "mycelium": (111, 99, 105),
    "farmland": (95, 67, 45), "dirt_path": (148, 117, 82),
    "sand": (219, 207, 163), "red_sand": (186, 99, 44), "gravel": (136, 126, 126),
    "sandstone": (216, 202, 155), "red_sandstone": (178, 89, 32),
    "stone": (125, 125, 125), "cobblestone": (110, 110, 110),
    "mossy_cobblestone": (96, 110, 90), "andesite": (136, 136, 136),
    "diorite": (188, 188, 188), "granite": (150, 109, 88),
    "deepslate": (80, 80, 85), "cobbled_deepslate": (77, 77, 80),
    "bedrock": (55, 55, 55), "obsidian": (21, 15, 35),
    "netherrack": (111, 54, 52), "soul_sand": (92, 64, 51),
    "basalt": (73, 72, 78), "blackstone": (42, 35, 40),
    "end_stone": (219, 222, 158), "end_stone_bricks": (219, 222, 158),
    "snow": (240, 251, 251), "snow_block": (240, 251, 251), "ice": (145, 183, 253),
    "packed_ice": (141, 180, 250), "blue_ice": (116, 167, 253),
    "clay": (159, 164, 177), "terracotta": (152, 94, 70),
    "water": (63, 118, 228), "lava": (216, 89, 21),
    "oak_log": (107, 85, 50), "spruce_log": (58, 37, 16),
    "birch_log": (216, 215, 210), "jungle_log": (89, 70, 27),
    "acacia_log": (103, 96, 86), "dark_oak_log": (60, 41, 18),
    "cherry_log": (54, 33, 44), "mangrove_log": (84, 67, 41),
    "oak_leaves": (55, 120, 35), "spruce_leaves": (45, 84, 45),
    "birch_leaves": (68, 124, 50), "jungle_leaves": (48, 132, 40),
    "acacia_leaves": (60, 130, 40), "dark_oak_leaves": (40, 100, 30),
    "cherry_leaves": (228, 165, 190), "mangrove_leaves": (55, 115, 40),
    "oak_planks": (162, 130, 78), "spruce_planks": (114, 84, 48),
    "birch_planks": (192, 175, 121), "jungle_planks": (160, 115, 80),
    "acacia_planks": (168, 90, 50), "dark_oak_planks": (66, 43, 20),
    "cherry_planks": (227, 179, 148), "mangrove_planks": (120, 54, 48),
    "bricks": (150, 97, 83), "stone_bricks": (122, 122, 122),
    "glass": (200, 230, 240), "white_wool": (233, 236, 236),
    "black_wool": (25, 25, 25), "gray_wool": (70, 75, 80),
    "red_wool": (160, 40, 35), "blue_wool": (55, 60, 155),
    "green_wool": (85, 110, 30), "yellow_wool": (200, 160, 30),
    "orange_wool": (215, 120, 25), "purple_wool": (120, 60, 170),
    "iron_block": (220, 220, 220), "gold_block": (245, 205, 60),
    "diamond_block": (95, 225, 215), "emerald_block": (60, 190, 100),
    "coal_ore": (110, 110, 110), "iron_ore": (150, 130, 115),
    "gold_ore": (150, 140, 90), "diamond_ore": (125, 155, 150),
    "lapis_ore": (105, 115, 160), "redstone_ore": (140, 90, 90),
    "emerald_ore": (100, 140, 100), "copper_ore": (135, 110, 90),
    "tnt": (170, 60, 30), "bookshelf": (140, 110, 65),
    "torch": (255, 220, 90), "lantern": (255, 200, 80),
    "glowstone": (240, 190, 100), "sea_lantern": (170, 200, 190),
    "pumpkin": (200, 120, 20), "melon": (150, 170, 40),
    "hay_block": (165, 140, 25), "cactus": (90, 140, 55),
    "sugar_cane": (140, 180, 100), "bamboo": (100, 145, 45),
    "vine": (60, 120, 45), "lily_pad": (50, 110, 45),
    "moss_block": (90, 110, 45), "moss_carpet": (90, 110, 45),
    "amethyst_block": (140, 95, 200), "calcite": (215, 215, 210),
    "tuff": (108, 109, 102), "dripstone_block": (134, 108, 92),
    "prismarine": (100, 150, 140), "dark_prismarine": (60, 90, 80),
    "sea_lantern2": (170, 200, 190), "magma_block": (140, 65, 30),
    "nether_wart_block": (115, 20, 20), "warped_nylium": (45, 120, 110),
    "crimson_nylium": (130, 40, 50), "chorus_plant": (95, 60, 95),
}

# heuristiques par mot-clé quand le bloc n'est pas dans la table
_HINTS = [
    ("water", (63, 118, 228)), ("lava", (216, 89, 21)),
    ("leaves", (60, 120, 40)), ("leaf", (60, 120, 40)),
    ("log", (105, 85, 50)), ("wood", (110, 85, 55)), ("stem", (90, 70, 55)),
    ("planks", (160, 130, 80)), ("plank", (160, 130, 80)),
    ("sand", (219, 207, 163)), ("gravel", (136, 126, 126)),
    ("snow", (240, 251, 251)), ("ice", (145, 183, 253)),
    ("stone", (120, 120, 120)), ("cobble", (110, 110, 110)),
    ("deepslate", (80, 80, 85)), ("bedrock", (55, 55, 55)),
    ("obsidian", (21, 15, 35)), ("netherrack", (111, 54, 52)),
    ("grass", (94, 157, 62)), ("dirt", (134, 96, 67)),
    ("wool", (180, 180, 180)), ("concrete", (150, 150, 150)),
    ("terracotta", (140, 95, 70)), ("glass", (200, 230, 240)),
    ("ore", (140, 130, 120)), ("brick", (140, 100, 85)),
    ("glow", (240, 200, 90)), ("lamp", (240, 200, 90)),
    ("shroomlight", (240, 150, 90)), ("kelp", (60, 120, 60)),
    ("seagrass", (60, 130, 70)), ("coral", (200, 110, 100)),
    ("flower", (200, 90, 140)), ("rose", (200, 60, 60)),
    ("mushroom", (170, 120, 110)), ("fungus", (150, 100, 110)),
    ("copper", (170, 110, 80)), ("iron", (200, 200, 200)),
    ("gold", (230, 200, 70)), ("basalt", (73, 72, 78)),
    ("blackstone", (42, 35, 40)), ("nylium", (100, 80, 80)),
    ("end_stone", (219, 222, 158)), ("purpur", (170, 125, 170)),
    ("clay", (159, 164, 177)), ("mud", (87, 64, 56)),
    ("calcite", (215, 215, 210)), ("tuff", (108, 109, 102)),
    ("dripstone", (134, 108, 92)), ("prismarine", (100, 150, 140)),
    ("magma", (140, 65, 30)), ("ladder", (140, 110, 60)),
]
AIR = {"minecraft:air", "minecraft:cave_air", "minecraft:void_air"}
SEA_LEVEL = 62


def block_color(name: str) -> tuple:
    short = name.split(":", 1)[-1]
    c = COLORS.get(short)
    if c:
        return c
    for key, col in _HINTS:
        if key in short:
            return col
    return (90, 100, 90)  # inconnu : gris-vert discret


# --------------------------------------------------------------- régions

def region_dir(server_dir: Path, dimension: str) -> Path | None:
    """Dossier region/ de la dimension (ancien et nouveau layout)."""
    world = Path(server_dir) / "world"
    short = dimension.split(":")[-1] if ":" in dimension else dimension
    cands = {
        "overworld": ["region", "dimensions/minecraft/overworld/region"],
        "the_nether": ["DIM-1/region",
                       "dimensions/minecraft/the_nether/region"],
        "the_end": ["DIM1/region", "dimensions/minecraft/the_end/region"],
    }.get(short, [f"dimensions/minecraft/{short}/region", "region"])
    for rel in cands:
        d = world / rel
        if d.exists() and any(d.glob("*.mca")):
            return d
    for rel in cands:
        d = world / rel
        if d.exists():
            return d
    return None


def _read_chunk(rfile: Path, cx: int, cz: int):
    """Compound NBT du chunk (cx,cz) dans un fichier région, ou None."""
    try:
        with open(rfile, "rb") as f:
            off = ((cx & 31) + (cz & 31) * 32) * 4
            f.seek(off)
            loc = f.read(4)
            if len(loc) < 4:
                return None
            sector = (loc[0] << 16) | (loc[1] << 8) | loc[2]
            if sector == 0:
                return None
            f.seek(sector * 4096)
            head = f.read(5)
            if len(head) < 5:
                return None
            length = int.from_bytes(head[:4], "big")
            comp = head[4]
            payload = f.read(length - 1)
    except OSError:
        return None
    try:
        if comp == 2:
            payload = zlib.decompress(payload)
        elif comp == 1:
            import gzip as _gz
            payload = _gz.decompress(payload)
        else:
            return None  # lz4/zstd : non géré
        return nbtlib.File.parse(io.BytesIO(payload))
    except Exception:
        return None


def _palette_index(section, x: int, y: int, z: int):
    """Index palette du bloc (x,y,z locaux) dans une section, ou None."""
    bs = section.get("block_states")
    if not bs:
        return None
    palette = bs.get("palette", [])
    if not palette:
        return None
    data = bs.get("data")
    if data is None:                      # palette à 1 seul bloc
        return 0
    bits = max(4, math.ceil(math.log2(len(palette))))
    per = 64 // bits
    idx = (y * 16 + z) * 16 + x
    li, off = idx // per, (idx % per) * bits
    if li >= len(data):
        return None
    return (int(data[li]) >> off) & ((1 << bits) - 1)


def _surface_y(chunk, lx: int, lz: int, min_y: int):
    """Y de la surface pour une colonne via Heightmaps, sinon None."""
    hm = chunk.get("Heightmaps")
    if not hm or "WORLD_SURFACE" not in hm:
        return None
    arr = hm["WORLD_SURFACE"]
    i = lz * 16 + lx
    val = (int(arr[i // 7]) >> ((i % 7) * 9)) & 0x1FF
    return min_y + val - 1


def _top_block(chunk, lx: int, lz: int, sections_desc, min_y: int):
    """(nom, y) du premier bloc non-air de la colonne, en descendant."""
    start = _surface_y(chunk, lx, lz, min_y)
    for sec in sections_desc:
        sy = int(sec.get("Y", 0)) * 16
        palette = sec.get("block_states", {}).get("palette", [])
        if not palette:
            continue
        if start is not None:
            if sy + 15 < start - 96:      # section entière sous la surface
                continue
            y0, y1 = min(15, start - sy), -1
        else:
            y0, y1 = 15, -1
        if y0 < 0:
            continue
        for y in range(y0, y1, -1):
            pi = _palette_index(sec, lx, y, lz)
            if pi is None or pi >= len(palette):
                continue
            entry = palette[pi]
            name = (str(entry) if isinstance(entry, nbtlib.String)
                    else str(entry.get("Name", "minecraft:air")))
            if name not in AIR:
                return name, sy + y
    return None, None


# ------------------------------------------------------------------ rendu

def render(server_dir: Path, dimension: str, x: float, z: float,
           yaw: float = 0.0, radius: int = 2, scale: int = 3) -> tuple:
    """Image PIL des chunks autour de (x,z) + marqueur joueur.

    radius = nombre de chunks de chaque côté (2 → 5×5 chunks = 80×80 blocs).
    Retourne (Image, nb_chunks_trouvés)."""
    rdir = region_dir(server_dir, dimension)
    size = (radius * 2 + 1) * 16
    img = Image.new("RGB", (size, size), (20, 22, 28))
    px = img.load()
    found = 0
    # arrondi vers le bas : int() tronque vers zéro et décalait d'un chunk
    # les positions négatives (x = -0.5 est dans le chunk -1, pas 0)
    ccx, ccz = math.floor(x) >> 4, math.floor(z) >> 4
    if rdir:
        min_y = -64 if "nether" not in dimension else 0
        for dz in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                cx, cz = ccx + dx, ccz + dz
                rf = rdir / f"r.{cx >> 5}.{cz >> 5}.mca"
                if not rf.exists():
                    continue
                chunk = _read_chunk(rf, cx, cz)
                if chunk is None:
                    continue
                found += 1
                sections = sorted(
                    (s for s in chunk.get("sections", [])
                     if "block_states" in s),
                    key=lambda s: int(s.get("Y", 0)), reverse=True)
                smin = (min(int(s.get("Y", 0)) for s in sections) * 16
                        if sections else min_y)
                ox, oz = (dx + radius) * 16, (dz + radius) * 16
                for lz in range(16):
                    for lx in range(16):
                        name, by = _top_block(chunk, lx, lz,
                                              sections, smin)
                        if name is None:
                            continue
                        r, g, b = block_color(name)
                        # léger relief selon la hauteur
                        if by is not None:
                            f = 1.0 + max(-0.25, min(0.25,
                                                   (by - SEA_LEVEL) / 220))
                            r, g, b = (min(255, int(r * f)),
                                       min(255, int(g * f)),
                                       min(255, int(b * f)))
                        px[ox + lx, oz + lz] = (r, g, b)
    img = img.resize((size * scale, size * scale), Image.NEAREST)
    _draw_marker(img, x, z, yaw, ccx - radius, ccz - radius, scale)
    return img, found


def _draw_marker(img: Image.Image, x: float, z: float, yaw: float,
                 chunk_x0: int, chunk_z0: int, scale: int):
    """Croix rouge + flèche de direction à la position du joueur."""
    d = ImageDraw.Draw(img)
    mx = (x - chunk_x0 * 16) * scale
    my = (z - chunk_z0 * 16) * scale
    r = 7
    d.ellipse([mx - r, my - r, mx + r, my + r], outline=(255, 40, 40),
              width=3)
    d.ellipse([mx - 2, my - 2, mx + 2, my + 2], fill=(255, 40, 40))
    # flèche de regard (yaw : 0 = sud +Z, tourne vers l'ouest)
    rad = math.radians(yaw)
    ax = mx - math.sin(rad) * (r + 9)
    ay = my + math.cos(rad) * (r + 9)
    d.line([mx, my, ax, ay], fill=(255, 40, 40), width=3)
