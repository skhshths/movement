"""
The level creator.

Place blocks with the mouse, see exact hitboxes, measure gaps against the
player's hitbox and movement speeds, playtest instantly, then publish. A
published level gets a six-character ID anyone can play; the first person to
beat it verifies it and puts it on the public list.

MOUSE
  left           place the current block (drag to size it) / select and move
  right          delete (hold and drag to erase)
  middle drag    pan        wheel   zoom
KEYS
  1-9, 0         first ten blocks       Q / E   previous / next tool
  WASD           pan                    arrows  nudge selection by the grid
  R              rotate selection       [ ]     power down / up
  G              grid size              H       hitboxes
  P              player reference       T       theme
  CTRL+C / X     copy / cut             CTRL+V  paste (click to place copies)
  CTRL+D         duplicate              DEL     delete selection
  CTRL+Z / Y     undo / redo            HOME    jump to the start
  ENTER          playtest               M       spawn at start / at cursor
  ESC            deselect, then leave
In a playtest: ESC back to editing, R restart, H hitboxes, TAB slow motion,
COMMA pause, PERIOD step one frame while paused.
"""
import math

import pygame

import net
from levels import KINDS, ORDER, SIZE_MAX, Obj, Run, draw_objects, dump, level_info_line, load
from player import DASH_SPEED, DASH_TIME, GRAVITY, JUMP_V, RUN_SPEED, Input, Player
from scenes import Menu, Play, draw_level_hud, hovered, level_camera
from ui import (DIM, GOLD, GREEN, INK, PANEL, RED, TEXT, TextBox, button, draw_panel, draw_sky,
                fmt_time, shade_screen, tint_rect)
from world import PALETTES, mix

GRIDS = [1, 2, 4, 8, 16, 32, 64]
ZOOMS = [0.25, 0.35, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0]
TOOLS = ["select", "measure"] + ORDER
THEMES = list(PALETTES)
REF = (60, 255, 120)          # player reference colour
SIDEBAR_W = 190
TOPBAR_H = 52
BOTTOMBAR_H = 34
RUN_PF = RUN_SPEED / 120      # px per frame
DASH_PF = DASH_SPEED / 120

HELP = ["MOUSE"] + [l for l in __doc__.split("MOUSE", 1)[1].splitlines() if l.strip()]


def new_level():
    return [Obj("wall", -256, 64, 1792, 128), Obj("start", 0, 32, 32, 32),
            Obj("finish", 1280, 0, 48, 64)]


class Editor:
    def __init__(self, app):
        self.app = app
        draft = net.load("draft")
        self.objs, self.theme, self.title = new_level(), "lowmarket", ""
        if draft:
            try:
                self.objs, self.theme = load(draft["data"])
                self.title = draft.get("name", "")
            except (ValueError, KeyError, TypeError):
                pass
        self.zoom = 1.0
        self.cam = pygame.Vector2(-300, -400)
        self.home()
        self.tool = "wall"
        self.grid_i = GRIDS.index(16)
        self.hitboxes = False
        self.ghost = True
        self.from_cursor = False   # playtests spawn at the mouse instead of the start
        self.sel = set()
        self.undo_stack, self.redo_stack = [], []
        self.clip = []
        self.pasting = False    # clipboard follows the mouse; click to place it
        self.sel_buttons = {}   # copy / cut / duplicate / delete over the selection
        self.drag = None
        self.panning = False
        self.erasing = False
        self.mouse = (0, 0)
        self.t = 0.0
        self.dirty_t = None
        self.help = False
        self.modal = None       # publish dialog
        self.test = None        # Run while playtesting
        self.test_inp = Input()
        self.slow = False
        self.paused = False
        self.step_once = False
        self.slow_acc = 0.0
        self.ui = {}            # button name -> rect
        self.toast = None       # [text, colour, age]
        self.tool_rects = []

    # -- helpers ------------------------------------------------------------
    @property
    def grid(self):
        return GRIDS[self.grid_i]

    def to_world(self, pos):
        return pygame.Vector2(pos[0] / self.zoom + self.cam.x, pos[1] / self.zoom + self.cam.y)

    def to_screen(self, x, y):
        return ((x - self.cam.x) * self.zoom, (y - self.cam.y) * self.zoom)

    def snap(self, v):
        g = self.grid
        return round(v / g) * g

    def home(self):
        start = next((o for o in self.objs if o.t == "start"), None)
        if start:
            w, h = self.app.screen.get_size()
            self.cam = pygame.Vector2(start.x - w / 2 / self.zoom, start.y - h / 2 / self.zoom)

    def snapshot(self):
        return ([o.to_list() for o in self.objs], self.theme)

    def push_undo(self):
        self.undo_stack.append(self.snapshot())
        del self.undo_stack[:-200]
        self.redo_stack.clear()
        self.dirty_t = self.dirty_t or 0.0

    def restore(self, snap):
        objs, self.theme = snap
        self.objs = [Obj(*o) for o in objs]
        self.sel.clear()
        self.dirty_t = self.dirty_t or 0.0

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(self.snapshot())
            self.restore(self.undo_stack.pop())

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(self.snapshot())
            self.restore(self.redo_stack.pop())

    def save_draft(self):
        net.save("draft", {"name": self.title, "data": dump(self.objs, self.theme)})
        self.dirty_t = None

    def pick(self, wpos):
        """Topmost object under a world point; zones lose to everything else."""
        best = None
        for i in range(len(self.objs) - 1, -1, -1):
            o = self.objs[i]
            if o.t == "saw":
                hit = math.dist(wpos, (o.x + o.w / 2, o.y + o.h / 2)) <= o.w / 2 + 2
            else:
                hit = o.rect.collidepoint(wpos)
            if hit:
                if o.kind.group != "zone":
                    return i
                if best is None:
                    best = i
        return best

    def targets(self):
        """Selection, or whatever is under the mouse."""
        if self.sel:
            return sorted(self.sel)
        i = self.pick(self.to_world(self.mouse))
        return [] if i is None else [i]

    def in_ui(self, pos):
        w, h = self.app.screen.get_size()
        return pos[0] < SIDEBAR_W or pos[1] < TOPBAR_H or pos[1] > h - BOTTOMBAR_H

    # -- editing ------------------------------------------------------------
    def place(self, kind, rect=None, wpos=None):
        k = KINDS[kind]
        self.push_undo()
        d = 1 if kind == "boost" else 0
        if rect is None:
            w, h = k.size
            x, y = self.snap(wpos.x - w / 2), self.snap(wpos.y - h / 2)
            rect = pygame.Rect(x, y, w, h)
        if kind == "start":
            self.objs = [o for o in self.objs if o.t != "start"]
        self.objs.append(Obj(kind, rect.x, rect.y, rect.w, rect.h, d, 3 if k.power else 1))
        self.sel = {len(self.objs) - 1}

    def delete(self, idxs):
        if not idxs:
            return
        self.push_undo()
        drop = set(idxs)
        self.objs = [o for i, o in enumerate(self.objs) if i not in drop]
        self.sel.clear()

    def adjust(self, rotate=0, power=0):
        idxs = self.targets()
        if not idxs:
            return
        self.push_undo()
        for i in idxs:
            o = self.objs[i]
            k = o.kind
            if rotate and k.dirs:
                o.d = (o.d + rotate) % (4 if k.dirs == 4 else 2)
            if power and k.power:
                o.p = max(1, min(5, o.p + power))

    def nudge(self, dx, dy):
        if not self.sel:
            return
        self.push_undo()
        for i in self.sel:
            self.objs[i].x += dx * self.grid
            self.objs[i].y += dy * self.grid

    def copy(self, cut=False):
        if not self.sel:
            return
        # the start is unique, so it never goes on the clipboard
        self.clip = [self.objs[i].to_list() for i in sorted(self.sel) if self.objs[i].t != "start"]
        n = len(self.clip)
        plural = "" if n == 1 else "s"
        self.toast = [f"{'Cut' if cut else 'Copied'} {n} block{plural}", GOLD, 0.0]
        if cut:
            self.delete(self.sel)

    def start_paste(self):
        if not self.clip:
            self.toast = ["Nothing copied yet", RED, 0.0]
            return
        self.pasting = True
        self.tool = "select"
        self.sel.clear()

    def paste_offset(self):
        """Shift that puts the clipboard's top-left corner on the cursor."""
        wpos = self.to_world(self.mouse)
        x0 = min(o[1] for o in self.clip)
        y0 = min(o[2] for o in self.clip)
        return self.snap(wpos.x) - x0, self.snap(wpos.y) - y0

    def paste(self):
        self.push_undo()
        dx, dy = self.paste_offset()
        start = len(self.objs)
        for o in self.clip:
            self.objs.append(Obj(o[0], o[1] + dx, o[2] + dy, *o[3:]))
        self.sel = set(range(start, len(self.objs)))

    def duplicate(self):
        self.copy()
        self.start_paste()

    def selection_button(self, name):
        if name == "copy":
            self.copy()
        elif name == "cut":
            self.copy(cut=True)
        elif name == "duplicate":
            self.duplicate()
        elif name == "delete":
            self.delete(self.sel)

    def set_zoom(self, i, anchor):
        i = max(0, min(len(ZOOMS) - 1, i))
        before = self.to_world(anchor)
        self.zoom = ZOOMS[i]
        after = self.to_world(anchor)
        self.cam += before - after

    def playtest(self):
        here = self.from_cursor
        if not any(o.t == "start" for o in self.objs) and not here:
            self.toast = ["Place a start first", RED, 0.0]
            return
        spawn = None
        if here:
            wpos = self.to_world(self.mouse)
            spawn = (wpos.x, wpos.y + Player.H_STAND / 2)
        self.save_draft()
        self.test = Run(self.objs, self.theme, spawn)
        self.slow = self.paused = False

    # -- events ---------------------------------------------------------------
    def event(self, e):
        if self.modal:
            self.modal_event(e)
        elif self.test:
            self.test_event(e)
        else:
            self.edit_event(e)

    def test_event(self, e):
        if e.type != pygame.KEYDOWN:
            return
        if e.key == pygame.K_ESCAPE:
            self.test = None
        elif e.key == pygame.K_r:
            self.test.restart()
        elif e.key == pygame.K_h:
            self.hitboxes = not self.hitboxes
        elif e.key == pygame.K_TAB:
            self.slow = not self.slow
        elif e.key == pygame.K_COMMA:
            self.paused = not self.paused
        elif e.key == pygame.K_PERIOD:
            self.paused = True
            self.step_once = True

    def edit_event(self, e):
        mods = pygame.key.get_mods()
        ctrl = mods & (pygame.KMOD_CTRL | pygame.KMOD_META)
        shift = mods & pygame.KMOD_SHIFT
        if e.type == pygame.KEYDOWN:
            k = e.key
            if self.help:
                self.help = False
                return
            if ctrl and k == pygame.K_z:
                self.redo() if shift else self.undo()
            elif ctrl and k == pygame.K_y:
                self.redo()
            elif ctrl and k == pygame.K_a:
                self.sel = set(range(len(self.objs)))
            elif ctrl and k == pygame.K_c:
                self.copy()
            elif ctrl and k == pygame.K_x:
                self.copy(cut=True)
            elif ctrl and k == pygame.K_v:
                self.start_paste()
            elif ctrl and k == pygame.K_d:
                self.duplicate()
            elif ctrl:
                return
            elif k == pygame.K_ESCAPE:
                if self.pasting:
                    self.pasting = False
                elif self.sel:
                    self.sel.clear()
                elif self.tool != "select":
                    self.tool = "select"
                else:
                    self.leave()
            elif pygame.K_1 <= k <= pygame.K_9 or k == pygame.K_0:
                n = 9 if k == pygame.K_0 else k - pygame.K_1
                self.tool = ORDER[n]
                self.sel.clear()
                self.pasting = False
            elif k in (pygame.K_q, pygame.K_e):
                i = TOOLS.index(self.tool) + (1 if k == pygame.K_e else -1)
                self.tool = TOOLS[i % len(TOOLS)]
            elif k == pygame.K_r:
                self.adjust(rotate=-1 if shift else 1)
            elif k == pygame.K_RIGHTBRACKET:
                self.adjust(power=1)
            elif k == pygame.K_LEFTBRACKET:
                self.adjust(power=-1)
            elif k == pygame.K_g:
                self.grid_i = (self.grid_i + (-1 if shift else 1)) % len(GRIDS)
            elif k == pygame.K_h:
                self.hitboxes = not self.hitboxes
            elif k == pygame.K_p:
                self.ghost = not self.ghost
            elif k == pygame.K_t:
                self.cycle_theme()
            elif k == pygame.K_c:
                self.copy()
            elif k == pygame.K_x:
                self.copy(cut=True)
            elif k == pygame.K_v:
                self.start_paste()
            elif k in (pygame.K_DELETE, pygame.K_BACKSPACE):
                self.delete(self.sel)
            elif k == pygame.K_LEFT:
                self.nudge(-1, 0)
            elif k == pygame.K_RIGHT:
                self.nudge(1, 0)
            elif k == pygame.K_UP:
                self.nudge(0, -1)
            elif k == pygame.K_DOWN:
                self.nudge(0, 1)
            elif k == pygame.K_HOME:
                self.home()
            elif k == pygame.K_RETURN:
                self.playtest()
            elif k == pygame.K_m:
                self.from_cursor = not self.from_cursor
            elif k in (pygame.K_F1, pygame.K_SLASH):
                self.help = True
        elif e.type == pygame.MOUSEMOTION:
            self.mouse = e.pos
            if self.panning:
                self.cam -= pygame.Vector2(e.rel) / self.zoom
            if self.erasing:
                i = self.pick(self.to_world(e.pos))
                if i is not None:
                    self.objs.pop(i)
                    self.sel.clear()
            if self.drag:
                self.drag_update()
        elif e.type == pygame.MOUSEWHEEL:
            if not self.in_ui(self.mouse):
                self.set_zoom(ZOOMS.index(self.zoom) + (1 if e.y > 0 else -1), self.mouse)
        elif e.type == pygame.MOUSEBUTTONDOWN:
            self.mouse = e.pos
            if e.button == 2:
                self.panning = True
            elif e.button == 3 and self.pasting:
                self.pasting = False
            elif e.button == 3 and not self.in_ui(e.pos):
                self.push_undo()
                self.erasing = True
                i = self.pick(self.to_world(e.pos))
                if i is not None:
                    self.objs.pop(i)
                    self.sel.clear()
            elif e.button == 1:
                hit = next((n for n, r in self.sel_buttons.items() if r.collidepoint(e.pos)), None)
                if hit:
                    self.selection_button(hit)
                elif self.in_ui(e.pos):
                    self.click_ui(e.pos)
                elif self.pasting:
                    self.paste()           # keep placing copies until ESC
                else:
                    self.drag_start(e.pos, shift)
        elif e.type == pygame.MOUSEBUTTONUP:
            if e.button == 2:
                self.panning = False
            elif e.button == 3:
                self.erasing = False
            elif e.button == 1 and self.drag:
                self.drag_end()

    def cycle_theme(self):
        self.push_undo()
        self.theme = THEMES[(THEMES.index(self.theme) + 1) % len(THEMES)]

    def leave(self):
        self.save_draft()
        self.app.go(Menu(self.app))

    def click_ui(self, pos):
        i = hovered(self.tool_rects, pos)
        if i is not None:
            self.tool = TOOLS[i]
            self.sel.clear()
            self.pasting = False
            return
        for name, r in self.ui.items():
            if r.collidepoint(pos):
                if name == "test":
                    self.playtest()
                elif name == "publish":
                    self.open_publish()
                elif name == "spawn":
                    self.from_cursor = not self.from_cursor
                elif name == "theme":
                    self.cycle_theme()
                elif name == "new":
                    self.push_undo()
                    self.objs = new_level()
                    self.sel.clear()
                    self.title = ""
                    self.home()
                elif name == "menu":
                    self.leave()
                elif name == "help":
                    self.help = True
                return

    # -- dragging -------------------------------------------------------------
    def drag_start(self, pos, shift):
        wpos = self.to_world(pos)
        tool = self.tool
        if tool == "measure":
            self.drag = dict(mode="measure", a=pygame.Vector2(self.snap(wpos.x), self.snap(wpos.y)))
        elif tool == "select":
            # bottom-right handle of a single selected block resizes it
            if len(self.sel) == 1:
                o = self.objs[next(iter(self.sel))]
                hx, hy = self.to_screen(o.x + o.w, o.y + o.h)
                if o.kind.resize and abs(pos[0] - hx) < 10 and abs(pos[1] - hy) < 10:
                    self.push_undo()
                    self.drag = dict(mode="resize", i=next(iter(self.sel)))
                    return
            i = self.pick(wpos)
            if i is None:
                if not shift:
                    self.sel.clear()
                self.drag = dict(mode="box", a=wpos)
                return
            if shift:
                self.sel ^= {i}
            elif i not in self.sel:
                self.sel = {i}
            self.push_undo()
            self.drag = dict(mode="move", a=wpos,
                             orig={j: (self.objs[j].x, self.objs[j].y) for j in self.sel})
        elif KINDS[tool].resize:
            self.drag = dict(mode="place", a=pygame.Vector2(self.snap(wpos.x), self.snap(wpos.y)))
        else:
            self.place(tool, wpos=wpos)
        self.drag_update()

    def drag_rect(self):
        """The block a place-drag would make, in world coordinates."""
        a = self.drag["a"]
        b = self.to_world(self.mouse)
        b = pygame.Vector2(self.snap(b.x), self.snap(b.y))
        x0, x1 = sorted((a.x, b.x))
        y0, y1 = sorted((a.y, b.y))
        if (x0, y0) == (x1, y1):
            return pygame.Rect(x0, y0, *KINDS[self.tool].size)   # a click: default size
        g = self.grid
        return pygame.Rect(x0, y0, min(SIZE_MAX, max(g, x1 - x0)), min(SIZE_MAX, max(g, y1 - y0)))

    def drag_update(self):
        d = self.drag
        if not d:
            return
        wpos = self.to_world(self.mouse)
        if d["mode"] == "move":
            dx = self.snap(wpos.x - d["a"].x)
            dy = self.snap(wpos.y - d["a"].y)
            for j, (x, y) in d["orig"].items():
                self.objs[j].x, self.objs[j].y = x + dx, y + dy
        elif d["mode"] == "resize":
            o = self.objs[d["i"]]
            o.w = min(SIZE_MAX, max(1, self.snap(wpos.x) - o.x))
            o.h = min(SIZE_MAX, max(1, self.snap(wpos.y) - o.y))

    def drag_end(self):
        d = self.drag
        self.drag = None
        if d["mode"] == "place":
            self.drag = d
            rect = self.drag_rect()
            self.drag = None
            self.place(self.tool, rect)
        elif d["mode"] == "box":
            b = self.to_world(self.mouse)
            r = pygame.FRect(min(d["a"].x, b.x), min(d["a"].y, b.y),
                             abs(b.x - d["a"].x), abs(b.y - d["a"].y))
            if r.w > 2 or r.h > 2:
                self.sel |= {i for i, o in enumerate(self.objs) if r.colliderect(o.rect)}
        elif d["mode"] == "move":
            if all((self.objs[j].x, self.objs[j].y) == xy for j, xy in d["orig"].items()):
                self.undo_stack.pop()       # just a click, nothing moved

    # -- publishing -------------------------------------------------------------
    def open_publish(self):
        starts = sum(o.t == "start" for o in self.objs)
        problem = None
        if starts != 1:
            problem = "Your level needs a start."
        elif not any(o.t == "finish" for o in self.objs):
            problem = "Your level needs a finish."
        self.modal = dict(name=TextBox(self.title, 40), author=TextBox(self.app.name, 24),
                          field="name", req=None, result=None, error=problem)

    def modal_event(self, e):
        m = self.modal
        if e.type == pygame.TEXTINPUT and not m["result"]:
            m[m["field"]].key(e)
        if e.type != pygame.KEYDOWN:
            return
        if m["result"]:
            if e.key == pygame.K_RETURN:
                self.modal = None
                self.app.go(Play(self.app, m["result"], back=self))
            elif e.key == pygame.K_ESCAPE:
                self.modal = None
            return
        if e.key == pygame.K_ESCAPE:
            self.modal = None
        elif e.key == pygame.K_TAB:
            m["field"] = "author" if m["field"] == "name" else "name"
        elif e.key == pygame.K_RETURN:
            if m["req"] or (m["error"] and "needs" in m["error"]):
                return
            name = m["name"].value.strip()
            if not name:
                m["error"] = "Give your level a name."
                return
            self.title = name
            self.app.name = m["author"].value.strip()
            net.save("name", self.app.name)
            self.save_draft()
            m["error"] = None
            m["req"] = net.api("POST", "/levels", {"name": name, "author": self.app.name or "Anonymous",
                                                   "data": dump(self.objs, self.theme)})
        else:
            m[m["field"]].key(e)

    def modal_step(self):
        m = self.modal
        req = m["req"]
        if req and req.done:
            m["req"] = None
            if req.error:
                m["error"] = req.error
            else:
                m["result"] = req.data["id"]
                mine = net.load("published", []) or []
                mine.insert(0, {"id": m["result"], "name": self.title})
                net.save("published", mine[:50])

    # -- update -----------------------------------------------------------------
    def step(self, dt):
        self.t += dt
        if self.toast:
            self.toast[2] += dt
            if self.toast[2] > 2.5:
                self.toast = None
        if self.modal:
            self.modal_step()
        if self.test:
            self.test_step(dt)
            return
        if self.dirty_t is not None:
            self.dirty_t += dt
            if self.dirty_t > 3:
                self.save_draft()
        if self.modal or pygame.key.get_mods() & (pygame.KMOD_CTRL | pygame.KMOD_META):
            return
        k = pygame.key.get_pressed()
        speed = 900 * (3 if k[pygame.K_LSHIFT] or k[pygame.K_RSHIFT] else 1) / self.zoom
        self.cam.x += (k[pygame.K_d] - k[pygame.K_a]) * speed * dt
        self.cam.y += (k[pygame.K_s] - k[pygame.K_w]) * speed * dt

    def test_step(self, dt):
        inp = self.app.inp
        ti = self.test_inp
        # presses are latched so slow motion and pausing don't drop them
        ti.jump_pressed |= inp.jump_pressed
        ti.dash_pressed |= inp.dash_pressed
        for name in ("left", "right", "up", "down", "jump_held"):
            setattr(ti, name, getattr(inp, name))
        if self.paused:
            if not self.step_once:
                return
            self.step_once = False
        elif self.slow:
            self.slow_acc += 0.25
            if self.slow_acc < 1:
                return
            self.slow_acc -= 1
        if not self.test.finished:
            self.test.step(dt, ti)
        ti.jump_pressed = ti.dash_pressed = False

    # -- drawing ----------------------------------------------------------------
    def draw(self, s):
        f = self.app.fonts
        if self.test:
            self.draw_test(s, f)
            return
        w, h = s.get_size()
        draw_sky(s, self.cam, PALETTES[self.theme])
        self.draw_grid(s)
        draw_objects(s, self.cam, self.zoom, self.objs, self.theme, self.t, None,
                     self.hitboxes, f, self.sel)
        self.draw_handles(s)
        on_bar = any(r.collidepoint(self.mouse) for r in self.sel_buttons.values())
        if self.pasting and not self.in_ui(self.mouse):
            self.draw_paste_ghost(s, f)
        elif not self.in_ui(self.mouse) and not self.panning and not on_bar:
            self.draw_cursor(s, f)
        self.draw_selection_bar(s, f)
        self.draw_bars(s, f)
        if self.toast:
            img = f.mid.render(self.toast[0], True, self.toast[1])
            r = img.get_rect(midtop=(w / 2, TOPBAR_H + 20))
            draw_panel(s, r.inflate(24, 14), 220)
            s.blit(img, r)
        if self.help:
            self.draw_help(s, f)
        if self.modal:
            self.draw_modal(s, f)

    def draw_grid(self, s):
        w, h = s.get_size()
        pal = PALETTES[self.theme]
        g = self.grid
        while g * self.zoom < 8:
            g *= 2
        minor = mix(pal["sky_bot"], (255, 255, 255), 0.06)
        major = mix(pal["sky_bot"], (255, 255, 255), 0.2)
        x0 = math.floor(self.cam.x / g) * g
        y0 = math.floor(self.cam.y / g) * g
        x = x0
        while (x - self.cam.x) * self.zoom < w:
            sx = (x - self.cam.x) * self.zoom
            pygame.draw.line(s, major if x % 256 == 0 else minor, (sx, 0), (sx, h))
            x += g
        y = y0
        while (y - self.cam.y) * self.zoom < h:
            sy = (y - self.cam.y) * self.zoom
            pygame.draw.line(s, major if y % 256 == 0 else minor, (0, sy), (w, sy))
            y += g
        ox, oy = self.to_screen(0, 0)
        pygame.draw.circle(s, major, (ox, oy), 4, 1)

    def draw_handles(self, s):
        if len(self.sel) == 1:
            o = self.objs[next(iter(self.sel))]
            if o.kind.resize:
                hx, hy = self.to_screen(o.x + o.w, o.y + o.h)
                pygame.draw.rect(s, GOLD, (hx - 5, hy - 5, 10, 10))
                pygame.draw.rect(s, INK, (hx - 5, hy - 5, 10, 10), 1)

    def draw_paste_ghost(self, s, f):
        dx, dy = self.paste_offset()
        z = self.zoom
        for o in self.clip:
            x, y = self.to_screen(o[1] + dx, o[2] + dy)
            r = pygame.Rect(round(x), round(y), max(1, round(o[3] * z)), max(1, round(o[4] * z)))
            tint_rect(s, r, KINDS[o[0]].colour, 110)
            pygame.draw.rect(s, KINDS[o[0]].colour, r, 1)
        n = len(self.clip)
        plural = "" if n == 1 else "s"
        self.label(s, f, f"click to place {n} block{plural}   ESC / right-click done",
                   self.mouse, GOLD)

    def draw_selection_bar(self, s, f):
        """Copy / cut / duplicate / delete buttons just above the selection."""
        self.sel_buttons = {}
        if not self.sel or self.drag or self.pasting or self.tool != "select":
            return
        boxes = [self.objs[i].rect for i in self.sel]
        x, y = self.to_screen(min(r.left for r in boxes), min(r.top for r in boxes))
        w, h = s.get_size()
        bw, bh, gap = 92, 28, 6
        names = (("copy", "Copy"), ("cut", "Cut"), ("duplicate", "Duplicate"), ("delete", "Delete"))
        total = len(names) * (bw + gap)
        x = max(SIDEBAR_W + 8, min(x, w - total - 8))
        y = max(TOPBAR_H + 8, min(y - bh - 10, h - BOTTOMBAR_H - bh - 40))
        accent = PALETTES[self.theme]["accent"]
        for k, (name, label) in enumerate(names):
            r = pygame.Rect(x + k * (bw + gap), y, bw, bh)
            colour = RED if name == "delete" else accent
            self.sel_buttons[name] = button(s, f, r, label, r.collidepoint(self.mouse), colour, f.small)

    def label(self, s, f, text, pos, colour=TEXT):
        img = f.small.render(text, True, colour)
        r = img.get_rect(topleft=(pos[0] + 14, pos[1] + 14))
        w, h = s.get_size()
        if r.right > w - 8:             # keep it on screen
            r.right = pos[0] - 14
        r.bottom = min(r.bottom, h - BOTTOMBAR_H - 8)
        draw_panel(s, r.inflate(10, 6), 210, radius=6)
        s.blit(img, r)

    def draw_cursor(self, s, f):
        wpos = self.to_world(self.mouse)
        sp = (self.snap(wpos.x), self.snap(wpos.y))
        if self.ghost:
            self.draw_reference(s, f, sp)
        d = self.drag
        if d and d["mode"] == "place":
            r = self.drag_rect()
            sr = pygame.Rect(*self.to_screen(r.x, r.y), r.w * self.zoom, r.h * self.zoom)
            pygame.draw.rect(s, KINDS[self.tool].colour, sr, 2)
            self.label(s, f, f"{r.w} x {r.h}   ({r.w / RUN_PF:.1f} frames run, "
                             f"{r.w / DASH_PF:.1f} dash)", self.mouse)
        elif d and d["mode"] == "measure":
            a = d["a"]
            b = pygame.Vector2(sp)
            pygame.draw.line(s, GOLD, self.to_screen(*a), self.to_screen(*b), 2)
            for p in (a, b):
                pygame.draw.circle(s, GOLD, self.to_screen(*p), 4)
            dx, dy = b.x - a.x, b.y - a.y
            dist = math.hypot(dx, dy)
            self.label(s, f, f"dx {dx:g}  dy {dy:g}  length {dist:.1f}   "
                             f"{dist / RUN_PF:.1f} frames at run, {dist / DASH_PF:.1f} at dash",
                       self.mouse, GOLD)
        elif d and d["mode"] == "box":
            a = self.to_screen(*d["a"])
            r = pygame.Rect(min(a[0], self.mouse[0]), min(a[1], self.mouse[1]),
                            abs(self.mouse[0] - a[0]), abs(self.mouse[1] - a[1]))
            pygame.draw.rect(s, GOLD, r, 1)
        elif self.tool not in ("select", "measure"):
            k = KINDS[self.tool]
            if k.resize:
                x, y = self.to_screen(*sp)
                pygame.draw.line(s, k.colour, (x - 8, y), (x + 8, y), 2)
                pygame.draw.line(s, k.colour, (x, y - 8), (x, y + 8), 2)
            else:
                w, h = k.size
                x, y = self.snap(wpos.x - w / 2), self.snap(wpos.y - h / 2)
                sx, sy = self.to_screen(x, y)
                pygame.draw.rect(s, k.colour, (sx, sy, w * self.zoom, h * self.zoom), 1)

    def draw_reference(self, s, f, sp):
        """Ghost of the player's hitbox at the cursor, with a full jump arc
        each way and where a dash ends, to size gaps and climbs exactly."""
        z = self.zoom
        pw, ph, sh = Player.WIDTH, Player.H_STAND, Player.H_SLIDE
        bx, by = sp                                   # bottom-centre of the player
        r = pygame.Rect(*self.to_screen(bx - pw / 2, by - ph), pw * z, ph * z)
        pygame.draw.rect(s, REF, r, 1)
        slide = pygame.Rect(*self.to_screen(bx - pw / 2, by - sh), pw * z, sh * z)
        for x in range(slide.left, slide.right, 6):
            pygame.draw.line(s, REF, (x, slide.top), (x + 2, slide.top))
        air = 2 * JUMP_V / GRAVITY
        for side in (-1, 1):
            pts = []
            for n in range(0, int(air * 60) + 1):
                t = n / 60
                pts.append(self.to_screen(bx + side * RUN_SPEED * t,
                                          by - JUMP_V * t + GRAVITY * t * t / 2))
            for p in pts[::2]:
                pygame.draw.circle(s, mix(REF, INK, 0.3), p, 2)
        top = JUMP_V ** 2 / (2 * GRAVITY)
        apex = pygame.Rect(*self.to_screen(bx - pw / 2, by - ph - top), pw * z, ph * z)
        pygame.draw.rect(s, mix(REF, INK, 0.5), apex, 1)
        reach = DASH_SPEED * DASH_TIME
        cx, cy = bx, by - ph / 2
        for a in range(8):
            ang = a * math.pi / 4
            p = self.to_screen(cx + math.cos(ang) * reach, cy + math.sin(ang) * reach)
            pygame.draw.line(s, REF, (p[0] - 3, p[1]), (p[0] + 3, p[1]))
            pygame.draw.line(s, REF, (p[0], p[1] - 3), (p[0], p[1] + 3))
        if z >= 0.75:
            img = f.small.render(f"{pw}x{ph}", True, REF)
            s.blit(img, img.get_rect(midbottom=(r.centerx, r.top - 2)))

    def draw_bars(self, s, f):
        w, h = s.get_size()
        pal = PALETTES[self.theme]
        accent = pal["accent"]
        # top bar
        pygame.draw.rect(s, PANEL, (0, 0, w, TOPBAR_H))
        pygame.draw.line(s, accent, (0, TOPBAR_H), (w, TOPBAR_H), 2)
        title = f.mid.render("LEVEL CREATOR", True, GOLD)
        s.blit(title, (16, 15))
        x = SIDEBAR_W + 20
        self.ui = {}
        for name, label, width in (("test", "Playtest  ENTER", 170),
                                   ("spawn", "Spawn: " + ("cursor" if self.from_cursor else "start"), 150),
                                   ("publish", "Publish", 110),
                                   ("theme", f"Theme: {self.theme.title()}", 200),
                                   ("new", "New", 70), ("help", "Keys", 80), ("menu", "Menu", 90)):
            r = pygame.Rect(x, 8, width, 36)
            hot = r.collidepoint(self.mouse)
            self.ui[name] = button(s, f, r, label, hot, accent, f.font)
            x += width + 10
        # sidebar of tools
        pygame.draw.rect(s, PANEL, (0, TOPBAR_H, SIDEBAR_W, h - TOPBAR_H))
        row = max(18, min(30, (h - TOPBAR_H - BOTTOMBAR_H - 12) // len(TOOLS)))
        self.tool_rects = []
        for i, tool in enumerate(TOOLS):
            r = pygame.Rect(6, TOPBAR_H + 6 + i * row, SIDEBAR_W - 12, row - 2)
            self.tool_rects.append(r)
            on = tool == self.tool
            if on:
                pygame.draw.rect(s, mix(PANEL, accent, 0.35), r, border_radius=6)
            elif r.collidepoint(self.mouse):
                pygame.draw.rect(s, mix(PANEL, (255, 255, 255), 0.08), r, border_radius=6)
            if tool == "select":
                name, col = "Select / move", TEXT
            elif tool == "measure":
                name, col = "Measure", GOLD
            else:
                name, col = KINDS[tool].name, KINDS[tool].colour
            sw = pygame.Rect(r.x + 6, r.centery - 7, 14, 14)
            pygame.draw.rect(s, col, sw, border_radius=3)
            n = ORDER.index(tool) + 1 if tool in ORDER and ORDER.index(tool) < 10 else None
            if n:
                key = f.small.render(str(n % 10), True, DIM)
                s.blit(key, key.get_rect(midright=(r.right - 6, r.centery)))
            s.blit(f.small.render(name, True, TEXT if on else DIM), (r.x + 28, r.centery - 7))
        # bottom status bar
        bar = pygame.Rect(SIDEBAR_W, h - BOTTOMBAR_H, w - SIDEBAR_W, BOTTOMBAR_H)
        pygame.draw.rect(s, PANEL, bar)
        wpos = self.to_world(self.mouse)
        info = f"x {wpos.x:.0f}  y {wpos.y:.0f}    grid {self.grid} (G)    zoom {self.zoom:g}x"
        info += f"    hitboxes {'on' if self.hitboxes else 'off'} (H)    player ref {'on' if self.ghost else 'off'} (P)"
        s.blit(f.small.render(info, True, DIM), (bar.x + 12, bar.y + 10))
        idxs = sorted(self.sel)
        hover = self.pick(wpos) if not self.in_ui(self.mouse) else None
        if len(idxs) == 1:
            line = level_info_line(self.objs[idxs[0]]) + "    R rotate  [ ] power  CTRL+C copy"
        elif self.pasting:
            line = "Pasting: click to place copies, ESC or right-click when done"
        elif idxs:
            line = (f"{len(idxs)} selected    CTRL+C copy  CTRL+X cut  CTRL+D duplicate"
                    "  DEL delete  arrows nudge")
        elif hover is not None:
            line = level_info_line(self.objs[hover])
        elif self.tool in KINDS:
            line = f"{KINDS[self.tool].name}: {KINDS[self.tool].info}"
        else:
            line = ("Click a block to select it, drag to move. Drag the corner handle to resize."
                    if self.tool == "select" else
                    "Drag to measure distance, in pixels and in frames of movement.")
        img = f.small.render(line, True, TEXT)
        s.blit(img, img.get_rect(bottomleft=(SIDEBAR_W + 12, h - BOTTOMBAR_H - 8)))
        if self.title:
            t = f.font.render(self.title, True, TEXT)
            s.blit(t, t.get_rect(topright=(w - 16, TOPBAR_H + 10)))

    def draw_help(self, s, f):
        w, h = s.get_size()
        shade_screen(s, 170)
        box = pygame.Rect(0, 0, 640, 40 + len(HELP) * 24)
        box.center = (w / 2, h / 2)
        draw_panel(s, box, 240)
        for i, line in enumerate(HELP):
            col = GOLD if line.strip().isupper() else TEXT
            s.blit(f.font.render(line.rstrip(), True, col), (box.x + 24, box.y + 20 + i * 24))

    def draw_modal(self, s, f):
        w, h = s.get_size()
        m = self.modal
        shade_screen(s, 170)
        box = pygame.Rect(0, 0, 620, 360)
        box.center = (w / 2, h / 2)
        draw_panel(s, box, 245)
        pygame.draw.rect(s, GOLD, box, 2, border_radius=12)
        if m["result"]:
            head = f.big.render("Published!", True, GREEN)
            s.blit(head, head.get_rect(midtop=(box.centerx, box.y + 30)))
            code = f.title.render(m["result"], True, GOLD)
            s.blit(code, code.get_rect(center=(box.centerx, box.y + 150)))
            for i, line in enumerate(("Anyone can play it with this ID.",
                                      "The first person to beat it verifies it and",
                                      "puts it on the public level list.")):
                img = f.font.render(line, True, TEXT)
                s.blit(img, img.get_rect(midtop=(box.centerx, box.y + 220 + i * 24)))
            hint = f.font.render("ENTER play it now    ESC keep editing", True, DIM)
            s.blit(hint, hint.get_rect(midbottom=(box.centerx, box.bottom - 18)))
            return
        head = f.big.render("Publish level", True, GOLD)
        s.blit(head, head.get_rect(midtop=(box.centerx, box.y + 24)))
        for i, (key, label) in enumerate((("name", "Level name"), ("author", "Your name"))):
            r = pygame.Rect(box.x + 30, box.y + 120 + i * 100, box.w - 60, 54)
            tb = m[key]
            if m["field"] == key:
                tb.draw(s, f, r, self.t, label, f.mid)
            else:
                draw_panel(s, r, 200)
                s.blit(f.mid.render(tb.value, True, DIM), (r.x + 18, r.y + 16))
                s.blit(f.font.render(label, True, DIM), (r.x + 6, r.y - 22))
        if m["req"]:
            msg, col = "Publishing...", DIM
        elif m["error"]:
            msg, col = m["error"], RED
        else:
            msg, col = "ENTER publish    TAB switch field    ESC cancel", DIM
        img = f.font.render(msg, True, col)
        s.blit(img, img.get_rect(midbottom=(box.centerx, box.bottom - 18)))

    def draw_test(self, s, f):
        run = self.test
        w, h = s.get_size()
        # paused or slowed playtests draw exactly where the physics is
        alpha = 1.0 if self.paused or self.slow else self.app.alpha
        cam = level_camera(s, run, alpha)
        draw_sky(s, cam, PALETTES[run.theme])
        run.draw(s, cam, f, self.hitboxes, alpha)
        mode = []
        if self.slow:
            mode.append("SLOW x0.25")
        if self.paused:
            mode.append("PAUSED  (. step)")
        draw_level_hud(s, f, run, "PLAYTEST" + ("   " + "   ".join(mode) if mode else ""),
                       "ESC edit   R restart   H hitboxes   TAB slow   , pause")
        if run.finished:
            shade_screen(s, 140)
            head = f.huge.render("CLEARED", True, GOLD)
            s.blit(head, head.get_rect(center=(w / 2, h * 0.35)))
            t = f.huge.render(fmt_time(run.time), True, TEXT)
            s.blit(t, t.get_rect(center=(w / 2, h * 0.35 + 80)))
            hint = f.font.render("R  again    ESC back to editing", True, DIM)
            s.blit(hint, hint.get_rect(center=(w / 2, h * 0.35 + 140)))
