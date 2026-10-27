"""The menu, the level list, play-by-ID and playing a shared level."""
import math
import sys

import pygame

import net
from levels import Run, load
from player import MAX_DASHES
from ui import (DIM, GOLD, GREEN, INK, PANEL, PLAYER_READY, RED, TEXT, TextBox, button,
                draw_panel, draw_sky, fmt_time, shade_screen)
from world import PALETTES, WORLD_W, mix, palette_at

WEB = sys.platform == "emscripten"
ID_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def menu_backdrop(s, t, dim=0):
    """Slow pan across the story world's skies, behind the menus. `dim`
    darkens it like shade_screen would, but by darkening the colours
    instead of the finished pixels, which is far cheaper in the browser."""
    w, h = s.get_size()
    x = (t * 500) % WORLD_W
    cam = pygame.Vector2(x, -250 + math.sin(t * 0.2) * 200)
    pal = palette_at(x + w / 2)
    k = 1 - dim / 255
    dark = {name: tuple(int(c * k) for c in col) for name, col in pal.items()}
    draw_sky(s, cam, dark)
    return pal


def hovered(rects, pos):
    for i, r in enumerate(rects):
        if r and r.collidepoint(pos):
            return i
    return None


# ------------------------------------------------------------------ menu ---
class Menu:
    def __init__(self, app):
        self.app = app
        self.t = 0.0
        self.sel = 0
        self.rects = []
        self.naming = None

    def items(self):
        items = [("story", "Story Mode"), ("create", "Level Creator"),
                 ("id", "Play Level by ID"), ("browse", "Browse Levels"),
                 ("name", f"Name: {self.app.name or 'Anonymous'}")]
        if not WEB:
            items.append(("quit", "Quit"))
        return items

    def activate(self, key):
        app = self.app
        if key == "story":
            app.play_story()
        elif key == "create":
            import editor
            app.go(editor.Editor(app))
        elif key == "id":
            app.go(IdEntry(app))
        elif key == "browse":
            app.go(Browse(app))
        elif key == "name":
            self.naming = TextBox(app.name, 24)
        elif key == "quit":
            app.running = False

    def event(self, e):
        items = self.items()
        if self.naming:
            if e.type == pygame.KEYDOWN and e.key == pygame.K_RETURN:
                self.app.name = self.naming.value.strip()
                net.save("name", self.app.name)
                self.naming = None
            elif e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
                self.naming = None
            else:
                self.naming.key(e)
            return
        if e.type == pygame.KEYDOWN:
            if e.key in (pygame.K_w, pygame.K_UP):
                self.sel = (self.sel - 1) % len(items)
            elif e.key in (pygame.K_s, pygame.K_DOWN):
                self.sel = (self.sel + 1) % len(items)
            elif e.key in (pygame.K_RETURN, pygame.K_SPACE):
                self.activate(items[self.sel][0])
            elif e.key == pygame.K_ESCAPE and not WEB:
                self.app.running = False
        elif e.type == pygame.MOUSEMOTION:
            i = hovered(self.rects, e.pos)
            if i is not None:
                self.sel = i
        elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            i = hovered(self.rects, e.pos)
            if i is not None:
                self.activate(items[i][0])

    def step(self, dt):
        self.t += dt

    def draw(self, s):
        f = self.app.fonts
        w, h = s.get_size()
        pal = menu_backdrop(s, self.t, 70)
        title = f.title.render("VELOCITY", True, TEXT)
        shadow = f.title.render("VELOCITY", True, INK)
        r = title.get_rect(center=(w / 2, h * 0.2))
        s.blit(shadow, r.move(6, 6))
        s.blit(title, r)
        # a little square racing under the title
        x = r.left + (self.t * 600) % (r.w + 200) - 100
        if r.left <= x <= r.right - 18:
            pygame.draw.rect(s, PLAYER_READY, (x, r.bottom + 6, 18, 18))
        sub = f.mid.render("a high-speed movement game", True, pal["accent"])
        s.blit(sub, sub.get_rect(center=(w / 2, r.bottom + 40)))

        items = self.items()
        bw, bh, gap = 380, 54, 12
        top = max(r.bottom + 80, h / 2 - (len(items) * (bh + gap)) / 2 + 40)
        self.rects = []
        for i, (key, label) in enumerate(items):
            rect = pygame.Rect(0, 0, bw, bh)
            rect.midtop = (w / 2, top + i * (bh + gap))
            self.rects.append(button(s, f, rect, label, i == self.sel, pal["accent"]))
        if self.naming:
            shade_screen(s, 160)
            box = pygame.Rect(0, 0, 520, 70)
            box.center = (w / 2, h / 2)
            self.naming.draw(s, f, box, self.t, "Your name, shown on levels and records")
            hint = f.font.render("ENTER save    ESC cancel", True, DIM)
            s.blit(hint, hint.get_rect(midtop=(w / 2, box.bottom + 12)))


# ---------------------------------------------------------- play by ID ---
class IdEntry:
    def __init__(self, app):
        self.app = app
        self.t = 0.0
        self.box = TextBox("", 6, ID_CHARS, upper=True)
        self.mine = net.load("published", []) or []
        self.rects = []
        self.sel = None

    def event(self, e):
        if e.type == pygame.KEYDOWN:
            if e.key == pygame.K_ESCAPE:
                self.app.go(Menu(self.app))
            elif e.key == pygame.K_RETURN and len(self.box.value) == 6:
                self.app.go(Play(self.app, self.box.value, back=self))
            else:
                self.box.key(e)
        elif e.type == pygame.TEXTINPUT:
            self.box.key(e)
        elif e.type == pygame.MOUSEMOTION:
            self.sel = hovered(self.rects, e.pos)
        elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            i = hovered(self.rects, e.pos)
            if i is not None:
                self.app.go(Play(self.app, self.mine[i]["id"], back=self))

    def step(self, dt):
        self.t += dt

    def draw(self, s):
        f = self.app.fonts
        w, h = s.get_size()
        menu_backdrop(s, self.t, 120)
        head = f.huge.render("PLAY BY ID", True, TEXT)
        s.blit(head, head.get_rect(center=(w / 2, h * 0.18)))
        box = pygame.Rect(0, 0, 300, 80)
        box.center = (w / 2, h * 0.36)
        self.box.draw(s, f, box, self.t, "Level ID", f.huge)
        hint = f.font.render("ENTER play    ESC back", True, DIM)
        s.blit(hint, hint.get_rect(midtop=(w / 2, box.bottom + 12)))
        self.rects = []
        if self.mine:
            y = box.bottom + 70
            lab = f.mid.render("Levels you published", True, GOLD)
            s.blit(lab, lab.get_rect(midtop=(w / 2, y)))
            y += 40
            for i, lv in enumerate(self.mine[:8]):
                r = pygame.Rect(0, 0, 520, 40)
                r.midtop = (w / 2, y + i * 46)
                self.rects.append(button(s, f, r, f"{lv['id']}   {lv['name']}", i == self.sel,
                                         GOLD, f.font))


# --------------------------------------------------------------- browse ---
class Browse:
    ROW = 52

    def __init__(self, app):
        self.app = app
        self.t = 0.0
        self.sort = "new"
        self.sel = 0
        self.scroll = 0.0
        self.rects = []
        self.tab_rects = []
        self.reload()

    def reload(self):
        self.levels = []
        self.total = None
        self.sel = 0
        self.scroll = 0.0
        self.req = net.api("GET", f"/levels?sort={self.sort}&offset=0")
        self.error = None

    def more(self):
        if self.req is None and self.total is not None and len(self.levels) < self.total:
            self.req = net.api("GET", f"/levels?sort={self.sort}&offset={len(self.levels)}")

    def play(self, i):
        self.app.go(Play(self.app, self.levels[i]["id"], back=self))

    def set_sort(self, sort):
        if sort != self.sort:
            self.sort = sort
            self.reload()

    def event(self, e):
        if e.type == pygame.KEYDOWN:
            if e.key == pygame.K_ESCAPE:
                self.app.go(Menu(self.app))
            elif e.key == pygame.K_TAB:
                self.set_sort("top" if self.sort == "new" else "new")
            elif e.key in (pygame.K_w, pygame.K_UP) and self.levels:
                self.sel = max(0, self.sel - 1)
            elif e.key in (pygame.K_s, pygame.K_DOWN) and self.levels:
                self.sel = min(len(self.levels) - 1, self.sel + 1)
            elif e.key in (pygame.K_RETURN, pygame.K_SPACE) and self.levels:
                self.play(self.sel)
            elif e.key == pygame.K_F5:
                self.reload()
        elif e.type == pygame.MOUSEWHEEL:
            self.scroll = max(0.0, self.scroll - e.y * self.ROW)
        elif e.type == pygame.MOUSEMOTION:
            i = hovered(self.rects, e.pos)
            if i is not None:
                self.sel = i
        elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            t = hovered(self.tab_rects, e.pos)
            if t is not None:
                self.set_sort(("new", "top")[t])
                return
            i = hovered(self.rects, e.pos)
            if i is not None:
                self.play(i)

    def step(self, dt):
        self.t += dt
        if self.req and self.req.done:
            if self.req.error:
                self.error = self.req.error
            else:
                self.levels += self.req.data["levels"]
                self.total = self.req.data["total"]
            self.req = None

    def draw(self, s):
        f = self.app.fonts
        w, h = s.get_size()
        pal = menu_backdrop(s, self.t, 130)
        head = f.huge.render("LEVELS", True, TEXT)
        s.blit(head, head.get_rect(midtop=(w / 2, 30)))
        sub = f.font.render("Every level here has been beaten at least once.", True, DIM)
        s.blit(sub, sub.get_rect(midtop=(w / 2, 100)))
        self.tab_rects = []
        for i, (key, label) in enumerate((("new", "Newest"), ("top", "Most cleared"))):
            r = pygame.Rect(0, 0, 200, 40)
            r.midtop = (w / 2 + (i - 0.5) * 214, 130)
            self.tab_rects.append(button(s, f, r, label, self.sort == key, pal["accent"], f.font))

        pw = min(980, w - 40)
        area = pygame.Rect((w - pw) // 2, 190, pw, h - 250)
        draw_panel(s, area, 170)
        cols = [("ID", 16), ("NAME", 110), ("BY", 0.5), ("CLEARS", 0.68), ("BEST", 0.8)]

        def cx(c):
            return area.x + (c if c > 1 else c * area.w)

        for name, c in cols:
            s.blit(f.small.render(name, True, DIM), (cx(c), area.y + 10))
        clip = pygame.Rect(area.x, area.y + 34, area.w, area.h - 40)
        if self.levels:
            # keep the selection in view
            top = self.sel * self.ROW
            if top < self.scroll:
                self.scroll = top
            elif top + self.ROW > self.scroll + clip.h:
                self.scroll = top + self.ROW - clip.h
            self.scroll = max(0.0, min(self.scroll, len(self.levels) * self.ROW - clip.h))
            if (len(self.levels) * self.ROW - self.scroll) < clip.h + self.ROW * 3:
                self.more()
        s.set_clip(clip)
        self.rects = []
        for i, lv in enumerate(self.levels):
            y = clip.y + i * self.ROW - self.scroll
            r = pygame.Rect(area.x + 6, y, area.w - 12, self.ROW - 6)
            if r.bottom < clip.top or r.top > clip.bottom:
                self.rects.append(None)
                continue
            self.rects.append(r)
            sel = i == self.sel
            draw_panel(s, r, 220 if sel else 120, mix(PANEL, pal["accent"], 0.25) if sel else PANEL, 8)
            yy = r.centery
            for text, c, col, font in (
                    (lv["id"], 16, GOLD, f.mid), (lv["name"], 110, TEXT, f.mid),
                    (lv["author"], 0.5, DIM, f.font), (str(lv["clears"]), 0.68, TEXT, f.font),
                    (f"{fmt_time(lv['best'])}  {lv.get('best_by') or ''}", 0.8, PLAYER_READY, f.font)):
                img = font.render(text, True, col)
                limit = (cx(0.5) - cx(110) - 10) if c == 110 else None
                if limit and img.get_width() > limit:
                    img = img.subsurface((0, 0, limit, img.get_height()))
                s.blit(img, img.get_rect(midleft=(cx(c), yy)))
        s.set_clip(None)
        msg = None
        if self.error:
            msg = (self.error, RED)
        elif self.req and not self.levels:
            msg = ("Loading...", DIM)
        elif not self.levels:
            msg = ("No verified levels yet. Make one and beat it!", DIM)
        if msg:
            img = f.mid.render(msg[0], True, msg[1])
            s.blit(img, img.get_rect(center=area.center))
        hint = f.font.render("ENTER play    TAB sort    ESC back", True, DIM)
        s.blit(hint, hint.get_rect(midbottom=(w / 2, h - 18)))


# ----------------------------------------------------------------- play ---
def draw_level_hud(s, fonts, run, title=None, sub=None):
    """Timer, speed, dash and trick feed shared by play and playtest."""
    f = fonts
    w, h = s.get_size()
    p = run.player
    timer = f.huge.render(fmt_time(run.time), True, TEXT if run.started else DIM)
    shadow = f.huge.render(fmt_time(run.time), True, INK)
    r = timer.get_rect(midtop=(w / 2, 14))
    s.blit(shadow, r.move(3, 3))
    s.blit(timer, r)
    d = f.font.render(f"deaths {run.deaths}", True, DIM)
    s.blit(d, d.get_rect(midtop=(w / 2, r.bottom + 2)))
    if title:
        panel = pygame.Rect(16, 16, max(260, f.mid.size(title)[0] + 36), 70 if sub else 46)
        if sub:
            panel.w = max(panel.w, f.font.size(sub)[0] + 36)
        draw_panel(s, panel)
        s.blit(f.mid.render(title, True, GOLD), (panel.x + 18, panel.y + 12))
        if sub:
            s.blit(f.font.render(sub, True, DIM), (panel.x + 18, panel.y + 42))
    # speed and dash, bottom right like the story HUD
    spd = f.big.render(f"{p.speed():.0f}", True, TEXT)
    s.blit(spd, spd.get_rect(bottomright=(w - 28, h - 40)))
    lab = f.font.render("SPEED", True, DIM)
    s.blit(lab, lab.get_rect(bottomright=(w - 28, h - 18)))
    for i in range(MAX_DASHES):
        col = PLAYER_READY if i < p.dashes else PANEL
        c = (w - 40 - i * 22, h - 108)
        pygame.draw.circle(s, INK, c, 9)
        pygame.draw.circle(s, col, c, 7)
    y = h - 130
    for i, (name, age, col) in enumerate(reversed(run.feed)):
        fade = round(max(0, 1 - age / 2.5) * 12) / 12   # few steps, so text caches
        img = (f.mid if i == 0 else f.font).render(name, True, mix(INK, col if i == 0 else TEXT, fade))
        y -= img.get_height() + 2
        s.blit(img, (w - img.get_width() - 28, y))


def level_camera(s, run, alpha):
    w, h = s.get_size()
    p = run.player
    cam = pygame.Vector2(p.lerp_rect(alpha).center) - (w / 2, h / 2)
    if p.shake > 0:
        t = pygame.time.get_ticks()
        cam += (math.sin(t * 0.09) * p.shake, math.cos(t * 0.11) * p.shake)
    return pygame.Vector2(round(cam.x), round(cam.y))    # whole pixels: no 1px seams


class Play:
    """Plays a shared level fetched by ID. Clearing it reports the time, and
    the first clear ever verifies the level."""

    def __init__(self, app, level_id, back):
        self.app = app
        self.back = back
        self.id = level_id
        self.req = net.api("GET", f"/levels/{level_id}")
        self.meta = None
        self.run = None
        self.error = None
        self.hitboxes = False
        self.clear_req = None
        self.result = None
        self.t = 0.0

    def event(self, e):
        if e.type != pygame.KEYDOWN:
            return
        if e.key == pygame.K_ESCAPE:
            self.app.go(self.back)
        elif e.key == pygame.K_h:
            self.hitboxes = not self.hitboxes
        elif e.key == pygame.K_r and self.run and not self.clear_req:
            self.run.restart()
            self.result = None

    def step(self, dt):
        self.t += dt
        if self.req and self.req.done:
            if self.req.error:
                self.error = self.req.error
            else:
                self.meta = self.req.data
                try:
                    objs, theme = load(self.meta["data"])
                    self.run = Run(objs, theme)
                except (ValueError, KeyError, TypeError):
                    self.error = "this level's data is broken"
            self.req = None
        if self.clear_req and self.clear_req.done:
            self.result = self.clear_req
            self.clear_req = None
            if not self.result.error:
                self.meta["verified"] = 1
                if self.result.data["record"]:
                    self.meta["best"] = self.result.data["best"]
                    self.meta["best_by"] = self.app.name or "Anonymous"
        if not self.run:
            return
        was = self.run.finished
        self.run.step(dt, self.app.inp)
        if self.run.finished and not was:
            self.clear_req = net.api("POST", f"/levels/{self.id}/clear", {
                "time": round(self.run.time, 4), "deaths": self.run.deaths,
                "name": self.app.name or "Anonymous"})

    def draw(self, s):
        f = self.app.fonts
        w, h = s.get_size()
        if not self.run:
            menu_backdrop(s, self.t, 140)
            text, col = (self.error, RED) if self.error else (f"Loading level {self.id}...", TEXT)
            img = f.big.render(text, True, col)
            s.blit(img, img.get_rect(center=(w / 2, h / 2)))
            hint = f.font.render("ESC back", True, DIM)
            s.blit(hint, hint.get_rect(midtop=(w / 2, h / 2 + 40)))
            return
        run = self.run
        cam = level_camera(s, run, self.app.alpha)
        draw_sky(s, cam, PALETTES[run.theme])
        run.draw(s, cam, f, self.hitboxes, self.app.alpha)
        m = self.meta
        status = "verified" if m["verified"] else "unverified: be the first to beat it!"
        best = f"   best {fmt_time(m['best'])} by {m['best_by']}" if m.get("best") is not None else ""
        draw_level_hud(s, f, run, m["name"], f"{m['id']} by {m['author']}   {status}{best}")
        if run.finished:
            self.draw_clear(s, f, run)

    def draw_clear(self, s, f, run):
        w, h = s.get_size()
        shade_screen(s, 150)
        head = f.huge.render("CLEARED", True, GOLD)
        s.blit(head, head.get_rect(center=(w / 2, h * 0.3)))
        t = f.huge.render(fmt_time(run.time), True, TEXT)
        s.blit(t, t.get_rect(center=(w / 2, h * 0.3 + 80)))
        d = f.mid.render(f"{run.deaths} death{'' if run.deaths == 1 else 's'}", True, DIM)
        s.blit(d, d.get_rect(center=(w / 2, h * 0.3 + 130)))
        if self.clear_req:
            msg, col = "Sending your time...", DIM
        elif self.result and self.result.error:
            msg, col = f"Couldn't send your time: {self.result.error}", RED
        elif self.result:
            r = self.result.data
            if r["verified_now"]:
                msg, col = "You verified this level! It's on the public list now.", GREEN
            elif r["record"]:
                msg, col = "New record!", GREEN
            else:
                msg, col = f"Record: {fmt_time(r['best'])}", TEXT
        else:
            msg, col = "", TEXT
        img = f.mid.render(msg, True, col)
        s.blit(img, img.get_rect(center=(w / 2, h * 0.3 + 180)))
        hint = f.font.render("R  play again    ESC back", True, DIM)
        s.blit(hint, hint.get_rect(center=(w / 2, h * 0.3 + 230)))
