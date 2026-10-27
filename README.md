# VELOCITY

A high-speed courier game in Python (pygame-ce). The Static has knocked out
every beacon in the Reach; as a courier you carry deliveries between six towns
across a huge, tall world, from valley floors to sky cities, chaining speed tech
to get there fast. A main story walks you through every move, and Dispatchers
in each town hand out timed delivery jobs for coins.

**Play in the browser:** https://a.oliverbar.net

The web version is the same Python code, packaged for the browser with
[pygbag](https://github.com/pygame-web/pygbag). A Cloudflare Worker rebuilds
and publishes it on every push to `main`:

| Setting | Value |
|---|---|
| Build command | `pip install pygbag==0.9.3 && python -m pygbag --build .` |
| Deploy command | `npx wrangler deploy` |

`wrangler.jsonc` tells the deploy to serve `build/web` as static files.

## Controls

| Key | Action |
|---|---|
| A / D (or arrows) | run |
| W / S | aim dashes up / down |
| Space (or K) | jump |
| Shift (or J) | dash in the held direction |
| S | slide on the ground, fast fall in the air |
| E (or Enter) | talk / advance dialogue |
| R | respawn at the last town |

The full list of maneuvers is in the docstring at the top of `player.py`.

## Code

| File | What's in it |
|---|---|
| `main.py` | game loop, rendering, HUD, dialogue, browser resizing |
| `player.py` | input and every movement maneuver |
| `world.py` | world generation, towns, colour palettes |
| `quests.py` | story, characters, main quest and delivery jobs |

## Run locally

```bash
pip install -r requirements.txt
python main.py
```

Browser build:

```bash
pip install pygbag
python -m pygbag .
```

Then open http://localhost:8000.
