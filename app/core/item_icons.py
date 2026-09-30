"""Icônes d'items façon inventaire du jeu, à partir des textures officielles.

Rien n'est embarqué dans l'app : à la première ouverture d'une fiche joueur,
le client Minecraft de la version du serveur est téléchargé depuis les
serveurs de Mojang (comme le fait un launcher) et seuls les modèles et
textures d'items / blocs sont gardés dans runtimes/textures/<version>/.

Rendu : items « plats » (item/generated, handheld…) = calques superposés ;
blocs = petit cube isométrique (dessus / côté / face) ; sinon repli sur une
pastille avec les initiales (items moddés, coffres, lits…).
"""
import json
import threading
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from ..config import RUNTIMES_DIR
from .downloader import _get_json, download_file

MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
_KEEP = ("assets/minecraft/textures/item/", "assets/minecraft/textures/block/",
         "assets/minecraft/models/item/", "assets/minecraft/models/block/")
_FLAT = ("item/generated", "item/handheld", "builtin/generated")
# textures en niveaux de gris teintées par le biome / la couleur par défaut
_TINTS = {
    "block/grass_block_top": (124, 189, 107), "block/short_grass": (124, 189, 107),
    "block/grass": (124, 189, 107), "block/fern": (124, 189, 107),
    "block/tall_grass_top": (124, 189, 107), "block/tall_grass_bottom": (124, 189, 107),
    "block/large_fern_top": (124, 189, 107), "block/large_fern_bottom": (124, 189, 107),
    "block/vine": (72, 181, 24), "block/lily_pad": (32, 128, 48),
    "block/oak_leaves": (72, 181, 24), "block/jungle_leaves": (72, 181, 24),
    "block/acacia_leaves": (72, 181, 24), "block/dark_oak_leaves": (72, 181, 24),
    "block/mangrove_leaves": (146, 199, 71), "block/birch_leaves": (128, 167, 85),
    "block/spruce_leaves": (97, 153, 97),
    "item/leather_helmet": (160, 101, 64), "item/leather_chestplate": (160, 101, 64),
    "item/leather_leggings": (160, 101, 64), "item/leather_boots": (160, 101, 64),
    "item/leather_horse_armor": (160, 101, 64),
    "item/potion_overlay": (56, 93, 198), "item/tipped_arrow_head": (56, 93, 198),
}
_locks: dict = {}
_locks_guard = threading.Lock()


class TextureError(Exception):
    pass


# ============================================================ téléchargement

def tex_dir(version: str) -> Path:
    return RUNTIMES_DIR / "textures" / version


def available(version: str) -> bool:
    return (tex_dir(version) / ".ok").exists()


def cached_versions() -> list:
    root = RUNTIMES_DIR / "textures"
    if not root.exists():
        return []
    return sorted(p.name for p in root.iterdir() if (p / ".ok").exists())


def best_cached(version: str) -> Path | None:
    """Textures de la version demandée, sinon d'une autre version déjà
    téléchargée (la plupart des items sont identiques)."""
    if available(version):
        return tex_dir(version)
    others = cached_versions()
    return tex_dir(others[-1]) if others else None


def ensure(version: str, progress=None) -> Path:
    """Télécharge et extrait les textures de `version` si besoin (bloquant,
    à appeler depuis un thread). Lève TextureError."""
    d = tex_dir(version)
    if available(version):
        return d
    with _locks_guard:
        lock = _locks.setdefault(version, threading.Lock())
    with lock:
        if available(version):
            return d
        try:
            man = _get_json(MANIFEST)
            entry = next((v for v in man["versions"] if v["id"] == version),
                         None)
            if entry is None:          # version exotique -> dernière release
                latest = man["latest"]["release"]
                entry = next(v for v in man["versions"] if v["id"] == latest)
            url = _get_json(entry["url"])["downloads"]["client"]["url"]
            jar = d.parent / f"{version}-client.jar"
            download_file(url, jar, progress)
            with zipfile.ZipFile(jar) as z:
                for n in z.namelist():
                    if n.startswith(_KEEP) and n.endswith((".png", ".json")):
                        out = d / n[len("assets/minecraft/"):]
                        out.parent.mkdir(parents=True, exist_ok=True)
                        out.write_bytes(z.read(n))
            jar.unlink(missing_ok=True)
            (d / ".ok").write_text(entry["id"], encoding="utf-8")
        except Exception as e:  # noqa: BLE001 — réseau, zip, disque
            raise TextureError(str(e)) from e
    return d


# ============================================================ rendu

def _name(ref: str) -> str:
    """'minecraft:item/x' -> 'item/x'."""
    return ref.split(":", 1)[-1]


class Icons:
    """Cache d'icônes RGBA carrées de `size` px pour un dossier de textures
    (None = pas de textures : pastilles à initiales)."""

    def __init__(self, root: Path | None, size: int = 32):
        self.root = Path(root) if root else None
        self.size = size
        self._cache: dict = {}
        self._models: dict = {}

    def get(self, item_id: str) -> Image.Image:
        key = item_id
        if key not in self._cache:
            img = None
            if self.root and item_id.startswith("minecraft:"):
                try:
                    img = self._render(item_id.split(":", 1)[1])
                except Exception:  # noqa: BLE001 — modèle inattendu
                    img = None
            self._cache[key] = img or _placeholder(item_id, self.size)
        return self._cache[key]

    # ------------------------------------------------------------ modèles
    def _model(self, ref: str):
        ref = _name(ref)
        if ref not in self._models:
            f = self.root / "models" / f"{ref}.json"
            try:
                self._models[ref] = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._models[ref] = None
        return self._models[ref]

    def _resolve(self, ref: str):
        """(chaîne des parents, textures fusionnées) d'un modèle."""
        chain, textures = [], {}
        cur, depth = ref, 0
        while cur and depth < 12:
            chain.append(_name(cur))
            m = self._model(cur)
            if not m:
                break
            for k, v in (m.get("textures") or {}).items():
                textures.setdefault(k, v)
            cur, depth = m.get("parent"), depth + 1
        return chain, textures

    def _tex(self, textures: dict, *keys):
        for key in keys:
            v, n = textures.get(key), 0
            while isinstance(v, str) and v.startswith("#") and n < 6:
                v, n = textures.get(v[1:]), n + 1
            if isinstance(v, str):
                img = self._load(v)
                if img is not None:
                    return img
        return None

    def _load(self, ref: str):
        ref = _name(ref)
        f = self.root / "textures" / f"{ref}.png"
        if not f.exists():
            return None
        img = Image.open(f).convert("RGBA")
        if img.height > img.width:                  # texture animée
            img = img.crop((0, 0, img.width, img.width))
        tint = _TINTS.get(ref)
        if tint:
            img = _tint(img, tint)
        return img

    # ------------------------------------------------------------ dessin
    def _render(self, name: str):
        chain, textures = self._resolve(f"item/{name}")
        if any(c in _FLAT or c.startswith("item/handheld") for c in chain):
            layers = [self._tex(textures, f"layer{i}") for i in range(5)]
            layers = [x for x in layers if x is not None]
            if layers:
                return _flat(layers, self.size)
        if any(c.startswith("block/") for c in chain[1:]):
            top = self._tex(textures, "top", "end", "up", "all", "texture",
                            "particle")
            side = self._tex(textures, "side", "north", "south", "all",
                             "texture", "particle")
            front = self._tex(textures, "front", "east", "side", "all",
                              "texture", "particle")
            if top is not None and side is not None:
                return _cube(top, side, front or side, self.size)
            one = self._tex(textures, "cross", "plant", "particle")
            if one is not None:
                return _flat([one], self.size)
        for ref in (f"item/{name}", f"block/{name}"):
            img = self._load(ref)
            if img is not None:
                if ref.startswith("block/"):
                    return _cube(img, img, img, self.size)
                return _flat([img], self.size)
        one = self._tex(textures, "particle")
        return _flat([one], self.size) if one is not None else None


def _tint(img: Image.Image, rgb) -> Image.Image:
    r, g, b, a = img.split()
    grey = Image.merge("RGB", (r, g, b)).convert("L")
    out = Image.merge("RGB", [grey.point(lambda v, c=c: v * c // 255)
                              for c in rgb])
    out.putalpha(a)
    return out


def _flat(layers, size: int) -> Image.Image:
    base = Image.new("RGBA", layers[0].size, (0, 0, 0, 0))
    for layer in layers:
        if layer.size != base.size:
            layer = layer.resize(base.size, Image.NEAREST)
        base.alpha_composite(layer)
    return base.resize((size, size), Image.NEAREST)


def _face(tex: Image.Image, out_size: int, origin, ux, vy, shade: float):
    """Projette la texture 16×16 sur le parallélogramme origin + u·ux + v·vy
    (transformation affine inverse : sortie -> texture)."""
    w, h = tex.size
    a, c = ux
    b, d = vy
    det = a * d - b * c
    ia, ib, ic, id_ = d / det, -b / det, -c / det, a / det
    ox, oy = origin
    data = (w * ia, w * ib, -w * (ia * ox + ib * oy),
            h * ic, h * id_, -h * (ic * ox + id_ * oy))
    face = tex.transform((out_size, out_size), Image.AFFINE, data,
                         resample=Image.NEAREST, fillcolor=(0, 0, 0, 0))
    if shade < 1.0:
        rgb = ImageEnhance.Brightness(face.convert("RGB")).enhance(shade)
        rgb.putalpha(face.getchannel("A"))
        face = rgb
    return face


def _cube(top, side, front, size: int) -> Image.Image:
    s = size * 4                                    # sur-échantillonnage
    m = s * 0.06
    w = s - 2 * m
    t, l, r = (s / 2, m), (m, m + w / 4), (s - m, m + w / 4)
    c = (s / 2, m + w / 2)
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    img.alpha_composite(_face(top, s, l, (t[0] - l[0], t[1] - l[1]),
                              (c[0] - l[0], c[1] - l[1]), 1.0))
    img.alpha_composite(_face(side, s, l, (c[0] - l[0], c[1] - l[1]),
                              (0, w / 2), 0.78))
    img.alpha_composite(_face(front, s, c, (r[0] - c[0], r[1] - c[1]),
                              (0, w / 2), 0.6))
    return img.resize((size, size), Image.LANCZOS)


def _placeholder(item_id: str, size: int) -> Image.Image:
    name = item_id.split(":", 1)[-1]
    letters = "".join(p[0] for p in name.split("_")[:2]).upper() or "?"
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    pad = max(2, size // 8)
    dr.rounded_rectangle((pad, pad, size - pad, size - pad), radius=size // 6,
                         fill=(90, 90, 110, 230),
                         outline=(40, 40, 50, 255), width=max(1, size // 24))
    font = font_for(max(8, size // 3))
    dr.text((size / 2, size / 2), letters, font=font, fill=(235, 235, 235),
            anchor="mm")
    return img


_FONTS: dict = {}


def font_for(px: int):
    if px not in _FONTS:
        for name in ("arialbd.ttf", "segoeuib.ttf", "DejaVuSans-Bold.ttf"):
            try:
                _FONTS[px] = ImageFont.truetype(name, px)
                break
            except OSError:
                continue
        else:
            _FONTS[px] = ImageFont.load_default()
    return _FONTS[px]
