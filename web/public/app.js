// Mood Clip controller. Talks only to this site's own /api (same origin, HTTPS).
const TOKEN_KEY = "moodclip.controlCode";
const COLOUR_KEY = "moodclip.colour";
const POLL_MS = 3000;
const ONLINE_WINDOW_MS = 20000; // the clip syncs every ~5 s, so 20 s of silence = offline
const SPOTIFY_PLACEHOLDER = { text: "Spotify not connected yet", bg: "#93BA9B", sprite: "music" };

const $ = (selector) => document.querySelector(selector);

// localStorage can throw (private mode, blocked storage); the app must still work.
const store = {
  get(key) { try { return localStorage.getItem(key); } catch { return null; } },
  set(key, value) { try { localStorage.setItem(key, value); } catch { /* not persisted */ } },
  remove(key) { try { localStorage.removeItem(key); } catch { /* ignore */ } },
};

let token = store.get(TOKEN_KEY);
let catalog = { modes: [], moods: [] };
let state = { desired: null, reported: null };
let sendingMood = null;
let pollTimer = null;

// ---------- API ----------
class AuthError extends Error {}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "content-type": "application/json",
      ...(token ? { authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });
  const body = await response.json().catch(() => ({}));
  if (response.status === 401) throw new AuthError(body.error || "Wrong control code");
  if (!response.ok) throw new Error(body.error || `Request failed (${response.status})`);
  return body;
}

// ---------- Preview: draws the clip's 320x170 screen like the device does ----------
const imageCache = new Map();
function loadImage(path) {
  if (!path) return null;
  if (!imageCache.has(path)) {
    const img = new Image();
    img.src = path;
    imageCache.set(path, img);
  }
  const img = imageCache.get(path);
  return img.complete && img.naturalWidth ? img : null;
}

// Magic 8 Ball answer triangle in assets/magic8/answer.png (same numbers as device/magic8.py).
const M8 = { centerX: 160, top: 22, half: 96, apex: 153, textTop: 30, margin: 8 };
const FONT_W = 6;  // the clip's built-in font cell, before scaling
const FONT_H = 12;

// Same wrapping as magic8.layout() on the clip: 2x text if it fits the triangle, else 1x.
function magic8Layout(answer) {
  const allWords = answer.replace("–", "-").split(/\s+/);
  for (const scale of [2, 1]) {
    const words = [...allWords];
    const lines = [];
    let y = M8.textTop;
    let fits = true;
    while (words.length) {
      const bottom = y + FONT_H * scale;
      const half = (M8.half * (M8.apex - bottom)) / (M8.apex - M8.top) - M8.margin;
      const limit = Math.floor((2 * half) / (FONT_W * scale));
      let line = words.shift();
      if (line.length > limit) { fits = false; break; }
      while (words.length && line.length + 1 + words[0].length <= limit) line += ` ${words.shift()}`;
      lines.push(line);
      y += FONT_H * scale;
    }
    if (fits) return { scale, lines };
  }
  return { scale: 1, lines: [answer] };
}

function drawPixelText(ctx, text, x, y, scale, color) {
  ctx.fillStyle = color;
  ctx.font = `bold ${Math.round(FONT_H * scale * 0.85)}px ui-monospace, Menlo, Consolas, monospace`;
  ctx.textBaseline = "top";
  [...text].forEach((char, i) => ctx.fillText(char, x + i * FONT_W * scale, y));
}

const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

class Preview {
  // Device layout: text 6x12 font at 5x (30 px per character), sprite 40x40 at 3x, centred at the bottom.
  static CHAR_W = 30;
  static SPEED = 90; // px per second, matches the clip

  constructor(canvas) {
    this.ctx = canvas.getContext("2d");
    this.screen = null;
    this.x = 320;
    this.last = 0;
    requestAnimationFrame((t) => this.frame(t));
  }

  set(screen) {
    const key = screen ? `${screen.text}|${screen.bg}|${screen.sprite}|${screen.border}|${screen.image}|${screen.answer}` : "";
    if (key === this.key) return;
    this.key = key;
    this.screen = screen;
    this.x = 320;
  }

  frame(time) {
    const dt = this.last ? Math.min((time - this.last) / 1000, 0.1) : 0;
    this.last = time;
    const screen = this.screen;
    if (screen?.text) {
      const width = screen.text.length * Preview.CHAR_W;
      if (reduceMotion.matches) {
        this.x = 8;
      } else {
        this.x -= Preview.SPEED * dt;
        if (this.x < -width) this.x = 320 + 40;
      }
    }
    this.draw();
    requestAnimationFrame((t) => this.frame(t));
  }

  draw() {
    const ctx = this.ctx;
    const screen = this.screen;
    ctx.imageSmoothingEnabled = false;
    ctx.fillStyle = screen ? screen.bg : "#000";
    ctx.fillRect(0, 0, 320, 170);
    if (!screen) return;

    // Full-screen artwork (Magic 8 Ball); falls back to a caption if the image is missing.
    const art = loadImage(screen.image);
    if (art) ctx.drawImage(art, 0, 0, 320, 170);
    else if (screen.caption) drawPixelText(ctx, screen.caption, 160 - screen.caption.length * FONT_W, 73, 2, "#fff");
    if (screen.answer) {
      const { scale, lines } = magic8Layout(screen.answer);
      lines.forEach((line, i) =>
        drawPixelText(ctx, line, M8.centerX - (line.length * FONT_W * scale) / 2, M8.textTop + i * FONT_H * scale, scale, "#fff"));
    }

    const img = screen.sprite ? loadImage(`sprites/${screen.sprite}.png`) : null;
    if (img) ctx.drawImage(img, 100, 50, 120, 120);

    if (screen.text) {
      ctx.fillStyle = "#111";
      ctx.font = "bold 46px ui-monospace, Menlo, Consolas, monospace";
      ctx.textBaseline = "top";
      [...screen.text].forEach((char, i) => ctx.fillText(char, this.x + i * Preview.CHAR_W, 10));
    }

    if (screen.border) {
      ctx.strokeStyle = "#111";
      ctx.lineWidth = 8;
      ctx.strokeRect(0, 0, 320, 170);
    }
  }
}

const dashPreview = new Preview($("#dash-preview"));
const createPreview = new Preview($("#create-preview"));

// ---------- Helpers ----------
const moodById = (id) => catalog.moods.find((mood) => mood.id === id);
const modeById = (id) => catalog.modes.find((mode) => mode.id === id);

function ago(iso) {
  if (!iso) return "Never";
  const seconds = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 1000));
  if (seconds < 5) return "Just now";
  if (seconds < 60) return `${seconds} s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  return new Date(iso).toLocaleString();
}

function isOnline() {
  const seen = state.reported?.last_seen;
  return Boolean(seen) && Date.now() - Date.parse(seen) < ONLINE_WINDOW_MS;
}

function signalText(rssi) {
  if (typeof rssi !== "number") return "–";
  const label = rssi >= -55 ? "Strong" : rssi >= -70 ? "Good" : "Weak";
  return `${label} (${rssi} dBm)`;
}

function isPending() {
  const desired = state.desired;
  if (!desired || desired.version === 0) return false;
  return (state.reported?.applied_version ?? -1) < desired.version;
}

// What the clip is showing (from its last report), falling back to the last command.
function shownScreen() {
  const reported = state.reported;
  const mode = reported?.mode ?? state.desired?.mode;
  if (mode === "spotify") return SPOTIFY_PLACEHOLDER;
  if (mode === "magic8") {
    const m8 = reported?.mode === "magic8" ? reported.magic8 : null;
    return m8?.state === "answer" && m8.answer
      ? { image: "magic8/answer.png", answer: m8.answer, bg: "#241C33" }
      : { image: "magic8/idle.png", caption: "Ask a question...", bg: "#7B5CC4" };
  }
  const moodId = reported?.mood ?? state.desired?.modes?.moods?.mood;
  return moodById(moodId) ?? null;
}

let toastTimer = null;
function toast(message) {
  const el = $("#toast");
  el.textContent = message;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 3200);
}

// ---------- Rendering ----------
function renderStatus() {
  const online = isOnline();
  const pill = $("#status-pill");
  pill.classList.toggle("is-online", online);
  pill.querySelector(".pill-text").textContent = online ? "Clip online" : state.reported ? "Clip offline" : "Clip not seen yet";

  const reported = state.reported;
  const mode = modeById(reported?.mode);
  const mood = moodById(reported?.mood);
  $("#dash-mode").textContent = mode ? mode.name : "–";
  const onMagic8 = reported?.mode === "magic8";
  $("#dash-mood-label").textContent = onMagic8 ? "Answer" : "Mood";
  $("#dash-mood").textContent = onMagic8 ? (reported.magic8?.answer ?? "No shake yet") : mood ? mood.text : "–";
  $("#dash-online").textContent = online ? "Online" : "Offline";
  $("#dash-sync").textContent = ago(reported?.last_seen);
  $("#dash-pending").hidden = !isPending();

  $("#set-wifi").textContent = online ? "Connected to hotspot" : "Not connected";
  $("#set-signal").textContent = signalText(reported?.rssi);
  $("#set-ip").textContent = reported?.ip || "–";
  $("#set-sync").textContent = ago(reported?.last_seen);
  $("#set-battery").textContent = typeof reported?.battery === "number" ? `${reported.battery}%` : "Not reported";

  dashPreview.set(shownScreen());
  renderModeTiles();
  renderMoodButtons();
  renderModeCards();
}

function renderModeTiles() {
  const container = $("#dash-modes");
  const currentMode = state.reported?.mode;
  container.replaceChildren(...catalog.modes.map((mode) => {
    const ready = mode.status === "ready";
    const tile = document.createElement("button");
    tile.type = "button";
    tile.className = "mode-tile";
    tile.disabled = !ready;
    tile.setAttribute("aria-current", String(mode.id === currentMode));
    tile.innerHTML = `<strong></strong><span class="small muted"></span>`;
    tile.querySelector("strong").textContent = mode.name;
    tile.querySelector("span").textContent = ready ? (mode.id === currentMode ? "On clip now" : "Open") : "Coming soon";
    if (ready) tile.addEventListener("click", () => { location.hash = "#screens"; });
    return tile;
  }));
}

function renderScreenList() {
  const list = $("#screen-list");
  list.replaceChildren(...catalog.modes.map((mode) => {
    const ready = mode.status === "ready";
    const card = document.createElement("article");
    card.className = `card screen-card${ready ? "" : " is-disabled"}`;
    card.innerHTML = `<header><h3></h3>${ready ? "" : '<span class="badge">Soon</span>'}</header><p></p>`;
    card.querySelector("h3").textContent = mode.name;
    card.querySelector("p").textContent = mode.summary;
    if (mode.id === "moods") {
      const grid = document.createElement("div");
      grid.className = "mood-grid";
      grid.id = "mood-grid";
      card.append(grid);
    } else {
      if (mode.id === "magic8") {
        const latest = document.createElement("p");
        latest.id = "magic8-latest";
        latest.className = "latest";
        card.append(latest);
      }
      const button = document.createElement("button");
      button.className = "btn";
      button.type = "button";
      button.disabled = !ready;
      button.style.marginTop = "12px";
      button.textContent = "Show on clip";
      if (ready) {
        button.dataset.modeButton = mode.id;
        button.addEventListener("click", () => sendCommand({ mode: mode.id }));
      }
      card.append(button);
    }
    return card;
  }));
  renderMoodButtons();
  renderModeCards();
}

// "Show on clip" buttons for ready modes other than Moods, plus Magic 8's latest answer.
function renderModeCards() {
  const reported = state.reported;
  const queuedMode = isPending() ? state.desired?.mode : null;
  document.querySelectorAll("[data-mode-button]").forEach((button) => {
    const id = button.dataset.modeButton;
    const onClip = reported?.mode === id;
    button.textContent = onClip ? "On clip now" : queuedMode === id ? "Queued…" : "Show on clip";
    button.setAttribute("aria-pressed", String(onClip));
  });
  const latest = $("#magic8-latest");
  if (latest) {
    const m8 = reported?.magic8;
    latest.textContent = m8?.answer
      ? `Latest answer: “${m8.answer}”${m8.count ? ` (shake #${m8.count})` : ""}`
      : "No answer yet. Switch the clip to Magic 8 Ball and press its bottom button.";
  }
}

function renderMoodButtons() {
  const grid = $("#mood-grid");
  if (!grid) return;
  const onClip = state.reported?.mode === "moods" ? state.reported?.mood : null;
  if (grid.childElementCount !== catalog.moods.length) {
    grid.replaceChildren(...catalog.moods.map((mood, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "mood-btn";
      button.dataset.mood = mood.id;
      button.innerHTML = `<span class="num"></span><img class="sprite" alt="" width="64" height="64"><span class="label"></span>`;
      button.querySelector(".num").textContent = index + 1;
      button.querySelector("img").src = `sprites/${mood.sprite}.png`;
      button.querySelector(".label").textContent = mood.text;
      button.setAttribute("aria-label", `Mood ${index + 1}: ${mood.text}`);
      button.addEventListener("click", () => sendMood(mood.id));
      return button;
    }));
  }
  const queued = isPending() && state.desired?.mode === "moods" ? state.desired.modes.moods.mood : null;
  for (const button of grid.children) {
    const id = button.dataset.mood;
    button.setAttribute("aria-pressed", String(id === onClip));
    button.classList.toggle("is-sending", id === sendingMood);
    button.classList.toggle("is-queued", id === queued && id !== onClip);
  }
}

// ---------- Actions ----------
function sendMood(moodId) {
  return sendCommand({ mode: "moods", mood: moodId });
}

async function sendCommand(command) {
  if (sendingMood) return;
  sendingMood = command.mood ?? command.mode;
  renderMoodButtons();
  try {
    const { desired } = await api("/api/command", { method: "POST", body: JSON.stringify(command) });
    state.desired = desired;
    toast(isOnline() ? "Sent. The clip updates within a few seconds." : "Saved. The clip will update when it's back online.");
  } catch (error) {
    handleError(error);
  } finally {
    sendingMood = null;
    renderStatus();
  }
}

async function refresh() {
  try {
    state = await api("/api/state");
    renderStatus();
  } catch (error) {
    handleError(error, { quiet: true });
  }
}

function handleError(error, { quiet = false } = {}) {
  if (error instanceof AuthError) {
    showGate(error.message);
    return;
  }
  console.error(error);
  if (!quiet) toast(error.message || "Something went wrong");
  else $("#status-pill .pill-text").textContent = "Can't reach server";
}

function startPolling() {
  stopPolling();
  refresh();
  pollTimer = setInterval(() => { if (!document.hidden) refresh(); }, POLL_MS);
}

function stopPolling() {
  clearInterval(pollTimer);
  pollTimer = null;
}

// ---------- Gate ----------
function showGate(message = "") {
  stopPolling();
  token = null;
  store.remove(TOKEN_KEY);
  $("#app").hidden = true;
  $("#gate").hidden = false;
  $("#gate-error").hidden = !message;
  $("#gate-error").textContent = message;
  $("#gate-code").focus();
}

async function showApp() {
  $("#gate").hidden = true;
  $("#app").hidden = false;
  route();
  startPolling();
}

$("#gate-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  token = $("#gate-code").value.trim();
  try {
    state = await api("/api/state");
    store.set(TOKEN_KEY, token);
    $("#gate-code").value = "";
    renderStatus();
    showApp();
  } catch (error) {
    showGate(error instanceof AuthError ? "That code didn't work. Check it and try again." : error.message);
  }
});

$("#forget-code").addEventListener("click", () => showGate());

// ---------- Create (preview only) ----------
function updateCreatePreview() {
  const text = $("#create-text").value;
  $("#create-count").textContent = `${text.length}/80`;
  createPreview.set({ text: text || "Your message here", bg: $("#create-bg").value, sprite: null });
}
$("#create-text").addEventListener("input", updateCreatePreview);
$("#create-bg").addEventListener("input", updateCreatePreview);

// ---------- Colour toggle for previews ----------
function applyColour(on) {
  document.body.classList.toggle("mono", !on);
  document.querySelectorAll("[data-colour-toggle]").forEach((box) => { box.checked = on; });
  store.set(COLOUR_KEY, on ? "1" : "0");
}
document.querySelectorAll("[data-colour-toggle]").forEach((box) =>
  box.addEventListener("change", () => applyColour(box.checked)));

// ---------- Routing ----------
const VIEWS = ["dashboard", "screens", "create", "settings"];
function route() {
  const view = VIEWS.includes(location.hash.slice(1)) ? location.hash.slice(1) : "dashboard";
  document.querySelectorAll("[data-view]").forEach((el) => { el.hidden = el.id !== view; });
  document.querySelectorAll("[data-tab]").forEach((tab) => {
    if (tab.dataset.tab === view) tab.setAttribute("aria-current", "page");
    else tab.removeAttribute("aria-current");
  });
  window.scrollTo(0, 0);
}
window.addEventListener("hashchange", route);
document.addEventListener("visibilitychange", () => { if (!document.hidden && pollTimer) refresh(); });

// ---------- Start ----------
async function init() {
  applyColour(store.get(COLOUR_KEY) === "1");
  updateCreatePreview();
  try {
    catalog = await api("/api/catalog");
  } catch (error) {
    toast("Can't reach the server. Check your connection.");
    console.error(error);
  }
  renderScreenList();
  if (token) showApp();
  else showGate();
}
init();
