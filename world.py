"""
The world of VELOCITY: a wide, tall seeded map of terrain, big ground
structures, floating platforms all the way up the sky, and six towns, each
with its own colour palette that blends into its neighbours.
"""
import random

import pygame

WORLD_W = 96000
WORLD_TOP = -8000
WORLD_BOTTOM = 2600
WORLD_SEED = 11
TOWN_HALF = 1000             # half the width of a town plaza


def lerp(a, b, t):
    return a + (b - a) * t


def mix(c1, c2, t):
    return tuple(int(lerp(a, b, t)) for a, b in zip(c1, c2))


def shade(c, k):
    return tuple(max(0, min(255, int(v * k))) for v in c)


# every town sets the look of the land around it
PALETTES = {
    "lowmarket": dict(
        sky_top=(34, 26, 64), sky_bot=(240, 150, 110), far=(120, 70, 100),
        near=(78, 46, 78), ground=(96, 62, 50), top=(236, 178, 96),
        struct=(128, 82, 66), plat=(190, 120, 80), edge=(255, 214, 150),
        accent=(255, 170, 80)),
    "cinder": dict(
        sky_top=(28, 8, 18), sky_bot=(214, 74, 40), far=(110, 34, 36),
        near=(66, 20, 26), ground=(70, 28, 26), top=(255, 118, 48),
        struct=(104, 40, 34), plat=(170, 66, 44), edge=(255, 178, 96),
        accent=(255, 90, 40)),
    "mistral": dict(
        sky_top=(16, 34, 76), sky_bot=(150, 210, 240), far=(80, 124, 170),
        near=(44, 76, 120), ground=(48, 70, 104), top=(176, 234, 255),
        struct=(70, 104, 150), plat=(96, 150, 200), edge=(214, 246, 255),
        accent=(120, 220, 255)),
    "verdant": dict(
        sky_top=(16, 44, 44), sky_bot=(160, 226, 150), far=(56, 110, 84),
        near=(32, 74, 56), ground=(42, 72, 44), top=(124, 224, 100),
        struct=(56, 100, 62), plat=(78, 158, 86), edge=(196, 255, 166),
        accent=(140, 255, 110)),
    "glasswater": dict(
        sky_top=(24, 18, 64), sky_bot=(118, 128, 236), far=(66, 64, 140),
        near=(42, 40, 100), ground=(46, 44, 88), top=(124, 206, 255),
        struct=(70, 62, 130), plat=(110, 96, 200), edge=(206, 196, 255),
        accent=(170, 140, 255)),
    "skyhold": dict(
        sky_top=(30, 28, 64), sky_bot=(255, 218, 146), far=(160, 128, 96),
        near=(116, 88, 72), ground=(122, 100, 72), top=(255, 232, 146),
        struct=(150, 124, 90), plat=(212, 178, 104), edge=(255, 246, 206),
        accent=(255, 214, 90)),
}

TOWNS = [
    dict(id="lowmarket", name="Lowmarket", x=2600, kind="ground"),
    dict(id="cinder", name="Cinder Hollow", x=18000, kind="valley"),
    dict(id="mistral", name="Mistral Spire", x=34000, kind="spire", y=-2600),
    dict(id="verdant", name="Verdant Shelf", x=51000, kind="shelf", y=-1500),
    dict(id="glasswater", name="Glasswater", x=69000, kind="ground"),
    dict(id="skyhold", name="Skyhold", x=88000, kind="sky", y=-6800),
]


def palette_at(x):
    """Palette for world x, blended between the nearest towns."""
    if x <= TOWNS[0]["x"]:
        return PALETTES[TOWNS[0]["id"]]
    for a, b in zip(TOWNS, TOWNS[1:]):
        if x <= b["x"]:
            t = (x - a["x"]) / (b["x"] - a["x"])
            t = t * t * (3 - 2 * t)
            pa, pb = PALETTES[a["id"]], PALETTES[b["id"]]
            return {k: mix(pa[k], pb[k], t) for k in pa}
    return PALETTES[TOWNS[-1]["id"]]


class World:
    """Solids are indexed by a grid so only nearby ones are checked or
    drawn. Each solid has a style: (kind, fill, top colour)."""
    CELL = 512

    def __init__(self, seed=WORLD_SEED):
        self.rng = random.Random(seed)
        self.solids = []
        self.styles = []
        self.grid = {}
        self.grounds = []          # (x0, x1, surface y)
        self.decor = []            # town buildings etc, drawn behind
        self.towns = []
        self.clear_zones = []
        self.generate()
        lm = self.towns[0]
        self.spawn = (lm["x"] - 850, lm["plaza_y"])

    # -- spatial index --------------------------------------------------------
    def cells(self, r):
        c = self.CELL
        for cx in range(r.left // c, (r.right - 1) // c + 1):
            for cy in range(r.top // c, (r.bottom - 1) // c + 1):
                yield cx, cy

    def query(self, rect):
        found = set()
        for cell in self.cells(pygame.Rect(rect)):
            found.update(self.grid.get(cell, ()))
        return [self.solids[i] for i in sorted(found)]

    def query_styled(self, rect):
        found = set()
        for cell in self.cells(pygame.Rect(rect)):
            found.update(self.grid.get(cell, ()))
        return [(self.solids[i], self.styles[i]) for i in sorted(found)]

    def blocked(self, rect):
        return any(rect.colliderect(s) for s in self.query(rect))

    def add(self, x, y, w, h, kind="struct"):
        r = pygame.Rect(int(x), int(y), int(w), int(h))
        i = len(self.solids)
        self.solids.append(r)
        pal = palette_at(r.centerx)
        if kind == "ground":
            style = ("ground", pal["ground"], pal["top"])
        elif kind == "plat":
            style = ("plat", pal["plat"], pal["edge"])
        elif kind == "town":
            style = ("town", shade(pal["struct"], 1.15), pal["accent"])
        else:
            style = ("struct", pal["struct"], pal["edge"])
        self.styles.append(style)
        for cell in self.cells(r):
            self.grid.setdefault(cell, []).append(i)
        return r

    def ground_at(self, x):
        for x0, x1, h in self.grounds:
            if x0 <= x < x1:
                return h
        return self.grounds[-1][2]

    def town_at(self, x, y):
        for t in self.towns:
            if abs(x - t["x"]) < TOWN_HALF + 200 and \
                    t["plaza_y"] - 900 < y < t["plaza_y"] + 300:
                return t
        return None

    # -- generation -----------------------------------------------------------
    def ground(self, x, w, h):
        self.add(x, h, w, WORLD_BOTTOM - h, "ground")
        self.grounds.append((x, x + w, h))
        return x + w

    def generate(self):
        rng = self.rng
        self.add(-40, WORLD_TOP, 40, WORLD_BOTTOM - WORLD_TOP)
        x, h = 0, 800
        pending = list(TOWNS)
        while x < WORLD_W:
            town = pending[0] if pending else None
            if town and x >= town["x"] - TOWN_HALF - 1400:
                x, h = self.build_town(town, x, h)
                pending.pop(0)
                continue
            limit = (town["x"] - TOWN_HALF - 1400) if town else WORLD_W
            kind = rng.choices(("flat", "step", "valley", "lips", "mesa"),
                               (5, 4, 2, 1, 2))[0]
            if kind in ("valley", "lips", "mesa") and x + 2800 > limit:
                kind = "flat"            # these can't be cut short
            if kind == "valley":
                w = rng.randrange(250, 700, 10)
                x = self.ground(x, w, h + rng.randrange(200, 460, 20))
                h = max(260, min(1300, h + rng.randrange(-100, 120, 20)))
                continue
            if kind == "lips":
                for _ in range(rng.randint(2, 4)):
                    x = self.ground(x, rng.randrange(200, 400, 10), h)
                    x = self.ground(x, rng.randrange(120, 220, 10), h - 20)
                continue
            if kind == "mesa":            # stepped hill, every step jumpable
                n = rng.randint(2, 4)
                for i in range(n):
                    x = self.ground(x, rng.randrange(160, 320, 10),
                                    h - (i + 1) * 100)
                x = self.ground(x, rng.randrange(400, 900, 10), h - n * 100)
                for i in reversed(range(n)):
                    x = self.ground(x, rng.randrange(160, 320, 10), h - i * 100)
                continue
            if kind == "step":
                h += rng.choice((-1, 1)) * rng.randrange(40, 200, 20)
                h = max(260, min(1300, h))
            w = min(rng.randrange(800, 2600, 20), max(300, limit - x))
            self.decorate(x, x + w, h)
            x = self.ground(x, w, h)
        self.add(x, WORLD_TOP, 40, WORLD_BOTTOM - WORLD_TOP)
        self.sky_platforms(x)

    def decorate(self, x0, x1, h):
        rng = self.rng
        cx = x0 + rng.randrange(150, 400)
        features = (self.hanging, self.pillar, self.tunnel, self.shaft,
                    self.stairs, self.tower, self.ruin)
        while cx < x1 - 300:
            used = rng.choice(features)(cx, h, x1 - cx - 100)
            cx += used + rng.randrange(250, 700)

    def hanging(self, x, h, room):
        w = min(room, self.rng.randrange(160, 480, 10))
        bh = self.rng.randrange(160, 520, 20)
        self.add(x, h - 180 - bh, w, bh)
        return w

    def pillar(self, x, h, room):
        w = self.rng.randrange(60, 120, 10)
        ph = self.rng.randrange(100, 260, 20)      # low enough to wall run over
        self.add(x, h - ph, w, ph)
        return w

    def tunnel(self, x, h, room):
        w = min(room, self.rng.randrange(500, 1500, 20))
        self.add(x, h - 140, w, 30)
        return w

    def shaft(self, x, h, room):
        gap = self.rng.randrange(150, 230, 10)
        wh = self.rng.randrange(400, 900, 20)
        self.add(x, h - wh, 40, wh - 60)              # walls hang: crawl under
        self.add(x + 40 + gap, h - wh, 40, wh - 60)
        top = self.rng.randrange(200, 500, 10)
        self.add(x + 80 + gap, h - wh, top, 30)
        return 80 + gap + top

    def stairs(self, x, h, room):
        px, py = x, h
        for _ in range(self.rng.randint(3, 8)):
            px += self.rng.randrange(120, 260, 10)
            py -= self.rng.randrange(90, 125, 5)
            self.add(px, py, self.rng.randrange(100, 220, 10), 20, "plat")
        return px - x + 220

    def tower(self, x, h, room):
        w = self.rng.randrange(160, 320, 10)
        th = self.rng.randrange(700, 1800, 20)
        self.add(x, h - th, w, th - 60)              # slide under it
        side = 1
        y = h - self.rng.randrange(120, 200, 10)
        while y > h - th + 60:
            lx = x + w if side > 0 else x - 100
            self.add(lx, y, 100, 20, "plat")
            side = -side
            y -= self.rng.randrange(130, 220, 10)
        return w + 100

    def ruin(self, x, h, room):
        # a tall broken wall: wall run it and whip over the top
        wh = self.rng.randrange(300, 700, 20)
        self.add(x, h - wh, 50, wh - 60)
        self.add(x - 150, h - wh - 20, 250, 20)
        return 120

    def ladder(self, x, y_from, y_to):
        # zigzag rungs from the ground up to a height, always jumpable
        py, i = y_from - 110, 0
        while py > y_to + 40:
            self.add(x + (i % 2) * 220, py, 140, 20, "plat")
            py -= self.rng.randrange(95, 115, 5)
            i += 1

    def build_town(self, town, x, h):
        rng = self.rng
        tx = town["x"]
        # quiet approach
        x = self.ground(x, tx - TOWN_HALF - 400 - x, h)
        kind = town["kind"]
        if kind == "valley":
            for i in range(1, 5):
                x = self.ground(x, 100, h + i * 120)
            plaza_h = h + 480
            x = self.ground(x, tx + TOWN_HALF - x, plaza_h)
            for i in reversed(range(4)):
                x = self.ground(x, 100, h + i * 120)
            plaza_y = plaza_h
        else:
            x = self.ground(x, tx + TOWN_HALF + 400 - x, h)
            plaza_y = h
        if kind == "spire":
            y = town["y"]
            self.add(tx - TOWN_HALF, y, 2 * TOWN_HALF, 70, "town")
            self.add(tx - 260, y + 70, 520, h - 220 - (y + 70), "town")
            yy, side = y + 260, 1
            while yy < h - 260:
                lx = tx + 260 if side > 0 else tx - 380
                self.add(lx, yy, 120, 20, "plat")
                side, yy = -side, yy + 200
            self.ladder(tx - TOWN_HALF - 420, h, y)
            plaza_y = y
        elif kind == "shelf":
            y = town["y"]
            self.add(tx - 1200, y, 2400, 160, "town")
            for bx in (-900, -150, 600):
                self.add(tx + bx, y + 160, 300, 140, "town")
            self.ladder(tx - 1600, h, y)
            plaza_y = y
        elif kind == "sky":
            y = town["y"]
            self.add(tx - TOWN_HALF, y, 2 * TOWN_HALF, 100, "town")
            self.ladder(tx - TOWN_HALF - 420, h, y)
            plaza_y = y
        town = dict(town, plaza_y=plaza_y)
        self.towns.append(town)
        self.clear_zones.append(pygame.Rect(tx - TOWN_HALF - 300, plaza_y - 900,
                                            2 * TOWN_HALF + 600, 1100))
        self.town_decor(town)
        return x, h

    def town_decor(self, town):
        rng = self.rng
        pal = PALETTES[town["id"]]
        tx, y = town["x"], town["plaza_y"]
        bx = tx - TOWN_HALF + 60
        while bx < tx + TOWN_HALF - 200:
            w = rng.randrange(150, 280, 10)
            hgt = rng.randrange(120, 280, 10)
            wall = mix(pal["struct"], pal["accent"], rng.uniform(0.15, 0.45))
            roof = shade(pal["accent"], rng.uniform(0.6, 0.9))
            wins = []
            for wy in range(y - hgt + 30, y - 40, 56):
                for wx in range(bx + 24, bx + w - 30, 52):
                    if rng.random() < 0.75:
                        wins.append((wx, wy))
            self.decor.append(dict(kind="house", rect=pygame.Rect(bx, y - hgt, w, hgt),
                                   wall=wall, roof=roof, windows=wins))
            bx += w + rng.randrange(60, 180, 10)
        for lx in range(tx - TOWN_HALF + 40, tx + TOWN_HALF, 320):
            self.decor.append(dict(kind="lamp", pos=(lx, y), color=pal["accent"]))
        self.decor.append(dict(kind="sign", pos=(tx - TOWN_HALF + 20, y),
                               text=town["name"], color=pal["accent"]))

    def sky_platforms(self, end):
        """Small platforms scattered through the whole sky, plus the odd
        floating block or wall slab for skims, wraps and wall runs."""
        rng = self.rng
        cw, ch = 320, 220
        for gx in range(400, end - 400, cw):
            floor = self.ground_at(gx) - 320
            for gy in range(WORLD_TOP + 300, floor, ch):
                r = rng.random()
                if r > 0.55:
                    continue
                px = gx + rng.randrange(0, cw - 100)
                py = gy + rng.randrange(0, ch - 40)
                if r < 0.03:
                    w, hh = rng.randrange(200, 520, 20), rng.randrange(100, 300, 20)
                    kind = "struct"
                elif r < 0.05:
                    w, hh = 40, rng.randrange(300, 600, 20)
                    kind = "struct"
                else:
                    w, hh = rng.randrange(70, 200, 10), 18
                    kind = "plat"
                cand = pygame.Rect(px, py, w, hh)
                if py + hh > self.ground_at(px) - 300:
                    continue
                if any(cand.colliderect(z) for z in self.clear_zones):
                    continue
                if self.blocked(cand.inflate(120, 120)):
                    continue
                self.add(px, py, w, hh, kind)
