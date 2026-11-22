# Aquarium screen (Phase 1): three fish swim over an illustrated background.
#
# The background is a 16-bit RGB565 BMP (smooth gradients, no 256-colour banding) loaded once
# into RAM. Each fish is one indexed spritesheet: the frame changes by setting the TileGrid's
# tile, and turning around just mirrors it with flip_x, so no extra images are needed.
# Only the small areas around moving fish are redrawn each frame.
#
# Artwork (made with tools/convert_sprites.py from assets/aquarium/):
#   /aquarium/background.bmp  320x170 16-bit RGB565
#   /aquarium/clownfish.bmp   304x30  8 frames of 38x30, facing right
#   /aquarium/blue_tang.bmp   304x30  8 frames of 38x30, facing right
#   /aquarium/betta.bmp       432x42  8 frames of 54x42, facing right
# A missing file is skipped with a warning (plain water colour for the background).
#
# Bottom button: reserved for feeding (Phase 2), does nothing yet.
import math
import random
import time

import bitmaptools
import displayio

from billboard import HEIGHT, WIDTH, display, load_bmp, rect

ART_DIR = "/aquarium/"
WATER_COLOR = 0x2E8FC0  # only used when background.bmp is missing

SWIM_TOP = 4       # fish never go above this
SWIM_BOTTOM = 112  # ...or below this (the sand and coral start around y=115-130)
EDGE_EASE = 24     # fish slow down within this many pixels of a wall before turning
MAX_STEP = 0.1     # seconds; after a pause (e.g. a cloud sync) fish carry on instead of jumping

# One entry per fish. speed: px/s; fps: animation frames per second; bob: vertical sway in px
# over bob_period seconds; wander: seconds between choosing a new depth (None = stay at one depth).
SPECIES = (
    {"name": "clownfish", "frame": (38, 30), "frames": 8, "speed": 30, "fps": 9,
     "y": 26, "bob": 3, "bob_period": 1.6, "wander": (3, 6), "x": 40, "dir": 1},
    {"name": "blue_tang", "frame": (38, 30), "frames": 8, "speed": 20, "fps": 7,
     "y": 70, "bob": 2, "bob_period": 2.8, "wander": None, "x": 230, "dir": -1},
    {"name": "betta", "frame": (54, 42), "frames": 8, "speed": 12, "fps": 5,
     "y": 44, "bob": 4, "bob_period": 4.0, "wander": (6, 10), "x": 140, "dir": 1},
)

_art_cache = {}


def load_bmp565(path):
    """Load a 16-bit RGB565 BMP (from tools/convert_sprites.py) into a 16-bit Bitmap."""
    with open(path, "rb") as f:
        header = f.read(54)
        data_offset = int.from_bytes(header[10:14], "little")
        width = int.from_bytes(header[18:22], "little")
        height = int.from_bytes(header[22:26], "little")
        bitmap = displayio.Bitmap(width, height, 65536)
        f.seek(data_offset)
        bitmaptools.readinto(bitmap, f, 16, element_size=2, reverse_rows=True)
    shader = displayio.ColorConverter(input_colorspace=displayio.Colorspace.RGB565)
    return bitmap, shader


def _art(name, loader=load_bmp):
    """Load an artwork file once and keep it in RAM; None if missing."""
    if name not in _art_cache:
        try:
            _art_cache[name] = loader(ART_DIR + name)
        except OSError:
            print("Aquarium: missing artwork {} - skipping it".format(ART_DIR + name))
            _art_cache[name] = None
    return _art_cache[name]


class Fish:
    def __init__(self, species, bitmap, palette):
        self.s = species
        self.w, self.h = species["frame"]
        self.grid = displayio.TileGrid(bitmap, pixel_shader=palette, width=1, height=1,
                                       tile_width=self.w, tile_height=self.h)
        self.x = float(species["x"])
        self.dir = species["dir"]
        self.depth = float(species["y"])     # current centre depth (drifts towards target)
        self.target = self.depth
        self.next_wander = self._wander_delay()
        self.frame = random.randrange(species["frames"])
        self.frame_time = 0.0
        self.phase = random.random() * 2 * math.pi  # so the fish don't bob in sync
        self.grid[0] = self.frame
        self.grid.flip_x = self.dir < 0  # sprites face right
        self._place(0.0)

    def _wander_delay(self):
        wander = self.s["wander"]
        return random.uniform(*wander) if wander else None

    def _place(self, t):
        bob = self.s["bob"] * math.sin(2 * math.pi * t / self.s["bob_period"] + self.phase)
        y = self.depth + bob
        y = min(max(y, SWIM_TOP), SWIM_BOTTOM - self.h)
        x, y = int(self.x), int(y)
        if self.grid.x != x:
            self.grid.x = x
        if self.grid.y != y:
            self.grid.y = y

    def update(self, dt, t):
        # Swim, easing off near the walls, then turn around (always fully on screen).
        right_limit = WIDTH - self.w
        room = (right_limit - self.x) if self.dir > 0 else self.x
        ease = 0.35 + 0.65 * min(1.0, room / EDGE_EASE)
        self.x += self.dir * self.s["speed"] * ease * dt
        if self.x <= 0 or self.x >= right_limit:
            self.x = min(max(self.x, 0), right_limit)
            self.dir = -self.dir
            self.grid.flip_x = self.dir < 0

        # Occasionally pick a new depth and drift there slowly.
        if self.next_wander is not None:
            self.next_wander -= dt
            if self.next_wander <= 0:
                low = SWIM_TOP + self.s["bob"]
                high = SWIM_BOTTOM - self.h - self.s["bob"]
                self.target = random.uniform(low, high)
                self.next_wander = self._wander_delay()
        step = 8 * dt  # px/s
        if abs(self.target - self.depth) <= step:
            self.depth = self.target
        else:
            self.depth += step if self.target > self.depth else -step

        # Swimming frames in sheet order.
        self.frame_time += dt
        frame_length = 1 / self.s["fps"]
        if self.frame_time >= frame_length:
            self.frame_time %= frame_length
            self.frame = (self.frame + 1) % self.s["frames"]
            self.grid[0] = self.frame

        self._place(t)


class AquariumScreen:
    id = "aquarium"  # mode id shared with the website (web/lib/core.js MODES)
    name = "Aquarium"

    def __init__(self):
        self.fish = []

    def show(self):
        root = displayio.Group()
        background = _art("background.bmp", load_bmp565)
        if background:
            bitmap, shader = background
            root.append(displayio.TileGrid(bitmap, pixel_shader=shader))
        else:
            rect(root, WATER_COLOR, 0, 0, WIDTH, HEIGHT)

        self.fish = []
        for species in SPECIES:
            art = _art(species["name"] + ".bmp")
            if art:
                fish = Fish(species, *art)
                self.fish.append(fish)
                root.append(fish.grid)
        display.root_group = root
        self.started = time.monotonic_ns()
        self.last = self.started

    def on_button(self):
        """Bottom button: reserved for feeding in Phase 2. Does nothing yet."""

    def tick(self):
        # monotonic_ns: time.monotonic() loses precision after hours of uptime.
        now = time.monotonic_ns()
        dt = min((now - self.last) / 1_000_000_000, MAX_STEP)
        self.last = now
        t = (now - self.started) / 1_000_000_000
        for fish in self.fish:
            fish.update(dt, t)
