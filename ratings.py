"""
Level difficulty ratings: eight tiers, each split 1 (low) to 5 (high), stored
as one number from 1 (Easy 1) to 40 (Legendary 5). 0 means unrated.

  Easy        anyone can clear it
  Medium      needs the basics: dashes, wall kicks
  Hard        chains moves together, a few tight spots
  Expert      demands real tech: wavedashes, slingshots, corner tricks
  Insane      long, precise chains with little room for error
  Extreme     frame-tight inputs, start to finish
  Impossible  only the best players will ever clear it
  Legendary   the hardest levels in the game

The admin sets a level's official rating; anyone who clears a level can
suggest one, and the average suggestion is shown beside it.
"""
import pygame

TIERS = [
    ("Easy", (110, 230, 120)),
    ("Medium", (190, 230, 90)),
    ("Hard", (255, 214, 90)),
    ("Expert", (255, 150, 60)),
    ("Insane", (255, 80, 80)),
    ("Extreme", (230, 70, 200)),
    ("Impossible", (150, 90, 255)),
    ("Legendary", (90, 220, 255)),
]
MAX = len(TIERS) * 5


def name(r):
    if not r:
        return "Unrated"
    r = max(1, min(MAX, round(r)))
    return f"{TIERS[(r - 1) // 5][0]} {(r - 1) % 5 + 1}"


def colour(r):
    if not r:
        return (150, 146, 176)
    return TIERS[(max(1, min(MAX, round(r))) - 1) // 5][1]


def suggested(level):
    """Average community suggestion for a level dict from the server, or None."""
    n = level.get("sugg_count") or 0
    return level["sugg_sum"] / n if n else None


def picker(s, fonts, centre, mouse, chosen=0):
    """Draws a grid of every rating (a row per tier) and returns
    {rating: rect} so the caller can handle clicks."""
    from ui import INK, TEXT, draw_panel
    cell_w, cell_h, gap, label_w = 46, 30, 6, 120
    w = label_w + 5 * (cell_w + gap)
    h = len(TIERS) * (cell_h + gap)
    x0 = centre[0] - w // 2
    y0 = centre[1] - h // 2
    draw_panel(s, pygame.Rect(x0 - 16, y0 - 16, w + 32, h + 26), 235)
    rects = {}
    for t, (tier, col) in enumerate(TIERS):
        y = y0 + t * (cell_h + gap)
        img = fonts.font.render(tier, True, col)
        s.blit(img, img.get_rect(midleft=(x0, y + cell_h // 2)))
        for k in range(5):
            r = t * 5 + k + 1
            rect = pygame.Rect(x0 + label_w + k * (cell_w + gap), y, cell_w, cell_h)
            hot = rect.collidepoint(mouse) or r == chosen
            pygame.draw.rect(s, col if hot else INK, rect, border_radius=6)
            pygame.draw.rect(s, col, rect, 2, border_radius=6)
            num = fonts.font.render(str(k + 1), True, INK if hot else TEXT)
            s.blit(num, num.get_rect(center=rect.center))
            rects[r] = rect
    return rects
