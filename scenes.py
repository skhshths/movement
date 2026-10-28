"""The menu, the level list, play-by-ID, playing a shared level and watching
a level's verifying clear."""
import math
import sys

import pygame

import net
import ratings
from levels import Run, apply_mask, decode_replay, encode_replay, input_mask, load
from player import DT, MAX_DASHES, Input
from ui import (DIM, GOLD, GREEN, INK, PANEL, PLAYER_READY, RED, TEXT, TextBox, button,
                draw_panel, draw_sky, fmt_time, shade_screen)
from world import PALETTES, WORLD_W, mix, palette_at

WEB = sys.platform == "emscripten"
ID_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def admin_code(app):
    """The admin code, while you're named admin and have entered it."""
    if app.name.lower() == "admin":
        return net.load("admin_code") or None
    return None


def admin_headers(app):
    code = admin_code(app)
    return {"x-admin-code": code} if code else None


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


def rating_text(level):
    """"Hard 3   creator says Hard 2   players say Expert 1" for a level
    dict from the server."""
    text = ratings.name(level.get("rating"))
    if level.get("proposed"):
        text += f"   creator says {ratings.name(level['proposed'])}"
    sugg = ratings.suggested(level)
    if sugg:
        text += f"   players say {ratings.name(sugg)}"
    return text


def list_rating(level):
    """Rating column text and colour: the official rating, else the
    creator's proposed difficulty, marked as theirs."""
    if level.get("rating"):
        return ratings.name(level["rating"]), ratings.colour(level["rating"])
    if level.get("proposed"):
        return f"{ratings.name(level['proposed'])} (creator)", ratings.colour(level["proposed"])
    return "Unrated", DIM


# ------------------------------------------------------------------ menu ---
class Menu:
    def __init__(self, app):
        self.app = app
        self.t = 0.0
        self.sel = 0
        self.rects = []
        self.naming = None
        self.code = None         # admin code box, after naming yourself admin
        self.code_req = None
        self.code_error = None

    def items(self):
        name = self.app.name or "Anonymous"
        if admin_code(self.app):
            name += " (admin)"
        items = [("story", "Story Mode"), ("create", "Level Creator"),
                 ("id", "Play Level by ID"), ("browse", "Browse Levels"),
                 ("name", f"Name: {name}")]
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

    def set_name(self, name):
        self.app.name = name
        net.save("name", name)

    def event(self, e):
        items = self.items()
        if self.code:
            # naming yourself admin needs the admin code
            if e.type == pygame.KEYDOWN and e.key == pygame.K_RETURN and not self.code_req:
                self.code_error = None
                self.code_req = net.api("POST", "/admin/check", {"code": self.code.value})
            elif e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
                self.code = self.naming = None
            else:
                self.code.key(e)
            return
        if self.naming:
            if e.type == pygame.KEYDOWN and e.key == pygame.K_RETURN:
                name = self.naming.value.strip()
                if name.lower() == "admin":
                    self.code = TextBox("", 64, mask=True)
                    self.code_error = None
                    return
                self.set_name(name)
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
        req = self.code_req
        if req and req.done:
            self.code_req = None
            if not req.error and req.data.get("ok"):
                net.save("admin_code", self.code.value)
                self.set_name(self.naming.value.strip())
                self.code = self.naming = None
            else:
                self.code_error = req.error or "Wrong admin code"
                self.code.value = ""

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
            if self.code:
                self.code.draw(s, f, box, self.t, "Admin code")
                if self.code_req:
                    msg, col = "Checking...", DIM
                elif self.code_error:
                    msg, col = self.code_error, RED
                else:
                    msg, col = "ENTER check    ESC cancel", DIM
            else:
                self.naming.draw(s, f, box, self.t, "Your name, shown on levels and records")
                msg, col = "ENTER save    ESC cancel", DIM
            hint = f.font.render(msg, True, col)
            s.blit(hint, hint.get_rect(midtop=(w / 2, box.bottom + 12)))


# ---------------------------------------------------------- play by ID ---
class IdEntry:
    def __init__(self, app):
        self.app = app
        self.t = 0.0
        self.box = TextBox("", 6, ID_CHARS, upper=True)
        self.mine = net.load("published", []) or []
        self.rects = []
        self.edit_rects = []
        self.sel = None
        self.req = None          # fetching a level to edit
        self.req_entry = None
        self.error = None

    def edit(self, i):
        self.req_entry = self.mine[i]
        self.req = net.api("GET", f"/levels/{self.req_entry['id']}")
        self.error = None

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
            i = hovered(self.edit_rects, e.pos)
            if i is not None:
                self.edit(i)
                return
            i = hovered(self.rects, e.pos)
            if i is not None:
                self.app.go(Play(self.app, self.mine[i]["id"], back=self))

    def step(self, dt):
        self.t += dt
        req = self.req
        if req and req.done:
            self.req = None
            if req.error:
                self.error = req.error
                return
            import editor
            entry = self.req_entry
            objs, theme = load(req.data["data"])
            link = {"id": entry["id"], "token": entry["token"]} if entry.get("token") else None
            self.app.go(editor.Editor(self.app, dict(objs=objs, theme=theme,
                                                     title=req.data["name"], link=link,
                                                     proposed=req.data.get("proposed"))))

    def draw(self, s):
        f = self.app.fonts
        w, h = s.get_size()
        pal = menu_backdrop(s, self.t, 120)
        head = f.huge.render("PLAY BY ID", True, TEXT)
        s.blit(head, head.get_rect(center=(w / 2, h * 0.18)))
        box = pygame.Rect(0, 0, 300, 80)
        box.center = (w / 2, h * 0.36)
        self.box.draw(s, f, box, self.t, "Level ID", f.huge)
        hint = f.font.render("ENTER play    ESC back", True, DIM)
        s.blit(hint, hint.get_rect(midtop=(w / 2, box.bottom + 12)))
        self.rects = []
        self.edit_rects = []
        if self.mine:
            y = box.bottom + 70
            lab = f.mid.render("Levels you published   (click to play)", True, GOLD)
            s.blit(lab, lab.get_rect(midtop=(w / 2, y)))
            y += 40
            for i, lv in enumerate(self.mine[:8]):
                r = pygame.Rect(0, 0, 520, 40)
                r.midtop = (w / 2 - 50, y + i * 46)
                self.rects.append(button(s, f, r, f"{lv['id']}   {lv['name']}", i == self.sel,
                                         GOLD, f.font))
                er = pygame.Rect(r.right + 10, r.y, 90, 40)
                self.edit_rects.append(button(s, f, er, "Edit", er.collidepoint(pygame.mouse.get_pos()),
                                              pal["accent"], f.font))
        msg = ("Loading level to edit...", DIM) if self.req else (self.error, RED) if self.error else None
        if msg:
            img = f.font.render(msg[0], True, msg[1])
            s.blit(img, img.get_rect(midbottom=(w / 2, h - 16)))


# --------------------------------------------------------------- browse ---
class Browse:
    ROW = 52
    SORTS = [("new", "Newest"), ("top", "Most cleared"), ("hard", "Hardest"),
             ("unverified", "Unverified")]

    def __init__(self, app):
        self.app = app
        self.t = 0.0
        self.sort = "new"
        self.sel = 0
        self.scroll = 0.0
        self.rects = []
        self.tab_rects = []
        self.reload()

    def sorts(self):
        # the admin also sees every level, verified or not
        return self.SORTS + ([("all", "All (admin)")] if admin_code(self.app) else [])

    def url(self, offset):
        if self.sort == "all":
            return f"/admin/levels?offset={offset}"
        return f"/levels?sort={self.sort}&offset={offset}"

    def reload(self):
        self.levels = []
        self.total = None
        self.sel = 0
        self.scroll = 0.0
        self.req = net.api("GET", self.url(0), headers=admin_headers(self.app))
        self.error = None

    def more(self):
        if self.req is None and self.total is not None and len(self.levels) < self.total:
            self.req = net.api("GET", self.url(len(self.levels)), headers=admin_headers(self.app))

    def play(self, i):
        self.app.go(Play(self.app, self.levels[i]["id"], back=self))

    def set_sort(self, sort):
        if sort != self.sort:
            self.sort = sort
            self.reload()

    def event(self, e):
        sorts = [k for k, _ in self.sorts()]
        if e.type == pygame.KEYDOWN:
            if e.key == pygame.K_ESCAPE:
                self.app.go(Menu(self.app))
            elif e.key == pygame.K_TAB:
                self.set_sort(sorts[(sorts.index(self.sort) + 1) % len(sorts)])
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
                self.set_sort(sorts[t])
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
        sub = {"all": "Every level, newest first, including unverified ones.",
               "unverified": "Nobody has beaten these yet. Be the first and verify one!"
               }.get(self.sort, "Every level here has been beaten at least once.")
        sub = f.font.render(sub, True, DIM)
        s.blit(sub, sub.get_rect(midtop=(w / 2, 100)))
        self.tab_rects = []
        sorts = self.sorts()
        for i, (key, label) in enumerate(sorts):
            r = pygame.Rect(0, 0, 180, 40)
            r.midtop = (w / 2 + (i - (len(sorts) - 1) / 2) * 192, 130)
            self.tab_rects.append(button(s, f, r, label, self.sort == key, pal["accent"], f.font))

        pw = min(1100, w - 40)
        area = pygame.Rect((w - pw) // 2, 190, pw, h - 250)
        draw_panel(s, area, 170)
        cols = [("ID", 16), ("NAME", 110), ("BY", 0.38), ("DIFFICULTY", 0.51), ("CLEARS", 0.75),
                ("BEST", 0.83)]

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
            rating, rcol = list_rating(lv)
            if self.sort == "all" and not lv.get("verified", 1):
                rating = "unverified  " + rating
            for text, c, col, font, limit_to in (
                    (lv["id"], 16, GOLD, f.mid, None), (lv["name"], 110, TEXT, f.mid, 0.38),
                    (lv["author"], 0.38, DIM, f.font, 0.51), (rating, 0.51, rcol, f.font, 0.75),
                    (str(lv["clears"]), 0.75, TEXT, f.font, None),
                    (f"{fmt_time(lv['best'])}  {lv.get('best_by') or ''}", 0.83, PLAYER_READY,
                     f.font, None)):
                img = font.render(text, True, col)
                if limit_to:
                    limit = cx(limit_to) - cx(c) - 10
                    if img.get_width() > limit:
                        img = img.subsurface((0, 0, limit, img.get_height()))
                s.blit(img, img.get_rect(midleft=(cx(c), yy)))
        s.set_clip(None)
        msg = None
        if self.error:
            msg = (self.error, RED)
        elif self.req and not self.levels:
            msg = ("Loading...", DIM)
        elif not self.levels:
            msg = ("No unverified levels right now." if self.sort == "unverified"
                   else "No verified levels yet. Make one and beat it!", DIM)
        if msg:
            img = f.mid.render(msg[0], True, msg[1])
            s.blit(img, img.get_rect(center=area.center))
        hint = f.font.render("ENTER play    TAB sort    ESC back", True, DIM)
        s.blit(hint, hint.get_rect(midbottom=(w / 2, h - 18)))


# ----------------------------------------------------------------- play ---
def draw_level_hud(s, fonts, run, title=None, sub=None, sub2=None, sub2_colour=DIM):
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
        lines = [x for x in (sub, sub2) if x]
        panel = pygame.Rect(16, 16, max(260, f.mid.size(title)[0] + 36), 46 + 26 * len(lines))
        for line in lines:
            panel.w = max(panel.w, f.font.size(line)[0] + 36)
        panel.w = min(panel.w, w // 2 - 160)
        draw_panel(s, panel)
        s.blit(f.mid.render(title, True, GOLD), (panel.x + 18, panel.y + 12))
        for i, line in enumerate(lines):
            col = sub2_colour if line is sub2 else DIM
            s.blit(f.font.render(line, True, col), (panel.x + 18, panel.y + 42 + i * 26))
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
    """Plays a shared level fetched by ID. Clearing it reports the time (the
    first clear ever verifies the level and uploads a recording of it), and
    you can suggest a difficulty. The admin can also rate it, watch the
    verifying clear and delete it."""

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
        self.masks = []          # inputs of every step since the last restart
        self.suggest_req = None
        self.suggested = None    # rating suggested after this clear, or an error
        self.picker = {}
        self.admin = None        # None, "rate" or "delete" (confirming)
        self.admin_req = None
        self.admin_msg = None
        self.admin_rects = {}
        self.mouse = (0, 0)
        self.t = 0.0

    def restart(self):
        self.run.restart()
        self.masks = []
        self.result = None
        self.suggested = None

    def event(self, e):
        if e.type == pygame.MOUSEMOTION:
            self.mouse = e.pos
        elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            self.click(e.pos)
        if e.type != pygame.KEYDOWN:
            return
        if e.key == pygame.K_ESCAPE:
            if self.admin:
                self.admin = None
            else:
                self.app.go(self.back)
        elif e.key == pygame.K_h:
            self.hitboxes = not self.hitboxes
        elif e.key == pygame.K_r and self.run and not self.clear_req:
            self.restart()

    def click(self, pos):
        if self.admin == "rate" or (self.run and self.run.finished and self.can_suggest()):
            r = next((r for r, rect in self.picker.items() if rect.collidepoint(pos)), None)
            if r is not None:
                if self.admin == "rate":
                    self.admin_post("rate", {"rating": r})
                else:
                    self.suggest_req = net.api("POST", f"/levels/{self.id}/suggest", {"rating": r})
                    self.suggested = r
                return
        name = next((n for n, rect in self.admin_rects.items() if rect.collidepoint(pos)), None)
        if name == "rate":
            self.admin = None if self.admin == "rate" else "rate"
        elif name == "unrate":
            self.admin_post("rate", {"rating": 0})
        elif name == "watch":
            self.admin_msg = "Loading recording..."
            self.admin_req = ("replay", net.api("GET", f"/levels/{self.id}/replay",
                                                headers=admin_headers(self.app)))
        elif name == "delete":
            if self.admin == "delete":
                self.admin_post("delete", {})
            else:
                self.admin = "delete"
                self.admin_msg = "Click Delete again to delete this level for good"

    def admin_post(self, action, body):
        body["code"] = admin_code(self.app)
        self.admin_req = (action, net.api("POST", f"/levels/{self.id}/{action}", body))
        self.admin_msg = "Saving..."

    def can_suggest(self):
        return (self.result and not self.result.error and self.suggested is None
                and not self.admin)

    def step(self, dt):
        self.t += dt
        if self.req and self.req.done:
            if self.req.error:
                self.error = self.req.error
            else:
                self.meta = self.req.data
                try:
                    objs, theme = load(self.meta["data"])
                    self.objs, self.theme = objs, theme
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
        if self.suggest_req and self.suggest_req.done:
            if self.suggest_req.error:
                self.suggested = self.suggest_req.error
            self.suggest_req = None
        if self.admin_req and self.admin_req[1].done:
            self.admin_done(*self.admin_req)
        if not self.run or self.admin:
            return                   # the admin rating grid pauses the level
        was = self.run.finished
        if not was:
            self.masks.append(input_mask(self.app.inp))
        self.run.step(dt, self.app.inp)
        if self.run.finished and not was:
            body = {"time": round(self.run.time, 4), "deaths": self.run.deaths,
                    "name": self.app.name or "Anonymous"}
            if not self.meta["verified"]:
                body["replay"] = encode_replay(self.masks)   # kept if this verifies it
            if admin_code(self.app):
                body["code"] = admin_code(self.app)
            self.clear_req = net.api("POST", f"/levels/{self.id}/clear", body)

    def admin_done(self, action, req):
        self.admin_req = None
        if req.error:
            self.admin_msg = req.error
            return
        if action == "rate":
            self.meta["rating"] = req.data["rating"] or None
            self.admin = None
            self.admin_msg = f"Rated {ratings.name(req.data['rating'])}"
        elif action == "delete":
            self.app.go(Browse(self.app))
        elif action == "replay":
            if not req.data.get("replay"):
                self.admin_msg = "No recording for this level's first clear"
                return
            self.admin_msg = None
            self.app.go(Replay(self.app, self.meta, self.objs, self.theme,
                               req.data["replay"], req.data.get("verified_by"), back=self))

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
        draw_level_hud(s, f, run, m["name"], f"{m['id']} by {m['author']}   {status}{best}",
                       rating_text(m), ratings.colour(m.get("rating")))
        if run.finished and not self.admin:
            self.draw_clear(s, f, run)
        if admin_code(self.app):
            self.draw_admin(s, f)

    def draw_admin(self, s, f):
        w, h = s.get_size()
        self.admin_rects = {}
        names = [("rate", "Rate"), ("unrate", "Unrate")]
        if self.meta.get("has_replay"):
            names.append(("watch", "Watch first clear"))
        names.append(("delete", "Delete"))
        x = 16
        y = h - 52
        lab = f.small.render("ADMIN", True, GOLD)
        s.blit(lab, (x, y - 20))
        for name, label in names:
            width = f.font.size(label)[0] + 30
            r = pygame.Rect(x, y, width, 36)
            col = RED if name == "delete" else GOLD
            hot = r.collidepoint(self.mouse) or self.admin == name
            self.admin_rects[name] = button(s, f, r, label, hot, col, f.font)
            x += width + 8
        if self.admin_msg:
            img = f.font.render(self.admin_msg, True, TEXT)
            s.blit(img, (x + 10, y + 8))
        if self.admin == "rate":
            shade_screen(s, 120)
            head = f.big.render("Rate this level", True, GOLD)
            s.blit(head, head.get_rect(center=(w / 2, h / 2 - 210)))
            self.picker = ratings.picker(s, f, (w / 2, h / 2 + 10), self.mouse, m_rating(self.meta))

    def draw_clear(self, s, f, run):
        w, h = s.get_size()
        shade_screen(s, 150)
        y = max(110, h // 2 - 290)       # below the run timer
        head = f.huge.render("CLEARED", True, GOLD)
        s.blit(head, head.get_rect(midtop=(w / 2, y)))
        t = f.big.render(f"{fmt_time(run.time)}    {run.deaths} death{'' if run.deaths == 1 else 's'}",
                         True, TEXT)
        s.blit(t, t.get_rect(midtop=(w / 2, y + 70)))
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
        s.blit(img, img.get_rect(midtop=(w / 2, y + 125)))
        self.picker = {}
        if self.can_suggest():
            lab = f.mid.render("How hard was it? Suggest a difficulty (optional)", True, TEXT)
            s.blit(lab, lab.get_rect(midtop=(w / 2, y + 175)))
            self.picker = ratings.picker(s, f, (w / 2, y + 220 + 150), self.mouse)
        elif self.suggested is not None:
            if isinstance(self.suggested, str):
                text, col = self.suggested, RED
            else:
                text, col = f"Thanks! You suggested {ratings.name(self.suggested)}.", GREEN
            img = f.mid.render(text, True, col)
            s.blit(img, img.get_rect(midtop=(w / 2, y + 175)))
        hint = f.font.render("R  play again    ESC back", True, DIM)
        s.blit(hint, hint.get_rect(midbottom=(w / 2, h - 20)))


def m_rating(meta):
    return meta.get("rating") or 0


# --------------------------------------------------------------- replay ---
class Replay:
    """Plays back a recorded clear: the same inputs, step by step, through the
    same physics, so it does exactly what the player did."""

    def __init__(self, app, meta, objs, theme, text, by, back):
        self.app = app
        self.meta = meta
        self.back = back
        self.by = by or "someone"
        self.masks = decode_replay(text)
        self.objs, self.theme = objs, theme
        self.inp = Input()
        self.hitboxes = False
        self.slow = False
        self.paused = False
        self.step_once = False
        self.acc = 0.0
        self.reset()

    def reset(self):
        self.run = Run(self.objs, self.theme)
        self.i = 0

    def event(self, e):
        if e.type != pygame.KEYDOWN:
            return
        if e.key == pygame.K_ESCAPE:
            self.app.go(self.back)
        elif e.key == pygame.K_r:
            self.reset()
        elif e.key == pygame.K_h:
            self.hitboxes = not self.hitboxes
        elif e.key == pygame.K_TAB:
            self.slow = not self.slow
        elif e.key == pygame.K_COMMA:
            self.paused = not self.paused
        elif e.key == pygame.K_PERIOD:
            self.paused = True
            self.step_once = True

    def step(self, dt):
        if self.paused:
            if not self.step_once:
                return
            self.step_once = False
        elif self.slow:
            self.acc += 0.25
            if self.acc < 1:
                return
            self.acc -= 1
        if self.i < len(self.masks) and not self.run.finished:
            apply_mask(self.inp, self.masks[self.i])
            self.i += 1
            self.run.step(DT, self.inp)

    def draw(self, s):
        f = self.app.fonts
        w, h = s.get_size()
        run = self.run
        alpha = 1.0 if self.paused or self.slow else self.app.alpha
        cam = level_camera(s, run, alpha)
        draw_sky(s, cam, PALETTES[run.theme])
        run.draw(s, cam, f, self.hitboxes, alpha)
        done = self.i >= len(self.masks) or run.finished
        if run.finished:
            state, col = f"Reached the finish in {fmt_time(run.time)}", GREEN
        elif done:
            state, col = "Recording ended before the finish", RED
        else:
            state, col = f"{self.i / max(1, len(self.masks)) * 100:.0f}%", DIM
        draw_level_hud(s, f, run, f"REPLAY   first clear by {self.by}",
                       "ESC back   R restart   H hitboxes   TAB slow   , pause   . step",
                       state, col)
        bar = pygame.Rect(w // 4, h - 14, w // 2, 6)
        pygame.draw.rect(s, PANEL, bar)
        pygame.draw.rect(s, GOLD, (bar.x, bar.y, bar.w * self.i / max(1, len(self.masks)), bar.h))
