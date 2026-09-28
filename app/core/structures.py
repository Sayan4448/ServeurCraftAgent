"""Blueprints de structures construites en jeu via commandes vanilla.

Chaque blueprint retourne une liste de commandes (fill/setblock) que
l'agent envoie à la console du serveur. Coordonnées = coin bas-ouest.
"""


def _fill(x1, y1, z1, x2, y2, z2, block):
    return f"fill {x1} {y1} {z1} {x2} {y2} {z2} minecraft:{block}"


def _set(x, y, z, block):
    return f"setblock {x} {y} {z} minecraft:{block}"


def _walls(x, y, z, w, h, d, block):
    """Boîte creuse : sol, plafond, 4 murs, intérieur vidé."""
    return [
        _fill(x, y, z, x + w - 1, y, z + d - 1, block),                    # sol
        _fill(x, y + h - 1, z, x + w - 1, y + h - 1, z + d - 1, block),    # toit
        _fill(x, y + 1, z, x + w - 1, y + h - 2, z, block),                # nord
        _fill(x, y + 1, z + d - 1, x + w - 1, y + h - 2, z + d - 1, block),# sud
        _fill(x, y + 1, z, x, y + h - 2, z + d - 1, block),                # ouest
        _fill(x + w - 1, y + 1, z, x + w - 1, y + h - 2, z + d - 1, block),# est
        _fill(x + 1, y + 1, z + 1, x + w - 2, y + h - 2, z + d - 2, "air"),# creux
    ]


def prison(x, y, z, size=4):
    """Prison : bâtiment en briques avec `size` cellules à barreaux."""
    cells = max(2, min(int(size or 4), 10))
    w, h, d = 3 * cells + 3, 6, 9
    cmds = _walls(x, y, z, w, h, d, "stone_bricks")
    for i in range(cells):
        cx = x + 1 + i * 3
        # cloison latérale de la cellule + façade en barreaux côté couloir
        cmds.append(_fill(cx + 2, y + 1, z + 1, cx + 2, y + h - 3, z + 4,
                          "stone_bricks"))
        cmds.append(_fill(cx, y + 1, z + 4, cx + 2, y + 3, z + 4,
                          "iron_bars"))
        # porte de cellule en fer (fermée tant que pas alimentée)
        cmds.append(_set(cx + 1, y + 1, z + 4, "iron_door[half=lower]"))
        cmds.append(_set(cx + 1, y + 2, z + 4, "iron_door[half=upper]"))
        # couche rudimentaire
        cmds.append(_fill(cx, y + 1, z + 1, cx + 1, y + 1, z + 2,
                          "smooth_stone_slab"))
        # éclairage du couloir
        cmds.append(_set(cx + 1, y + h - 1, z + 6, "glowstone"))
    # entrée principale au sud
    mx = x + w // 2
    cmds += [_set(mx, y + 1, z + d - 1, "iron_door[half=lower]"),
             _set(mx, y + 2, z + d - 1, "iron_door[half=upper]")]
    return cmds


def cage(x, y, z, size=5):
    """Cage en barreaux de fer."""
    s = max(3, min(int(size or 5), 15))
    return _walls(x, y, z, s, 5, s, "iron_bars")


def maison(x, y, z, size=7):
    """Maison en bois avec fenêtres, porte, toit en dalles."""
    s = max(5, min(int(size or 7), 15))
    cmds = _walls(x, y, z, s, 5, s, "oak_planks")
    # fenêtres nord et sud
    cmds += [_fill(x + 2, y + 2, z, x + 3, y + 3, z, "glass"),
             _fill(x + s - 4, y + 2, z + s - 1, x + s - 3, y + 3, z + s - 1,
                   "glass")]
    # porte d'entrée nord
    mx = x + s // 2
    cmds += [_set(mx, y + 1, z, "oak_door[half=lower]"),
             _set(mx, y + 2, z, "oak_door[half=upper]")]
    # toit débordant + lanterne intérieure
    cmds.append(_fill(x - 1, y + 5, z - 1, x + s, y + 5, z + s, "oak_slab"))
    cmds.append(_set(x + 2, y + 1, z + 2, "lantern"))
    return cmds


def mur(x, y, z, size=10):
    """Mur de pierre avec créneaux."""
    length = max(4, min(int(size or 10), 50))
    cmds = [_fill(x, y, z, x + length - 1, y + 3, z, "stone_bricks")]
    for i in range(0, length, 2):
        cmds.append(_set(x + i, y + 4, z, "stone_brick_wall"))
    return cmds


def arene(x, y, z, size=12):
    """Arène : sol de dalles entouré de barrières, lanternes aux coins."""
    s = max(8, min(int(size or 12), 30))
    cmds = [_fill(x, y, z, x + s - 1, y, z + s - 1, "stone_slab"),
            _fill(x, y + 1, z, x + s - 1, y + 1, z, "oak_fence"),
            _fill(x, y + 1, z + s - 1, x + s - 1, y + 1, z + s - 1,
                  "oak_fence"),
            _fill(x, y + 1, z, x, y + 1, z + s - 1, "oak_fence"),
            _fill(x + s - 1, y + 1, z, x + s - 1, y + 1, z + s - 1,
                  "oak_fence")]
    for cx, cz in ((x, z), (x + s - 1, z), (x, z + s - 1),
                   (x + s - 1, z + s - 1)):
        cmds.append(_set(cx, y + 2, cz, "lantern"))
    return cmds


def fontaine(x, y, z, size=5):
    """Fontaine : bassin circulaire et pilier central."""
    s = max(5, min(int(size or 5), 11))
    if s % 2 == 0:
        s += 1
    c = s // 2
    cmds = [
        _fill(x, y, z, x + s - 1, y, z, "stone_bricks"),
        _fill(x, y, z + s - 1, x + s - 1, y, z + s - 1, "stone_bricks"),
        _fill(x, y, z, x, y, z + s - 1, "stone_bricks"),
        _fill(x + s - 1, y, z, x + s - 1, y, z + s - 1, "stone_bricks"),
        _fill(x + 1, y, z + 1, x + s - 2, y, z + s - 2, "water"),
        _fill(x + c, y + 1, z + c, x + c, y + 3, z + c, "stone_bricks"),
        _set(x + c, y + 4, z + c, "water"),
    ]
    return cmds


def tour(x, y, z, size=12):
    """Tour de guet 5x5 avec créneaux et lanterne."""
    h = max(6, min(int(size or 12), 40))
    cmds = _walls(x, y, z, 5, h, 5, "stone_bricks")
    # créneaux sur le toit
    for i in (0, 2, 4):
        cmds.append(_set(x + i, y + h, z, "stone_brick_wall"))
        cmds.append(_set(x + i, y + h, z + 4, "stone_brick_wall"))
        cmds.append(_set(x, y + h, z + i, "stone_brick_wall"))
        cmds.append(_set(x + 4, y + h, z + i, "stone_brick_wall"))
    cmds.append(_set(x + 2, y + h, z + 2, "lantern"))
    return cmds


BLUEPRINTS = {
    "prison": prison, "cage": cage, "maison": maison, "mur": mur,
    "arene": arene, "fontaine": fontaine, "tour": tour,
}
