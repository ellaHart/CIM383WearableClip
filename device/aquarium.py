# Aquarium screen: fish swim over an illustrated background; the bottom button feeds them.
#
# The background is a 16-bit RGB565 BMP (smooth gradients, no 256-colour banding) loaded once
# into RAM. Each fish is one indexed spritesheet shared by every fish of that species: the frame
# changes by setting the TileGrid's tile, and turning around just mirrors it with flip_x.
# Only the small areas around moving fish and food are redrawn each frame.
#
# Feeding (bottom button): a pellet drops in, the nearest free fish swims to it and eats it, and
# then a new fish of a random species appears nearby (up to MAX_FISH in total). The three original
# fish are permanent; every new fish lives for LIFESPAN seconds on its own timer.
#
# The population survives mode changes (the screen keeps its fish) and restarts: each new fish's
# expiry is saved as real-world Unix time in NVM (clock.py learns the time from the API's
# HTTPS "Date" header). After a restart, saved fish come back once the clock is known, minus any
# that expired while the clip was off. Fish born while the clock was unknown (no Wi-Fi since
# power-on) can't be dated, so they aren't saved and don't come back after a restart.
#
# Artwork (made with tools/convert_sprites.py from assets/aquarium/):
#   /aquarium/background.bmp  320x170 16-bit RGB565
#   /aquarium/clownfish.bmp   304x30  8 frames of 38x30, facing right
#   /aquarium/blue_tang.bmp   304x30  8 frames of 38x30, facing right
#   /aquarium/betta.bmp       432x42  8 frames of 54x42, facing right
# A missing file is skipped with a warning (plain water colour for the background).
import math
import random
import time

import bitmaptools
import displayio
import microcontroller
import vectorio

import clock
from billboard import HEIGHT, WIDTH, display, load_bmp, rect, solid

ART_DIR = "/aquarium/"
WATER_COLOR = 0x2E8FC0  # only used when background.bmp is missing

SWIM_TOP = 4       # fish never go above this
SWIM_BOTTOM = 112  # ...or below this (the sand and coral start around y=115-130)
EDGE_EASE = 24     # fish slow down within this many pixels of a wall before turning
MAX_STEP = 0.1     # seconds; after a pause (e.g. a cloud sync) fish carry on instead of jumping
# Redrawing is the expensive part (each moved sprite redraws its old and new area). With more
# fish than this, a fish only redraws when its swim frame changes (5-9x a second) instead of
# every loop frame; positions are still tracked continuously, so speeds don't change.
SMOOTH_FISH = 6

MAX_FISH = 20      # including the three permanent fish
LIFESPAN = 300     # seconds each fed-into-being fish lives
MAX_FOOD = 3       # pellets in the water at once; more presses are ignored until one is eaten
FOOD_COLOR = 0x7A4A1E
FOOD_RADIUS = 2
FOOD_START_Y = 6
FOOD_FALL = 18     # px/s
FOOD_REST_Y = SWIM_BOTTOM - 4  # pellets settle just above the sand
FOOD_TIMEOUT = 25  # seconds; an uneaten pellet dissolves, so nothing waits on it forever
CHASE_FACTOR = 2.2  # chasing fish swim this much faster than normal...
CHASE_MIN = 28      # ...and at least this fast (px/s)
EAT_DISTANCE = 5    # mouth within this many px of the pellet (horizontally) = eaten
SPAWN_SPREAD = 24   # new fish appear within this many px of where the food was eaten

# Saved population in microcontroller.nvm (bytes 0-5 are used by code.py and cloud_sync.py):
# magic byte, count, then per fish: species index (1 byte) + expiry Unix time (4 bytes).
NVM_START = 16
NVM_MAGIC = 0xA9
NVM_SIZE = 2 + (MAX_FISH - 3) * 5

# One entry per species; the first fish of each kind starts here and is permanent.
# speed: px/s; fps: animation frames per second; bob: vertical sway in px over bob_period
# seconds; wander: seconds between choosing a new depth (None = stay at one depth).
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


def _clamp(value, low, high):
    return min(max(value, low), high)


class Fish:
    def __init__(self, species, bitmap, palette, x=None, y=None, direction=None,
                 expires_ns=None, expires_unix=None, speed_scale=1.0):
        self.s = species
        self.w, self.h = species["frame"]
        self.grid = displayio.TileGrid(bitmap, pixel_shader=palette, width=1, height=1,
                                       tile_width=self.w, tile_height=self.h)
        self.x = float(species["x"] if x is None else x)
        self.dir = species["dir"] if direction is None else direction
        self.depth = float(species["y"] if y is None else y)  # top edge; drifts towards target
        self.target = self.depth
        self.speed = species["speed"] * speed_scale
        self.expires_ns = expires_ns      # None = permanent
        self.expires_unix = expires_unix  # set once real-world time is known (for saving)
        self.food = None                  # the pellet this fish is chasing
        self.next_wander = self._wander_delay()
        self.frame = random.randrange(species["frames"])
        self.frame_time = 0.0
        self.phase = random.random() * 2 * math.pi  # so the fish don't bob in sync
        self.grid[0] = self.frame
        self.grid.flip_x = self.dir < 0  # sprites face right
        self._place(0.0)

    @property
    def permanent(self):
        return self.expires_ns is None

    def mouth(self):
        """Where the fish's mouth is (sprites face right; flipped when swimming left)."""
        return self.x + (self.w - 4 if self.dir > 0 else 4), self.depth + self.h / 2

    def _wander_delay(self):
        wander = self.s["wander"]
        return random.uniform(*wander) if wander else None

    def _turn(self):
        self.dir = -self.dir
        self.grid.flip_x = self.dir < 0

    def _place(self, t):
        bob = self.s["bob"] * math.sin(2 * math.pi * t / self.s["bob_period"] + self.phase)
        if self.food:
            bob *= 0.3  # mostly steady while heading for food
        y = _clamp(self.depth + bob, SWIM_TOP, SWIM_BOTTOM - self.h)
        x, y = int(self.x), int(y)
        if self.grid.x != x:
            self.grid.x = x
        if self.grid.y != y:
            self.grid.y = y

    def _swim(self, dt):
        # Swim, easing off near the walls, then turn around (always fully on screen).
        right_limit = WIDTH - self.w
        room = (right_limit - self.x) if self.dir > 0 else self.x
        ease = 0.35 + 0.65 * min(1.0, room / EDGE_EASE)
        self.x += self.dir * self.speed * ease * dt
        if self.x <= 0 or self.x >= right_limit:
            self.x = _clamp(self.x, 0, right_limit)
            self._turn()

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

    def _chase(self, dt):
        """Swim straight at the pellet. Returns True once the mouth reaches it."""
        food = self.food
        # Face the pellet, judged from the middle of the body: the mouth jumps to the other end
        # when the sprite flips, so judging from the mouth made fish flip back and forth forever
        # whenever the pellet was under their body.
        offset = food.x - (self.x + self.w / 2)
        if offset * self.dir < 0 and abs(offset) > 2:
            self._turn()
        mouth_x, _ = self.mouth()
        if abs(food.x - mouth_x) <= EAT_DISTANCE and self.grid.y + 2 <= food.y <= self.grid.y + self.h - 2:
            return True
        target_x = _clamp(food.x - (mouth_x - self.x), 0, WIDTH - self.w)
        target_y = _clamp(food.y - self.h / 2, SWIM_TOP, SWIM_BOTTOM - self.h)
        dx, dy = target_x - self.x, target_y - self.depth
        distance = math.sqrt(dx * dx + dy * dy)
        step = max(CHASE_MIN, self.speed * CHASE_FACTOR) * dt
        if distance <= step:
            self.x, self.depth = target_x, target_y
        elif distance:
            self.x += dx / distance * step
            self.depth += dy / distance * step
        return False

    def update(self, dt, t, smooth=True):
        """Move and animate one frame. Returns True if the fish just ate its pellet.

        smooth=False: only redraw on this fish's own animation frames (see SMOOTH_FISH).
        """
        ate = self._chase(dt) if self.food else False
        if not self.food:
            self._swim(dt)

        # Swimming frames in sheet order.
        self.frame_time += dt
        frame_length = 1 / self.s["fps"]
        advanced = self.frame_time >= frame_length
        if advanced:
            self.frame_time %= frame_length
            self.frame = (self.frame + 1) % self.s["frames"]
            self.grid[0] = self.frame

        if smooth or advanced or self.food:
            self._place(t)
        return ate


class Food:
    def __init__(self, x, now_ns):
        self.base_x = x
        self.x = x
        self.y = float(FOOD_START_Y)
        self.born_ns = now_ns
        self.eater = None
        self.shape = vectorio.Circle(pixel_shader=solid(FOOD_COLOR), radius=FOOD_RADIUS,
                                     x=int(x), y=FOOD_START_Y)

    def update(self, dt, t):
        if self.y < FOOD_REST_Y:
            self.y = min(self.y + FOOD_FALL * dt, FOOD_REST_Y)
            self.x = self.base_x + 2 * math.sin(t * 3 + self.base_x)  # slight sway while sinking
        x, y = int(self.x), int(self.y)
        if self.shape.x != x:
            self.shape.x = x
        if self.shape.y != y:
            self.shape.y = y


class AquariumScreen:
    id = "aquarium"  # mode id shared with the website (web/lib/core.js MODES)
    name = "Aquarium"

    def __init__(self):
        self.root = None    # built on first show() and kept, so the population survives mode changes
        self.fish = []
        self.food = []
        self.pending = self._load_saved()  # saved fish waiting for the clock to be known
        self.saved = None

    @property
    def animating(self):
        # While food is in the water, code.py holds network calls back so feeding stays smooth.
        return bool(self.food)

    # --- Building the scene ---
    def _build(self):
        self.root = displayio.Group()
        background = _art("background.bmp", load_bmp565)
        if background:
            bitmap, shader = background
            self.root.append(displayio.TileGrid(bitmap, pixel_shader=shader))
        else:
            rect(self.root, WATER_COLOR, 0, 0, WIDTH, HEIGHT)
        self.fish_layer = displayio.Group()
        self.food_layer = displayio.Group()
        self.root.append(self.fish_layer)
        self.root.append(self.food_layer)
        for species in SPECIES:  # the three permanent fish
            art = _art(species["name"] + ".bmp")
            if art:
                self._add(Fish(species, *art))

    def _add(self, fish):
        self.fish.append(fish)
        self.fish_layer.append(fish.grid)

    def _remove(self, fish):
        if fish.food:
            fish.food.eater = None
        self.fish.remove(fish)
        self.fish_layer.remove(fish.grid)

    def _spawn(self, index, now_ns, near=None, expires_ns=None, expires_unix=None):
        """Add a temporary fish of SPECIES[index]; returns it, or None if full/missing art."""
        species = SPECIES[index]
        art = _art(species["name"] + ".bmp")
        if not art or len(self.fish) >= MAX_FISH:
            return None
        w, h = species["frame"]
        if near:
            x = near[0] - w / 2 + random.uniform(-SPAWN_SPREAD, SPAWN_SPREAD)
            y = near[1] - h / 2 + random.uniform(-12, 12)
        else:
            x = random.uniform(0, WIDTH - w)
            y = random.uniform(SWIM_TOP, SWIM_BOTTOM - h)
        if expires_ns is None:
            expires_ns = now_ns + LIFESPAN * 1_000_000_000
            unix = clock.now()
            expires_unix = unix + LIFESPAN if unix is not None else None
        fish = Fish(species, *art, x=_clamp(x, 0, WIDTH - w), y=_clamp(y, SWIM_TOP, SWIM_BOTTOM - h),
                    direction=random.choice((-1, 1)), expires_ns=expires_ns,
                    expires_unix=expires_unix, speed_scale=random.uniform(0.85, 1.15))
        self._add(fish)
        return fish

    def show(self):
        if self.root is None:
            self._build()
        display.root_group = self.root
        self.started = time.monotonic_ns()
        self.last = self.started
        self._maintain(self.started)

    # --- Feeding ---
    def on_button(self):
        """Bottom button: drop a food pellet (ignored if MAX_FOOD pellets are already in)."""
        if len(self.food) >= MAX_FOOD or not self.fish:
            return
        food = Food(random.uniform(20, WIDTH - 20), time.monotonic_ns())
        self.food.append(food)
        self.food_layer.append(food.shape)
        self._assign(food)

    def _assign(self, food):
        """Send the nearest fish that isn't already chasing food."""
        best, best_distance = None, None
        for fish in self.fish:
            if fish.food:
                continue
            mouth_x, mouth_y = fish.mouth()
            distance = (mouth_x - food.x) ** 2 + (mouth_y - food.y) ** 2
            if best is None or distance < best_distance:
                best, best_distance = fish, distance
        if best:
            best.food = food
            food.eater = best

    def _remove_food(self, food):
        if food.eater:
            food.eater.food = None
            food.eater.target = food.eater.depth  # carry on from here instead of drifting back
        self.food.remove(food)
        self.food_layer.remove(food.shape)

    def _eaten(self, food, fish, now_ns):
        spot = (food.x, food.y)
        self._remove_food(food)
        if len(self.fish) >= MAX_FISH:
            print("Aquarium: fed - tank is full ({} fish)".format(len(self.fish)))
            return
        baby = self._spawn(random.randrange(len(SPECIES)), now_ns, near=spot)
        if baby:
            print("Aquarium: fed - a {} appeared ({} fish)".format(baby.s["name"], len(self.fish)))
            self._save()

    # --- Lifespans and saving ---
    def _maintain(self, now_ns):
        """Expire old fish, date fish once the clock is known, and restore saved fish."""
        changed = False
        for fish in [f for f in self.fish if not f.permanent and f.expires_ns <= now_ns]:
            self._remove(fish)
            print("Aquarium: a {} swam off ({} fish)".format(fish.s["name"], len(self.fish)))
            changed = True

        unix = clock.now()
        if unix is not None:
            for fish in self.fish:
                if not fish.permanent and fish.expires_unix is None:
                    fish.expires_unix = unix + (fish.expires_ns - now_ns) // 1_000_000_000
                    changed = True
            if self.pending:
                restored = 0
                for index, expires_unix in self.pending:
                    remaining = expires_unix - unix
                    if remaining > 0 and self._spawn(index, now_ns, expires_ns=now_ns + remaining * 1_000_000_000,
                                                     expires_unix=expires_unix):
                        restored += 1
                print("Aquarium: restored {} of {} saved fish".format(restored, len(self.pending)))
                self.pending = []
                changed = True
        if changed:
            self._save()

    def _save(self):
        """Write temporary fish (and any not yet restored) to NVM, only if something changed."""
        records = [(SPECIES.index(f.s), f.expires_unix) for f in self.fish
                   if not f.permanent and f.expires_unix is not None]
        records = (records + self.pending)[:MAX_FISH - 3]
        data = bytes((NVM_MAGIC, len(records)))
        for index, expires_unix in records:
            data += bytes((index,)) + expires_unix.to_bytes(4, "little")
        data += bytes(NVM_SIZE - len(data))
        if data != self.saved:
            microcontroller.nvm[NVM_START:NVM_START + NVM_SIZE] = data
            self.saved = data

    def _load_saved(self):
        raw = bytes(microcontroller.nvm[NVM_START:NVM_START + NVM_SIZE])
        if raw[0] != NVM_MAGIC:
            return []
        records = []
        for i in range(min(raw[1], MAX_FISH - 3)):
            record = raw[2 + i * 5:7 + i * 5]
            if record[0] < len(SPECIES):
                records.append((record[0], int.from_bytes(record[1:5], "little")))
        if records:
            print("Aquarium: {} saved fish will come back once the clock is set".format(len(records)))
        return records

    def tick(self):
        # monotonic_ns: time.monotonic() loses precision after hours of uptime.
        now = time.monotonic_ns()
        dt = min((now - self.last) / 1_000_000_000, MAX_STEP)
        self.last = now
        t = (now - self.started) / 1_000_000_000
        self._maintain(now)

        for food in list(self.food):
            food.update(dt, t)
            if now - food.born_ns > FOOD_TIMEOUT * 1_000_000_000:
                self._remove_food(food)
            elif food.eater is None:
                self._assign(food)

        smooth = len(self.fish) <= SMOOTH_FISH
        for fish in list(self.fish):
            if fish.update(dt, t, smooth):
                self._eaten(fish.food, fish, now)
