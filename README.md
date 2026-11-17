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

**Buttons:** BOOT = next mood (or back to the mood screen), IO14 = next screen (Moods → Spotify → …). The current mood and screen are remembered after a restart. Swap `MOOD_BUTTON`/`SCREEN_BUTTON` in `device/code.py` if they feel backwards.

**Adding a screen:** write a class with `name`, `show()` and `tick()` in `device/code.py` and add it to `SCREENS`. `device/billboard.py` draws the scrolling-text-plus-sprite layout any screen can reuse.

**Wi-Fi (phone hotspot):** open `D:\settings.toml` on the board and add the two lines from `settings.example.toml` with your real hotspot name and password. That file stays on the board only: it's in `.gitignore`, and `deploy.ps1` never touches it. The hotspot must be 2.4 GHz (iPhone: turn on *Maximize Compatibility*). `device/wifi_link.py` connects in the background of the display loop, runs one HTTPS test, and prints `Wi-Fi:` / `HTTPS:` lines to the serial console. Without Wi-Fi, the moods and buttons work as usual.

**Boot modes** (`device/boot.py`, applies after a hard reset):
- Normal: your PC can edit CIRCUITPY.
- Hold the **IO14** button while pressing reset: `code.py` can save files (status cache); CIRCUITPY is read-only on the PC.
