"""
=============================================================================
  VELOCITY  -  a high-speed movement game (pygame-ce)
=============================================================================
Opens on a menu: the story mode, a level creator, playing a level by its ID
and a list of every verified level. Levels are shared online through the
level server in worker/, so anyone can play what anyone builds.

Runs on desktop and in the browser (via pygbag). In the browser the game
resizes itself to fill the whole window.

  main.py     app loop and the story mode
  scenes.py   menu, level list, play-by-ID and playing a level
  editor.py   the level creator
  levels.py   level blocks, level physics and drawing
  net.py      level server requests and local saves
  ui.py       shared colours, fonts, sky and widgets
  player.py   input and every movement maneuver (see its docstring)
  world.py    story world generation, towns and colour palettes
  quests.py   story, characters, main quest and delivery jobs
"""
import asyncio
import math
import os
import random
import sys
import time

import pygame

import net
from player import DT, FPS, MAX_DASHES, Input, Player
from quests import NPCS, Quests
from ui import (DIM, GOLD, INK, PANEL, PLAYER_DASH, PLAYER_EMPTY, PLAYER_READY, TEXT,
                Fonts, draw_panel, draw_sky, pixel_rect, tint_rect, wrap)
from world import PALETTES, WORLD_BOTTOM, WORLD_TOP, WORLD_W, World, mix, palette_at, shade

WEB = sys.platform == "emscripten"
START_SIZE = (1280, 720)

MINIMAP_R = 100              # radius of the round minimap
MINIMAP_SCALE = 30           # world px per minimap px
TALK_RANGE = 90


class Dialogue:
    SPEED = 70               # characters per second

    def __init__(self, lines, colors):
        self.lines = lines
        self.colors = colors
        self.i = 0
        self.shown = 0.0

    @property
    def done(self):
        return self.i >= len(self.lines)

    def update(self, dt):
        self.shown += self.SPEED * dt

    def advance(self):
        if self.shown < len(self.lines[self.i][1]):
            self.shown = len(self.lines[self.i][1])
        else:
            self.i += 1
            self.shown = 0.0


class App:
    """Owns the window and the loop, and runs whichever scene is current."""

    def __init__(self):
        pygame.init()
        flags = 0 if WEB else pygame.RESIZABLE
        self.screen = pygame.display.set_mode(START_SIZE, flags)
        pygame.display.set_caption("VELOCITY")
        icon = os.path.join(os.path.dirname(os.path.abspath(__file__)), "favicon.png")
        try:
            pygame.display.set_icon(pygame.image.load(icon))
        except (pygame.error, FileNotFoundError):
            pass                     # the icon is cosmetic
        if WEB:
            import platform
            platform.document.body.style.background = "#0c0a18"
        self.clock = pygame.time.Clock()
        self.fonts = Fonts()
        self.inp = Input()
        self.name = net.load("name", "") or ""
        self.running = True
        self.alpha = 1.0
        self.scale = None              # browser render scale, see read_scale
        self.perf = None               # F3 frame timing
        self.frame = 0
        self.story = None            # kept so leaving the story doesn't lose progress
        import scenes
        self.scene = scenes.Menu(self)

    def go(self, scene):
        self.scene = scene

    def play_story(self):
        if self.story is None:
            self.story = Game(self)
        self.go(self.story)

    def sync_size(self):
        if WEB:
            # match the canvas to the browser window so there are no bars
            import platform
            w = int(platform.window.innerWidth)
            h = int(platform.window.innerHeight)
            if w <= 200 or h <= 200:
                return
            if self.scale is None:
                self.read_scale()
            size = (round(w * self.scale), round(h * self.scale))
            if size != self.screen.get_size():
                self.screen = pygame.display.set_mode(size)
                platform.window.config.gui_divider = 1
                platform.window.window_resize()
        else:
            self.screen = pygame.display.get_surface()

    def read_scale(self):
        """Drawing resolution is always the window's, unless the address
        asks for less with ?scale=0.7 (the browser then stretches it). It
        never changes while you play."""
        self.scale = 1.0
        import platform
        query = str(platform.window.location.search)
        if "scale=" in query:
            try:
                self.scale = max(0.3, min(1.0, float(query.split("scale=")[1].split("&")[0])))
            except ValueError:
                pass

    async def run(self):
        acc = 0.0
        while self.running:
            # the browser paces frames to the display itself; capping the
            # clock there makes frames miss vsync and halves the frame rate
            acc += min(self.clock.tick(0 if WEB else FPS) / 1000, 0.05)
            real_jump = False        # a jump key other than W this frame
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    return
                if e.type == pygame.KEYDOWN:
                    if e.key == pygame.K_F3:
                        self.perf = None if self.perf else dict(
                            frame=16.0, step=0.0, draw=0.0, flip=0.0, last=time.perf_counter())
                    if e.key in (pygame.K_SPACE, pygame.K_k):
                        self.inp.jump_pressed = True
                        self.inp.jump_w = False
                        real_jump = True
                    if e.key in (pygame.K_w, pygame.K_UP):
                        # W and the up arrow jump too, but also aims dashes (see Player.update)
                        self.inp.jump_pressed = True
                        self.inp.jump_w = not real_jump
                    if e.key in (pygame.K_LSHIFT, pygame.K_RSHIFT, pygame.K_j):
                        self.inp.dash_pressed = True
                    if e.key in (pygame.K_e, pygame.K_RETURN):
                        self.inp.interact_pressed = True
                self.scene.event(e)
            self.inp.poll()
            net.poll()
            if self.frame % 20 == 0:
                self.sync_size()
            self.frame += 1
            t0 = time.perf_counter()
            while acc >= DT:
                self.scene.step(DT)
                self.inp.jump_pressed = self.inp.dash_pressed = False
                self.inp.jump_w = self.inp.interact_pressed = False
                acc -= DT
            self.alpha = acc / DT        # how far into the next physics step we are
            t1 = time.perf_counter()
            self.scene.draw(self.screen)
            t2 = time.perf_counter()
            if self.perf is not None:
                self.draw_perf(t1 - t0, t2 - t1)
            pygame.display.flip()
            t3 = time.perf_counter()
            if self.perf is not None:
                self.perf["flip"] += ((t3 - t2) * 1000 - self.perf["flip"]) * 0.05
            await asyncio.sleep(0)   # hands control to the browser each frame

    def draw_perf(self, step, draw):
        """F3: frame rate and where the time goes."""
        p = self.perf
        now = time.perf_counter()
        p["frame"] += ((now - p["last"]) * 1000 - p["frame"]) * 0.05
        p["last"] = now
        p["step"] += (step * 1000 - p["step"]) * 0.05
        p["draw"] += (draw * 1000 - p["draw"]) * 0.05
        w, h = self.screen.get_size()
        text = (f"{1000 / max(p['frame'], 0.01):.0f} fps   frame {p['frame']:.1f}  step {p['step']:.1f}"
                f"  draw {p['draw']:.1f}  flip {p['flip']:.1f} ms   {w}x{h}"
                f"  scale {self.scale or 1:.1f}")
        img = self.fonts.font.render(text, True, (255, 255, 120), (0, 0, 0))
        self.screen.blit(img, (8, h - 26))
        if WEB and self.frame % 60 == 0:
            import platform
            platform.window.eval(f"window.vperf = {text!r}")


class Game:
    """Story mode: the open world, towns, quests and deliveries."""

    def __init__(self, app):
        self.app = app
        f = app.fonts
        self.font, self.mid, self.big, self.huge = f.font, f.mid, f.big, f.huge
        self.inp = app.inp
        self.world = World()
        self.quests = Quests(self.world.towns)
        self.player = Player(self.world.spawn)
        self.cam = pygame.Vector2()
        self.time = 0.0
        self.feed = []          # [text, age, colour]
        self.trail = []         # [rect, colour, age]
        self.particles = []     # [x, y, vx, vy, life, max_life, colour, size]
        self.dialogue = None
        self.town = None
        self.checkpoint = self.world.towns[0]
        self.banner = None      # [text, age, colour]
        self.was_ground = True
        self.was_dashing = False
        self.prev_vy = 0.0
        self.minimap = self.render_minimap()
        self.mm_key = None
        self.npcs = {k: self.quests.npc_pos(k) for k in NPCS}

    # -- setup ----------------------------------------------------------------
    def render_minimap(self):
        sc = MINIMAP_SCALE
        pad = MINIMAP_R * 2
        self.mm_origin = (-pad * sc - 100, WORLD_TOP - pad * sc)
        size = ((WORLD_W + 400) // sc + pad * 2,
                (WORLD_BOTTOM - WORLD_TOP) // sc + pad * 2)
        mm = pygame.Surface(size)
        mm.fill(INK)
        ox, oy = self.mm_origin
        for r, (kind, fill, top) in zip(self.world.solids, self.world.styles):
            col = top if kind in ("plat", "town") else shade(fill, 1.5)
            pygame.draw.rect(mm, col, ((r.x - ox) // sc, (r.y - oy) // sc,
                                       max(1, r.w // sc), max(1, r.h // sc)))
        r = MINIMAP_R
        self.mm_mask = pygame.Surface((2 * r, 2 * r), pygame.SRCALPHA)
        pygame.draw.circle(self.mm_mask, (255, 255, 255, 255), (r, r), r)
        return mm

    def respawn(self):
        t = self.checkpoint
        self.player.spawn = (t["x"] - 850, t["plaza_y"])
        self.player.reset()
        self.trail.clear()

    @property
    def screen(self):
        return self.app.screen

    def event(self, e):
        if e.type == pygame.KEYDOWN:
            if e.key == pygame.K_ESCAPE:
                import scenes
                self.app.go(scenes.Menu(self.app))
            elif e.key == pygame.K_r and not self.dialogue:
                self.respawn()

    def step(self, dt):
        self.time += dt
        p = self.player
        if self.dialogue:
            self.dialogue.update(dt)
            if self.inp.interact_pressed or self.inp.jump_pressed:
                self.dialogue.advance()
                if self.dialogue.done:
                    self.dialogue = None
        else:
            p.update(dt, self.inp, self.world.query(p.rect.inflate(400, 400)))
            near = self.nearest_npc()
            if near and self.inp.interact_pressed and p.on_ground:
                self.talk(near)
        for name in p.events:
            self.add_feed(name, PLAYER_EMPTY)
            self.burst(p.rect.center, palette_at(p.rect.centerx)["accent"], 14, 380)
        if p.dashing and not self.was_dashing:
            self.burst(p.rect.center, PLAYER_DASH, 8, 260)
        if p.on_ground and not self.was_ground and self.prev_vy > 500:
            self.dust(p.rect.midbottom, min(16, int(self.prev_vy / 80)))
        self.was_dashing = p.dashing
        self.was_ground = p.on_ground
        self.prev_vy = p.vy

        for f in self.feed:
            f[1] += dt
        self.feed = [f for f in self.feed[-5:] if f[1] < 3.0]
        if self.banner:
            self.banner[1] += dt
            if self.banner[1] > 3.0:
                self.banner = None

        town = self.world.town_at(*p.rect.center)
        if town is not self.town:
            self.town = town
            if town:
                self.checkpoint = town
                self.banner = [town["name"], 0.0, PALETTES[town["id"]]["accent"]]
        if p.rect.top > WORLD_BOTTOM:
            self.respawn()

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

        w, h = self.screen.get_size()
        self.cam = pygame.Vector2(p.rect.center) - (w / 2, h / 2)

    def add_feed(self, text, colour):
        self.feed.append([text, 0.0, colour])

    def burst(self, pos, colour, n, speed):
        for _ in range(n):
            a = random.uniform(0, math.tau)
            s = random.uniform(0.3, 1) * speed
            life = random.uniform(0.25, 0.5)
            self.particles.append([pos[0], pos[1], math.cos(a) * s, math.sin(a) * s - 120,
                                   life, life, colour, random.choice((3, 4, 5))])

    def dust(self, pos, n):
        col = palette_at(pos[0])["top"]
        for i in range(n):
            d = -1 if i % 2 else 1
            life = random.uniform(0.3, 0.6)
            self.particles.append([pos[0], pos[1] - 2, d * random.uniform(80, 320),
                                   -random.uniform(60, 220), life, life, col, 4])

    # -- talking --------------------------------------------------------------
    def nearest_npc(self):
        px, py = self.player.rect.midbottom
        best, bd = None, TALK_RANGE
        for k, (nx, ny) in self.npcs.items():
            d = abs(nx - px)
            if d < bd and abs(ny - py) < 50:
                best, bd = k, d
        return best

    def talk(self, npc_id):
        lines = self.quests.talk(npc_id, self.time)
        colours = {n["name"]: n["color"] for n in NPCS.values()}
        self.dialogue = Dialogue(lines, colours)
        self.player.vx = 0.0

    # -- drawing --------------------------------------------------------------
    def player_colour(self):
        p = self.player
        if p.dashing:
            return PLAYER_DASH
        return PLAYER_READY if p.dashes else PLAYER_EMPTY

    def draw(self, s):
        p = self.player
        shake = pygame.Vector2()
        if p.shake > 0:
            t = pygame.time.get_ticks()
            shake.update(math.sin(t * 0.09) * p.shake, math.cos(t * 0.11) * p.shake)
        w, h = s.get_size()
        drawn = p.lerp_rect(self.app.alpha)
        cam = pygame.Vector2(drawn.center) - (w / 2, h / 2) + shake
        cam.update(round(cam.x), round(cam.y))    # whole pixels: no 1px seams
        pal = palette_at(cam.x + w / 2)

        draw_sky(s, cam, pal)
        self.draw_world(s, cam)
        self.draw_npcs(s, cam)

        for rect, col, age in self.trail:
            tint_rect(s, pixel_rect(rect, cam), col, int(140 * (1 - age / 0.18)))
        for x, y, vx, vy, life, mx, col, size in self.particles:
            pygame.draw.rect(s, mix(pal["sky_bot"], col, life / mx),
                             (x - cam.x - size / 2, y - cam.y - size / 2, size, size))

        pr = pixel_rect(drawn, cam)
        pygame.draw.rect(s, INK, pr.inflate(4, 4))
        pygame.draw.rect(s, self.player_colour(), pr)
        if self.quests.item or self.quests.job:      # parcel on your back
            box = pygame.Rect(0, 0, 14, 12)
            box.midbottom = (pr.centerx - p.facing * 6, pr.top - 2)
            pygame.draw.rect(s, (196, 140, 80), box)
            pygame.draw.rect(s, INK, box, 2)

        self.draw_target_arrow(s, cam)
        if self.dialogue:
            self.draw_dialogue(s)
        self.draw_hud(s)
        self.draw_banner(s)

    def draw_world(self, s, cam):
        w, h = s.get_size()
        view = pygame.Rect(cam.x, cam.y, w, h)
        screen = s.get_rect().inflate(8, 8)
        for d in self.world.decor:
            self.draw_decor(s, cam, d, view)
        for r, (kind, fill, top) in self.world.query_styled(view):
            rr = r.move(-cam.x, -cam.y)
            cl = rr.clip(screen)
            pygame.draw.rect(s, fill, cl)
            if kind == "ground":
                if rr.top >= -16:
                    pygame.draw.rect(s, top, (cl.x, rr.top, cl.w, 10))
                    pygame.draw.rect(s, shade(fill, 0.8), (cl.x, rr.top + 10, cl.w, 6))
            elif kind == "plat":
                pygame.draw.rect(s, top, (cl.x, rr.top, cl.w, 4))
                pygame.draw.rect(s, shade(fill, 0.7), (cl.x, rr.bottom - 4, cl.w, 4))
            else:
                pygame.draw.rect(s, shade(fill, 0.75), cl, 3)
                if rr.top >= -6:
                    pygame.draw.rect(s, top, (cl.x, rr.top, cl.w, 5))

    def draw_decor(self, s, cam, d, view):
        if d["kind"] == "house":
            r = d["rect"]
            if not r.inflate(80, 200).colliderect(view):
                return
            rr = r.move(-cam.x, -cam.y)
            pygame.draw.rect(s, d["wall"], rr)
            pygame.draw.polygon(s, d["roof"], [(rr.left - 14, rr.top), (rr.right + 14, rr.top),
                                               (rr.centerx, rr.top - 60)])
            for wx, wy in d["windows"]:
                win = (wx - cam.x, wy - cam.y, 22, 26)
                pygame.draw.rect(s, (255, 226, 140), win)
                pygame.draw.rect(s, shade(d["wall"], 0.6), win, 3)
            door = pygame.Rect(0, 0, 30, 48)
            door.midbottom = rr.midbottom
            pygame.draw.rect(s, shade(d["wall"], 0.5), door)
        elif d["kind"] == "lamp":
            x, y = d["pos"]
            if not view.inflate(100, 200).collidepoint(x, y):
                return
            sx, sy = x - cam.x, y - cam.y
            pygame.draw.line(s, INK, (sx, sy), (sx, sy - 80), 4)
            glow = 0.6 + 0.4 * math.sin(self.time * 3 + x)
            pygame.draw.circle(s, shade(d["color"], 0.6 + 0.4 * glow), (sx, sy - 86), 12)
            pygame.draw.circle(s, (255, 250, 220), (sx, sy - 86), 6)
        elif d["kind"] == "sign":
            x, y = d["pos"]
            if not view.inflate(600, 200).collidepoint(x, y):
                return
            sx, sy = x - cam.x, y - cam.y
            img = self.mid.render(d["text"], True, INK)
            board = img.get_rect(midbottom=(sx + img.get_width() / 2 + 16, sy - 60)).inflate(20, 12)
            pygame.draw.line(s, INK, (sx + 16, sy), (sx + 16, sy - 60), 5)
            pygame.draw.rect(s, d["color"], board, border_radius=4)
            pygame.draw.rect(s, INK, board, 3, border_radius=4)
            s.blit(img, img.get_rect(center=board.center))

    def draw_npcs(self, s, cam):
        w, h = s.get_size()
        main_t = self.quests.main_target()
        job_t = self.quests.job_target()
        near = None if self.dialogue else self.nearest_npc()
        px = self.player.rect.centerx
        for k, (x, y) in self.npcs.items():
            sx, sy = x - cam.x, y - cam.y
            if not -100 < sx < w + 100 or not -150 < sy < h + 150:
                continue
            n = NPCS[k]
            bob = math.sin(self.time * 2.4 + x) * 2
            body = pygame.Rect(0, 0, 28, 30)
            body.midbottom = (sx, sy + bob)
            pygame.draw.rect(s, INK, body.inflate(4, 4), border_radius=6)
            pygame.draw.rect(s, n["color"], body, border_radius=6)
            look = 4 if px > x else -4
            for ex in (-5, 5):
                pygame.draw.rect(s, INK, (body.centerx + ex + look - 2, body.top + 9, 4, 6))
            if k.endswith("_disp"):          # cap for dispatchers
                pygame.draw.rect(s, (60, 70, 160), (body.left - 2, body.top - 6, body.w + 4, 8))
            marker = None
            if k == main_t:
                marker = ("!", GOLD)
            elif k == job_t:
                marker = ("!", PLAYER_READY)
            elif k.endswith("_disp") and not self.quests.job:
                marker = ("$", (255, 236, 150))
            if marker:
                img = self.big.render(marker[0], True, marker[1])
                s.blit(img, img.get_rect(midbottom=(sx, body.top - 6 + bob * 2)))
            if abs(px - x) < 320:
                tag = self.font.render(n["name"], True, TEXT)
                s.blit(tag, tag.get_rect(midbottom=(sx, body.top - (50 if marker else 8))))
            if k == near:
                hint = self.font.render("E  talk", True, GOLD)
                s.blit(hint, hint.get_rect(midtop=(sx, body.bottom + 8)))

    def target(self):
        t = self.quests.main_target() or self.quests.job_target()
        return (self.npcs[t], t) if t else (None, None)

    def draw_target_arrow(self, s, cam):
        pos, tid = self.target()
        if not pos:
            return
        w, h = s.get_size()
        tx, ty = pos[0] - cam.x, pos[1] - 40 - cam.y
        if 40 < tx < w - 40 and 40 < ty < h - 40:
            return
        cx, cy = w / 2, h / 2
        a = math.atan2(ty - cy, tx - cx)
        # pinned to an ellipse inside the screen edge
        ex, ey = cx + math.cos(a) * (w / 2 - 60), cy + math.sin(a) * (h / 2 - 60)
        col = GOLD if tid == self.quests.main_target() else PLAYER_READY
        tip = (ex + math.cos(a) * 18, ey + math.sin(a) * 18)
        left = (ex + math.cos(a + 2.4) * 16, ey + math.sin(a + 2.4) * 16)
        right = (ex + math.cos(a - 2.4) * 16, ey + math.sin(a - 2.4) * 16)
        pygame.draw.polygon(s, INK, [(x + 2, y + 2) for x, y in (tip, left, right)])
        pygame.draw.polygon(s, col, [tip, left, right])
        p = self.player.rect.center
        dist = math.hypot(pos[0] - p[0], pos[1] - p[1])
        img = self.font.render(f"{dist / 1000:.1f}k", True, col)
        s.blit(img, img.get_rect(center=(ex - math.cos(a) * 26, ey - math.sin(a) * 26)))

    def draw_dialogue(self, s):
        w, h = s.get_size()
        d = self.dialogue
        speaker, text = d.lines[d.i]
        right = w - 2 * MINIMAP_R - 300
        box = pygame.Rect(24, h - 196, max(360, min(820, right - 24)), 172)
        draw_panel(s, box, 225)
        col = d.colors.get(speaker, GOLD)
        pygame.draw.rect(s, col, box, 3, border_radius=12)
        if speaker:
            s.blit(self.mid.render(speaker, True, col), (box.x + 20, box.y + 16))
        shown = text[:int(d.shown)]
        for i, line in enumerate(wrap(self.mid, shown, box.w - 40)[:4]):
            s.blit(self.mid.render(line, True, TEXT), (box.x + 20, box.y + 50 + i * 28))
        if d.shown >= len(text) and int(self.time * 3) % 2:
            more = "E / SPACE" + ("  >" if d.i < len(d.lines) - 1 else "  close")
            img = self.font.render(more, True, DIM)
            s.blit(img, img.get_rect(bottomright=(box.right - 16, box.bottom - 12)))

    def draw_banner(self, s):
        if not self.banner:
            return
        text, age, col = self.banner
        w, h = s.get_size()
        a = max(0, min(1, age / 0.3, (3.0 - age) / 0.6))
        img = self.huge.render(text.upper(), True, col).copy()
        shadow = self.huge.render(text.upper(), True, INK).copy()
        img.set_alpha(int(255 * a))
        shadow.set_alpha(int(200 * a))
        r = img.get_rect(center=(w / 2, h * 0.22))
        s.blit(shadow, r.move(4, 4))
        s.blit(img, r)

    def draw_hud(self, s):
        # every stat lives in one cluster around the round minimap
        w, h = s.get_size()
        p = self.player
        sc = MINIMAP_SCALE
        r = MINIMAP_R
        cx, cy = w - r - 28, h - r - 28
        ox, oy = self.mm_origin

        def to_mm(wx, wy):
            return (wx - ox) / sc, (wy - oy) / sc

        px, py = to_mm(*p.rect.center)
        px, py = round(px), round(py)
        # the round map only changes when you move a whole map pixel
        key = (px, py, w, h)
        if self.mm_key != key:
            self.mm_key = key
            disc = pygame.Surface((2 * r, 2 * r), pygame.SRCALPHA)
            disc.blit(self.minimap, (0, 0), (px - r, py - r, 2 * r, 2 * r))
            view = pygame.Rect(0, 0, w / sc, h / sc)
            view.center = (r, r)
            pygame.draw.rect(disc, DIM, view, 1)
            for t in self.world.towns:
                tx, ty = to_mm(t["x"], t["plaza_y"])
                pygame.draw.circle(disc, INK, (tx - px + r, ty - py + r), 6)
                pygame.draw.circle(disc, PALETTES[t["id"]]["accent"], (tx - px + r, ty - py + r), 4)
            disc.blit(self.mm_mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
            self.mm_disc = disc
        pygame.draw.circle(s, INK, (cx, cy), r + 4)
        s.blit(self.mm_disc, (cx - r, cy - r))
        # quest target: on the map, or pinned to the rim when far away
        pos, tid = self.target()
        if pos:
            tx, ty = to_mm(*pos)
            dx, dy = tx - px, ty - py
            dist = math.hypot(dx, dy)
            col = GOLD if tid == self.quests.main_target() else PLAYER_READY
            if dist > r - 8:
                dx, dy = dx / dist * (r - 8), dy / dist * (r - 8)
            pulse = 5 + 2 * math.sin(self.time * 6)
            pygame.draw.circle(s, col, (cx + dx, cy + dy), pulse, 2)
            pygame.draw.circle(s, col, (cx + dx, cy + dy), 3)
        pygame.draw.rect(s, INK, (cx - 5, cy - 5, 10, 10))
        pygame.draw.rect(s, self.player_colour(), (cx - 3, cy - 3, 6, 6))
        pygame.draw.circle(s, palette_at(p.rect.centerx)["accent"], (cx, cy), r, 3)

        # speed gauge: arc around the rim, filling clockwise from the bottom
        spd = p.speed()
        frac = min(1, spd / 1500)
        ring = pygame.Rect(0, 0, 2 * r + 24, 2 * r + 24)
        ring.center = (cx, cy)
        pygame.draw.arc(s, PANEL, ring, math.pi / 2, math.pi * 1.5, 7)
        if frac > 0:
            col = mix(PLAYER_READY, PLAYER_EMPTY, min(1, frac * 1.3))
            pygame.draw.arc(s, col, ring, math.pi * 1.5 - math.pi * frac, math.pi * 1.5, 7)

        # speed, dash and coins to the left of the map
        right = cx - r - 30
        num = self.big.render(f"{spd:.0f}", True, TEXT)
        s.blit(num, (right - num.get_width(), cy - num.get_height() + 2))
        lab = self.font.render("SPEED", True, DIM)
        s.blit(lab, (right - lab.get_width(), cy + 6))
        for i in range(MAX_DASHES):
            col = PLAYER_READY if i < p.dashes else PANEL
            pygame.draw.circle(s, INK, (right - 8 - i * 22, cy + 44), 9)
            pygame.draw.circle(s, col, (right - 8 - i * 22, cy + 44), 7)
        coins = self.mid.render(str(self.quests.coins), True, GOLD)
        crect = coins.get_rect(bottomright=(right, cy + 88))
        s.blit(coins, crect)
        d = (crect.left - 14, crect.centery)
        pygame.draw.polygon(s, GOLD, [(d[0], d[1] - 8), (d[0] + 7, d[1]), (d[0], d[1] + 8),
                                      (d[0] - 7, d[1])])

        # quest panel above the map
        pw = 360
        q = self.quests
        rows = [("MAIN STORY" if not q.main_done else "STORY COMPLETE", GOLD)]
        rows += [(line, TEXT) for line in wrap(self.font, q.objective(), pw - 32)]
        if q.item:
            rows.append((f"Carrying: {q.item}", DIM))
        if q.job:
            dest = q.towns[q.job["to"]]["name"]
            left = q.job["par"] - (self.time - q.job["started"])
            rows.append(("JOB", PLAYER_READY))
            rows += [(line, TEXT) for line in
                     wrap(self.font, f"{q.job['item']} to the Dispatcher in {dest}", pw - 32)]
            rows.append((f"Par {left:.0f}s" if left > 0 else "Over par",
                         DIM if left > 0 else PLAYER_EMPTY))
        ph = 20 + len(rows) * 22
        panel = pygame.Rect(w - pw - 24, cy - r - 24 - ph, pw, ph)
        draw_panel(s, panel)
        for i, (text, col) in enumerate(rows):
            s.blit(self.font.render(text, True, col), (panel.x + 16, panel.y + 12 + i * 22))

        # trick feed above the panel, newest at the bottom and biggest
        y = panel.top - 10
        for i, (name, age, col) in enumerate(reversed(self.feed)):
            fade = round(max(0, 1 - age / 3.0) * 12) / 12   # few steps, so text caches
            base = col if i == 0 and age < 0.8 else TEXT
            img = (self.mid if i == 0 else self.font).render(name, True, mix(INK, base, fade))
            y -= img.get_height() + 2
            s.blit(img, (w - img.get_width() - 28, y))


async def main():
    await App().run()
    pygame.quit()


if __name__ == "__main__":
    asyncio.run(main())
