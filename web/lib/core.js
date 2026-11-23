// Shared API logic for the Vercel Functions in web/api/. Each api/*.js file is a thin wrapper.
//
// Environment variables (Vercel project settings, or web/.env.local for the local server):
//   CONTROL_TOKEN        code the website sends (typed once on your phone)
//   DEVICE_TOKEN         code the clip sends (in the clip's settings.toml)
//   KV_REST_API_URL      added by the Upstash Redis integration
//   KV_REST_API_TOKEN    added by the Upstash Redis integration
import { Redis } from "@upstash/redis";
import MOODS from "./moods.generated.js"; // copied from device/moods.json by scripts/sync-assets.mjs

// The screen modes. "ready" = selectable now; the rest are shown as placeholders.
export const MODES = [
  { id: "moods", name: "Mood Expressions", status: "ready", summary: "Pixel-art moods with scrolling text." },
  { id: "magic8", name: "Magic 8 Ball", status: "ready", summary: "Press the clip's bottom button to shake it for an answer." },
  { id: "aquarium", name: "Aquarium", status: "ready", summary: "A clownfish, a blue tang and a betta swim around. Press the clip's bottom button to feed them." },
  { id: "whiteboard", name: "Whiteboard", status: "ready", summary: "Draw on your phone and send it to the clip." },
  { id: "spotify", name: "Spotify Now Playing", status: "ready", summary: "The song you're playing on Spotify, with its artist." },
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
    whiteboard: { rev: 0 },  // revision of the latest drawing (KEYS.drawing)
  },
};

// Whiteboard drawings: 320x170, 1 bit per pixel, 1 = black. Rows top to bottom, 40 bytes each;
// within a byte the leftmost pixel is the most significant bit. 6800 bytes in total.
// Stored in Redis as { rev, data: base64 } (only the latest drawing is kept).
export const DRAWING = { width: 320, height: 170, bytes: (320 / 8) * 170 };

const KEYS = {
  desired: "moodclip:desired",
  reported: "moodclip:reported",
  version: "moodclip:version",
  drawing: "moodclip:drawing",
  drawingRev: "moodclip:drawing_rev",
  spotifyAuth: "moodclip:spotify_auth",   // { refresh_token, access_token, expires_at } - server only
  spotifyState: "moodclip:spotify_state", // OAuth CSRF state { state, created_at }
  spotifyNow: "moodclip:spotify_now",     // cached now-playing { fetched_at, result }
};

// ---------- Storage: Upstash Redis on Vercel, in-memory for the local test server ----------
const memory = new Map();
const memoryStore = {
  get: async (key) => (memory.has(key) ? structuredClone(memory.get(key)) : null),
  set: async (key, value) => { memory.set(key, structuredClone(value)); },
  incr: async (key) => { const next = (memory.get(key) ?? 0) + 1; memory.set(key, next); return next; },
};

let store;
function getStore() {
  if (store !== undefined) return store;
  const url = process.env.KV_REST_API_URL ?? process.env.UPSTASH_REDIS_REST_URL;
  const token = process.env.KV_REST_API_TOKEN ?? process.env.UPSTASH_REDIS_REST_TOKEN;
  if (url && token) {
    const redis = new Redis({ url, token }); // stores objects as JSON and parses them back
    store = { get: (key) => redis.get(key), set: (key, value) => redis.set(key, value), incr: (key) => redis.incr(key) };
  } else if (process.env.VERCEL) {
    store = null; // deployed without a database: fail loudly instead of forgetting state
  } else {
    store = memoryStore;
  }
  return store;
}

async function readState() {
  const db = getStore();
  const [desired, reported] = await Promise.all([db.get(KEYS.desired), db.get(KEYS.reported)]);
  return { desired: desired ?? DEFAULT_DESIRED, reported: reported ?? null };
}

// ---------- HTTP helpers ----------
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

// Wraps a handler with token checks, database checks and error handling.
function endpoint(tokenName, handler) {
  return async (request) => {
    try {
      if (tokenName) {
        const secret = process.env[tokenName];
        if (!secret) return error(500, `${tokenName} is not set in the Vercel project's environment variables`);
        if (!authorized(request, secret)) {
          return error(401, tokenName === "DEVICE_TOKEN" ? "Bad device token" : "Wrong control code");
        }
      }
      if (!getStore()) return error(500, "Database not connected: add Upstash Redis to the Vercel project");
      return await handler(request);
    } catch (err) {
      console.error(err);
      return error(500, "Server error");
    }
  };
}

// Small payload for the clip: only what it needs to act on.
function deviceView(desired) {
  return {
    version: desired.version,
    mode: desired.mode,
    mood: desired.modes.moods.mood,
    drawing: desired.modes.whiteboard?.rev ?? 0, // the clip downloads the drawing only when this changes
  };
}

// Keep only known, small fields from the clip's report.
function cleanReport(body) {
  const pick = (value, type, max = 64) =>
    typeof value === type ? (type === "string" ? value.slice(0, max) : value) : null;
  const magic8 = body.magic8 && typeof body.magic8 === "object" ? body.magic8 : null;
  return {
    mode: MODE_IDS.has(body.mode) ? body.mode : null,
    mood: MOOD_IDS.has(body.mood) ? body.mood : null,
    // Magic 8 Ball: what its screen shows and the latest answer (null before the first shake).
    magic8: magic8
      ? {
          state: ["idle", "shaking", "answer"].includes(magic8.state) ? magic8.state : null,
          answer: pick(magic8.answer, "string", 40),
          count: pick(magic8.count, "number"),
        }
      : null,
    applied_version: pick(body.applied_version, "number"),
    drawing_rev: pick(body.drawing_rev, "number"), // whiteboard drawing the clip has (0 = none yet)
    rssi: pick(body.rssi, "number"),
    ip: pick(body.ip, "string", 40),
    uptime: pick(body.uptime, "number"),
    battery: pick(body.battery, "number"),
    firmware: pick(body.firmware, "string"),
  };
}

// ---------- Endpoints ----------
export const catalog = async () => json({ modes: MODES, moods: MOODS });

export const getState = endpoint("CONTROL_TOKEN", async () =>
  json({ ...(await readState()), spotify: await nowPlaying() }));

export const postCommand = endpoint("CONTROL_TOKEN", async (request) => {
  const body = await readJson(request);
  if (!body || !MODE_IDS.has(body.mode)) return error(400, "Unknown mode");
  if (!READY_MODES.has(body.mode)) return error(409, `${body.mode} isn't available on the clip yet`);
  if (body.mode === "moods" && !MOOD_IDS.has(body.mood)) return error(400, "Unknown mood");

  const db = getStore();
  const version = await db.incr(KEYS.version);
  const { desired } = await readState();
  const next = structuredClone(desired);
  next.mode = body.mode;
  if (body.mode === "moods") next.modes.moods.mood = body.mood;
  next.version = version;
  next.updated_at = new Date().toISOString();
  await db.set(KEYS.desired, next);
  return json({ desired: next });
});

export const postDeviceSync = endpoint("DEVICE_TOKEN", async (request) => {
  const body = await readJson(request);
  if (!body || typeof body !== "object") return error(400, "Expected a JSON body");
  const db = getStore();
  await db.set(KEYS.reported, { ...cleanReport(body), last_seen: new Date().toISOString() });
  const { desired } = await readState();
  const view = deviceView(desired);
  // Song info only while the clip shows the Spotify screen (no Spotify calls otherwise).
  if (body.mode === "spotify") view.spotify = deviceSpotify(await nowPlaying());
  return json(view);
});

// ---------- Whiteboard ----------
function binary(bytes, rev) {
  return new Response(bytes, {
    headers: {
      "content-type": "application/octet-stream",
      "content-length": String(bytes.length),
      "cache-control": "no-store",
      "x-drawing-rev": String(rev),
    },
  });
}

async function readDrawing() {
  const saved = await getStore().get(KEYS.drawing);
  if (!saved?.data) return null;
  return { rev: saved.rev, bytes: Uint8Array.from(Buffer.from(saved.data, "base64")) };
}

// Website uploads a drawing (raw 6800-byte body). It becomes the latest drawing, and the clip is
// switched to the whiteboard through the normal versioned command.
export const postDrawing = endpoint("CONTROL_TOKEN", async (request) => {
  const declared = Number(request.headers.get("content-length"));
  if (declared && declared !== DRAWING.bytes) return error(413, `A drawing must be exactly ${DRAWING.bytes} bytes`);
  const body = new Uint8Array(await request.arrayBuffer());
  if (body.length !== DRAWING.bytes) return error(400, `A drawing must be exactly ${DRAWING.bytes} bytes`);

  const db = getStore();
  const rev = await db.incr(KEYS.drawingRev);
  await db.set(KEYS.drawing, { rev, data: Buffer.from(body).toString("base64") });

  const version = await db.incr(KEYS.version);
  const { desired } = await readState();
  const next = structuredClone(desired);
  next.mode = "whiteboard";
  next.modes.whiteboard = { rev };
  next.version = version;
  next.updated_at = new Date().toISOString();
  await db.set(KEYS.desired, next);
  return json({ rev, desired: next });
});

// Website reads the latest drawing back (for the dashboard preview).
export const getDrawing = endpoint("CONTROL_TOKEN", async () => {
  const drawing = await readDrawing();
  return drawing ? binary(drawing.bytes, drawing.rev) : error(404, "No drawing yet");
});

// Clip downloads the latest drawing (raw bytes, revision in the x-drawing-rev header).
export const getDeviceDrawing = endpoint("DEVICE_TOKEN", async () => {
  const drawing = await readDrawing();
  return drawing ? binary(drawing.bytes, drawing.rev) : error(404, "No drawing yet");
});

// ---------- Spotify Now Playing (display only) ----------
// Authorization Code flow, scope user-read-currently-playing only. Tokens live in Redis and never
// reach the website or the clip. Development Mode apps need the app owner to have Premium.
// Environment variables: SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, optional SPOTIFY_REDIRECT_URI
// (default: <this site>/api/spotify/callback - must match the Spotify dashboard exactly).
const SPOTIFY_SCOPE = "user-read-currently-playing";
const SPOTIFY_CACHE_MS = 10_000;          // ask Spotify at most every 10 s
const SPOTIFY_STATE_MAX_AGE_MS = 10 * 60_000;

function spotifyConfigured() {
  return Boolean(process.env.SPOTIFY_CLIENT_ID && process.env.SPOTIFY_CLIENT_SECRET);
}

function redirectUri(request) {
  return process.env.SPOTIFY_REDIRECT_URI || `${new URL(request.url).origin}/api/spotify/callback`;
}

async function spotifyToken(params) {
  const basic = Buffer.from(`${process.env.SPOTIFY_CLIENT_ID}:${process.env.SPOTIFY_CLIENT_SECRET}`).toString("base64");
  const response = await fetch("https://accounts.spotify.com/api/token", {
    method: "POST",
    headers: { authorization: `Basic ${basic}`, "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams(params),
  });
  const body = await response.json().catch(() => ({}));
  return { ok: response.ok, status: response.status, body };
}

function saveTokens(body, previous = {}) {
  return {
    // Spotify may or may not send a new refresh token; keep the old one if not.
    refresh_token: body.refresh_token ?? previous.refresh_token,
    access_token: body.access_token,
    expires_at: Date.now() + (body.expires_in ?? 3600) * 1000 - 60_000, // refresh a minute early
  };
}

async function accessToken(db, auth) {
  if (auth.access_token && Date.now() < auth.expires_at) return auth.access_token;
  const result = await spotifyToken({ grant_type: "refresh_token", refresh_token: auth.refresh_token });
  if (!result.ok) {
    if (result.body?.error === "invalid_grant") {  // revoked or expired: needs reconnecting
      await db.set(KEYS.spotifyAuth, null);
      throw Object.assign(new Error("Spotify access was revoked. Connect again."), { revoked: true });
    }
    throw new Error(`Spotify token refresh failed (${result.status})`);
  }
  const next = saveTokens(result.body, auth);
  await db.set(KEYS.spotifyAuth, next);
  return next.access_token;
}

function trackFrom(data) {
  const item = data?.item;
  if (!item) return { playing: false, title: null, artist: null, image: null };
  const artist = item.artists?.map((a) => a.name).join(", ") || item.show?.name || null;
  return {
    playing: Boolean(data.is_playing),
    title: item.name ?? null,
    artist,
    image: item.album?.images?.at(-1)?.url ?? null, // smallest cover, for the website only
  };
}

// What's playing now, from a 10 s cache. { configured, connected, playing, title, artist, image, error? }
export async function nowPlaying() {
  const configured = spotifyConfigured();
  const db = getStore();
  const auth = configured ? await db.get(KEYS.spotifyAuth) : null;
  if (!auth?.refresh_token) return { configured, connected: false };

  const cached = await db.get(KEYS.spotifyNow);
  if (cached && Date.now() - cached.fetched_at < SPOTIFY_CACHE_MS) return cached.result;

  const quiet = { configured, connected: true, playing: false, title: null, artist: null, image: null };
  let result;
  try {
    const token = await accessToken(db, auth);
    const response = await fetch("https://api.spotify.com/v1/me/player/currently-playing?additional_types=episode", {
      headers: { authorization: `Bearer ${token}` },
    });
    if (response.status === 204) {
      result = quiet; // nothing playing
    } else if (response.status === 401) {
      await db.set(KEYS.spotifyAuth, { ...auth, expires_at: 0 }); // force a token refresh next time
      result = cached?.result ?? quiet;
    } else if (response.status === 429) {
      result = cached?.result ?? quiet;
      await db.set(KEYS.spotifyNow, { fetched_at: Date.now() + 20_000, result }); // back off ~30 s
      return result;
    } else if (!response.ok) {
      result = { ...(cached?.result ?? quiet), error: `Spotify error ${response.status}` };
    } else {
      result = { configured, connected: true, ...trackFrom(await response.json()) };
    }
  } catch (err) {
    if (err.revoked) {
      await db.set(KEYS.spotifyNow, null);
      return { configured, connected: false, error: err.message };
    }
    console.error(err);
    result = { ...(cached?.result ?? quiet), error: "Couldn't reach Spotify" };
  }
  await db.set(KEYS.spotifyNow, { fetched_at: Date.now(), result });
  return result;
}

// The clip gets plain text only: accents removed (e.g. "Beyonce") since its font is ASCII.
function deviceSpotify(now) {
  const plain = (text) => (text ? text.normalize("NFD").replace(/[\u0300-\u036f]/g, "").slice(0, 80) : "");
  if (!now.connected) return { state: "disconnected", title: "", artist: "" };
  if (!now.title) return { state: "idle", title: "", artist: "" };
  return { state: now.playing ? "playing" : "paused", title: plain(now.title), artist: plain(now.artist) };
}

// Website: start connecting. Returns Spotify's authorize URL (the browser then goes there).
export const postSpotifyLogin = endpoint("CONTROL_TOKEN", async (request) => {
  if (!spotifyConfigured()) return error(500, "SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET are not set in Vercel");
  const state = crypto.randomUUID();
  await getStore().set(KEYS.spotifyState, { state, created_at: Date.now() });
  const url = new URL("https://accounts.spotify.com/authorize");
  url.search = new URLSearchParams({
    response_type: "code",
    client_id: process.env.SPOTIFY_CLIENT_ID,
    scope: SPOTIFY_SCOPE,
    redirect_uri: redirectUri(request),
    state,
  }).toString();
  return json({ url: url.toString() });
});

// Spotify redirects the browser here. Protected by the one-time state value instead of a token.
export const getSpotifyCallback = async (request) => {
  const back = (result) => Response.redirect(`${new URL(request.url).origin}/?spotify=${result}#screens`, 302);
  try {
    if (!spotifyConfigured() || !getStore()) return back("error");
    const url = new URL(request.url);
    const db = getStore();
    const saved = await db.get(KEYS.spotifyState);
    await db.set(KEYS.spotifyState, null); // one use only
    const state = url.searchParams.get("state") ?? "";
    if (!saved?.state || !sameToken(state, saved.state) || Date.now() - saved.created_at > SPOTIFY_STATE_MAX_AGE_MS) {
      return back("error");
    }
    if (url.searchParams.get("error") || !url.searchParams.get("code")) return back("denied");
    const result = await spotifyToken({
      grant_type: "authorization_code",
      code: url.searchParams.get("code"),
      redirect_uri: redirectUri(request),
    });
    if (!result.ok || !result.body.refresh_token) return back("error");
    await db.set(KEYS.spotifyAuth, saveTokens(result.body));
    await db.set(KEYS.spotifyNow, null);
    return back("connected");
  } catch (err) {
    console.error(err);
    return back("error");
  }
};

// Website: forget the Spotify connection (tokens deleted from Redis).
export const postSpotifyDisconnect = endpoint("CONTROL_TOKEN", async () => {
  const db = getStore();
  await db.set(KEYS.spotifyAuth, null);
  await db.set(KEYS.spotifyNow, null);
  return json({ connected: false });
});
