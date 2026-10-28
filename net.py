"""
Talking to the level server, and saving small things locally.

Requests never block the game: `api()` returns a Request right away and the
scenes check `req.done` each frame. On desktop a thread does the HTTP call;
in the browser the page's own fetch() does, and the result is collected from
JavaScript once it lands.

Local storage is a JSON file in the home folder on desktop and localStorage
in the browser.
"""
import json
import os
import sys
import threading

WEB = sys.platform == "emscripten"
# desktop talks to the live site; set VELOCITY_API to use a local server
API = "" if WEB else os.environ.get("VELOCITY_API", "https://movement.oliverbar.net")

_JS = """
window.vnet = window.vnet || {
  res: {},
  go(id, method, url, body, headers) {
    const opt = {method: method, headers: headers || {}};
    if (body) { opt.body = body; opt.headers["content-type"] = "application/json"; }
    fetch(url, opt)
      .then(r => r.text().then(t => { this.res[id] = JSON.stringify([r.status, t]); }))
      .catch(e => { this.res[id] = JSON.stringify([0, String(e)]); });
  },
  take(id) {
    const v = this.res[id];
    if (v === undefined) return "";
    delete this.res[id];
    return v;
  }
};
"""


class Request:
    def __init__(self):
        self.done = False
        self.status = 0
        self.data = None
        self.error = None

    def finish(self, status, text):
        self.status = status
        try:
            self.data = json.loads(text)
        except ValueError:
            self.data = None
        if status == 0:
            self.error = "can't reach the level server"
        elif status >= 400 or not isinstance(self.data, dict):
            self.error = (self.data or {}).get("error") if isinstance(self.data, dict) else None
            self.error = self.error or f"server error ({status})"
        self.done = True


_pending = {}
_next_id = 0


def api(method, path, body=None, headers=None):
    """Starts a request to the level server, e.g. api("GET", "/levels/ABC123")."""
    global _next_id
    req = Request()
    url = f"{API}/api{path}"
    data = json.dumps(body) if body is not None else None
    if WEB:
        import platform
        if _next_id == 0:
            platform.window.eval(_JS)
        _next_id += 1
        _pending[_next_id] = req
        platform.window.eval(f"vnet.go({_next_id}, {json.dumps(method)}, "
                             f"{json.dumps(url)}, {json.dumps(data)}, {json.dumps(headers or {})})")
    else:
        threading.Thread(target=_desktop, args=(req, method, url, data, headers or {}),
                         daemon=True).start()
    return req


def _desktop(req, method, url, data, headers):
    import urllib.error
    import urllib.request
    r = urllib.request.Request(url, method=method,
                               data=data.encode() if data else None,
                               headers={"content-type": "application/json",
                                        "user-agent": "velocity", **headers})
    try:
        with urllib.request.urlopen(r, timeout=10) as res:
            req.finish(res.status, res.read().decode())
    except urllib.error.HTTPError as e:
        req.finish(e.code, e.read().decode(errors="replace"))
    except Exception:
        req.finish(0, "")


def poll():
    """Collects finished browser requests. Call once per frame."""
    if not WEB or not _pending:
        return
    import platform
    for rid in list(_pending):
        raw = str(platform.window.eval(f"vnet.take({rid})") or "")
        if raw:
            status, text = json.loads(raw)
            _pending.pop(rid).finish(int(status), text)


# ---------------------------------------------------------------- storage --
def _path():
    return os.path.join(os.path.expanduser("~"), ".velocity.json")


def _load_all():
    try:
        with open(_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def load(key, default=None):
    if WEB:
        import platform
        raw = str(platform.window.eval(
            f"localStorage.getItem({json.dumps('velocity:' + key)}) || ''") or "")
        try:
            return json.loads(raw) if raw else default
        except ValueError:
            return default
    return _load_all().get(key, default)


def save(key, value):
    if WEB:
        import platform
        platform.window.eval(f"localStorage.setItem({json.dumps('velocity:' + key)}, "
                             f"{json.dumps(json.dumps(value))})")
        return
    data = _load_all()
    data[key] = value
    try:
        with open(_path(), "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass


# ------------------------------------------------------------ about:blank --
_BLANK_JS = r"""(function () {
  var w = window.open("about:blank", "_blank");
  if (!w) return "blocked";
  var d = w.document;
  d.title = "VELOCITY";
  var icon = d.createElement("link");
  icon.rel = "icon";
  icon.href = new URL("favicon.png", location.href).href;
  d.head.appendChild(icon);
  d.body.style.cssText = "margin:0;height:100vh;overflow:hidden;background:#000";
  var f = d.createElement("iframe");
  f.src = location.href;
  f.allow = "fullscreen; autoplay; gamepad; clipboard-read; clipboard-write";
  f.style.cssText = "border:0;width:100%;height:100%;display:block";
  d.body.appendChild(f);
  f.focus();
  return "ok";
})()"""


def can_open_blank():
    """In the browser, and not already inside an about:blank tab."""
    if not WEB:
        return False
    import platform
    return bool(platform.window.eval("window.top === window.self"))


def open_blank():
    """Opens the game in a new tab whose address is about:blank: the tab
    holds a full-size frame of this site. Returns "ok" or "blocked" (the
    browser stopped the pop-up)."""
    import platform
    return str(platform.window.eval(_BLANK_JS))
