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
const M8 = { centerX: 160, top: 22, half: 96, apex: 153, textTop: 24, margin: 2, scale: 2, inkRows: 10 };
const FONT_W = 6;  // the clip's built-in font cell, before scaling
const FONT_H = 12;

// Same wrapping as magic8.layout() on the clip: one text size, long answers wrap onto more lines.
function magic8Layout(answer) {
  const words = answer.replace("–", "-").split(/\s+/);
  const lines = [];
  let y = M8.textTop;
  while (words.length) {
    const bottom = y + M8.inkRows * M8.scale;
    const half = (M8.half * (M8.apex - bottom)) / (M8.apex - M8.top) - M8.margin;
    const limit = Math.floor((2 * half) / (FONT_W * M8.scale));
    let line = words.shift();
    while (words.length && line.length + 1 + words[0].length <= limit) line += ` ${words.shift()}`;
    lines.push(line);
    y += FONT_H * M8.scale;
  }
  return lines;
}

function drawPixelText(ctx, text, x, y, scale, color) {
  ctx.fillStyle = color;
  ctx.font = `bold ${Math.round(FONT_H * scale * 0.85)}px ui-monospace, Menlo, Consolas, monospace`;
  ctx.textBaseline = "top";
  [...text].forEach((char, i) => ctx.fillText(char, x + i * FONT_W * scale, y));
}

// Aquarium preview: first frame of each fish at its starting spot (same as device/aquarium.py).
const AQUARIUM_FISH = [
  { sheet: "aquarium/clownfish.png", w: 38, h: 30, x: 40, y: 26 },
  { sheet: "aquarium/blue_tang.png", w: 38, h: 30, x: 230, y: 70, flip: true },
  { sheet: "aquarium/betta.png", w: 54, h: 42, x: 140, y: 44 },
];

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
    const key = screen ? `${screen.text}|${screen.bg}|${screen.sprite}|${screen.border}|${screen.image}|${screen.answer}|${Boolean(screen.fish)}|${screen.board}` : "";
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

    // Full-screen artwork (Magic 8 Ball, aquarium); falls back to a caption if the image is missing.
    const art = loadImage(screen.image);
    if (art && screen.cover) {
      // Fill 320x170 without stretching, cropping the overflow evenly (like the clip's background).
      const scale = Math.max(320 / art.naturalWidth, 170 / art.naturalHeight);
      const sw = 320 / scale, sh = 170 / scale;
      ctx.imageSmoothingEnabled = true;
      ctx.drawImage(art, (art.naturalWidth - sw) / 2, (art.naturalHeight - sh) / 2, sw, sh, 0, 0, 320, 170);
      ctx.imageSmoothingEnabled = false;
    } else if (art) ctx.drawImage(art, 0, 0, 320, 170);
    else if (screen.caption) drawPixelText(ctx, screen.caption, 160 - screen.caption.length * FONT_W, 73, 2, "#fff");
    for (const fish of screen.fish ?? []) {
      const sheet = loadImage(fish.sheet);
      if (!sheet) continue;
      ctx.save();
      if (fish.flip) { ctx.translate(fish.x * 2 + fish.w, 0); ctx.scale(-1, 1); }
      ctx.drawImage(sheet, 0, 0, fish.w, fish.h, fish.x, fish.y, fish.w, fish.h);
      ctx.restore();
    }
    if (screen.board !== undefined) {
      const drawing = previewDrawing(screen.board);
      if (drawing) ctx.drawImage(drawing, 0, 0);
      else ["Draw something", "on your phone!"].forEach((line, i) =>
        drawPixelText(ctx, line, 160 - line.length * FONT_W, 61 + i * 26, 2, "#111"));
    }
    if (screen.answer) {
      magic8Layout(screen.answer).forEach((line, i) =>
        drawPixelText(ctx, line, M8.centerX - (line.length * FONT_W * M8.scale) / 2, M8.textTop + i * FONT_H * M8.scale, M8.scale, "#fff"));
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
  if (mode === "whiteboard") return { board: reported?.drawing_rev || state.desired?.modes?.whiteboard?.rev || 0, bg: "#fff" };
  if (mode === "aquarium") return { image: "aquarium/background.jpg", cover: true, fish: AQUARIUM_FISH, bg: "#2E8FC0" };
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
  updateBoardStatus();
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

// ---------- Whiteboard ----------
// The canvas is exactly the clip's 320x170 pixels (scaled up with CSS, pixelated), so what you see
// is what the clip shows. After each stroke the canvas is snapped to pure black and white.
//
// Upload format (must match device/whiteboard.py): 320x170, 1 bit per pixel, 1 = black.
// Rows top to bottom, 40 bytes per row; in each byte the leftmost pixel is the most significant bit.
const BOARD_W = 320;
const BOARD_H = 170;
const BOARD_BYTES = (BOARD_W / 8) * BOARD_H; // 6800
const BOARD_TOOLS = { pen: { color: "#000", width: 3 }, eraser: { color: "#fff", width: 10 } };

const board = $("#board");
const boardCtx = board.getContext("2d", { willReadFrequently: true });
let boardTool = "pen";
let boardPointer = null;
let boardLast = null;
let boardSending = false;
let boardWaitingFor = null; // drawing revision we're waiting for the clip to show

function setBoardStatus(text, done = false) {
  const el = $("#board-status");
  el.textContent = text;
  el.classList.toggle("is-done", done);
}

function clearBoard() {
  boardCtx.fillStyle = "#fff";
  boardCtx.fillRect(0, 0, BOARD_W, BOARD_H);
}

function boardPoint(event) {
  const rect = board.getBoundingClientRect(); // CSS size can be anything; map back to 320x170
  return {
    x: ((event.clientX - rect.left) * BOARD_W) / rect.width,
    y: ((event.clientY - rect.top) * BOARD_H) / rect.height,
  };
}

function boardStroke(from, to) {
  const { color, width } = BOARD_TOOLS[boardTool];
  boardCtx.strokeStyle = color;
  boardCtx.lineWidth = width;
  boardCtx.lineCap = "round";
  boardCtx.lineJoin = "round";
  boardCtx.beginPath();
  boardCtx.moveTo(from.x, from.y);
  boardCtx.lineTo(to.x, to.y);
  boardCtx.stroke();
}

function boardDot(point) {
  const { color, width } = BOARD_TOOLS[boardTool];
  boardCtx.fillStyle = color;
  boardCtx.beginPath();
  boardCtx.arc(point.x, point.y, width / 2, 0, Math.PI * 2);
  boardCtx.fill();
}

// Snap anti-aliased edges to pure black/white, exactly as the clip will show them.
function snapBoard() {
  const image = boardCtx.getImageData(0, 0, BOARD_W, BOARD_H);
  const px = image.data;
  for (let i = 0; i < px.length; i += 4) {
    const value = px[i] * 0.299 + px[i + 1] * 0.587 + px[i + 2] * 0.114 < 128 ? 0 : 255;
    px[i] = px[i + 1] = px[i + 2] = value;
    px[i + 3] = 255;
  }
  boardCtx.putImageData(image, 0, 0);
}

function encodeBoard() {
  const px = boardCtx.getImageData(0, 0, BOARD_W, BOARD_H).data;
  const bytes = new Uint8Array(BOARD_BYTES);
  for (let y = 0; y < BOARD_H; y++) {
    for (let x = 0; x < BOARD_W; x++) {
      if (px[(y * BOARD_W + x) * 4] < 128) bytes[y * (BOARD_W / 8) + (x >> 3)] |= 0x80 >> (x & 7);
    }
  }
  return bytes;
}

function decodeBoard(bytes) {
  const canvas = document.createElement("canvas");
  canvas.width = BOARD_W;
  canvas.height = BOARD_H;
  const ctx = canvas.getContext("2d");
  const image = ctx.createImageData(BOARD_W, BOARD_H);
  for (let y = 0; y < BOARD_H; y++) {
    for (let x = 0; x < BOARD_W; x++) {
      const black = bytes[y * (BOARD_W / 8) + (x >> 3)] & (0x80 >> (x & 7));
      const i = (y * BOARD_W + x) * 4;
      image.data[i] = image.data[i + 1] = image.data[i + 2] = black ? 0 : 255;
      image.data[i + 3] = 255;
    }
  }
  ctx.putImageData(image, 0, 0);
  return canvas;
}

// Latest drawing for the dashboard preview, fetched once per revision.
const previewCache = { rev: 0, canvas: null, loading: false };
function previewDrawing(rev) {
  if (!rev) return null;
  if (rev !== previewCache.rev && !previewCache.loading) {
    previewCache.loading = true;
    fetch("/api/drawing", { headers: { authorization: `Bearer ${token}` } })
      .then(async (response) => {
        if (!response.ok) throw new Error(`drawing ${response.status}`);
        const bytes = new Uint8Array(await response.arrayBuffer());
        if (bytes.length !== BOARD_BYTES) throw new Error("bad drawing size");
        previewCache.canvas = decodeBoard(bytes);
        previewCache.rev = Number(response.headers.get("x-drawing-rev")) || rev;
      })
      .catch((error) => console.warn(error))
      .finally(() => { previewCache.loading = false; });
  }
  return previewCache.canvas;
}

board.addEventListener("pointerdown", (event) => {
  if (boardPointer !== null) return; // one finger at a time
  event.preventDefault();
  board.setPointerCapture(event.pointerId);
  boardPointer = event.pointerId;
  boardLast = boardPoint(event);
  boardDot(boardLast); // a tap makes a dot (browsers skip zero-length strokes)
});
board.addEventListener("pointermove", (event) => {
  if (event.pointerId !== boardPointer) return;
  event.preventDefault();
  for (const point of event.getCoalescedEvents?.() ?? [event]) { // every sample, for smooth lines
    const next = boardPoint(point);
    boardStroke(boardLast, next);
    boardLast = next;
  }
});
function endStroke(event) {
  if (event.pointerId !== boardPointer) return;
  boardPointer = null;
  snapBoard();
}
board.addEventListener("pointerup", endStroke);
board.addEventListener("pointercancel", endStroke);

document.querySelectorAll("[data-tool]").forEach((button) =>
  button.addEventListener("click", () => {
    boardTool = button.dataset.tool;
    document.querySelectorAll("[data-tool]").forEach((b) => b.setAttribute("aria-pressed", String(b === button)));
  }));
$("#board-clear").addEventListener("click", () => {
  clearBoard();
  setBoardStatus("Cleared. Nothing changes on the clip until you send.");
});

$("#board-send").addEventListener("click", async () => {
  if (boardSending) return;
  boardSending = true;
  const button = $("#board-send");
  button.disabled = true;
  button.textContent = "Sending…";
  setBoardStatus("Sending your drawing…");
  try {
    const { rev, desired } = await api("/api/drawing", {
      method: "POST",
      headers: { "content-type": "application/octet-stream" },
      body: encodeBoard(),
    });
    state.desired = desired;
    boardWaitingFor = rev;
    setBoardStatus(isOnline()
      ? "Sent! Waiting for the clip to show it…"
      : "Saved. It'll appear when the clip is back online.");
  } catch (error) {
    if (error instanceof AuthError) return handleError(error);
    setBoardStatus(`Couldn't send (${error.message}). Your drawing is still here, so try again.`);
  } finally {
    boardSending = false;
    button.disabled = false;
    button.textContent = "Send to Clip";
  }
});

// Only claim it's on the clip once the clip reports this drawing on its whiteboard screen.
function updateBoardStatus() {
  const reported = state.reported;
  if (boardWaitingFor && reported?.mode === "whiteboard" && (reported.drawing_rev ?? 0) >= boardWaitingFor) {
    boardWaitingFor = null;
    setBoardStatus("✓ Showing on the clip", true);
  }
}

clearBoard();

// ---------- Routing ----------
const VIEWS = ["dashboard", "screens", "draw", "create", "settings"];
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
