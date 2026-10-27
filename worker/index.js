// VELOCITY level server.
//
// Serves the pygbag web build as static files and a small JSON API for
// player-made levels. Levels live in one SQLite-backed Durable Object, which
// Cloudflare creates on the first deploy, so there is nothing to set up by
// hand.
//
//   POST /api/levels               publish {name, author, data} -> {id}
//   GET  /api/levels?sort=&offset= verified levels, newest or most cleared
//   GET  /api/levels/:id           one level, including its data
//   POST /api/levels/:id/clear     report a clear {time, deaths, name}
//
// A level is unlisted until someone beats it; the first clear verifies it and
// puts it on the public list.
import { DurableObject } from "cloudflare:workers";

const ID_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";   // no 0/O or 1/I
const ID_LEN = 6;
const MAX_DATA = 200_000;
const MAX_OBJECTS = 5000;
const PAGE = 40;
const PUBLISH_LIMIT = 20;         // per address per hour
const COORD_MAX = 1_000_000;      // must match levels.py
const SIZE_MAX = 10_000;
const KINDS = new Set(["wall", "kill", "bounce", "boost", "ice", "oneway", "crumble", "blinkA",
  "blinkB", "gate", "saw", "orb", "grav", "wind", "nodash", "check", "start", "finish"]);

const HEADERS = {
  "content-type": "application/json",
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, POST, OPTIONS",
  "access-control-allow-headers": "content-type",
  "cache-control": "no-store",
};

function reply(data, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: HEADERS });
}

function clean(text, max) {
  return String(text ?? "").replace(/[\x00-\x1f\x7f]/g, "").trim().slice(0, max);
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
    if (!Array.isArray(o) || o.length !== 7 || !KINDS.has(o[0]) ||
        !o.slice(1).every(Number.isFinite)) return "bad object";
    const [, x, y, w, h] = o;
    if (Math.abs(x) > COORD_MAX || Math.abs(y) > COORD_MAX ||
        w < 1 || h < 1 || w > SIZE_MAX || h > SIZE_MAX) return "object out of range";
    if (o[0] === "start") starts++;
    if (o[0] === "finish") finishes++;
  }
  if (starts !== 1) return "a level needs exactly one start";
  if (finishes < 1) return "a level needs a finish";
  return null;
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
    this.recent = new Map();      // address -> publish times
  }

  publish(name, author, data, addr) {
    const now = Date.now();
    const times = (this.recent.get(addr) || []).filter((t) => now - t < 3600_000);
    if (times.length >= PUBLISH_LIMIT) return { error: "publishing too fast, try later" };
    times.push(now);
    this.recent.set(addr, times);
    let id;
    do {
      id = "";
      for (let i = 0; i < ID_LEN; i++) id += ID_CHARS[Math.floor(Math.random() * ID_CHARS.length)];
    } while (this.sql.exec("SELECT 1 FROM levels WHERE id = ?", id).toArray().length);
    this.sql.exec("INSERT INTO levels (id, name, author, data, created) VALUES (?, ?, ?, ?, ?)",
      id, name, author, data, now);
    return { id };
  }

  level(id) {
    const rows = this.sql.exec("SELECT * FROM levels WHERE id = ?", id).toArray();
    if (!rows.length) return null;
    this.sql.exec("UPDATE levels SET plays = plays + 1 WHERE id = ?", id);
    return rows[0];
  }

  list(sort, offset) {
    const order = sort === "top" ? "clears DESC, verified_at DESC" : "verified_at DESC";
    const levels = this.sql.exec(
      `SELECT id, name, author, created, verified_by, verified_at, plays, clears, best, best_by
       FROM levels WHERE verified = 1 ORDER BY ${order} LIMIT ? OFFSET ?`,
      PAGE, offset).toArray();
    const total = this.sql.exec("SELECT COUNT(*) AS n FROM levels WHERE verified = 1").one().n;
    return { levels, total, offset };
  }

  clear(id, time, deaths, name) {
    const rows = this.sql.exec("SELECT verified, best FROM levels WHERE id = ?", id).toArray();
    if (!rows.length) return null;
    const { verified, best } = rows[0];
    const now = Date.now();
    if (!verified) {
      this.sql.exec("UPDATE levels SET verified = 1, verified_by = ?, verified_at = ? WHERE id = ?",
        name, now, id);
    }
    const record = best === null || time < best;
    if (record) this.sql.exec("UPDATE levels SET best = ?, best_by = ? WHERE id = ?", time, name, id);
    this.sql.exec("UPDATE levels SET clears = clears + 1 WHERE id = ?", id);
    return { verified_now: !verified, record, best: record ? time : best };
  }
}

async function api(request, store, path) {
  const url = new URL(request.url);
  const parts = path.split("/").filter(Boolean);       // ["levels", id?, "clear"?]
  let body = {};
  if (request.method === "POST") {
    try {
      body = await request.json();
    } catch {
      return reply({ error: "bad request" }, 400);
    }
  }

  if (parts.length === 1 && parts[0] === "levels") {
    if (request.method === "GET") {
      const offset = Math.max(0, parseInt(url.searchParams.get("offset") || "0", 10) || 0);
      return reply(await store.list(url.searchParams.get("sort") || "new", offset));
    }
    if (request.method === "POST") {
      const name = clean(body.name, 40);
      const author = clean(body.author, 24) || "Anonymous";
      if (!name) return reply({ error: "give your level a name" }, 400);
      const problem = checkLevel(body.data);
      if (problem) return reply({ error: problem }, 400);
      const addr = request.headers.get("cf-connecting-ip") || "local";
      const out = await store.publish(name, author, body.data, addr);
      return reply(out, out.error ? 429 : 200);
    }
  }

  if (parts.length >= 2 && parts[0] === "levels") {
    const id = parts[1].toUpperCase();
    if (parts.length === 2 && request.method === "GET") {
      const level = await store.level(id);
      return level ? reply(level) : reply({ error: "no level with that ID" }, 404);
    }
    if (parts.length === 3 && parts[2] === "clear" && request.method === "POST") {
      const time = Number(body.time);
      if (!Number.isFinite(time) || time < 0.5 || time > 86400) return reply({ error: "bad time" }, 400);
      const deaths = Math.max(0, Math.floor(Number(body.deaths) || 0));
      const out = await store.clear(id, time, deaths, clean(body.name, 24) || "Anonymous");
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
      return await api(request, store, url.pathname.slice(4));
    } catch (err) {
      return reply({ error: "server error" }, 500);
    }
  },
};
