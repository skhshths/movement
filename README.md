# VELOCITY

A high-speed courier game in Python (pygame-ce). The Static has knocked out
every beacon in the Reach; as a courier you carry deliveries between six towns
across a huge, tall world, from valley floors to sky cities, chaining speed tech
to get there fast. A main story walks you through every move, and Dispatchers
in each town hand out timed delivery jobs for coins.

It opens on a menu:

- **Story Mode**: the open world and its quests.
- **Level Creator**: build hard platforming and speed levels from walls,
  kill bricks, bounce pads, speed strips, ice, one-way platforms, crumbling
  and blinking blocks, speed gates, saws, dash orbs, gravity, wind and
  no-dash zones, checkpoints, text blocks with messages for players, and a
  finish. Toggle exact hitboxes, size gaps
  against a ghost of the player's hitbox (with jump arcs and dash reach),
  measure distances in frames, and playtest instantly with slow motion and
  frame stepping. Press **Keys** in the editor for every shortcut.
- **Play Level by ID**: every published level gets a six-character ID.
- **Browse Levels**: the public list. A level only appears here once someone
  has beaten it, and it shows its difficulty, clears and the record time. The
  **Unverified** tab lists levels nobody has beaten yet.
- **Open in about:blank** (browser only): opens the game in a new tab whose
  address bar says about:blank. The browser may ask you to allow pop-ups.

Level names are unique. Publishing from a level you published before (the
editor remembers, or use **Edit** under Play by ID) updates it in place: same
ID, but it's unverified again and its clears, record and rating reset.

The first clear of a level uploads a recording of it. Creators pick a
proposed difficulty when they publish, anyone who clears a level can suggest
one, and the admin sets the official rating, from
Easy 1 up through Medium, Hard, Expert, Insane, Extreme and Impossible to
Legendary 5 (see `ratings.py`).

### Admin

Set your name to `admin` in the menu and the game asks for the admin code.
With it you can rate levels, watch a level's verifying clear, delete levels
and see unverified levels under Browse. The code is checked by the server
against the Worker secret `ADMIN_CODE` (Cloudflare dashboard: the Worker's
Settings, Variables and Secrets, type Secret). It is never in this repo.
`keep_vars` in `wrangler.jsonc` stops deploys from wiping it if it was saved
as plain text instead.

**Play in the browser:** https://movement.oliverbar.net

The web version is the same Python code, packaged for the browser with
[pygbag](https://github.com/pygame-web/pygbag). A Cloudflare Worker rebuilds
and publishes it on every push to `main`:

| Setting | Value |
|---|---|
| Build command | `pip install pygbag==0.9.3 && python -m pygbag --build .` |
| Deploy command | `npx wrangler deploy` |

`wrangler.jsonc` serves `build/web` as static files and runs
`worker/index.js` for `/api/*`, the level server. Levels are stored in a
SQLite-backed Durable Object, which Cloudflare creates on the first deploy:
nothing to set up by hand.

| Endpoint | |
|---|---|
| `POST /api/levels` | publish `{name, author, data}`, returns `{id}` |
| `GET /api/levels?sort=new\|top\|hard&offset=` | verified levels |
| `GET /api/levels/:id` | one level with its data |
| `POST /api/levels/:id/clear` | report a clear `{time, deaths, name, replay}`; the first one verifies the level |
| `POST /api/levels/:id/suggest` | suggest a difficulty `{rating}` |
| admin | `/api/admin/check`, `/api/admin/levels`, `/api/levels/:id/replay`, `/rate`, `/delete` |

## Controls

| Key | Action |
|---|---|
| A / D (or arrows) | run |
| W / S (or up / down) | aim dashes up / down (W and up also jump; with dash they only aim) |
| Space (or K, W, up) | jump: a quick tap hops exactly the player's height |
| Shift (or J) | dash in the held direction |
| S | slide on the ground, fast fall in the air |
| E (or Enter) | talk / advance dialogue |
| R | respawn at the last town / restart a level |
| H | show hitboxes (levels) |
| Esc | back to the menu |
| F3 | frame rate and timing |

On a slow computer, add `?scale=0.7` (0.3 to 1) to the address to draw at a
lower resolution; the browser stretches it to fill the window.

The full list of maneuvers is in the docstring at the top of `player.py`.

## Code

| File | What's in it |
|---|---|
| `main.py` | app loop, browser resizing, story mode rendering, HUD, dialogue |
| `scenes.py` | menu, level list, play by ID, playing a shared level, replays |
| `ratings.py` | the difficulty rating scale |
| `editor.py` | the level creator |
| `levels.py` | level blocks, level physics and drawing |
| `net.py` | level server requests and local saves |
| `ui.py` | shared colours, fonts, sky and widgets |
| `worker/index.js` | the level server (Cloudflare Worker + Durable Object) |
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

The desktop game talks to the live level server. To run everything locally,
build the web version, start `npx wrangler dev`, open http://localhost:8787,
and point the desktop game at it with `VELOCITY_API=http://localhost:8787`.
