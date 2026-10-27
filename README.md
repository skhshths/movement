# VELOCITY

A high-speed movement game in Python (pygame-ce). Run, dash, slide, wall run and
chain speed tech across a huge open world, with a round minimap and all your
stats in the bottom-right corner.

**Play in the browser:** https://a.oliverbar.net

The web version is the same Python code, packaged for the browser with
[pygbag](https://github.com/pygame-web/pygbag). Cloudflare Pages rebuilds and
publishes it on every push to `main`, with these build settings:

| Setting | Value |
|---|---|
| Build command | `pip install pygbag==0.9.3 && python -m pygbag --build .` |
| Build output directory | `build/web` |
| Environment variable | `PYTHON_VERSION` = `3.12` |

## Controls

| Key | Action |
|---|---|
| A / D (or arrows) | run |
| W / S | aim dashes up / down |
| Space (or K) | jump |
| Shift (or J) | dash in the held direction |
| S | slide on the ground, fast fall in the air |
| R | respawn |

The full list of maneuvers is in the docstring at the top of `main.py`.

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
