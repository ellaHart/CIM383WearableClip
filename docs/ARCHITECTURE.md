# Mood Clip: website controller architecture

```
 iPhone (Safari)                 Cloudflare (HTTPS)                    Clip (T-Display-S3)
 ┌──────────────┐  /api/state    ┌──────────────────────────┐  POST /api/device/sync   ┌──────────────┐
 │ web/public   │ ─────────────▶ │ Worker  web/src/worker.js │ ◀────────────────────── │ cloud_sync.py│
 │ (static site)│  /api/command  │ + Durable Object ClipState│  every 5 s over the     │ (keep-alive  │
 └──────────────┘                └──────────────────────────┘  phone's hotspot        │  HTTPS)      │
                                                                                        └──────────────┘
```

The phone and the clip never talk directly. Both talk to the same HTTPS backend, so it doesn't
matter that an iPhone hotspot may block device-to-device traffic, and the website works from anywhere.

## Why this stack
- **Cloudflare Worker + Workers Assets** serves the website *and* the API from one free HTTPS URL
  (`https://moodclip.<subdomain>.workers.dev`). No server to run, no separate frontend host.
- **One Durable Object** (`ClipState`) stores the state. It is strongly consistent, so the website
  and the clip always read the latest command (Workers KV can lag up to a minute).
- **No frontend framework**: plain HTML/CSS/JS in `web/public`. Nothing to build; easy to read.
- **No extra CircuitPython libraries**: `cloud_sync.py` is a small HTTPS client built on the
  built-in `wifi`, `socketpool` and `ssl` modules, with one kept-alive connection
  (measured: first request ~3.2 s, later ones ~0.2 s).

## Information architecture (bottom tab bar)
| Tab | Contents | Status |
|---|---|---|
| **Dashboard** | Live 320×170 preview (grayscale, colour toggle), current screen + mood, online/offline, last sync, the five modes | Working |
| **Screens** | Mood Screens (8 moods, tap to send); Spotify, Magic 8 Ball, Aquarium, Custom shown disabled with planned behaviour | Moods working |
| **Create** | Message editor, background colour, live preview; image upload and "Send to clip" disabled | Preview only |
| **Device** | Wi-Fi status, signal, IP, last sync; battery; button mapping; remember last screen; brightness; display on/off | Status working, controls placeholders |

## Data model
Mood ids come from `device/moods.json`, the single source shared by the clip and the API:
`cheer, friendly, alert, love, sleepy, laptop, judging, eating`.

**Modes**: `moods` (ready), `spotify`, `magic8`, `aquarium`, `custom` (planned).

**Desired state** (what the website asks for):
```json
{
  "version": 3,
  "updated_at": "2026-11-17T20:52:56Z",
  "mode": "moods",
  "modes": {
    "moods": { "mood": "love" },
    "spotify": {},
    "magic8": {},
    "aquarium": {},
    "custom": { "text": "", "bg": "#FFFFFF", "image": null }
  }
}
```
**Reported state** (what the clip says it shows):
```json
{ "mode": "moods", "mood": "love", "applied_version": 3, "rssi": -41, "ip": "172.20.10.4",
  "uptime": 120, "battery": null, "firmware": "circuitpython-10.3.2", "last_seen": "…" }
```
`version` goes up with every website command. The clip applies each version once and stores the
last applied version in NVM, so physical button presses (and restarts) are never overwritten by an
old command. The website shows "Queued" until `applied_version` catches up, then "On clip".

## API
| Method & path | Auth | Purpose |
|---|---|---|
| `GET /api/catalog` | none | Modes + moods (from `device/moods.json`) |
| `GET /api/state` | `Bearer CONTROL_TOKEN` | `{ desired, reported }` |
| `POST /api/command` | `Bearer CONTROL_TOKEN` | `{ "mode": "moods", "mood": "love" }` → bumps version. Planned modes return 409. |
| `POST /api/device/sync` | `Bearer DEVICE_TOKEN` | Clip sends its reported state, gets `{ version, mode, mood }` back |

## Secrets
- `CONTROL_TOKEN`: the code you type once into the website on your phone (stored in that phone's
  browser only). `DEVICE_TOKEN`: lives only in the clip's `settings.toml`.
- Both are Cloudflare secrets (`npx wrangler secret put …`), never in git or in the frontend code.
  Local development uses `web/.dev.vars` (gitignored).

## Clip behaviour
- `cloud_sync.py` checks in every 5 s while Wi-Fi is up, and right away after a button press or an
  applied command. A request can pause the display for at most 5 s (usually ~0.2 s).
- Failures back off 10/20/40/60 s and are printed as `Cloud:` lines; the display loop never crashes.
- Without Wi-Fi or without `MOODCLIP_API_URL`, the clip works exactly as before (buttons, NVM memory).

## File structure
```
device/            CircuitPython (copied to CIRCUITPY by tools/deploy.ps1)
  code.py          screens, buttons, apply_remote()
  moods.json       mood list shared with the website
  billboard.py     scrolling text + sprite view
  wifi_link.py     hotspot connection
  cloud_sync.py    HTTPS check-ins with the API
web/
  wrangler.jsonc   Worker config (assets + Durable Object)
  src/worker.js    API + ClipState
  public/          index.html, app.css, app.js (sprites copied in by scripts/sync-assets.mjs)
  .dev.vars.example
docs/ARCHITECTURE.md
```
