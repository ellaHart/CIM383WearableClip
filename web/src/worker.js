// Mood Clip API (Cloudflare Worker). Static files in web/public are served by Workers Assets;
// everything under /api/ comes here. State lives in one Durable Object, so reads are always fresh.
//
// Secrets (never in git): CONTROL_TOKEN for the website, DEVICE_TOKEN for the clip.
// Local dev: web/.dev.vars    Production: npx wrangler secret put CONTROL_TOKEN / DEVICE_TOKEN
import { DurableObject } from "cloudflare:workers";
import MOODS from "../../device/moods.json";

// The five screen modes. "ready" = selectable now; the rest are shown as placeholders.
export const MODES = [
  { id: "moods", name: "Mood Screens", status: "ready", summary: "Pixel-art moods with scrolling text." },
  { id: "spotify", name: "Spotify Now Playing", status: "planned", summary: "Current song, artist and album art." },
  { id: "magic8", name: "Magic 8 Ball", status: "planned", summary: "Press the bottom button to shake for an answer." },
  { id: "aquarium", name: "Little Aquarium", status: "planned", summary: "Fish swim around; the bottom button drops food." },
  { id: "custom", name: "Custom Text / Photo", status: "planned", summary: "Your own message, background and image." },
];
const MODE_IDS = new Set(MODES.map((mode) => mode.id));
const MOOD_IDS = new Set(MOODS.map((mood) => mood.id));
const READY_MODES = new Set(MODES.filter((mode) => mode.status === "ready").map((mode) => mode.id));

// What the website asks the clip to show. `version` goes up on every command, so the clip
// applies each command once and physical button presses are not overwritten afterwards.
const DEFAULT_DESIRED = {
  version: 0,
  updated_at: null,
  mode: "moods",
  modes: {
    moods: { mood: MOODS[0].id },
    spotify: {},
    magic8: {},
    aquarium: {},
    custom: { text: "", bg: "#FFFFFF", image: null },
  },
};

export class ClipState extends DurableObject {
  async read() {
    const [desired, reported] = await Promise.all([
      this.ctx.storage.get("desired"),
      this.ctx.storage.get("reported"),
    ]);
    return { desired: desired ?? DEFAULT_DESIRED, reported: reported ?? null };
  }

  async command({ mode, mood }) {
    const { desired } = await this.read();
    const next = structuredClone(desired);
    next.mode = mode;
    if (mode === "moods") next.modes.moods.mood = mood;
    next.version = desired.version + 1;
    next.updated_at = new Date().toISOString();
    await this.ctx.storage.put("desired", next);
    return next;
  }

  async sync(report) {
    const reported = { ...report, last_seen: new Date().toISOString() };
    await this.ctx.storage.put("reported", reported);
    const { desired } = await this.read();
    return desired;
  }
}

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}

function error(status, message) {
  return json({ error: message }, status);
}

// Constant-time string comparison so tokens can't be guessed by timing.
function sameToken(a, b) {
  const left = new TextEncoder().encode(a);
  const right = new TextEncoder().encode(b);
  let diff = left.length ^ right.length;
  for (let i = 0; i < Math.max(left.length, right.length); i++) diff |= (left[i] ?? 0) ^ (right[i] ?? 0);
  return diff === 0;
}

function authorized(request, secret) {
  const header = request.headers.get("authorization") ?? "";
  const token = header.startsWith("Bearer ") ? header.slice(7) : "";
  return Boolean(secret) && Boolean(token) && sameToken(token, secret);
}

async function readJson(request) {
  try {
    return await request.json();
  } catch {
    return null;
  }
}

// Small payload for the clip: only what it needs to act on.
function deviceView(desired) {
  return { version: desired.version, mode: desired.mode, mood: desired.modes.moods.mood };
}

// Keep only known, small fields from the clip's report.
function cleanReport(body) {
  const pick = (value, type, max = 64) =>
    typeof value === type ? (type === "string" ? value.slice(0, max) : value) : null;
  return {
    mode: MODE_IDS.has(body.mode) ? body.mode : null,
    mood: MOOD_IDS.has(body.mood) ? body.mood : null,
    applied_version: pick(body.applied_version, "number"),
    rssi: pick(body.rssi, "number"),
    ip: pick(body.ip, "string", 40),
    uptime: pick(body.uptime, "number"),
    battery: pick(body.battery, "number"),
    firmware: pick(body.firmware, "string"),
  };
}

async function handleApi(request, env, url) {
  const state = env.CLIP_STATE.get(env.CLIP_STATE.idFromName("clip"));
  const route = `${request.method} ${url.pathname}`;

  if (route === "GET /api/catalog") {
    return json({ modes: MODES, moods: MOODS });
  }

  if (url.pathname.startsWith("/api/device/")) {
    if (!env.DEVICE_TOKEN) return error(500, "DEVICE_TOKEN is not configured on the server");
    if (!authorized(request, env.DEVICE_TOKEN)) return error(401, "Bad device token");
    if (route === "POST /api/device/sync") {
      const body = await readJson(request);
      if (!body || typeof body !== "object") return error(400, "Expected a JSON body");
      return json(deviceView(await state.sync(cleanReport(body))));
    }
    return error(404, "Unknown device endpoint");
  }

  if (!env.CONTROL_TOKEN) return error(500, "CONTROL_TOKEN is not configured on the server");
  if (!authorized(request, env.CONTROL_TOKEN)) return error(401, "Wrong control code");

  if (route === "GET /api/state") {
    return json(await state.read());
  }

  if (route === "POST /api/command") {
    const body = await readJson(request);
    if (!body || !MODE_IDS.has(body.mode)) return error(400, "Unknown mode");
    if (!READY_MODES.has(body.mode)) return error(409, `${body.mode} isn't available on the clip yet`);
    if (body.mode === "moods" && !MOOD_IDS.has(body.mood)) return error(400, "Unknown mood");
    const desired = await state.command({ mode: body.mode, mood: body.mood });
    return json({ desired });
  }

  return error(404, "Unknown endpoint");
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname.startsWith("/api/")) {
      try {
        return await handleApi(request, env, url);
      } catch (err) {
        console.error(err);
        return error(500, "Server error");
      }
    }
    return env.ASSETS.fetch(request);
  },
};
