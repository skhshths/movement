"""
=============================================================================
  VELOCITY  —  a high-speed movement game prototype (pygame-ce)
=============================================================================
You are a runner with a toolkit of speed tech, loose in a huge open world.
Chain maneuvers together to keep your momentum. A round minimap sits in
the bottom-right corner with all the stats around it. Runs on desktop and
in the browser (via pygbag).

CONTROLS
--------
  A / D  (or arrows)     run
  W / S                  aim dashes up / down
  SPACE  (or K)          jump
  SHIFT  (or J)          dash in the WASD direction (facing if none held)
  S on ground at speed   slide
  S in the air           fast fall
  R                      restart
  ESC                    quit

MANEUVERS
---------
  Omni Dash      Dash in any of 8 directions. One dash, refilled on landing.
  Slingshot      Dash down-and-diagonal into the floor from the air, then
                 IMMEDIATELY hold the opposite direction and jump: you are
                 launched the way you turned.
  Wavedash       Dash diagonally down into the floor: converts the dash into a
                 fast slide.
  Wave Jump      Jump out of a wavedash without turning around: long, flat
                 jump that keeps the slide speed.
  Slide          Hold S while running fast. Very low friction.
  Long Jump      Jump out of a slide: +15% speed, low arc.
  Bunny Hop      Jump within a few frames of landing while above run speed:
                 no ground friction, small speed bonus, chains.
  Dash Hop       Jump during a horizontal ground dash: huge, low leap.
  Ground Pound   Dash straight down into the floor.
  Pound Bounce   Jump right after a ground pound: very high vertical launch.
  Wall Kick      Hold toward a wall to slide down it; jump to kick off.
  Ricochet       Dash into a wall, then jump right away: bounce off it with
                 your dash speed and get your dash back.
  Wall Run       Dash diagonally up into a wall: sprint straight up it.
  Corner Whip    Rise past the top of a wall fast while holding toward it
                 (e.g. off a Wall Run): your upward speed is whipped
                 sideways over the corner.
  Ceiling Skim   Moving fast just under a ceiling holds you against it with
                 no gravity until you run out of ceiling. S lets go.
  Corner Wrap    Skim along the underside of a block (dash or skate just
                 under it), then press dash right as you pass its
                 outside corner: you swing around the corner and up its far
                 side in a big arc, keeping your momentum. Free: works even
                 with no dash left.
  Ledge Grab     Fall past a ledge while holding toward it to hang on it.
                 Refills your dash. S drops, away + jump wall kicks.
  Ledge Vault    Jump while hanging: spring up and over the ledge.
  Edge Jump      Run off a ledge and jump as LATE as possible (last few
                 frames before you'd fall): +25% speed.
  Ceiling Skate  Dash diagonally up into a ceiling: shoot along it at full
                 dash speed.
  Corner Boost   Hit a low lip at speed: pop up over it without losing speed.
  Momentum Roll  Land from a fast fall while holding S: your falling speed is
                 converted into a sprinting slide.
"""
import asyncio
import math
import random
import sys

import pygame

# ---------------------------------------------------------------- tuning ---
W, H = 1280, 720
FPS = 120
DT = 1 / FPS

GRAVITY = 2200
FAST_FALL_MULT = 1.7
MAX_FALL = 1400
RUN_SPEED = 420
GROUND_ACCEL = 3200
AIR_ACCEL = 1500
FRICTION = 3000            # stopping with no input
OVERSPEED_FRICTION = 900   # bleeding off speed above RUN_SPEED on the ground
JUMP_V = 780
COYOTE = 0.10
JUMP_BUFFER = 0.10

DASH_SPEED = 1100
DASH_TIME = 0.14
MAX_DASHES = 1

SLIDE_START = RUN_SPEED * 0.8
SLIDE_STOP = 180
SLIDE_FRICTION = 260
SLIDE_MIN_TIME = 0.30
LONGJUMP_VY = 560

BHOP_WINDOW = 0.07
BHOP_BONUS = 45

WAVEDASH_SPEED = 1000
SLING_WINDOW = 0.20
SLING_VX = 1350
SLING_VY = 820

POUND_WINDOW = 0.18
POUND_BOUNCE = 1250

HOP_VX = 1250
HOP_VY = 480

WALL_SLIDE_MAX = 220
WALLJUMP_X = 560
WALLJUMP_Y = 740

RICO_WINDOW = 0.15
RICO_VY = 700

WALLRUN_V = 1050

WHIP_MIN_VY = 400          # upward speed needed to whip over a corner
WHIP_CONVERT = 0.85        # share of upward speed turned sideways
WHIP_MIN_VX = 600
WHIP_VY = 260

CEIL_REACH = 24            # how close under a ceiling counts as hugging it
WRAP_WINDOW = 0.12         # time after passing the corner to press dash
WRAP_UP = 0.95             # share of speed sent upward
WRAP_FWD = 0.55            # share of speed kept forward

LEDGE_REACH = 14          # how far below a ledge top your head can catch it
LEDGE_VAULT_VX = 650
LEDGE_VAULT_VY = 640
REGRAB_TIME = 0.25

EDGE_WINDOW = 0.05         # last part of coyote time that counts as late
EDGE_BOOST = 1.25
SKATE_SPEED = 1150

CORNER_LIP = 22            # max lip height you can step / boost over
CORNER_POP = 380

ROLL_MIN_VY = 800
ROLL_CONVERT = 0.6         # share of falling speed turned into run speed

SHAKE_DECAY = 30           # shake pixels lost per second

MINIMAP_R = 100           # radius of the round minimap
MINIMAP_SCALE = 20         # world px per minimap px

# ---------------------------------------------------------------- colours --
BG = (14, 16, 26)
GRID = (26, 30, 46)
SOLID = (46, 52, 78)
SOLID_EDGE = (92, 104, 150)
PLAYER_READY = (90, 220, 255)
PLAYER_EMPTY = (255, 150, 70)
PLAYER_DASH = (255, 255, 255)
TEXT = (230, 234, 245)
DIM = (130, 138, 165)


def sign(v):
    return (v > 0) - (v < 0)


def approach(v, target, amount):
    if v < target:
        return min(v + amount, target)
    return max(v - amount, target)


# ------------------------------------------------------------------ level --
WORLD_W = 48000
WORLD_TOP = -3500
WORLD_BOTTOM = 2200
WORLD_SEED = 7


class World:
    """A big seeded world of terrain and structures, indexed by a grid so
    only nearby solids are checked or drawn."""
    CELL = 512

    def __init__(self, seed=WORLD_SEED):
        self.solids = []
        self.grounds = []       # (x0, x1, surface y)
        self.rng = random.Random(seed)
        self.generate()
        self.grid = {}
        for i, r in enumerate(self.solids):
            for cell in self.cells(r):
                self.grid.setdefault(cell, []).append(i)
        x0, x1, h = self.grounds[0]
        self.spawn = (x0 + 300, h)

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

    def add(self, x, y, w, h):
        self.solids.append(pygame.Rect(int(x), int(y), int(w), int(h)))

    def ground_at(self, x):
        for x0, x1, h in self.grounds:
            if x0 <= x < x1:
                return h
        return self.grounds[-1][2]

    # -- generation -----------------------------------------------------------
    def ground(self, x, w, h):
        self.add(x, h, w, WORLD_BOTTOM - h)
        self.grounds.append((x, x + w, h))
        return x + w

    def generate(self):
        rng = self.rng
        self.add(-40, WORLD_TOP, 40, WORLD_BOTTOM - WORLD_TOP)
        x, h = 0, 800
        x = self.ground(x, 1400, h)          # quiet spawn area
        while x < WORLD_W:
            kind = rng.choices(("flat", "step", "valley", "lips"),
                               (5, 4, 2, 1))[0]
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
            if kind == "step":
                h += rng.choice((-1, 1)) * rng.randrange(40, 200, 20)
                h = max(260, min(1300, h))
            w = rng.randrange(800, 2600, 20)
            self.decorate(x, x + w, h)
            x = self.ground(x, w, h)
        self.add(x, WORLD_TOP, 40, WORLD_BOTTOM - WORLD_TOP)
        self.sky_islands(x)

    def decorate(self, x0, x1, h):
        rng = self.rng
        cx = x0 + rng.randrange(150, 400)
        features = (self.hanging, self.pillar, self.tunnel, self.shaft,
                    self.stairs, self.tower)
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
        ph = self.rng.randrange(100, 260, 20)     # low enough to wall run over
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
            self.add(px, py, self.rng.randrange(100, 220, 10), 20)
        return px - x + 220

    def tower(self, x, h, room):
        w = self.rng.randrange(120, 260, 10)
        th = self.rng.randrange(500, 1300, 20)
        self.add(x, h - th, w, th - 60)              # slide under it
        side = 1
        y = h - self.rng.randrange(120, 200, 10)
        while y > h - th + 60:
            lx = x + w if side > 0 else x - 100
            self.add(lx, y, 100, 20)
            side = -side
            y -= self.rng.randrange(130, 220, 10)
        return w + 100

    def sky_islands(self, end):
        rng = self.rng
        sx = 2500
        while sx < end - 2000:
            gh = self.ground_at(sx)
            sy = gh - rng.randrange(600, 1700, 20)
            w = rng.randrange(400, 1400, 20)
            self.add(sx, sy, w, rng.randrange(30, 90, 10))
            if rng.random() < 0.5:                   # skim under it
                self.add(sx + w // 4, sy + 60, w // 2, 120)
            if rng.random() < 0.4:                   # tower on top
                tw = rng.randrange(80, 160, 10)
                th = rng.randrange(200, 600, 20)
                self.add(sx + w - tw - 40, sy - th, tw, th)
            # zigzag platforms up from the ground
            py, i = gh - 110, 0
            while py > sy + 60:
                self.add(sx - 360 + (i % 2) * 220, py, 140, 20)
                py -= rng.randrange(95, 120, 5)
                i += 1
            sx += w + rng.randrange(1500, 3500, 50)


# ----------------------------------------------------------------- input ---
class Input:
    def __init__(self):
        self.left = self.right = self.up = self.down = False
        self.jump_held = False
        self.jump_pressed = False
        self.dash_pressed = False

    def poll(self):
        k = pygame.key.get_pressed()
        self.left = k[pygame.K_a] or k[pygame.K_LEFT]
        self.right = k[pygame.K_d] or k[pygame.K_RIGHT]
        self.up = k[pygame.K_w] or k[pygame.K_UP]
        self.down = k[pygame.K_s] or k[pygame.K_DOWN]
        self.jump_held = k[pygame.K_SPACE] or k[pygame.K_k]


# ---------------------------------------------------------------- player ---
class Player:
    WIDTH, H_STAND, H_SLIDE = 32, 32, 18

    def __init__(self, spawn):
        self.spawn = spawn
        self.reset()

    def reset(self):
        self.rect = pygame.FRect(0, 0, self.WIDTH, self.H_STAND)
        self.rect.midbottom = self.spawn
        self.vx = self.vy = 0.0
        self.facing = 1
        self.mx = 0
        self.hold_down = False
        self.on_ground = False
        self.wall = 0
        self.wall_mem = 0
        self.dashes = MAX_DASHES
        self.hanging = False
        self.hang_dir = 0
        self.regrab_t = 0.0
        self.hugging = False
        self.wrap_t = 0.0
        self.wrap_dir = 0
        self.wrap_speed = 0.0
        self.dash_t = 0.0
        self.dash_dir = (0.0, 0.0)
        self.dash_from_air = False
        self.sliding = False
        self.slide_t = 0.0
        self.coyote = self.wall_coyote = self.jump_buf = self.land_t = 0.0
        self.sling_t = self.pound_t = self.rico_t = 0.0
        self.sling_dir = self.rico_dir = 0
        self.rico_speed = 0.0
        self.jump_cut_ok = False
        self.bhop_chain = 0
        self.events = []
        self.shake = 0.0

    @property
    def dashing(self):
        return self.dash_t > 0

    def speed(self):
        return math.hypot(self.vx, self.vy)

    def trick(self, name, shake=0.0):
        self.events.append(name)
        self.shake = max(self.shake, shake)

    # -- helpers ------------------------------------------------------------
    def collides(self, rect, solids):
        return any(rect.colliderect(s) for s in solids)

    def start_slide(self):
        if self.sliding:
            return
        bottom = self.rect.bottom
        self.rect.height = self.H_SLIDE
        self.rect.bottom = bottom
        self.sliding = True
        self.slide_t = 0.0

    def stop_slide(self, solids):
        if not self.sliding:
            return True
        tall = pygame.FRect(self.rect.x, self.rect.bottom - self.H_STAND,
                            self.WIDTH, self.H_STAND)
        if self.collides(tall, solids):
            return False      # no headroom, keep sliding
        self.rect = tall
        self.sliding = False
        return True

    def end_dash(self):
        self.dash_t = 0.0
        self.vx *= 0.75
        self.vy *= 0.45 if self.vy < 0 else 0.7

    # -- per-step update -----------------------------------------------------
    def update(self, dt, inp, solids):
        self.events = []
        for name in ("coyote", "wall_coyote", "jump_buf", "sling_t",
                     "pound_t", "rico_t", "regrab_t", "wrap_t"):
            setattr(self, name, max(0.0, getattr(self, name) - dt))
        self.shake = max(0.0, self.shake - SHAKE_DECAY * dt)
        if self.land_t > 0:
            self.land_t -= dt
            if self.land_t <= 0 and self.on_ground:
                self.bhop_chain = 0

        if inp.jump_pressed:
            self.jump_buf = JUMP_BUFFER
        mx = inp.right - inp.left
        my = inp.down - inp.up
        self.mx = mx
        self.hold_down = inp.down
        if mx and not self.dashing:
            self.facing = mx

        dash_pressed = inp.dash_pressed
        if dash_pressed and self.wrap_t > 0:
            s = max(self.wrap_speed, DASH_SPEED)
            self.vx = self.wrap_dir * s * WRAP_FWD
            self.vy = -s * WRAP_UP
            self.dash_t = self.wrap_t = 0.0
            self.jump_cut_ok = False
            dash_pressed = False
            self.trick("CORNER WRAP", 4)

        # dash start
        if dash_pressed and self.dashes > 0 and not self.dashing:
            dx, dy = mx, my
            if dx == 0 and dy == 0:
                dx = self.facing
            if dy < 0 or not self.on_ground or dx == 0:
                self.stop_slide(solids)
            n = math.hypot(dx, dy)
            self.dash_dir = (dx / n, dy / n)
            self.dash_t = DASH_TIME
            self.dashes -= 1
            self.dash_from_air = not self.on_ground
            self.jump_cut_ok = False
            self.hanging = False

        if self.dashing:
            self.vx = self.dash_dir[0] * DASH_SPEED
            self.vy = self.dash_dir[1] * DASH_SPEED
            self.dash_t -= dt
            if self.dash_t <= 0:
                self.end_dash()
        elif self.hanging:
            self.vx = self.vy = 0.0
            if inp.down:
                self.hanging = False
                self.regrab_t = REGRAB_TIME
        else:
            self.horizontal(dt, mx, inp, solids)
            g = GRAVITY
            if inp.down and not self.on_ground and self.vy > 0:
                g *= FAST_FALL_MULT
            self.vy = min(self.vy + g * dt, MAX_FALL * (1.4 if inp.down else 1))
            if self.hugging and not inp.down and self.vy > 0:
                self.vy = 0.0   # skim along the underside of a ceiling
            if self.wall and mx == self.wall and self.vy > WALL_SLIDE_MAX \
                    and not inp.down:
                self.vy = WALL_SLIDE_MAX
            if self.jump_cut_ok and not inp.jump_held and self.vy < 0:
                self.vy *= 0.5
                self.jump_cut_ok = False

        if self.jump_buf > 0:
            self.try_jump(mx, solids)

        prev_wall = self.wall
        self.move(dt, solids)
        if not self.on_ground:
            self.corner_whip(prev_wall, mx, solids)
            self.ledge_grab(mx, solids)
        self.track_ceiling(solids)

        if self.on_ground:
            self.coyote = COYOTE
            self.hanging = False
            if not self.dashing:
                self.dashes = MAX_DASHES
            if (inp.down and abs(self.vx) > SLIDE_START and not self.dashing
                    and not self.sliding):
                self.start_slide()
                self.trick("SLIDE")
        if self.wall and not self.on_ground:
            self.wall_coyote = COYOTE
            self.wall_mem = self.wall

    def horizontal(self, dt, mx, inp, solids):
        if self.sliding:
            self.slide_t += dt
            self.vx = approach(self.vx, 0, SLIDE_FRICTION * dt)
            if (abs(self.vx) < SLIDE_STOP or not self.on_ground
                    or (not inp.down and self.slide_t > SLIDE_MIN_TIME)):
                self.stop_slide(solids)
            return
        target = mx * RUN_SPEED
        if self.on_ground:
            if mx and (abs(self.vx) < RUN_SPEED or sign(self.vx) != mx):
                self.vx = approach(self.vx, target, GROUND_ACCEL * dt)
            elif self.land_t <= 0:      # bhop window: no friction
                fr = OVERSPEED_FRICTION if mx else FRICTION
                self.vx = approach(self.vx, target, fr * dt)
        elif mx and (abs(self.vx) < RUN_SPEED or sign(self.vx) != mx):
            self.vx = approach(self.vx, target, AIR_ACCEL * dt)

    def try_jump(self, mx, solids):
        grounded = self.on_ground or self.coyote > 0
        name, shake = None, 0.0
        if self.hanging:
            self.hanging = False
            self.regrab_t = REGRAB_TIME
            if mx == -self.hang_dir:
                self.vx = mx * WALLJUMP_X
                self.vy = -WALLJUMP_Y
                name = "WALL KICK"
            else:
                self.vx = self.hang_dir * LEDGE_VAULT_VX
                self.vy = -LEDGE_VAULT_VY
                name, shake = "LEDGE VAULT", 2
            self.facing = sign(self.vx)
        elif self.sling_t > 0 and mx == -self.sling_dir:
            self.vx, self.vy = mx * SLING_VX, -SLING_VY
            self.facing = mx
            name, shake = "SLINGSHOT", 6
        elif self.pound_t > 0:
            self.vy = -POUND_BOUNCE
            name, shake = "POUND BOUNCE", 5
        elif self.rico_t > 0:
            self.vx = -self.rico_dir * max(self.rico_speed * 1.05, 700)
            self.vy = -RICO_VY
            self.facing = -self.rico_dir
            self.dashes = MAX_DASHES
            name, shake = "RICOCHET", 4
        elif (self.dashing and self.on_ground and self.dash_dir[1] == 0):
            d = sign(self.dash_dir[0])
            self.vx, self.vy = d * HOP_VX, -HOP_VY
            self.dashes = MAX_DASHES
            name, shake = "DASH HOP", 3
        elif grounded:
            if self.sliding:
                d = sign(self.vx) or self.facing
                spd = abs(self.vx)
                self.vx = d * max(spd * 1.15, spd + 120)
                self.vy = -LONGJUMP_VY
                name = "WAVE JUMP" if self.sling_t > 0 else "LONG JUMP"
            elif (not self.on_ground and self.coyote <= EDGE_WINDOW
                    and abs(self.vx) > RUN_SPEED * 0.9):
                spd = abs(self.vx)
                self.vx = sign(self.vx) * max(spd * EDGE_BOOST, spd + 150)
                self.vy = -JUMP_V
                self.jump_cut_ok = True
                name, shake = "EDGE JUMP", 2
            elif self.land_t > 0 and abs(self.vx) > RUN_SPEED * 1.05:
                self.bhop_chain += 1
                self.vx += sign(self.vx) * BHOP_BONUS
                self.vy = -JUMP_V
                name = f"BUNNY HOP x{self.bhop_chain}"
            else:
                self.vy = -JUMP_V
                self.jump_cut_ok = True
        elif self.wall_coyote > 0:
            self.vx = -self.wall_mem * max(WALLJUMP_X, abs(self.vx))
            self.vy = -WALLJUMP_Y
            self.facing = -self.wall_mem
            self.jump_cut_ok = True
            name = "WALL KICK"
        else:
            return
        if self.sliding and not self.stop_slide(solids):
            self.vy = max(self.vy, 0)  # can't stand up: cancel the jump
            return
        self.dash_t = 0.0
        self.jump_buf = self.coyote = self.wall_coyote = 0.0
        self.sling_t = self.pound_t = self.rico_t = self.land_t = 0.0
        self.on_ground = False
        if name:
            self.trick(name, shake)

    def move(self, dt, solids):
        # horizontal
        self.rect.x += self.vx * dt
        for s in solids:
            if not self.rect.colliderect(s):
                continue
            if self.step_up(s, solids):
                continue
            if self.vx > 0:
                self.rect.right = s.left
                self.hit_wall(1)
            elif self.vx < 0:
                self.rect.left = s.right
                self.hit_wall(-1)
        self.wall = 0
        for side in (-1, 1):
            if self.collides(self.rect.move(side * 2, 0), solids):
                self.wall = side

        # vertical
        was_ground = self.on_ground
        self.rect.y += self.vy * dt
        for s in solids:
            if self.rect.colliderect(s):
                if self.vy > 0:
                    self.rect.bottom = s.top
                    self.hit_floor()
                elif self.vy < 0:
                    self.rect.top = s.bottom
                    self.hit_ceiling()
        self.on_ground = (self.vy >= 0 and
                          self.collides(self.rect.move(0, 1), solids))
        if self.on_ground and not was_ground:
            self.land_t = BHOP_WINDOW

    def corner_whip(self, prev_wall, mx, solids):
        # was on a wall, now risen just above its top while holding toward it
        if (prev_wall and not self.wall and mx == prev_wall
                and self.vy < -WHIP_MIN_VY and self.regrab_t <= 0
                and self.collides(self.rect.move(prev_wall * 2, 12), solids)):
            self.vx = prev_wall * max(-self.vy * WHIP_CONVERT, WHIP_MIN_VX)
            self.vy = -WHIP_VY
            self.dash_t = 0.0
            self.trick("CORNER WHIP", 3)

    def track_ceiling(self, solids):
        # opens the corner wrap window when you fly out from under a block
        d = sign(self.vx)
        hug = (not self.on_ground and abs(self.vx) > RUN_SPEED and
               self.collides(self.rect.move(0, -CEIL_REACH), solids))
        if (self.hugging and not hug and d and not self.on_ground and
                self.collides(self.rect.move(-d * 20, -CEIL_REACH), solids)):
            self.wrap_t = WRAP_WINDOW
            self.wrap_dir = d
            self.wrap_speed = abs(self.vx)
        self.hugging = hug

    def ledge_grab(self, mx, solids):
        if (self.hanging or self.dashing or self.sliding or not self.wall
                or mx != self.wall or self.vy < 0 or self.regrab_t > 0):
            return
        probe = self.rect.move(self.wall * 2, 0)
        for s in solids:
            if not probe.colliderect(s):
                continue
            if not 0 <= self.rect.top - s.top <= LEDGE_REACH:
                continue
            hang = self.rect.copy()
            hang.top = s.top
            x = s.left if self.wall > 0 else s.right - self.WIDTH
            stand = pygame.FRect(x, s.top - self.H_STAND,
                                 self.WIDTH, self.H_STAND)
            if self.collides(hang, solids) or self.collides(stand, solids):
                continue
            self.rect = hang
            self.hanging = True
            self.hang_dir = self.wall
            self.vx = self.vy = 0.0
            self.dashes = MAX_DASHES
            self.trick("LEDGE GRAB")
            return

    def step_up(self, s, solids):
        lip = self.rect.bottom - s.top
        if not self.vx or not 0 < lip <= CORNER_LIP:
            return False
        stepped = self.rect.copy()
        stepped.bottom = s.top
        if self.collides(stepped, solids):
            return False
        self.rect = stepped
        if abs(self.vx) > RUN_SPEED * 1.2:
            self.vy = min(self.vy, -CORNER_POP)
            self.dash_t = 0.0
            self.trick("CORNER BOOST", 2)
        return True

    def hit_wall(self, side):
        if self.dashing and sign(self.dash_dir[0]) == side:
            self.dash_t = 0.0
            if self.dash_dir[1] < 0:
                self.vy = -WALLRUN_V
                self.trick("WALL RUN", 2)
            else:
                self.rico_t = RICO_WINDOW
                self.rico_dir = side
                self.rico_speed = abs(self.vx)
        self.vx = 0

    def hit_ceiling(self):
        if self.dashing and self.dash_dir[0]:
            self.vx = sign(self.dash_dir[0]) * SKATE_SPEED
            self.trick("CEILING SKATE", 2)
        self.dash_t = 0.0
        self.vy = 0

    def hit_floor(self):
        if self.dashing and self.dash_dir[1] > 0:
            d = sign(self.dash_dir[0])
            self.dash_t = 0.0
            if d:
                self.vx = d * WAVEDASH_SPEED
                self.start_slide()
                if self.dash_from_air:
                    self.sling_t = SLING_WINDOW
                    self.sling_dir = d
                self.trick("WAVEDASH", 2)
            else:
                self.vx = 0
                self.pound_t = POUND_WINDOW
                self.trick("GROUND POUND", 7)
        elif self.vy > ROLL_MIN_VY and self.hold_down and not self.dashing:
            d = self.mx or sign(self.vx) or self.facing
            keep = abs(self.vx) if sign(self.vx) == d else 0
            self.vx = d * (max(keep, RUN_SPEED) + self.vy * ROLL_CONVERT)
            self.start_slide()
            self.trick("MOMENTUM ROLL", 3)
        self.vy = 0


# ------------------------------------------------------------------ game ---
class Game:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((W, H))
        pygame.display.set_caption("VELOCITY")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.Font(None, 24)
        self.big = pygame.font.Font(None, 56)
        self.inp = Input()
        self.world = World()
        self.player = Player(self.world.spawn)
        self.cam = pygame.Vector2()
        self.feed = []          # [name, age]
        self.trail = []         # [rect, colour, age]
        self.minimap = self.render_minimap()
        self.restart()

    def restart(self):
        self.player.reset()
        self.feed.clear()
        self.trail.clear()

    def render_minimap(self):
        # whole world at minimap scale, padded so any view window fits
        sc = MINIMAP_SCALE
        pad = MINIMAP_R * 2
        self.mm_origin = (-pad * sc - 100, WORLD_TOP - pad * sc)
        size = ((WORLD_W + 400) // sc + pad * 2,
                (WORLD_BOTTOM - WORLD_TOP) // sc + pad * 2)
        mm = pygame.Surface(size)
        mm.fill(BG)
        ox, oy = self.mm_origin
        for r in self.world.solids:
            pygame.draw.rect(mm, SOLID_EDGE, ((r.x - ox) // sc, (r.y - oy) // sc,
                                              max(1, r.w // sc), max(1, r.h // sc)))
        r = MINIMAP_R
        self.mm_mask = pygame.Surface((2 * r, 2 * r), pygame.SRCALPHA)
        pygame.draw.circle(self.mm_mask, (255, 255, 255, 255), (r, r), r)
        return mm

    async def run(self):
        acc = 0.0
        while True:
            acc += min(self.clock.tick(FPS) / 1000, 0.1)
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    return
                if e.type == pygame.KEYDOWN:
                    if e.key == pygame.K_ESCAPE and sys.platform != "emscripten":
                        return
                    if e.key == pygame.K_r:
                        self.restart()
                    if e.key in (pygame.K_SPACE, pygame.K_k):
                        self.inp.jump_pressed = True
                    if e.key in (pygame.K_LSHIFT, pygame.K_RSHIFT,
                                 pygame.K_j):
                        self.inp.dash_pressed = True
            self.inp.poll()
            while acc >= DT:
                self.step(DT)
                self.inp.jump_pressed = self.inp.dash_pressed = False
                acc -= DT
            self.draw()
            await asyncio.sleep(0)   # hands control to the browser each frame

    def step(self, dt):
        p = self.player
        p.update(dt, self.inp, self.world.query(p.rect.inflate(400, 400)))
        for name in p.events:
            self.feed.append([name, 0.0])
        self.feed = [f for f in self.feed[-6:] if f[1] < 2.5]
        for f in self.feed:
            f[1] += dt

        if p.rect.top > WORLD_BOTTOM:
            self.restart()

        if p.speed() > 650 or p.dashing:
            self.trail.append([p.rect.copy(), self.player_colour(), 0.0])
        for t in self.trail:
            t[2] += dt
        self.trail = [t for t in self.trail if t[2] < 0.18]

        self.cam = pygame.Vector2(p.rect.center) - (W / 2, H / 2)

    def player_colour(self):
        p = self.player
        if p.dashing:
            return PLAYER_DASH
        return PLAYER_READY if p.dashes else PLAYER_EMPTY

    # -- drawing ------------------------------------------------------------
    def draw(self):
        s = self.screen
        p = self.player
        s.fill(BG)
        shake = pygame.Vector2()
        if p.shake > 0:
            t = pygame.time.get_ticks()
            shake.update(math.sin(t * 0.09) * p.shake, math.cos(t * 0.11) * p.shake)
        cam = self.cam + shake

        # parallax grid
        gap = 80
        ox, oy = (-cam.x * 0.5) % gap, (-cam.y * 0.5) % gap
        for x in range(int(ox) - gap, W + gap, gap):
            pygame.draw.line(s, GRID, (x, 0), (x, H))
        for y in range(int(oy) - gap, H + gap, gap):
            pygame.draw.line(s, GRID, (0, y), (W, y))

        view = pygame.Rect(cam.x, cam.y, W, H)
        for r in self.world.query(view):
            rr = r.move(-cam.x, -cam.y).clip(s.get_rect().inflate(8, 8))
            pygame.draw.rect(s, SOLID, rr)
            pygame.draw.rect(s, SOLID_EDGE, rr, 2)

        for rect, col, age in self.trail:
            a = int(140 * (1 - age / 0.18))
            surf = pygame.Surface(rect.size, pygame.SRCALPHA)
            surf.fill((*col, a))
            s.blit(surf, (rect.x - cam.x, rect.y - cam.y))

        pr = p.rect.move(-cam.x, -cam.y)
        pygame.draw.rect(s, self.player_colour(), pr)

        self.draw_hud()
        pygame.display.flip()

    def draw_hud(self):
        # everything lives in one cluster around the round minimap
        s = self.screen
        p = self.player
        sc = MINIMAP_SCALE
        r = MINIMAP_R
        cx, cy = W - r - 24, H - r - 24

        # round minimap: cut a square window out, mask it to a circle
        ox, oy = self.mm_origin
        px = (p.rect.centerx - ox) / sc
        py = (p.rect.centery - oy) / sc
        disc = pygame.Surface((2 * r, 2 * r), pygame.SRCALPHA)
        disc.blit(self.minimap, (0, 0), (px - r, py - r, 2 * r, 2 * r))
        view = pygame.Rect(0, 0, W / sc, H / sc)
        view.center = (r, r)
        pygame.draw.rect(disc, DIM, view, 1)
        disc.blit(self.mm_mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        s.blit(disc, (cx - r, cy - r))
        pygame.draw.circle(s, self.player_colour(), (cx, cy), 3)
        pygame.draw.circle(s, SOLID_EDGE, (cx, cy), r, 2)

        # speed gauge: an arc around the rim, filling clockwise from the left
        spd = p.speed()
        frac = min(1, spd / 1500)
        ring = pygame.Rect(0, 0, 2 * r + 20, 2 * r + 20)
        ring.center = (cx, cy)
        pygame.draw.arc(s, GRID, ring, math.pi / 2, math.pi * 1.5, 6)
        if frac > 0:
            pygame.draw.arc(s, PLAYER_READY if frac < 0.66 else PLAYER_EMPTY,
                            ring, math.pi * 1.5 - math.pi * frac,
                            math.pi * 1.5, 6)

        # speed readout and dash pips to the left of the map
        num = self.big.render(f"{spd:.0f}", True, TEXT)
        lab = self.font.render("SPEED", True, DIM)
        right = cx - r - 26
        s.blit(num, (right - num.get_width(), cy - num.get_height() + 4))
        s.blit(lab, (right - lab.get_width(), cy + 8))
        for i in range(MAX_DASHES):
            col = PLAYER_READY if i < p.dashes else GRID
            pygame.draw.circle(s, col, (right - 7 - i * 20, cy + 44), 7)

        # trick feed stacked above the map, newest at the bottom and biggest
        y = cy - r - 22
        for i, (name, age) in enumerate(reversed(self.feed)):
            fade = max(0, 1 - age / 2.5)
            base = PLAYER_EMPTY if i == 0 and age < 0.6 else TEXT
            col = tuple(int(c * fade + b * (1 - fade)) for c, b in zip(base, BG))
            img = (self.big if i == 0 else self.font).render(name, True, col)
            y -= img.get_height() + 2
            s.blit(img, (W - img.get_width() - 24, y))


async def main():
    await Game().run()
    pygame.quit()


if __name__ == "__main__":
    asyncio.run(main())
