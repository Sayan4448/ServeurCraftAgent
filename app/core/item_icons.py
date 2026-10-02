"""Icônes d'items façon inventaire du jeu, à partir des textures officielles.

Rien n'est embarqué dans l'app : à la première ouverture d'une fiche joueur,
le client Minecraft de la version du serveur est téléchargé depuis les
serveurs de Mojang (comme le fait un launcher) et seuls les modèles et
textures d'items / blocs sont gardés dans runtimes/textures/<version>/.

Rendu : items « plats » (item/generated, handheld…) = calques superposés ;
blocs = petit cube isométrique (dessus / côté / face) ; sinon repli sur une
pastille avec les initiales (coffres, lits…).

Objets des mods : les modèles et textures sont lus dans les jars de mods/
du serveur (`mod_roots`), un dossier par espace de noms (`create`, …).
`catalog()` liste tous les objets connus, avec leur nom dans la langue de
l'app, pour le catalogue « Donner » façon inventaire créatif.
"""
import json
import threading
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from ..config import RUNTIMES_DIR
from .downloader import _get_json, download_file

MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
# items/ : définitions d'objets (1.21.4+), qui remplacent models/item pour
# les blocs ; lang/ : noms affichés
_KEEP = ("assets/minecraft/textures/item/", "assets/minecraft/textures/block/",
         "assets/minecraft/models/item/", "assets/minecraft/models/block/",
         "assets/minecraft/items/", "assets/minecraft/lang/")
ASSETS = "https://resources.download.minecraft.net/{}/{}"
# langue de l'app -> fichier de langue de Minecraft
LANG_CODES = {"fr": "fr_fr", "en": "en_us", "ru": "ru_ru", "ja": "ja_jp",
              "es": "es_es", "de": "de_de"}
MODS_CACHE = "_mods"
# textures de mods inutiles pour des icônes d'objets
_MOD_SKIP = ("textures/entity/", "textures/gui/", "textures/models/",
             "textures/environment/", "textures/particle/",
             "textures/painting/", "textures/mob_effect/", "textures/font/",
             "textures/misc/")
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
    # lang/ : ajouté avec le catalogue — un cache plus ancien est refait
    d = tex_dir(version)
    return (d / ".ok").exists() and (d / "lang" / "en_us.json").exists()


def cached_versions() -> list:
    root = RUNTIMES_DIR / "textures"
    if not root.exists():
        return []
    return sorted(p.name for p in root.iterdir() if available(p.name))


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
            meta = _get_json(entry["url"])
            url = meta["downloads"]["client"]["url"]
            jar = d.parent / f"{version}-client.jar"
            download_file(url, jar, progress)
            with zipfile.ZipFile(jar) as z:
                for n in z.namelist():
                    if n.startswith(_KEEP) and n.endswith((".png", ".json")):
                        out = d / n[len("assets/minecraft/"):]
                        out.parent.mkdir(parents=True, exist_ok=True)
                        out.write_bytes(z.read(n))
            jar.unlink(missing_ok=True)
            _fetch_langs(meta, d)
            (d / ".ok").write_text(entry["id"], encoding="utf-8")
        except Exception as e:  # noqa: BLE001 — réseau, zip, disque
            raise TextureError(str(e)) from e
    return d


def _fetch_langs(meta: dict, d: Path) -> None:
    """Noms des objets dans les langues de l'app (le jar ne contient que
    l'anglais ; les autres sont dans l'index des ressources). Facultatif :
    sans eux, les noms restent en anglais."""
    try:
        objects = _get_json(meta["assetIndex"]["url"])["objects"]
        for code in LANG_CODES.values():
            h = (objects.get(f"minecraft/lang/{code}.json") or {}).get("hash")
            if h and not (d / "lang" / f"{code}.json").exists():
                download_file(ASSETS.format(h[:2], h),
                              d / "lang" / f"{code}.json")
    except Exception:  # noqa: BLE001 — réseau, format de l'index
        pass


# ============================================================ mods

def mod_roots(server_dir: Path) -> dict:
    """{espace de noms: dossier models/ textures/ lang/} des mods du serveur.
    Les assets de chaque jar sont extraits une fois dans
    runtimes/textures/_mods/ (bloquant : à appeler depuis un thread)."""
    # ponytail: les jars imbriqués (META-INF/jars) ne sont pas ouverts et le
    # cache des mods retirés n'est jamais purgé — à faire si ça pèse.
    roots = {}
    for jar in sorted((Path(server_dir) / "mods").glob("*.jar")):
        try:
            d = RUNTIMES_DIR / "textures" / MODS_CACHE / \
                f"{jar.stem}-{jar.stat().st_size}"
            if not (d / ".ok").exists():
                _extract_mod(jar, d)
            for ns in d.iterdir():
                if ns.is_dir() and ns.name != "minecraft":
                    roots.setdefault(ns.name, ns)
        except (OSError, zipfile.BadZipFile):
            continue
    return roots


def _extract_mod(jar: Path, d: Path) -> None:
    langs = tuple(LANG_CODES.values())
    with zipfile.ZipFile(jar) as z:
        for info in z.infolist():
            parts = info.filename.split("/", 2)
            if len(parts) < 3 or parts[0] != "assets" or info.is_dir() \
                    or ".." in info.filename:
                continue
            rel = parts[2]
            if rel.endswith(".json"):
                keep = rel.startswith(("models/item/", "models/block/",
                                       "items/")) or \
                    (rel.startswith("lang/") and rel[5:-5] in langs)
            else:
                keep = rel.startswith("textures/") and rel.endswith(".png") \
                    and not rel.startswith(_MOD_SKIP) \
                    and info.file_size < 300_000
            if keep:
                out = d / parts[1] / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(z.read(info))
    d.mkdir(parents=True, exist_ok=True)
    (d / ".ok").write_text(jar.name, encoding="utf-8")


# ============================================================ catalogue

def _lang(root: Path, code: str) -> dict:
    """Noms de `root/lang` : anglais, complété par la langue demandée."""
    names = {}
    for c in dict.fromkeys(("en_us", code)):
        try:
            data = json.loads((root / "lang" / f"{c}.json").read_text(
                encoding="utf-8"))
            names.update({k: v for k, v in data.items()
                          if isinstance(v, str)})
        except (OSError, ValueError):
            pass
    return names


def catalog(roots: dict, lang: str = "en") -> list:
    """Tous les objets connus : [(id complet, nom affiché)], par espace de
    noms (`roots` = {"minecraft": dossier des textures, mod: dossier…})."""
    code = LANG_CODES.get(lang, "en_us")
    out = []
    for ns, root in roots.items():
        names = _lang(root, code)
        ids = {f.stem for f in (root / "items").glob("*.json")}
        if not ids:                    # avant 1.21.4 : un modèle par objet,
            ids = {f.stem for f in (root / "models" / "item").glob("*.json")}
            named = {i for i in ids if f"item.{ns}.{i}" in names
                     or f"block.{ns}.{i}" in names}
            ids = named or ids         # mais aussi des gabarits sans nom
        for i in sorted(ids - {"air"}):
            title = names.get(f"item.{ns}.{i}") or \
                names.get(f"block.{ns}.{i}") or i.replace("_", " ").title()
            out.append((f"{ns}:{i}", title))
    return out


# ============================================================ rendu

def _split(ref: str) -> tuple:
    """'create:item/x' -> ('create', 'item/x') ; sans préfixe : minecraft."""
    ns, _, path = ref.rpartition(":")
    return ns or "minecraft", path


def _first_model(node):
    """Modèle affiché par défaut d'une définition d'objet (items/*.json) :
    premier modèle simple trouvé, en préférant l'état « au repos »."""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return next((m for m in map(_first_model, node) if m), None)
    if not isinstance(node, dict):
        return None
    kind = _split(str(node.get("type", "")))[1]
    if kind == "model" and isinstance(node.get("model"), str):
        return node["model"]
    if kind == "special":
        return node.get("base")
    for key in ("on_false", "fallback", "model", "models", "cases",
                "entries"):
        found = _first_model(node.get(key))
        if found:
            return found
    return None


class Icons:
    """Cache d'icônes RGBA carrées de `size` px. `root` : dossier des
    textures de Minecraft (None = pastilles à initiales) ; `extra` :
    {espace de noms: dossier} pour les objets des mods."""

    def __init__(self, root: Path | None, size: int = 32,
                 extra: dict | None = None):
        self.root = Path(root) if root else None
        self.roots = {ns: Path(d) for ns, d in (extra or {}).items()}
        if self.root:
            self.roots["minecraft"] = self.root
        self.size = size
        self._cache: dict = {}
        self._models: dict = {}

    def get(self, item_id: str) -> Image.Image:
        key = item_id
        if key not in self._cache:
            img = None
            ns, name = _split(item_id)
            if ns in self.roots:
                try:
                    img = self._render(ns, name)
                except Exception:  # noqa: BLE001 — modèle inattendu
                    img = None
            self._cache[key] = img or _placeholder(item_id, self.size)
        return self._cache[key]

    # ------------------------------------------------------------ modèles
    def _json(self, ns: str, rel: str):
        root = self.roots.get(ns)
        if root is None:
            return None
        try:
            return json.loads((root / rel).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _model(self, ref: str):
        if ref not in self._models:
            ns, path = _split(ref)
            self._models[ref] = self._json(ns, f"models/{path}.json")
        return self._models[ref]

    def _resolve(self, ref: str):
        """(chaîne des parents sans espace de noms, textures fusionnées)."""
        chain, textures = [], {}
        cur, depth = ref, 0
        while cur and depth < 12:
            ns, path = _split(cur)
            chain.append(path)
            m = self._model(f"{ns}:{path}")
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
        ns, path = _split(ref)
        root = self.roots.get(ns)
        f = root / "textures" / f"{path}.png" if root else None
        if f is None or not f.exists():
            return None
        img = Image.open(f).convert("RGBA")
        if img.height > img.width:                  # texture animée
            img = img.crop((0, 0, img.width, img.width))
        tint = _TINTS.get(path) if ns == "minecraft" else None
        if tint:
            img = _tint(img, tint)
        return img

    # ------------------------------------------------------------ dessin
    def _render(self, ns: str, name: str):
        # 1.21.4+ : items/<nom>.json désigne le modèle (souvent block/<nom>)
        ref = _first_model(self._json(ns, f"items/{name}.json")) or \
            f"{ns}:item/{name}"
        chain, textures = self._resolve(ref)
        if any(c in _FLAT or c.startswith("item/handheld") for c in chain):
            layers = [self._tex(textures, f"layer{i}") for i in range(5)]
            layers = [x for x in layers if x is not None]
            if layers:
                return _flat(layers, self.size)
        if any(c.startswith("block/") for c in chain):
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
        for ref in (f"{ns}:item/{name}", f"{ns}:block/{name}"):
            img = self._load(ref)
            if img is not None:
                if "block/" in ref:
                    return _cube(img, img, img, self.size)
                return _flat([img], self.size)
        one = self._tex(textures, "particle", "layer0", "all", "texture")
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
