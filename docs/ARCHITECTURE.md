# Mood Clip: website controller architecture

```
 iPhone (Safari)              Vercel (HTTPS)                     Upstash Redis          Clip (T-Display-S3)
 ┌──────────────┐ /api/state  ┌─────────────────────────┐  REST  ┌─────────────┐  POST /api/device/sync  ┌──────────────┐
 │ web/public   │ ──────────▶ │ Vercel Functions web/api│ ─────▶ │ desired     │ ◀────────────────────── │ cloud_sync.py│
 │ (static site)│ /api/command│ (logic in web/lib)      │        │ reported    │  every 5 s over the     │ (keep-alive  │
 └──────────────┘             └─────────────────────────┘        │ version     │  phone's hotspot        │  HTTPS)      │
                                                                  └─────────────┘                          └──────────────┘
```

The phone and the clip never talk directly. Both talk to the same HTTPS backend, so it doesn't
matter that an iPhone hotspot may block device-to-device traffic, and the website works from anywhere.

## Why this stack
- **Vercel**, connected to this GitHub repo: every push builds and deploys automatically; pull
  requests get their own preview URL. The static site and the API share one HTTPS address.
- **Vercel Functions** (`web/api/*.js`) are tiny wrappers; all logic is in `web/lib/core.js`.
- **Upstash Redis** (from the Vercel Marketplace) keeps the state between function calls, which
  don't remember anything on their own. Three keys: `moodclip:desired`, `moodclip:reported`,
  `moodclip:version`. Reads are immediately consistent, so the clip always sees the latest command.
- **No frontend framework**: plain HTML/CSS/JS in `web/public`.
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
Mood ids come from `device/moods.json`, the single source shared by the clip and the API
(`npm run build` turns it into `web/lib/moods.generated.js`):
`cheer, friendly, alert, love, sleepy, laptop, judging, eating`.

**Modes**: `moods`, `magic8`, `aquarium` (ready); `spotify`, `custom` (planned).

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
  "uptime": 120, "battery": null, "firmware": "circuitpython-10.3.2", "last_seen": "…",
  "magic8": { "state": "answer", "answer": "It is certain", "count": 3 } }
```
`magic8` is present once the clip has shown the Magic 8 Ball screen: `state` is
`idle`, `shaking` or `answer`; `count` is answers revealed since the clip started.
`version` goes up with every website command (Redis `INCR`). The clip applies each version once
and stores the last applied version in NVM, so physical button presses (and restarts) are never
overwritten by an old command. The website shows "Queued" until `applied_version` catches up,
then "On clip".

## API
| Method & path | Auth | Purpose |
|---|---|---|
| `GET /api/catalog` | none | Modes + moods (from `device/moods.json`) |
| `GET /api/state` | `Bearer CONTROL_TOKEN` | `{ desired, reported }` |
| `POST /api/command` | `Bearer CONTROL_TOKEN` | `{ "mode": "moods", "mood": "love" }` → bumps version. Planned modes return 409. |
| `POST /api/device/sync` | `Bearer DEVICE_TOKEN` | Clip sends its reported state, gets `{ version, mode, mood }` back |

## Environment variables
| Name | Where it comes from | Who uses it |
|---|---|---|
| `CONTROL_TOKEN` | You make it up (long random string) and add it in Vercel | The code you type once on your phone; stored in that phone's browser only |
| `DEVICE_TOKEN` | You make it up and add it in Vercel | Also goes in the clip's `settings.toml` as `MOODCLIP_DEVICE_TOKEN` |
| `KV_REST_API_URL`, `KV_REST_API_TOKEN` | Added automatically when you connect Upstash Redis | Only the Vercel Functions |

None of these are in git or in the website's code. Locally, `web/.env.local` (gitignored) holds
test values, and the local server uses an in-memory store when the `KV_*` values are missing.
Deployed without a database or a token, the API answers with a clear 500 message instead of
silently forgetting state.

## Deploying on Vercel
1. **Import the repo**: Vercel → Add New → Project → import `ellaHart/CIM383WearableClip`.
   - **Root Directory: `web`** (Framework Preset: Other; build settings come from `web/vercel.json`).
   - Keep "Include files outside the root directory in the Build Step" **on** (the default): the
     build reads `device/moods.json` and `assets/sprites/`.
2. **Database**: in the project → Storage (or Marketplace) → **Upstash → Redis** → free plan,
   region close to the functions (US East / `iad1` by default) → connect to the project for
   Production *and* Preview. This adds `KV_REST_API_URL` and `KV_REST_API_TOKEN`.
3. **Tokens**: Settings → Environment Variables → add `CONTROL_TOKEN` and `DEVICE_TOKEN`
   (two different long random strings) for Production and Preview.
4. **Deploy**: pushes to `main` deploy to production (`https://<project>.vercel.app`). Every
   other branch, like `web-controller`, gets its own preview URL,
   `https://<project>-git-<branch>-<team>.vercel.app`, which stays the same across pushes.
5. **Preview protection**: Vercel protects preview URLs with a Vercel login by default. The clip
   can't log in, so to test a branch before merging, turn off *Vercel Authentication* under
   Settings → Deployment Protection. The API still requires the two tokens.
6. **Clip**: put the URL and `DEVICE_TOKEN` in `D:\settings.toml` as `MOODCLIP_API_URL` and
   `MOODCLIP_DEVICE_TOKEN`.

**Free-tier budget**: each clip check-in is one function call and two Redis commands; each website
refresh (every 3 s while the page is open) is one call and two commands. With the clip on ~4 h/day
that's ~90K calls and ~180K Redis commands a month, within Vercel Hobby and Upstash's free
500K commands/month. Leaving the clip on around the clock would use ~520K of each.

## Clip behaviour
- `cloud_sync.py` checks in every 5 s while Wi-Fi is up, and right away after a button press or an
  applied command. A request can pause the display for at most 5 s (usually ~0.2 s).
- Failures back off 10/20/40/60 s and are printed as `Cloud:` lines; the display loop never crashes.
- Without Wi-Fi or without `MOODCLIP_API_URL`, the clip works exactly as before (buttons, NVM memory).

## File structure
```
device/                 CircuitPython (copied to CIRCUITPY by tools/deploy.ps1)
  code.py               screens, buttons, apply_remote()
  moods.json            mood list shared with the website
  billboard.py          scrolling text + sprite view
  wifi_link.py          hotspot connection
  cloud_sync.py         HTTPS check-ins with the API
web/                    Vercel project root
  vercel.json           build command + output directory
  package.json          @upstash/redis; `npm run build`, `npm run dev`
  api/                  Vercel Functions: catalog, state, command, device/sync
  lib/core.js           API logic, auth, data model, Redis/in-memory store
  public/               index.html, app.css, app.js (sprites copied in by the build)
  scripts/sync-assets.mjs   build step: sprites + moods.generated.js
  scripts/local-server.mjs  local test server (no accounts)
  .env.example
docs/ARCHITECTURE.md
```
