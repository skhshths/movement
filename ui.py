"""Shared colours, fonts, the sky backdrop and small UI widgets."""
import math
import random

import pygame

from world import WORLD_TOP, mix

INK = (12, 10, 24)
PANEL = (18, 16, 34)
TEXT = (238, 236, 248)
DIM = (150, 146, 176)
GOLD = (255, 214, 90)
RED = (255, 90, 110)
GREEN = (120, 240, 150)
PLAYER_READY = (80, 230, 255)
PLAYER_EMPTY = (255, 140, 70)
PLAYER_DASH = (255, 255, 255)


class Fonts:
    def __init__(self):
        self.small = pygame.font.Font(None, 20)
        self.font = pygame.font.Font(None, 24)
        self.mid = pygame.font.Font(None, 30)
        self.big = pygame.font.Font(None, 52)
        self.huge = pygame.font.Font(None, 84)
        self.title = pygame.font.Font(None, 150)


def wrap(font, text, width):
    lines, line = [], ""
    for word in text.split():
        test = f"{line} {word}".strip()
        if font.size(test)[0] <= width or not line:
            line = test
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def fmt_time(t):
    if t is None:
        return "--"
    if t >= 60:
        return f"{int(t // 60)}:{t % 60:06.3f}"
    return f"{t:.3f}"


def ridge(x, seed, scale):
    """Smooth hill height for the parallax mountain layers."""
    return (math.sin(x * 0.0021 + seed) * 0.5 + math.sin(x * 0.0057 + seed * 2.3) * 0.3
            + math.sin(x * 0.013 + seed * 4.1) * 0.2) * scale


def draw_sky(s, cam, pal):
    w, h = s.get_size()
    # altitude gradient: low = warm horizon colour, high = deep sky
    # with a saturated, accent-tinted middle so the climb stays colourful
    bands = 14
    mid = mix(pal["sky_top"], pal["accent"], 0.45)
    for i in range(bands):
        y0 = h * i // bands
        wy = cam.y + y0 + h / bands / 2
        t = max(0, min(1, (1200 - wy) / (1200 - WORLD_TOP)))
        if t < 0.4:
            col = mix(pal["sky_bot"], mid, t / 0.4)
        else:
            col = mix(mid, pal["sky_top"], (t - 0.4) / 0.6)
        pygame.draw.rect(s, col, (0, y0, w, h // bands + 2))
    # stars come out as you climb
    alt = max(0, min(1, (-cam.y - 1500) / 4000))
    if alt > 0:
        star = mix(pal["sky_top"], (255, 255, 255), alt * 0.8)
        span = w + 200
        for i in range(70):
            sx = ((i * 977 + 131) - cam.x * 0.05) % span
            sy = (i * 571 + 53) % h
            pygame.draw.rect(s, star, (sx, sy, 2, 2))
    # clouds
    cloud = mix(pal["sky_bot"], (255, 255, 255), 0.35)
    tile = 900
    cx0 = cam.x * 0.2
    for i in range(-1, w // tile + 3):
        k = math.floor(cx0 / tile) + i
        rng = random.Random(k * 7919)
        cx = k * tile - cx0 + rng.randint(0, 400)
        cy = rng.randint(40, int(h * 0.5)) - (cam.y - 200) * 0.08
        for j in range(3):
            pygame.draw.ellipse(s, cloud, (cx + j * 50, cy - (j % 2) * 18, 120, 44))
    # two parallax mountain layers
    for par, seed, scale, base, col in ((0.12, 1.0, 180, 0.62, pal["far"]),
                                        (0.3, 5.0, 240, 0.78, pal["near"])):
        horizon = h * base - (cam.y - 600) * par
        if horizon - 2 * scale > h:
            continue
        pts = [(0, h)]
        for sx in range(0, w + 48, 48):
            pts.append((sx, horizon - ridge(cam.x * par + sx, seed, scale) - scale))
        pts.append((w, h))
        pygame.draw.polygon(s, col, pts)
        if horizon < h:
            pygame.draw.rect(s, col, (0, max(0, horizon), w, h))


def draw_panel(s, rect, alpha=200, colour=PANEL, radius=12):
    rect = pygame.Rect(rect)
    panel = pygame.Surface(rect.size, pygame.SRCALPHA)
    pygame.draw.rect(panel, (*colour, alpha), panel.get_rect(), border_radius=radius)
    s.blit(panel, rect)


def shade_screen(s, alpha=150):
    veil = pygame.Surface(s.get_size(), pygame.SRCALPHA)
    veil.fill((*INK, alpha))
    s.blit(veil, (0, 0))


def button(s, fonts, rect, label, hot=False, accent=GOLD, font=None):
    """Draws a button and returns its rect. `hot` = hovered or selected."""
    rect = pygame.Rect(rect)
    draw_panel(s, rect, 235 if hot else 190)
    pygame.draw.rect(s, accent if hot else DIM, rect, 3 if hot else 1, border_radius=12)
    img = (font or fonts.mid).render(label, True, accent if hot else TEXT)
    s.blit(img, img.get_rect(center=rect.center))
    return rect


class TextBox:
    """A one-line text field: typed characters arrive as TEXTINPUT events
    (on desktop and in the browser), backspace as KEYDOWN."""

    def __init__(self, value="", limit=24, allowed=None, upper=False):
        self.value = value
        self.limit = limit
        self.allowed = allowed
        self.upper = upper

    def key(self, e):
        """Feed it KEYDOWN and TEXTINPUT events."""
        if e.type == pygame.KEYDOWN:
            if e.key == pygame.K_BACKSPACE:
                self.value = self.value[:-1]
            return
        if e.type != pygame.TEXTINPUT:
            return
        for ch in e.text:
            if not ch.isprintable() or len(self.value) >= self.limit:
                continue
            if self.upper:
                ch = ch.upper()
            if self.allowed and ch not in self.allowed:
                continue
            self.value += ch

    def draw(self, s, fonts, rect, time, label=None, font=None):
        rect = pygame.Rect(rect)
        draw_panel(s, rect, 235)
        pygame.draw.rect(s, GOLD, rect, 2, border_radius=12)
        font = font or fonts.big
        img = font.render(self.value, True, TEXT)
        r = img.get_rect(midleft=(rect.x + 18, rect.centery))
        s.blit(img, r)
        if int(time * 2.5) % 2 == 0:
            pygame.draw.rect(s, GOLD, (r.right + 4, rect.centery - font.get_height() // 2 + 4,
                                       3, font.get_height() - 8))
        if label:
            lab = fonts.font.render(label, True, DIM)
            s.blit(lab, lab.get_rect(bottomleft=(rect.x + 6, rect.y - 6)))
