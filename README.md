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

**Buttons:** IO14 = next mood, BOOT = previous mood. The current mood is remembered after a restart.

**Boot modes** (`device/boot.py`, applies after a hard reset):
- Normal: your PC can edit CIRCUITPY.
- Hold the **IO14** button while pressing reset: `code.py` can save files (status cache); CIRCUITPY is read-only on the PC.
