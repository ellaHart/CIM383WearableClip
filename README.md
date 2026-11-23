# CIM383WearableClip

A Tamagotchi-inspired pixel-art mood/status hair clip: LILYGO T-Display-S3 (320×170 LCD) running CircuitPython 10, controlled from a phone website over Wi-Fi.

## Layout

| Folder | What's in it |
|---|---|
| `device/` | Everything that goes on the board's CIRCUITPY drive |
| `tools/deploy.ps1` | Copies `device/` to the board |
| `backups/` | Original files from the board, kept before anything was replaced |
| `settings.example.toml` | Template for the board's `settings.toml` (Wi-Fi). The real one is never committed. |

## Working on the device code

Edit files in `device/`, then from this folder run:

```powershell
.\tools\deploy.ps1
```

Pass `-Drive E:` if CIRCUITPY shows up as a different letter. Don't edit files directly on the board, or they won't be in git.

**Sprites:** put 40×40 PNGs in `assets/sprites/`, then run `python tools/convert_sprites.py` (needs `pip install pillow`) to make the BMPs in `device/sprites/`, and deploy.

**Magic 8 Ball art:** `assets/magic8/idle.png` (front, with "Ask a question...") and `assets/magic8/answer.png` (back, empty triangle), both 320×170 PNG. The same command converts them to `device/magic8/*.bmp`. The 20 answers and the triangle position live in `device/magic8.py`.

**Aquarium art:** `assets/aquarium/background.jpg` (any size; scaled to fill 320×170, cropping evenly, and saved as a smooth 16-bit image) plus `clownfish.png`, `blue_tang.png` and `betta.png` spritesheets (8 frames in a row, facing right, transparent background). The same command converts them to `device/aquarium/`. Speeds, depths and frame sizes live in `SPECIES` in `device/aquarium.py`.

**Buttons:** BOOT (bottom) = next mood on Moods, shake on Magic 8 Ball, otherwise back to Moods; IO14 (top) = next screen (Moods → Spotify → Magic 8 Ball → Aquarium). On the Aquarium the bottom button drops food: the nearest fish eats it and a new random fish appears (up to 20). The three original fish are permanent; new ones live 5 minutes each and are remembered across restarts once the clip has had Wi-Fi (it learns the real time from the website's replies). The current mood and screen are remembered after a restart. Swap `MOOD_BUTTON`/`SCREEN_BUTTON` in `device/code.py` if they feel backwards.

**Adding a screen:** write a class with `name`, `show()` and `tick()` in `device/code.py` and add it to `SCREENS`. `device/billboard.py` draws the scrolling-text-plus-sprite layout any screen can reuse.

**Wi-Fi (phone hotspot):** open `D:\settings.toml` on the board and add the two lines from `settings.example.toml` with your real hotspot name and password. That file stays on the board only: it's in `.gitignore`, and `deploy.ps1` never touches it. The hotspot must be 2.4 GHz (iPhone: turn on *Maximize Compatibility*). `device/wifi_link.py` connects in the background of the display loop, runs one HTTPS test, and prints `Wi-Fi:` / `HTTPS:` lines to the serial console. Without Wi-Fi, the moods and buttons work as usual.

**Moods** are listed in `device/moods.json`, shared by the clip and the website. Keep each `id` stable; it's how the website refers to a mood.

## Website controller (`web/`)

A phone website that picks the clip's mood remotely, through Vercel Functions and an Upstash Redis database. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

**Run it locally** (needs Node.js; no accounts; uses an in-memory store):
```powershell
cd web
npm install
copy .env.example .env.local   # then put two long random values in it
npm run dev                    # http://127.0.0.1:3000
```

**Deploy:** import this GitHub repo in Vercel with **Root Directory = `web`**, add Upstash Redis from the Vercel Marketplace, and set `CONTROL_TOKEN` / `DEVICE_TOKEN` as environment variables. Every push then deploys automatically. Step-by-step: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#deploying-on-vercel).

Then add `MOODCLIP_API_URL` and `MOODCLIP_DEVICE_TOKEN` to `D:\settings.toml` (see `settings.example.toml`). The clip prints `Cloud:` lines on the serial console.

**Boot modes** (`device/boot.py`, applies after a hard reset):
- Normal: your PC can edit CIRCUITPY.
- Hold the **IO14** button while pressing reset: `code.py` can save files (status cache); CIRCUITPY is read-only on the PC.
