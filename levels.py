"""
Player-made levels: the block types, the level file format, running a level
(physics glue between the blocks and the Player) and drawing it.

A level is JSON: {"v": 1, "theme": "<palette>", "objs": [[type, x, y, w, h,
d, p], ...]} where d is a direction (0 up, 1 right, 2 down, 3 left) and p a
power level 1-5, for the blocks that use them. A saw may have an 8th item, a
custom path: [[dx, dy], ...] points relative to its centre.

Replays are the inputs of every physics step, run-length encoded (see
encode_replay); the physics is deterministic, so they play back exactly.
"""
import json
import math
import random

import pygame

from player import AIR_LOCK, MAX_DASHES, SLIP, Player, sign
from ui import DIM, GOLD, INK, pixel_rect, tint_rect, PLAYER_DASH, PLAYER_EMPTY, PLAYER_READY, RED, TEXT, fmt_time
from world import PALETTES, mix, shade

DIRS = [(0, -1), (1, 0), (0, 1), (-1, 0)]
DIR_NAMES = ["up", "right", "down", "left"]

BOUNCE_POWER = [700, 950, 1200, 1450, 1750]
BOOST_POWER = [600, 850, 1100, 1350, 1600]
GRAV_MUL = [0.2, 0.4, 0.6, 1.5, 2.5]
WIND_PUSH = [120, 220, 320, 420, 520]        # sideways wind, px/s
WIND_LIFT = [1200, 1900, 2600, 3300, 4000]   # up/down wind, px/s^2 (gravity is 2200)
GATE_SPEED = [500, 700, 900, 1100, 1300]
SAW_RANGE = [64, 128, 192, 256, 384]
SAW_SPEED = 220
SAW_PATH_SPEED = [120, 180, 240, 320, 420]   # saws on a custom path, by power
PATH_MAX = 32
TEXT_MAX = 200            # characters in a text block
BLINK_TIME = 1.0          # blink blocks swap this often
CRUMBLE_DELAY = 0.35      # crumble blocks fall this long after you touch them
CRUMBLE_BACK = 2.5
ORB_BACK = 2.0
DEATH_FREEZE = 0.5        # after dying you wait this long at the respawn point
FALL_MARGIN = 1200        # fall this far below the lowest block and you die

CELL = 256
COORD_MAX = 1_000_000     # level files are untrusted: keep everything in range
SIZE_MAX = 10_000


class Kind:
    def __init__(self, name, group, size, resize=True, dirs=0, power=None,
                 colour=TEXT, info=""):
        self.name = name
        self.group = group      # solid, hazard, trigger, zone, marker
        self.size = size
        self.resize = resize
        self.dirs = dirs        # 0 none, 2 axis (horizontal / vertical), 4 any
        self.power = power      # (label, values) or None
        self.colour = colour
        self.info = info


KINDS = {
    "wall": Kind("Wall", "solid", (64, 64), colour=(150, 140, 190),
                 info="Solid block."),
    "kill": Kind("Kill Brick", "hazard", (64, 32), colour=(235, 50, 80),
                 info="Touch it and you die."),
    "bounce": Kind("Bounce Pad", "trigger", (64, 16), dirs=4,
                   power=("speed", BOUNCE_POWER), colour=(150, 255, 90),
                   info="Launches you its way at a set speed and refills your dash."),
    "boost": Kind("Speed Strip", "trigger", (128, 16), dirs=4,
                  power=("speed", BOOST_POWER), colour=(70, 210, 255),
                  info="Raises your speed its way to at least its power. Never slows you."),
    "ice": Kind("Ice", "solid", (128, 32), colour=(190, 240, 255),
                info="Slippery: on ice, WASD speeds you up and down slowly."),
    "oneway": Kind("One-Way", "solid", (96, 12), colour=(240, 200, 140),
                   info="Solid only from above. Jump up through it."),
    "crumble": Kind("Crumble", "solid", (64, 32), colour=(200, 140, 90),
                    info=f"Falls {CRUMBLE_DELAY}s after you touch it, returns after {CRUMBLE_BACK}s."),
    "blinkA": Kind("Blink A", "solid", (64, 32), colour=(255, 110, 200),
                   info=f"Solid for {BLINK_TIME:g}s, then gone for {BLINK_TIME:g}s. Swaps with Blink B."),
    "blinkB": Kind("Blink B", "solid", (64, 32), colour=(150, 120, 255),
                   info="Solid while Blink A is gone."),
    "gate": Kind("Speed Gate", "solid", (16, 96), power=("break at", GATE_SPEED),
                 colour=(255, 214, 90), info="Solid unless you hit it at least this fast."),
    "saw": Kind("Saw", "hazard", (32, 32), resize=False, dirs=2,
                power=("travel", SAW_RANGE), colour=(220, 220, 235),
                info="Moving kill circle. Direction picks its axis, power its travel."
                     " Give it a custom path from the selection bar."),
    "orb": Kind("Dash Orb", "trigger", (24, 24), resize=False, colour=PLAYER_READY,
                info=f"Refills your dash. Comes back after {ORB_BACK:g}s."),
    "grav": Kind("Gravity Zone", "zone", (192, 192), power=("gravity x", GRAV_MUL),
                 colour=(180, 120, 255), info="Changes gravity inside it."),
    "wind": Kind("Wind Zone", "zone", (192, 192), dirs=4,
                 power=("strength", [1, 2, 3, 4, 5]), colour=(220, 240, 255),
                 info="Pushes you its way. Strong updrafts beat gravity."),
    "nodash": Kind("No-Dash Zone", "zone", (192, 192), colour=(255, 120, 60),
                   info="You can't dash inside it."),
    "check": Kind("Checkpoint", "trigger", (32, 64), resize=False, colour=GOLD,
                  info="You respawn here after dying."),
    "start": Kind("Start", "marker", (32, 32), resize=False, colour=PLAYER_READY,
                  info="Where you spawn. One per level."),
    "finish": Kind("Finish", "trigger", (48, 64), colour=(255, 255, 255),
                   info="Touch it to clear the level."),
    "text": Kind("Text", "marker", (256, 64), colour=(255, 236, 170),
                 info="A message for players. Select it and press Text to write it."),
}
ORDER = ["wall", "kill", "bounce", "boost", "ice", "oneway", "crumble", "blinkA",
         "blinkB", "gate", "saw", "orb", "grav", "wind", "nodash", "check", "start",
         "finish", "text"]
SOLID = {k for k, v in KINDS.items() if v.group == "solid"}


class Obj:
    __slots__ = ("t", "x", "y", "w", "h", "d", "p", "path", "text")

    def __init__(self, t, x, y, w, h, d=0, p=1, path=None, text=None):
        self.t, self.x, self.y, self.w, self.h, self.d, self.p = t, x, y, w, h, d, p
        if t == "text" and isinstance(path, str):
            path, text = None, path         # a text block's 8th item is its text
        self.path = [list(pt) for pt in path] if path else None   # saws only
        self.text = (text or "") if t == "text" else None

    @property
    def rect(self):
        return pygame.FRect(self.x, self.y, self.w, self.h)

    @property
    def kind(self):
        return KINDS[self.t]

    def power(self):
        k = self.kind
        if self.path:
            return SAW_PATH_SPEED[self.p - 1]
        return k.power[1][self.p - 1] if k.power else None

    def copy(self):
        return Obj(*self.to_list())

    def to_list(self):
        out = [self.t, self.x, self.y, self.w, self.h, self.d, self.p]
        if self.path:
            out.append([list(pt) for pt in self.path])
        elif self.text:
            out.append(self.text)
        return out


def dump(objs, theme):
    return json.dumps({"v": 1, "theme": theme, "objs": [o.to_list() for o in objs]},
                      separators=(",", ":"))


def load(text):
    """Returns (objs, theme) from level JSON, skipping anything unknown."""
    data = json.loads(text) if isinstance(text, str) else text
    objs = []
    for o in data.get("objs", []):
        if (isinstance(o, list) and len(o) in (7, 8) and o[0] in KINDS
                and all(isinstance(v, (int, float)) for v in o[1:7])):
            t, x, y, w, h, d, p = o[:7]
            if not (abs(x) <= COORD_MAX and abs(y) <= COORD_MAX
                    and 1 <= w <= SIZE_MAX and 1 <= h <= SIZE_MAX):
                continue
            path = text = None
            if len(o) == 8 and t == "text" and isinstance(o[7], str):
                text = "".join(ch for ch in o[7][:TEXT_MAX] if ch.isprintable())
            if len(o) == 8 and t == "saw" and isinstance(o[7], list):
                path = [pt for pt in o[7][:PATH_MAX]
                        if isinstance(pt, list) and len(pt) == 2
                        and all(isinstance(v, (int, float)) and abs(v) <= COORD_MAX for v in pt)]
            objs.append(Obj(t, x, y, max(1, w), max(1, h), int(d) % 4,
                            max(1, min(5, int(p))), path, text))
    theme = data.get("theme")
    return objs, theme if theme in PALETTES else "lowmarket"


def saw_points(o):
    """World points of a saw's custom path, starting at the saw itself."""
    cx, cy = o.x + o.w / 2, o.y + o.h / 2
    return [(cx, cy)] + [(cx + dx, cy + dy) for dx, dy in o.path]


def saw_center(o, clock):
    """Saws slide back and forth along their axis from where they're placed,
    or follow their custom path: there and back (direction 0) or round in
    a loop (direction 1)."""
    if o.path:
        pts = saw_points(o)
        if o.d % 2:
            pts.append(pts[0])
        segs = [(a, b, math.dist(a, b)) for a, b in zip(pts, pts[1:])]
        total = sum(L for _, _, L in segs)
        if total <= 0:
            return pts[0]
        dist = clock * o.power()
        if o.d % 2:
            dist %= total
        else:
            dist %= 2 * total
            if dist > total:
                dist = 2 * total - dist
        for a, b, L in segs:
            if dist <= L and L > 0:
                f = dist / L
                return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
            dist -= L
        return pts[-1]
    rng = o.power()
    period = 2 * rng / SAW_SPEED
    off = rng * (0.5 - 0.5 * math.cos(clock * math.tau / period))
    cx, cy = o.x + o.w / 2, o.y + o.h / 2
    return (cx + off, cy) if o.d % 2 else (cx, cy + off)


def circle_hits(cx, cy, r, rect):
    nx = min(max(cx, rect.left), rect.right)
    ny = min(max(cy, rect.top), rect.bottom)
    return (nx - cx) ** 2 + (ny - cy) ** 2 < r * r


# ------------------------------------------------------------------- run ---
class Run:
    """A level being played: the player, block state, timer and effects."""

    def __init__(self, objs, theme, spawn=None):
        self.objs = [o.copy() for o in objs]
        self.theme = theme
        start = next((o for o in self.objs if o.t == "start"), None)
        self.start = (start.x + start.w / 2, start.y + start.h) if start else (0, 0)
        if spawn:
            self.start = spawn
        bottom = max((o.y + o.h for o in self.objs), default=0)
        self.death_y = bottom + FALL_MARGIN
        self.grid = {}
        self.saws = []
        self.changing = [i for i, o in enumerate(self.objs)
                         if o.t in ("blinkA", "blinkB", "crumble", "orb")]
        for i, o in enumerate(self.objs):
            if o.t == "saw":
                self.saws.append(o)
                continue
            r = o.rect
            for gx in range(int(r.left // CELL), int(r.right // CELL) + 1):
                for gy in range(int(r.top // CELL), int(r.bottom // CELL) + 1):
                    self.grid.setdefault((gx, gy), []).append(i)
        self.player = Player(self.start)
        self.clock = 0.0
        self.restart()

    def restart(self):
        self.clock = 0.0            # blinks and saws restart too, so replays match
        self.freeze_t = 0.0
        self.player.spawn = self.start
        self.checkpoint = None
        self.time = 0.0
        self.started = False
        self.finished = False
        self.deaths = 0
        self.feed = []
        self.reset_world()

    def reset_world(self):
        self.player.reset()
        n = len(self.objs)
        self.timer = [0.0] * n      # crumble countdown / orb + crumble return
        self.on = [True] * n        # crumble, blink, gate, orb present
        self.trail = []
        self.particles = []
        self.was_dashing = False
        self.sync_blinks(int(self.clock / BLINK_TIME) % 2 == 0, self.player.rect)

    def sync_blinks(self, blink_a, pr):
        """Blink blocks on or off for the current phase; one that should come
        back while you're inside it waits until you've left."""
        for i in self.changing:
            t = self.objs[i].t
            if t not in ("blinkA", "blinkB"):
                continue
            if blink_a != (t == "blinkA"):
                self.on[i] = False
            elif not self.on[i] and not pr.colliderect(self.objs[i].rect):
                self.on[i] = True

    def die(self):
        """Back to the last checkpoint, frozen for a moment, with saws and
        blink blocks back at their starting positions, so nothing can kill
        you over and over as you respawn."""
        self.deaths += 1
        self.burst(self.player.rect.center, RED, 24, 500)
        parts = self.particles
        self.clock = 0.0
        self.reset_world()
        self.particles = parts
        self.freeze_t = DEATH_FREEZE

    def near(self, rect):
        seen = set()
        for gx in range(int(rect.left // CELL), int(rect.right // CELL) + 1):
            for gy in range(int(rect.top // CELL), int(rect.bottom // CELL) + 1):
                for i in self.grid.get((gx, gy), ()):
                    if i not in seen:
                        seen.add(i)
                        yield i

    # -- one physics step ------------------------------------------------------
    def step(self, dt, inp):
        p = self.player
        if self.freeze_t > 0:
            # respawning: the player and every moving part wait, the timer runs
            self.freeze_t -= dt
            if self.started and not self.finished:
                self.time += dt
            p.prev = (p.rect.x, p.rect.y)
            self.effects(dt)
            return
        self.clock += dt
        if not self.finished and not self.started and (
                inp.left or inp.right or inp.up or inp.down or inp.jump_pressed
                or inp.dash_pressed):
            self.started = True
        if self.started and not self.finished:
            self.time += dt
        objs = self.objs
        pr = p.rect
        near = list(self.near(pr.inflate(320, 320)))
        blink_a = int(self.clock / BLINK_TIME) % 2 == 0

        # zones, timers and which blocks are solid this step
        p.grav_mul, p.push, p.lift, p.dash_lock = 1.0, 0.0, 0.0, False
        spd = p.speed()
        sweep = pr.inflate(abs(p.vx) * dt * 2 + 4, abs(p.vy) * dt * 2 + 4)
        solids = []
        ice = []
        # blink, crumble and orb blocks keep time everywhere, not just near you
        for i in self.changing:
            o = objs[i]
            t = o.t
            if t in ("crumble", "orb"):
                if self.timer[i] > 0:
                    self.timer[i] -= dt
                    if self.timer[i] <= 0:
                        r = o.rect
                        if self.on[i]:          # crumble finished falling
                            self.on[i] = False
                            self.timer[i] = CRUMBLE_BACK
                            self.burst(r.center, o.kind.colour, 10, 200)
                        elif not pr.colliderect(r):
                            self.on[i] = True
                        else:
                            self.timer[i] = 0.05    # wait until you've left
        self.sync_blinks(blink_a, pr)
        for i in near:
            o = objs[i]
            t = o.t
            r = o.rect
            if t in ("grav", "wind", "nodash"):
                if pr.colliderect(r):
                    if t == "grav":
                        p.grav_mul = o.power()
                    elif t == "nodash":
                        p.dash_lock = True
                    else:
                        dx, dy = DIRS[o.d]
                        p.push += dx * WIND_PUSH[o.p - 1]
                        p.lift -= dy * WIND_LIFT[o.p - 1]
                continue
            if t == "gate" and self.on[i]:
                if spd >= o.power() and sweep.colliderect(r):
                    self.on[i] = False
                    p.trick("GATE BREAK", 4)
                    self.burst(r.center, o.kind.colour, 18, 420)
            if t not in SOLID or not self.on[i]:
                continue
            if t == "oneway" and (pr.bottom > r.top + 0.01 or p.vy < 0):
                continue
            solids.append(r)
            if t == "ice":
                ice.append(r)
        foot = pr.move(0, 1)
        p.on_ice = p.on_ground and any(foot.colliderect(r) for r in ice)
        # kill bricks bound gaps too, for nudging you into them
        p.gap_sides = [objs[i].rect for i in near if objs[i].t == "kill"]

        p.update(dt, inp, solids)

        # touching things
        self.thread_gap(near, solids)
        pr = p.rect
        for i in near:
            o = objs[i]
            t = o.t
            if t == "crumble":
                if self.on[i] and self.timer[i] <= 0 and pr.inflate(2, 2).colliderect(o.rect):
                    self.timer[i] = CRUMBLE_DELAY
                continue
            if t not in ("kill", "bounce", "boost", "orb", "check", "finish"):
                continue
            r = o.rect
            if not pr.colliderect(r):
                continue
            if t == "kill":
                self.die()
                return
            if t == "bounce":
                self.launch(o, solids)
            elif t == "boost":
                self.boost(o)
            elif t == "orb" and self.on[i] and p.dashes < MAX_DASHES:
                p.dashes = MAX_DASHES
                self.on[i] = False
                self.timer[i] = ORB_BACK
                self.burst(r.center, PLAYER_READY, 10, 260)
            elif t == "check" and self.checkpoint != i:
                self.checkpoint = i
                p.spawn = (r.centerx, r.bottom)
                self.add_feed("CHECKPOINT", GOLD)
                self.burst(r.center, GOLD, 16, 300)
            elif t == "finish" and not self.finished:
                self.finished = True
                self.burst(pr.center, GOLD, 40, 600)
        for o in self.saws:
            cx, cy = saw_center(o, self.clock)
            if circle_hits(cx, cy, o.w / 2, pr):
                self.die()
                return
        if pr.top > self.death_y:
            self.die()
            return
        self.effects(dt)

    def thread_gap(self, near, solids):
        """Clipping a kill brick by a few pixels while threading a gap
        (something solid or deadly close on the other side) nudges you into
        the gap instead of killing you, like corner correction does for
        walls. Kill bricks out in the open stay exactly as deadly."""
        p = self.player
        kills = [self.objs[i].rect for i in near if self.objs[i].t == "kill"]
        blocked = list(solids) + kills
        for _ in range(3):
            r = p.rect
            hit = next((k for k in kills if r.colliderect(k)), None)
            if hit is None:
                return
            # only ever sideways to how you're moving: pushing you back the
            # way you came would turn the kill brick into a wall
            if abs(p.vy) >= abs(p.vx):
                ways = [(hit.left - r.right, 0), (hit.right - r.left, 0)]
            else:
                ways = [(0, hit.top - r.bottom), (0, hit.bottom - r.top)]
            for dx, dy in sorted(ways, key=lambda v: abs(v[0]) + abs(v[1])):
                if abs(dx) + abs(dy) > SLIP:
                    break
                moved = r.move(dx, dy)
                if p.collides(moved, blocked):
                    continue
                beyond = moved.move(sign(dx) * SLIP, sign(dy) * SLIP)
                if p.collides(beyond, blocked):       # a gap: nudge in
                    p.rect = moved
                    break
            else:
                return
            if p.rect is r:
                return

    def launch(self, o, solids):
        p = self.player
        dx, dy = DIRS[o.d]
        v = o.power()
        p.dash_t = 0.0
        p.hanging = False
        p.jump_cut_ok = False
        p.cancel_hop()
        if dy < 0:
            p.stop_slide(solids)
        if dx:
            p.vx = dx * v
            p.vy = min(p.vy, -250)
            p.air_lock_t = AIR_LOCK
            p.facing = dx
        else:
            p.vy = dy * v
        if dy <= 0:
            p.on_ground = False
            p.coyote = 0.0
        p.dashes = MAX_DASHES
        if "BOUNCE" not in p.events:
            p.trick("BOUNCE", 3)

    def boost(self, o):
        p = self.player
        dx, dy = DIRS[o.d]
        v = o.power()
        if dx and (sign(p.vx) != dx or abs(p.vx) < v):
            p.vx = dx * v
            p.facing = dx
            if "BOOST" not in p.events:
                p.trick("BOOST")
        elif dy and (sign(p.vy) != dy or abs(p.vy) < v):
            p.vy = dy * v
            p.cancel_hop()
            if dy < 0:
                p.on_ground = False
            if "BOOST" not in p.events:
                p.trick("BOOST")

    # -- effects --------------------------------------------------------------
    def add_feed(self, text, colour):
        self.feed.append([text, 0.0, colour])

    def burst(self, pos, colour, n, speed):
        for _ in range(n):
            a = random.uniform(0, math.tau)
            s = random.uniform(0.3, 1) * speed
            life = random.uniform(0.25, 0.5)
            self.particles.append([pos[0], pos[1], math.cos(a) * s, math.sin(a) * s - 120,
                                   life, life, colour, random.choice((3, 4, 5))])

    def effects(self, dt):
        p = self.player
        accent = PALETTES[self.theme]["accent"]
        for name in p.events:
            self.add_feed(name, PLAYER_EMPTY)
            self.burst(p.rect.center, accent, 12, 360)
        if p.dashing and not self.was_dashing:
            self.burst(p.rect.center, PLAYER_DASH, 8, 260)
        self.was_dashing = p.dashing
        for f in self.feed:
            f[1] += dt
        self.feed = [f for f in self.feed[-5:] if f[1] < 2.5]
        if p.speed() > 650 or p.dashing:
            self.trail.append([p.rect.copy(), self.player_colour(), 0.0])
        for t in self.trail:
            t[2] += dt
        self.trail = [t for t in self.trail if t[2] < 0.18]
        for q in self.particles:
            q[0] += q[2] * dt
            q[1] += q[3] * dt
            q[3] += 900 * dt
            q[4] -= dt
        self.particles = [q for q in self.particles if q[4] > 0]

    def player_colour(self):
        p = self.player
        if p.dashing:
            return PLAYER_DASH
        return PLAYER_READY if p.dashes else PLAYER_EMPTY

    def draw(self, s, cam, fonts, hitboxes=False, alpha=1.0):
        draw_objects(s, cam, 1.0, self.objs, self.theme, self.clock, self, hitboxes, fonts)
        p = self.player
        bg = PALETTES[self.theme]["sky_bot"]
        for rect, col, age in self.trail:
            tint_rect(s, pixel_rect(rect, cam), col, int(140 * (1 - age / 0.18)))
        for x, y, vx, vy, life, mx, col, size in self.particles:
            pygame.draw.rect(s, mix(bg, col, life / mx),
                             (x - cam.x - size / 2, y - cam.y - size / 2, size, size))
        pr = pixel_rect(p.lerp_rect(alpha), cam)
        if self.freeze_t > 0 and int(self.freeze_t * 16) % 2:
            return                      # blink while respawning
        if hitboxes:
            pygame.draw.rect(s, self.player_colour(), pr)
            pygame.draw.rect(s, (60, 255, 120), pr, 1)
            info = (f"x {p.rect.x:.1f}  y {p.rect.y:.1f}   vx {p.vx:.0f}  vy {p.vy:.0f}"
                    f"   {p.rect.w:.0f}x{p.rect.h:.0f}")
            img = fonts.small.render(info, True, (60, 255, 120))
            s.blit(img, img.get_rect(midbottom=(pr.centerx, pr.top - 8)))
        else:
            pygame.draw.rect(s, INK, pr.inflate(4, 4))
            pygame.draw.rect(s, self.player_colour(), pr)


# --------------------------------------------------------------- drawing ---
_text_cache = {}


def text_image(font, text, width, colour):
    """A text block's words wrapped to `width`, with a shadow; cached, since
    it's drawn every frame."""
    key = (id(font), text, width, colour)
    img = _text_cache.get(key)
    if img:
        return img
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}" if line else word
        if line and font.size(trial)[0] > width:
            lines.append(line)
            line = word
        else:
            line = trial
    if line:
        lines.append(line)
    lh = font.get_height() + 2
    imgs = [font.render(l, True, colour) for l in lines] or [font.render("", True, colour)]
    img = pygame.Surface((max(i.get_width() for i in imgs) + 2, lh * len(imgs) + 2), pygame.SRCALPHA)
    for n, (l, im) in enumerate(zip(lines, imgs)):
        img.blit(font.render(l, True, INK), (2, n * lh + 2))
        img.blit(im, (0, n * lh))
    if len(_text_cache) > 300:
        _text_cache.clear()
    _text_cache[key] = img
    return img


def _fill_alpha(s, colour, rect, alpha):
    tint_rect(s, rect, colour, alpha)


def _span(lo, hi, step, vis_lo, vis_hi):
    """range(lo, hi, step) limited to what's on screen, keeping the pattern
    lined up with the block."""
    if lo < vis_lo:
        lo += (vis_lo - lo) // step * step
    return range(int(lo), int(min(hi, vis_hi + step)), step)


def _chevrons(s, colour, r, d, clock, n=None):
    """Arrows pointing direction d, drifting along it."""
    dx, dy = DIRS[d]
    size = max(4, min(r.w, r.h) * 0.35)
    length = r.w if dx else r.h
    gap = max(size * 2.2, 14)
    count = n or max(1, int(length // gap))
    off = (clock * 40) % gap if n is None else 0
    view = s.get_rect().inflate(size * 4, size * 4)
    for k in range(count):
        t = (k * gap + off + gap / 2) % max(length, 1)
        if dx:
            cx = r.left + (t if dx > 0 else length - t)
            cy = r.centery
        else:
            cx = r.centerx
            cy = r.top + (t if dy > 0 else length - t)
        if not view.collidepoint(cx, cy):
            continue
        tip = (cx + dx * size, cy + dy * size)
        a = (cx - dx * size * 0.2 + dy * size, cy - dy * size * 0.2 + dx * size)
        b = (cx - dx * size * 0.2 - dy * size, cy - dy * size * 0.2 - dx * size)
        pygame.draw.lines(s, colour, False, [a, tip, b], 3)


def draw_objects(s, cam, zoom, objs, theme, clock, run=None, hitboxes=False,
                 fonts=None, selected=None):
    pal = PALETTES[theme]
    w, h = s.get_size()
    screen = pygame.Rect(-8, -8, w + 16, h + 16)
    blink_a = int(clock / BLINK_TIME) % 2 == 0
    later = []

    def tr(r):
        # round each edge (not position and size separately) so blocks that
        # touch in the world touch on screen and sit exactly on grid lines
        left = round((r[0] - cam.x) * zoom)
        top = round((r[1] - cam.y) * zoom)
        right = round((r[0] + r[2] - cam.x) * zoom)
        bottom = round((r[1] + r[3] - cam.y) * zoom)
        return pygame.Rect(left, top, max(1, right - left), max(1, bottom - top))

    for layer in ("zone", "solid", "other"):
        for i, o in enumerate(objs):
            g = o.kind.group
            if (layer == "zone") != (g == "zone") or (layer == "solid") != (g == "solid"):
                continue
            t = o.t
            if t == "saw":
                later.append((i, o))
                continue
            rr = tr((o.x, o.y, o.w, o.h))
            if not rr.colliderect(screen):
                continue
            if hitboxes:
                later.append((i, o))
            on = run.on[i] if run else True
            if run is None and t in ("blinkA", "blinkB"):
                on = blink_a == (t == "blinkA")
            col = o.kind.colour
            cl = rr.clip(screen)
            if t == "wall":
                pygame.draw.rect(s, pal["struct"], cl)
                pygame.draw.rect(s, shade(pal["struct"], 0.75), rr, max(1, int(3 * zoom)))
                pygame.draw.rect(s, pal["top"], (cl.x, rr.top, cl.w, max(1, int(5 * zoom))))
            elif t == "kill":
                pygame.draw.rect(s, (120, 20, 40), cl)
                step = max(6, int(16 * zoom))
                for k in _span(rr.left, rr.right, step, screen.left, screen.right):
                    a, b = (k, rr.top), (min(k + step // 2, rr.right), rr.top + min(step // 2, rr.h))
                    pygame.draw.line(s, col, a, b, 2)
                    pygame.draw.line(s, col, b, (min(k + step, rr.right), rr.top), 2)
                pygame.draw.rect(s, col, rr, 2)
            elif t in ("bounce", "boost"):
                pygame.draw.rect(s, shade(col, 0.45), cl, border_radius=3)
                pygame.draw.rect(s, col, rr, 2, border_radius=3)
                _chevrons(s, col, rr, o.d, clock if t == "boost" else 0, None if t == "boost" else 1)
            elif t == "ice":
                pygame.draw.rect(s, col, cl)
                pygame.draw.rect(s, (255, 255, 255), (cl.x, rr.top, cl.w, max(1, int(4 * zoom))))
                for k in _span(rr.left + 6, rr.right - 6, max(12, int(40 * zoom)), screen.left - 40, screen.right):
                    pygame.draw.line(s, (140, 200, 235), (k, rr.top + 8 * zoom),
                                     (k + 10 * zoom, rr.bottom - 4 * zoom), 2)
            elif t == "oneway":
                pygame.draw.rect(s, col, (cl.x, rr.top, cl.w, max(2, int(5 * zoom))))
                for k in _span(rr.left, rr.right, max(6, int(12 * zoom)), screen.left, screen.right):
                    pygame.draw.line(s, shade(col, 0.6), (k, rr.top + 4 * zoom),
                                     (k, rr.bottom), 1)
            elif t == "crumble":
                if not on:
                    pygame.draw.rect(s, shade(col, 0.6), rr, 1)
                    continue
                shaking = run and run.timer[i] > 0
                r2 = rr.move(random.randint(-2, 2), 0) if shaking else rr
                pygame.draw.rect(s, col, r2.clip(screen))
                pygame.draw.rect(s, shade(col, 0.55), r2, 2)
                pygame.draw.lines(s, shade(col, 0.5), False,
                                  [(r2.left + r2.w * 0.2, r2.top), (r2.left + r2.w * 0.4, r2.centery),
                                   (r2.left + r2.w * 0.3, r2.bottom)], 2)
                pygame.draw.lines(s, shade(col, 0.5), False,
                                  [(r2.left + r2.w * 0.7, r2.top), (r2.left + r2.w * 0.6, r2.centery),
                                   (r2.left + r2.w * 0.8, r2.bottom)], 2)
            elif t in ("blinkA", "blinkB"):
                if on:
                    pygame.draw.rect(s, col, cl)
                    pygame.draw.rect(s, shade(col, 0.6), rr, 3)
                else:
                    _fill_alpha(s, col, rr, 40)
                    pygame.draw.rect(s, col, rr, 1)
            elif t == "gate":
                if on:
                    _fill_alpha(s, col, rr, 120)
                    pygame.draw.rect(s, col, rr, 2)
                    if fonts and zoom >= 0.5:
                        img = fonts.small.render(str(o.power()), True, INK)
                        s.blit(img, img.get_rect(center=rr.center))
                else:
                    pygame.draw.rect(s, shade(col, 0.5), rr, 1)
            elif t == "orb":
                c = rr.center
                bob = math.sin(clock * 4 + i) * 3 * zoom
                rad = rr.w / 2
                if on:
                    pts = [(c[0], c[1] - rad + bob), (c[0] + rad, c[1] + bob),
                           (c[0], c[1] + rad + bob), (c[0] - rad, c[1] + bob)]
                    pygame.draw.polygon(s, col, pts)
                    pygame.draw.polygon(s, (255, 255, 255), pts, 2)
                else:
                    pygame.draw.circle(s, shade(col, 0.5), c, rad * 0.5, 1)
            elif t in ("grav", "wind", "nodash"):
                _fill_alpha(s, col, rr, 38)
                pygame.draw.rect(s, shade(col, 0.8), rr, 1)
                if t == "wind":
                    _chevrons(s, mix(col, pal["sky_bot"], 0.4), rr.inflate(-8, -8), o.d,
                              clock * (1 + o.p), None)
                elif t == "grav":
                    up = o.power() < 1
                    for k in range(6):
                        px = rr.left + (k * 37 % 97) / 97 * rr.w
                        ph = ((clock * (0.3 if up else 0.8) + k * 0.17) % 1)
                        py = rr.bottom - ph * rr.h if up else rr.top + ph * rr.h
                        pygame.draw.circle(s, col, (px, py), max(2, 3 * zoom))
                else:
                    step = max(10, int(24 * zoom))
                    for k in _span(-rr.h, rr.w, step,
                                   screen.left - screen.bottom - rr.left + rr.top,
                                   screen.right - screen.top - rr.left + rr.top):
                        a = (rr.left + max(k, 0), rr.top + max(-k, 0))
                        L = min(rr.w - max(k, 0), rr.h - max(-k, 0))
                        pygame.draw.line(s, shade(col, 0.7), a, (a[0] + L, a[1] + L), 1)
            elif t == "check":
                active = run and run.checkpoint == i
                pole = (rr.left + 4 * zoom, rr.top, max(2, 4 * zoom), rr.h)
                pygame.draw.rect(s, INK, pole)
                fc = col if active else (140, 140, 160)
                pygame.draw.polygon(s, fc, [(rr.left + 8 * zoom, rr.top),
                                            (rr.right + 8 * zoom, rr.top + 10 * zoom),
                                            (rr.left + 8 * zoom, rr.top + 20 * zoom)])
            elif t == "start":
                if run is None:
                    pygame.draw.rect(s, col, rr, 2)
                    if fonts:
                        img = fonts.font.render("S", True, col)
                        s.blit(img, img.get_rect(center=rr.center))
            elif t == "text":
                if run is None:
                    pygame.draw.rect(s, shade(col, 0.6), rr, 1)
                if fonts and zoom >= 0.4:
                    font = fonts.font if zoom >= 0.75 else fonts.small
                    img = text_image(font, o.text or ("" if run else "(empty: select it and press Text)"),
                                     max(40, rr.w - 12), col if o.text else DIM)
                    s.blit(img, img.get_rect(center=rr.center))
            elif t == "finish":
                sq = max(4, int(8 * zoom))
                for yy in _span(rr.top, rr.bottom, sq, screen.top, screen.bottom):
                    for xx in _span(rr.left, rr.right, sq, screen.left, screen.right):
                        dark = ((xx - rr.left) // sq + (yy - rr.top) // sq) % 2
                        pygame.draw.rect(s, INK if dark else (255, 255, 255),
                                         (xx, yy, min(sq, rr.right - xx), min(sq, rr.bottom - yy)))
                pygame.draw.rect(s, GOLD, rr, 2)
            if selected is not None and i in selected:
                pygame.draw.rect(s, GOLD, rr.inflate(6, 6), 2)

    # saws on top, then hitbox outlines over everything
    for i, o in later:
        if o.t != "saw":
            continue
        if run is None:
            # editor: show the path it travels
            if o.path:
                pts = saw_points(o) + ([saw_points(o)[0]] if o.d % 2 else [])
            else:
                a = (o.x + o.w / 2, o.y + o.h / 2)
                rng = o.power()
                pts = [a, (a[0] + rng, a[1]) if o.d % 2 else (a[0], a[1] + rng)]
            scr = [((x - cam.x) * zoom, (y - cam.y) * zoom) for x, y in pts]
            pygame.draw.lines(s, (120, 120, 140), False, scr, 2)
            for pt in scr[1:]:
                pygame.draw.circle(s, (120, 120, 140), pt, 4)
        cx, cy = saw_center(o, clock)
        c = ((cx - cam.x) * zoom, (cy - cam.y) * zoom)
        rad = o.w / 2 * zoom
        if not screen.inflate(rad * 2, rad * 2).collidepoint(c):
            continue
        teeth = []
        for k in range(16):
            a = clock * 9 + k * math.tau / 16
            rr_ = rad * (1.0 if k % 2 == 0 else 0.72)
            teeth.append((c[0] + math.cos(a) * rr_, c[1] + math.sin(a) * rr_))
        pygame.draw.polygon(s, o.kind.colour, teeth)
        pygame.draw.circle(s, RED, c, rad * 0.35)
        if selected is not None and i in selected:
            pygame.draw.circle(s, GOLD, c, rad + 4, 2)
    if not hitboxes:
        return
    for i, o in later:
        g = o.kind.group
        if o.t == "saw":
            cx, cy = saw_center(o, clock)
            pygame.draw.circle(s, (255, 60, 60), ((cx - cam.x) * zoom, (cy - cam.y) * zoom),
                               o.w / 2 * zoom, 1)
            continue
        rr = tr((o.x, o.y, o.w, o.h))
        on = run.on[i] if run else True
        colour = {"solid": (255, 255, 255), "hazard": (255, 60, 60), "trigger": (255, 230, 60),
                  "zone": (180, 160, 255), "marker": (80, 230, 255)}[g]
        if g == "solid" and not on:
            colour = (110, 110, 130)
        pygame.draw.rect(s, colour, rr, 1)
        if fonts and zoom >= 0.75 and rr.w >= 30:
            img = fonts.small.render(f"{o.w:g}x{o.h:g}", True, colour)
            if img.get_width() < rr.w:
                s.blit(img, (rr.x + 3, rr.y + 2))


def level_info_line(o):
    """Short description of an object's settings for the editor."""
    k = o.kind
    bits = [k.name]
    if o.path:
        bits.append(f"custom path, {len(o.path) + 1} points, "
                    f"{'loop' if o.d % 2 else 'back and forth'}")
        bits.append(f"speed {o.power()} (power {o.p})")
    else:
        if k.dirs == 4:
            bits.append(DIR_NAMES[o.d])
        elif k.dirs == 2:
            bits.append("horizontal" if o.d % 2 else "vertical")
        if k.power:
            bits.append(f"{k.power[0]} {o.power():g} (power {o.p})")
    bits.append(f"{o.w:g}x{o.h:g} at {o.x:g}, {o.y:g}")
    return "   ".join(bits)


# ---------------------------------------------------------------- replays ---
REPLAY_KEYS = ("left", "right", "up", "down", "jump_held", "jump_pressed", "dash_pressed",
               "jump_w")


def input_mask(inp):
    return sum(1 << i for i, k in enumerate(REPLAY_KEYS) if getattr(inp, k))


def apply_mask(inp, mask):
    for i, k in enumerate(REPLAY_KEYS):
        setattr(inp, k, bool(mask >> i & 1))


def encode_replay(masks):
    """[mask per step] -> compact "mask*count,..." text."""
    out = []
    for m in masks:
        if out and out[-1][0] == m:
            out[-1][1] += 1
        else:
            out.append([m, 1])
    return ",".join(f"{m}*{n}" if n > 1 else str(m) for m, n in out)


REPLAY_STEPS = 120 * 60 * 60       # an hour of steps is plenty


def decode_replay(text):
    """Recordings come from other players, so anything malformed is
    skipped and the length is capped before any list is built."""
    masks = []
    for part in str(text).split(","):
        m, _, n = part.partition("*")
        try:
            m, n = int(m), int(n or 1)
        except ValueError:
            continue
        if not 0 <= m < 256 or n < 1:
            continue
        n = min(n, REPLAY_STEPS - len(masks))
        masks.extend([m] * n)
        if len(masks) >= REPLAY_STEPS:
            break
    return masks


__all__ = ["KINDS", "ORDER", "Obj", "Run", "dump", "load", "draw_objects", "fmt_time",
           "level_info_line", "DIRS", "saw_center"]
