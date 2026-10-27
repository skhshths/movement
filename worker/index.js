// VELOCITY level server.
//
// Serves the pygbag web build as static files and a small JSON API for
// player-made levels. Levels live in one SQLite-backed Durable Object, which
// Cloudflare creates on the first deploy.
//
//   POST /api/levels                publish {name, author, data}, or update
//                                   one {id, token, ...} -> {id, token}
//   GET  /api/levels?sort=&offset=  verified levels: new, top or hard
//   GET  /api/levels/:id            one level, including its data
//   POST /api/levels/:id/clear      report a clear {time, deaths, name,
//                                   replay}; the first one verifies the
//                                   level and keeps its replay
//   POST /api/levels/:id/suggest    suggest a difficulty {rating}
//
// Admin (needs the ADMIN_CODE secret, sent as "code" or x-admin-code):
//   POST /api/admin/check           {code} -> {ok}
//   GET  /api/admin/levels          every level, verified or not
//   GET  /api/levels/:id/replay     the verifying clear's recording
//   POST /api/levels/:id/rate       {code, rating} (0 removes it)
//   POST /api/levels/:id/delete     {code}
//
// Names are unique. Updating a level (with the token handed out when it was
// published) unverifies it and resets its clears, record, rating and replay.
// Ratings run 1-40: eight tiers of five, see ratings.py.
import { DurableObject } from "cloudflare:workers";

const ID_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";   // no 0/O or 1/I
const ID_LEN = 6;
const MAX_DATA = 200_000;
const MAX_REPLAY = 400_000;
const MAX_OBJECTS = 5000;
const PAGE = 40;
const PUBLISH_LIMIT = 20;         // per address per hour
const ADMIN_TRIES = 10;           // wrong admin codes per address per hour
const ADMIN_TRIES_ALL = 100;      // wrong admin codes from everyone per hour
const REPLAY_STEPS = 120 * 60 * 60;   // an hour of physics steps
const REPLAY_FORMAT = /^\d{1,3}(\*\d{1,7})?(,\d{1,3}(\*\d{1,7})?)*$/;
const COORD_MAX = 1_000_000;      // must match levels.py
const SIZE_MAX = 10_000;
const PATH_MAX = 32;              // saw path points
const RATING_MAX = 40;
const KINDS = new Set(["wall", "kill", "bounce", "boost", "ice", "oneway", "crumble", "blinkA",
  "blinkB", "gate", "saw", "orb", "grav", "wind", "nodash", "check", "start", "finish"]);
// what any listing or level fetch may show; token and replay stay private
const PUBLIC = `id, name, author, created, updated, verified, verified_by, verified_at, plays,
  clears, best, best_by, rating, sugg_sum, sugg_count, replay IS NOT NULL AS has_replay`;

const HEADERS = {
  "content-type": "application/json",
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, POST, OPTIONS",
  "access-control-allow-headers": "content-type, x-admin-code",
  "cache-control": "no-store",
};

function reply(data, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: HEADERS });
}

function clean(text, max) {
  return String(text ?? "").replace(/[\x00-\x1f\x7f]/g, "").trim().slice(0, max);
}

function randomString(n) {
  let s = "";
  const bytes = crypto.getRandomValues(new Uint8Array(n));
  for (const b of bytes) s += ID_CHARS[b % ID_CHARS.length];
  return s;
}

function checkLevel(data) {
  if (typeof data !== "string" || data.length > MAX_DATA) return "level is too big";
  let level;
  try {
    level = JSON.parse(data);
  } catch {
    return "level data is not JSON";
  }
  const objs = level && level.objs;
  if (!Array.isArray(objs) || objs.length > MAX_OBJECTS) return "bad object list";
  let starts = 0, finishes = 0;
  for (const o of objs) {
    if (!Array.isArray(o) || (o.length !== 7 && o.length !== 8) || !KINDS.has(o[0]) ||
        !o.slice(1, 7).every(Number.isFinite)) return "bad object";
    const [, x, y, w, h] = o;
    if (Math.abs(x) > COORD_MAX || Math.abs(y) > COORD_MAX ||
        w < 1 || h < 1 || w > SIZE_MAX || h > SIZE_MAX) return "object out of range";
    if (o.length === 8) {
      const path = o[7];
      if (o[0] !== "saw" || !Array.isArray(path) || path.length > PATH_MAX ||
          !path.every((p) => Array.isArray(p) && p.length === 2 && p.every(Number.isFinite) &&
                             p.every((v) => Math.abs(v) <= COORD_MAX))) return "bad saw path";
    }
    if (o[0] === "start") starts++;
    if (o[0] === "finish") finishes++;
  }
  if (starts !== 1) return "a level needs exactly one start";
  if (finishes < 1) return "a level needs a finish";
  return null;
}

function checkReplay(text) {
  // "mask*count,..." with masks 0-127 and at most an hour of steps
  if (typeof text !== "string" || text.length > MAX_REPLAY || !REPLAY_FORMAT.test(text)) return null;
  let steps = 0;
  for (const part of text.split(",")) {
    const [mask, count] = part.split("*");
    if (Number(mask) > 127) return null;
    steps += Number(count || 1);
    if (steps > REPLAY_STEPS) return null;
  }
  return text;
}

function addressKey(addr) {
  // IPv6 users usually control a whole /64, so count wrong codes per /64.
  // Expand "::" first: the same /64 can be written many shortened ways.
  if (!addr.includes(":")) return addr;
  const [head, tail] = addr.toLowerCase().split("%")[0].split("::");
  const front = head ? head.split(":") : [];
  const back = tail !== undefined && tail ? tail.split(":") : [];
  if (back.length && back[back.length - 1].includes(".")) back.splice(-1, 1, "0", "0");  // v4 tail
  const zeros = tail !== undefined ? Array(Math.max(0, 8 - front.length - back.length)).fill("0") : [];
  const groups = [...front, ...zeros, ...back].slice(0, 4)
    .map((g) => (parseInt(g, 16) || 0).toString(16));
  while (groups.length < 4) groups.push("0");
  return groups.join(":") + "::/64";
}

async function codeMatches(env, code) {
  if (!env.ADMIN_CODE || typeof code !== "string" || !code) return false;
  const enc = new TextEncoder();
  const [a, b] = await Promise.all([crypto.subtle.digest("SHA-256", enc.encode(code)),
                                    crypto.subtle.digest("SHA-256", enc.encode(env.ADMIN_CODE))]);
  return crypto.subtle.timingSafeEqual(a, b);
}

function validRating(r, allowZero) {
  return Number.isInteger(r) && r >= (allowZero ? 0 : 1) && r <= RATING_MAX;
}

export class LevelStore extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.sql = ctx.storage.sql;
    this.sql.exec(`CREATE TABLE IF NOT EXISTS levels (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      author TEXT NOT NULL,
      data TEXT NOT NULL,
      created INTEGER NOT NULL,
      verified INTEGER NOT NULL DEFAULT 0,
      verified_by TEXT,
      verified_at INTEGER,
      plays INTEGER NOT NULL DEFAULT 0,
      clears INTEGER NOT NULL DEFAULT 0,
      best REAL,
      best_by TEXT)`);
    // columns added after the first release
    const have = new Set(this.sql.exec("PRAGMA table_info(levels)").toArray().map((c) => c.name));
    for (const [col, type] of [["token", "TEXT"], ["updated", "INTEGER"], ["rating", "INTEGER"],
                               ["replay", "TEXT"], ["sugg_sum", "INTEGER NOT NULL DEFAULT 0"],
                               ["sugg_count", "INTEGER NOT NULL DEFAULT 0"]]) {
      if (!have.has(col)) this.sql.exec(`ALTER TABLE levels ADD COLUMN ${col} ${type}`);
    }
    // admin code attempts, kept in storage so they survive restarts
    this.sql.exec("CREATE TABLE IF NOT EXISTS admin_tries (addr TEXT NOT NULL, t INTEGER NOT NULL)");
    this.recent = new Map();      // address -> publish times
    this.suggested = new Set();   // "address level" pairs that already suggested
  }

  // -- admin code -------------------------------------------------------------
  async checkAdmin(addr, code) {
    // The attempt is written down before the (async) comparison, so codes
    // sent in parallel can't slip past the limit; a right code clears it.
    const key = addressKey(addr);
    const now = Date.now();
    this.sql.exec("DELETE FROM admin_tries WHERE t < ?", now - 3600_000);
    const mine = this.sql.exec("SELECT COUNT(*) AS n FROM admin_tries WHERE addr = ?", key).one().n;
    const all = this.sql.exec("SELECT COUNT(*) AS n FROM admin_tries").one().n;
    // Under a mass attack (global cap reached) every address drops to one
    // try an hour instead of being locked out entirely, so the admin can
    // still get in from an address that hasn't been guessing.
    if (mine >= ADMIN_TRIES || (all >= ADMIN_TRIES_ALL && mine >= 1)) return { locked: true };
    this.sql.exec("INSERT INTO admin_tries (addr, t) VALUES (?, ?)", key, now);
    const ok = await codeMatches(this.env, code);
    if (ok) this.sql.exec("DELETE FROM admin_tries WHERE addr = ?", key);
    return { ok };
  }

  // -- levels -----------------------------------------------------------------
  nameTaken(name, exceptId) {
    return this.sql.exec("SELECT 1 FROM levels WHERE lower(name) = lower(?) AND id != ?",
      name, exceptId || "").toArray().length > 0;
  }

  publish(name, author, data, addr, id, token, admin) {
    const now = Date.now();
    const times = (this.recent.get(addr) || []).filter((t) => now - t < 3600_000);
    if (times.length >= PUBLISH_LIMIT && !admin) return { error: "publishing too fast, try later", status: 429 };
    if (id) {
      const rows = this.sql.exec("SELECT token FROM levels WHERE id = ?", id).toArray();
      if (!rows.length) return { error: "no level with that ID", status: 404 };
      if (!admin && (!rows[0].token || rows[0].token !== token)) {
        return { error: "you can only update levels you published", status: 403 };
      }
      if (this.nameTaken(name, id)) return { error: "another level already has that name", status: 409 };
      times.push(now);
      this.recent.set(addr, times);
      this.sql.exec(`UPDATE levels SET name = ?, data = ?, updated = ?, verified = 0,
          verified_by = NULL, verified_at = NULL, clears = 0, best = NULL, best_by = NULL,
          rating = NULL, replay = NULL, sugg_sum = 0, sugg_count = 0 WHERE id = ?`,
        name, data, now, id);
      return { id, token: rows[0].token || token, updated: true };
    }
    if (this.nameTaken(name)) return { error: "another level already has that name", status: 409 };
    times.push(now);
    this.recent.set(addr, times);
    do {
      id = randomString(ID_LEN);
    } while (this.sql.exec("SELECT 1 FROM levels WHERE id = ?", id).toArray().length);
    token = randomString(24);
    this.sql.exec(`INSERT INTO levels (id, name, author, data, created, token)
        VALUES (?, ?, ?, ?, ?, ?)`, id, name, author, data, now, token);
    return { id, token };
  }

  level(id) {
    const rows = this.sql.exec(`SELECT ${PUBLIC}, data FROM levels WHERE id = ?`, id).toArray();
    if (!rows.length) return null;
    this.sql.exec("UPDATE levels SET plays = plays + 1 WHERE id = ?", id);
    return rows[0];
  }

  replay(id) {
    const rows = this.sql.exec("SELECT replay, verified_by FROM levels WHERE id = ?", id).toArray();
    return rows.length ? rows[0] : null;
  }

  list(sort, offset, all) {
    const order = {
      top: "clears DESC, verified_at DESC",
      hard: "rating IS NULL, rating DESC, verified_at DESC",
      old: "created ASC",
    }[sort] || (all ? "created DESC" : "verified_at DESC");
    const where = all ? "" : "WHERE verified = 1";
    const levels = this.sql.exec(`SELECT ${PUBLIC} FROM levels ${where} ORDER BY ${order}
       LIMIT ? OFFSET ?`, PAGE, offset).toArray();
    const total = this.sql.exec(`SELECT COUNT(*) AS n FROM levels ${where}`).one().n;
    return { levels, total, offset };
  }

  clear(id, time, name, replay) {
    const rows = this.sql.exec("SELECT verified, best FROM levels WHERE id = ?", id).toArray();
    if (!rows.length) return null;
    const { verified, best } = rows[0];
    const now = Date.now();
    if (!verified) {
      this.sql.exec(`UPDATE levels SET verified = 1, verified_by = ?, verified_at = ?, replay = ?
          WHERE id = ?`, name, now, replay, id);
    }
    const record = best === null || time < best;
    if (record) this.sql.exec("UPDATE levels SET best = ?, best_by = ? WHERE id = ?", time, name, id);
    this.sql.exec("UPDATE levels SET clears = clears + 1 WHERE id = ?", id);
    return { verified_now: !verified, record, best: record ? time : best };
  }

  suggest(id, rating, addr) {
    const key = `${addr} ${id}`;
    if (this.suggested.has(key)) return { error: "you already suggested a difficulty", status: 429 };
    const rows = this.sql.exec("SELECT 1 FROM levels WHERE id = ? AND verified = 1", id).toArray();
    if (!rows.length) return { error: "no verified level with that ID", status: 404 };
    this.suggested.add(key);
    this.sql.exec("UPDATE levels SET sugg_sum = sugg_sum + ?, sugg_count = sugg_count + 1 WHERE id = ?",
      rating, id);
    return { ok: true };
  }

  rate(id, rating) {
    const n = this.sql.exec("SELECT 1 FROM levels WHERE id = ?", id).toArray().length;
    if (!n) return null;
    this.sql.exec("UPDATE levels SET rating = ? WHERE id = ?", rating || null, id);
    return { ok: true, rating };
  }

  remove(id) {
    const n = this.sql.exec("SELECT 1 FROM levels WHERE id = ?", id).toArray().length;
    if (!n) return null;
    this.sql.exec("DELETE FROM levels WHERE id = ?", id);
    return { ok: true };
  }
}

async function api(request, env, store, path) {
  const url = new URL(request.url);
  const parts = path.split("/").filter(Boolean);       // ["levels", id?, action?]
  const addr = request.headers.get("cf-connecting-ip") || "local";
  let body = {};
  if (request.method === "POST") {
    try {
      body = await request.json();
    } catch {
      return reply({ error: "bad request" }, 400);
    }
  }
  // admin: a code was offered; check it, counting wrong ones
  const offered = body.code || request.headers.get("x-admin-code");
  let admin = false;
  if (offered) {
    const check = await store.checkAdmin(addr, String(offered).slice(0, 256));
    if (check.locked) return reply({ error: "too many wrong codes, try later" }, 429);
    admin = check.ok;
  }
  const named = (text) => {
    // nobody but the admin may call themselves admin
    const name = clean(text, 24) || "Anonymous";
    return name.toLowerCase() === "admin" && !admin ? "Anonymous" : name;
  };

  if (parts[0] === "admin") {
    if (parts[1] === "check" && request.method === "POST") return reply({ ok: admin });
    if (parts[1] === "levels" && request.method === "GET") {
      if (!admin) return reply({ error: "admin only" }, 403);
      const offset = Math.max(0, parseInt(url.searchParams.get("offset") || "0", 10) || 0);
      return reply(await store.list(url.searchParams.get("sort") || "", offset, true));
    }
    return reply({ error: "not found" }, 404);
  }

  if (parts.length === 1 && parts[0] === "levels") {
    if (request.method === "GET") {
      const offset = Math.max(0, parseInt(url.searchParams.get("offset") || "0", 10) || 0);
      return reply(await store.list(url.searchParams.get("sort") || "new", offset, false));
    }
    if (request.method === "POST") {
      const name = clean(body.name, 40);
      if (!name) return reply({ error: "give your level a name" }, 400);
      const author = clean(body.author, 24) || "Anonymous";
      if (author.toLowerCase() === "admin" && !admin) {
        return reply({ error: "the name admin is reserved" }, 403);
      }
      const problem = checkLevel(body.data);
      if (problem) return reply({ error: problem }, 400);
      const id = body.id ? clean(body.id, ID_LEN).toUpperCase() : null;
      const out = await store.publish(name, author, body.data, addr, id, clean(body.token, 64), admin);
      return reply(out, out.status || 200);
    }
  }

  if (parts.length >= 2 && parts[0] === "levels") {
    const id = parts[1].toUpperCase();
    const action = parts[2];
    if (!action && request.method === "GET") {
      const level = await store.level(id);
      return level ? reply(level) : reply({ error: "no level with that ID" }, 404);
    }
    if (action === "replay" && request.method === "GET") {
      if (!admin) return reply({ error: "admin only" }, 403);
      const out = await store.replay(id);
      return out ? reply(out) : reply({ error: "no level with that ID" }, 404);
    }
    if (request.method !== "POST") return reply({ error: "not found" }, 404);
    if (action === "clear") {
      const time = Number(body.time);
      if (!Number.isFinite(time) || time < 0.5 || time > 86400) return reply({ error: "bad time" }, 400);
      const replay = checkReplay(body.replay);
      const out = await store.clear(id, time, named(body.name), replay);
      return out ? reply(out) : reply({ error: "no level with that ID" }, 404);
    }
    if (action === "suggest") {
      if (!validRating(body.rating, false)) return reply({ error: "bad rating" }, 400);
      const out = await store.suggest(id, body.rating, addr);
      return reply(out, out.status || 200);
    }
    if (action === "rate" || action === "delete") {
      if (!admin) return reply({ error: "admin only" }, 403);
      if (action === "rate" && !validRating(body.rating, true)) return reply({ error: "bad rating" }, 400);
      const out = action === "rate" ? await store.rate(id, body.rating) : await store.remove(id);
      return out ? reply(out) : reply({ error: "no level with that ID" }, 404);
    }
  }
  return reply({ error: "not found" }, 404);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (!url.pathname.startsWith("/api/")) return env.ASSETS.fetch(request);
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: HEADERS });
    const store = env.LEVELS.get(env.LEVELS.idFromName("global"));
    try {
      return await api(request, env, store, url.pathname.slice(4));
    } catch (err) {
      return reply({ error: "server error" }, 500);
    }
  },
};
