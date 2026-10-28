"""
Player movement for VELOCITY: input state, tuning and every maneuver.

CONTROLS
--------
  A / D  (or arrows)     run
  W / S                  aim dashes up / down
  SPACE  (or K)          jump
  SHIFT  (or J)          dash in the WASD direction (facing if none held)
  S on ground at speed   slide
  S in the air           fast fall
  E                      talk / advance dialogue
  R                      respawn at the last town
  ESC                    quit

MANEUVERS
---------
  Omni Dash      Dash in any of 8 directions. One dash, refilled on landing.
  Slingshot      Dash down-and-diagonal into the floor from the air, then
                 IMMEDIATELY hold the opposite direction and jump: you are
                 launched the way you turned.
  Slingshot Slam Right after a slingshot, dash down: you slam straight back
                 onto the floor keeping all your sideways speed, sliding.
  Flip Launch    Running fast on the ground, dash up and AWAY (back the way
                 you came): you're thrown that way, harder the faster you
                 were going.
  Wavedash       Dash diagonally down into the floor: converts the dash into a
                 fast slide.
  Wave Jump      Jump out of a wavedash without turning around: long, flat
                 jump that keeps the slide speed.
  Slide          Hold S while running fast. Very low friction.

  Tap Hop        Tap jump quickly: you hop exactly your own height, so your
                 feet land where your head was. Hold it for a full jump.

  Plain WASD movement is exact on the ground and in the air: full speed
  instantly, a dead stop when you let go, instant turns. Only speed beyond a
  run, which comes from moves, carries momentum and drifts.
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

  Corner correction: clip the corner of a gap or ceiling by a few pixels and
  you're nudged around it, so you can thread gaps exactly as wide (or tall)
  as yourself without being pixel perfect. Landing on a ledge's edge still
  counts as landing.
"""
import math

import pygame

FPS = 120
DT = 1 / FPS


GRAVITY = 2200
FAST_FALL_MULT = 1.7
MAX_FALL = 1400
RUN_SPEED = 420
GROUND_ACCEL = 3200
AIR_ACCEL = 1500            # turning against momentum in the air
FRICTION = 3000            # momentum bleeding off with no input
AIR_LOCK = 0.15            # air control ignored this long after a kick-off
OVERSPEED_FRICTION = 900   # bleeding off speed above RUN_SPEED on the ground
JUMP_V = 780
TAP_HOP = 32               # a quick tap of jump rises exactly this (the player's height)
TAP_TIME = 0.07            # released within this it's a tap; held longer, a full jump
# full jump height, kept exactly as it was before the tap hop (fixed-step peak)
FULL_JUMP = JUMP_V ** 2 / (2 * GRAVITY) + JUMP_V * DT / 2
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
SLIP = 8                   # corner correction: how far you get nudged into a gap
CORNER_POP = 380

ROLL_MIN_VY = 800
ROLL_CONVERT = 0.6         # share of falling speed turned into run speed

FLIP_MIN_SPEED = RUN_SPEED * 1.3   # ground speed needed for a flip launch
FLIP_X = 1.0               # share of ground speed thrown the other way
FLIP_Y = 0.75              # share of ground speed thrown upward
FLIP_BASE_VY = 200

SLAM_WINDOW = 0.25         # time after a slingshot to slam back down
SLAM_REACH = 240           # how far below you the floor can be

SHAKE_DECAY = 30           # shake pixels lost per second

ICE_ACCEL = 520            # how quickly you can change speed on ice



def sign(v):
    return (v > 0) - (v < 0)


def launch_speed(height, g, dt):
    """Upward speed that peaks `height` above where it's set, for this
    fixed-step integration (the step it's set in moves without gravity)."""
    a = g * dt / 2
    return -a + math.sqrt(a * a + 2 * g * height)


def approach(v, target, amount):
    if v < target:
        return min(v + amount, target)
    return max(v - amount, target)




# ----------------------------------------------------------------- input ---
class Input:
    def __init__(self):
        self.left = self.right = self.up = self.down = False
        self.jump_held = False
        self.jump_pressed = False
        self.dash_pressed = False
        self.interact_pressed = False

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
        self.prev = (self.rect.x, self.rect.y)   # position one step ago, for smooth drawing
        self.vx = self.vy = 0.0
        self.facing = 1
        self.mx = 0
        self.hold_down = False
        self.on_ground = False
        self.wall = 0
        self.wall_mem = 0
        self.dashes = MAX_DASHES
        self.hanging = False
        self.air_lock_t = 0.0
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
        self.sling_t = self.pound_t = self.rico_t = self.slam_t = 0.0
        self.sling_dir = self.rico_dir = 0
        self.rico_speed = 0.0
        self.jump_cut_ok = False
        self.cancel_hop()
        self.bhop_chain = 0
        self.events = []
        self.shake = 0.0
        # set every step by level blocks and zones (see levels.py)
        self.grav_mul = 1.0
        self.push = 0.0            # sideways wind, px/s
        self.lift = 0.0            # upward wind, px/s^2
        self.on_ice = False
        self.dash_lock = False

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
    def cancel_hop(self):
        self.hop_t = 0.0           # time left to decide tap or full jump
        self.hop_lock = False      # tapped: stop at exactly TAP_HOP
        self.hop_base = 0.0        # feet height at take-off

    def gravity(self):
        return GRAVITY * self.grav_mul - self.lift

    def lerp_rect(self, alpha):
        """Where to draw the player between the last two physics steps,
        so motion is smooth at any display refresh rate."""
        x0, y0 = self.prev
        r = self.rect.copy()
        r.x = x0 + (r.x - x0) * alpha
        r.y = y0 + (r.y - y0) * alpha
        return r

    def update(self, dt, inp, solids):
        self.events = []
        self.prev = (self.rect.x, self.rect.y)
        for name in ("coyote", "wall_coyote", "jump_buf", "sling_t",
                     "pound_t", "rico_t", "regrab_t", "wrap_t", "slam_t",
                     "air_lock_t"):
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

        if dash_pressed and self.slam_t > 0 and my > 0:
            dash_pressed = not self.slingshot_slam(solids)

        # dash start
        if dash_pressed and self.dashes > 0 and not self.dashing and not self.dash_lock:
            dx, dy = mx, my
            if dx == 0 and dy == 0:
                dx = self.facing
            if dy < 0 or not self.on_ground or dx == 0:
                self.stop_slide(solids)
            if (self.on_ground and dy < 0 and dx and dx == -sign(self.vx)
                    and abs(self.vx) >= FLIP_MIN_SPEED):
                self.flip_launch(dx, solids)
            else:
                n = math.hypot(dx, dy)
                self.dash_dir = (dx / n, dy / n)
                self.dash_t = DASH_TIME
                self.dashes -= 1
                self.dash_from_air = not self.on_ground
                self.jump_cut_ok = False
                self.cancel_hop()
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
            g = GRAVITY * self.grav_mul
            if inp.down and not self.on_ground and self.vy > 0:
                g *= FAST_FALL_MULT
            self.vy = min(self.vy + (g - self.lift) * dt,
                          MAX_FALL * (1.4 if inp.down else 1))
            if self.hugging and not inp.down and self.vy > 0:
                self.vy = 0.0   # skim along the underside of a ceiling
            if self.wall and mx == self.wall and self.vy > WALL_SLIDE_MAX \
                    and not inp.down:
                self.vy = WALL_SLIDE_MAX
            if self.hop_t > 0:
                self.hop_t -= dt
                if not inp.jump_held:
                    # a tap: finish the hop at exactly one player height
                    self.hop_t = 0.0
                    self.hop_lock = True
                elif self.hop_t <= 0:
                    # held: carry on into a full jump, as high as ever
                    # (speeds are worked out for normal gravity, so gravity
                    # and wind zones still change how high you go)
                    risen = self.hop_base - self.rect.bottom
                    self.vy = -launch_speed(max(0.0, FULL_JUMP - risen), GRAVITY, dt)
                    self.jump_cut_ok = True
            if self.jump_cut_ok and not inp.jump_held and self.vy < 0:
                self.vy *= 0.5
                self.jump_cut_ok = False

        if self.jump_buf > 0:
            self.try_jump(mx, solids)

        prev_wall = self.wall
        self.move(dt, solids)
        if self.hop_lock:
            self.hop_apex(solids)
        if not self.on_ground:
            self.corner_whip(prev_wall, mx, solids)
            self.ledge_grab(mx, solids)
        self.track_ceiling(solids)

        if self.on_ground:
            self.coyote = COYOTE
            self.hanging = False
            if self.vy >= 0:
                self.cancel_hop()
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
        if not self.on_ground and self.air_lock_t > 0:
            return                       # just kicked off a wall
        target = mx * RUN_SPEED + self.push
        if self.on_ground and self.on_ice:
            self.vx = approach(self.vx, target, ICE_ACCEL * dt)
            return
        if abs(self.vx - self.push) <= RUN_SPEED:
            # plain WASD movement is exact, on the ground and in the air:
            # full speed instantly, dead stop on release, instant turns
            self.vx = target
            return
        # faster than running means momentum from a move: it carries
        d = sign(self.vx - self.push)
        if self.on_ground:
            if mx and mx != d:
                self.vx = approach(self.vx, target, GROUND_ACCEL * dt)
            elif self.land_t <= 0:      # bhop window: no friction
                fr = OVERSPEED_FRICTION if mx else FRICTION
                self.vx = approach(self.vx, target, fr * dt)
        elif mx and mx != d:
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
                self.air_lock_t = AIR_LOCK
            else:
                self.vx = self.hang_dir * LEDGE_VAULT_VX
                self.vy = -LEDGE_VAULT_VY
                name, shake = "LEDGE VAULT", 2
            self.facing = sign(self.vx)
        elif self.sling_t > 0 and mx == -self.sling_dir:
            self.vx, self.vy = mx * SLING_VX, -SLING_VY
            self.facing = mx
            self.slam_t = SLAM_WINDOW
            name, shake = "SLINGSHOT", 6
        elif self.pound_t > 0:
            self.vy = -POUND_BOUNCE
            name, shake = "POUND BOUNCE", 5
        elif self.rico_t > 0:
            self.vx = -self.rico_dir * max(self.rico_speed * 1.05, 700)
            self.vy = -RICO_VY
            self.facing = -self.rico_dir
            self.dashes = MAX_DASHES
            self.air_lock_t = AIR_LOCK
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
            elif self.gravity() == GRAVITY:
                # starts as the tap hop; still held after TAP_TIME it
                # turns into the full jump (see update). Inside gravity and
                # wind zones jumps work as they always did.
                self.vy = -launch_speed(TAP_HOP, GRAVITY, DT)
                self.hop_t = TAP_TIME
                self.hop_base = self.rect.bottom
                self.hop_lock = False
                self.jump_cut_ok = False
            else:
                self.vy = -JUMP_V
                self.jump_cut_ok = True
        elif self.wall_coyote > 0:
            self.vx = -self.wall_mem * max(WALLJUMP_X, abs(self.vx))
            self.vy = -WALLJUMP_Y
            self.facing = -self.wall_mem
            self.jump_cut_ok = True
            self.air_lock_t = AIR_LOCK
            name = "WALL KICK"
        else:
            return
        if self.sliding and not self.stop_slide(solids):
            self.vy = max(self.vy, 0)  # can't stand up: cancel the jump
            return
        self.dash_t = 0.0
        if name:
            self.cancel_hop()          # any other jump replaces a hop
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
            if self.step_up(s, solids) or self.slip_under(s, solids):
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
                if self.vy and self.slip_past(s, solids):
                    continue
                if self.vy > 0:
                    self.rect.bottom = s.top
                    self.hit_floor()
                elif self.vy < 0:
                    self.rect.top = s.bottom
                    self.hit_ceiling()
                    self.cancel_hop()
        self.on_ground = (self.vy >= 0 and
                          self.collides(self.rect.move(0, 1), solids))
        if self.on_ground and not was_ground:
            self.land_t = BHOP_WINDOW

    def flip_launch(self, d, solids):
        # dash up and back while running fast: thrown that way, scaled by
        # how fast you were going
        spd = abs(self.vx)
        self.stop_slide(solids)
        self.vx = d * spd * FLIP_X
        self.vy = -(FLIP_BASE_VY + spd * FLIP_Y)
        self.dashes -= 1
        self.facing = d
        self.on_ground = False
        self.jump_cut_ok = False
        self.coyote = 0.0
        self.trick("FLIP LAUNCH", 5)

    def slingshot_slam(self, solids):
        # right after a slingshot, dash down: snap to the floor below with
        # all your sideways speed and none of the vertical
        drop = self.rect.copy()
        for _ in range(SLAM_REACH // 4):
            nxt = drop.move(0, 4)
            if self.collides(nxt, solids):
                break
            drop = nxt
        else:
            return False
        while not self.collides(drop.move(0, 1), solids):
            drop.y += 1                  # finish flush with the floor
        self.rect = drop
        self.vy = 0.0
        self.slam_t = self.sling_t = 0.0
        self.dash_t = 0.0
        self.on_ground = True
        self.start_slide()
        self.trick("SLINGSHOT SLAM", 6)
        return True

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

    def hop_apex(self, solids):
        """Pins a tapped hop's peak to exactly TAP_HOP above take-off,
        smoothing out the last fraction of a pixel of fixed-step error."""
        target = self.hop_base - TAP_HOP
        if (self.on_ground or self.dashing or self.hanging
                or self.gravity() != GRAVITY):    # zones change the height
            self.hop_lock = False
            return
        if self.rect.bottom < target:              # went past it: pull back
            peak = self.rect.copy()
            peak.bottom = target
            if not self.collides(peak, solids):
                self.rect = peak
            self.vy = max(self.vy, 0.0)
            self.hop_lock = False
        elif self.vy >= 0:                          # topped out just short
            peak = self.rect.copy()
            peak.bottom = target
            if self.rect.bottom - target <= 4 and not self.collides(peak, solids):
                self.rect = peak
                self.vy = 0.0
            self.hop_lock = False

    def slip_past(self, s, solids):
        """Moving vertically into a block you only clip by a few pixels:
        slide sideways around its corner. Going up this always applies (no
        head bonks on corners); going down only into a narrow gap, so
        landing on the edge of a ledge still lands."""
        r = self.rect
        if s.left > r.left and r.right - s.left <= SLIP:
            shift = s.left - r.right
        elif s.right < r.right and s.right - r.left <= SLIP:
            shift = s.right - r.left
        else:
            return False
        moved = r.move(shift, 0)
        if self.collides(moved, solids):
            return False
        if self.vy > 0 and not self.collides(moved.move(sign(shift) * SLIP, 0), solids):
            return False
        self.rect = moved
        return True

    def slip_under(self, s, solids):
        """Moving sideways into a block whose bottom corner you clip by a
        few pixels: duck under it, so you fit through slots your height."""
        r = self.rect
        drop = s.bottom - r.top
        if not 0 < drop <= SLIP or s.bottom >= r.bottom:
            return False
        moved = r.move(0, drop)
        if self.collides(moved, solids):
            return False
        self.rect = moved
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
