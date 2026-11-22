# Magic 8 Ball screen: bottom button shakes the ball, then the answer appears in the triangle.
#
# States: "idle" (front of the ball) -> "shaking" (~1.2 s, ball wiggles left/right)
#         -> "answer" (back of the ball, answer in the blue triangle) -> next press shakes again.
# Everything runs a little each frame from tick(); nothing blocks, so the display keeps refreshing.
#
# Artwork (made with tools/convert_sprites.py from assets/magic8/*.png):
#   /magic8/idle.bmp    320x170  front of the ball with "Ask a question..."
#   /magic8/answer.bmp  320x170  back of the ball with an empty answer triangle
# If a file is missing, the screen shows plain text instead and prints a warning.
import os
import random
import time

import displayio

from billboard import CHAR_H, CHAR_W, HEIGHT, WIDTH, display, load_bmp, rect, text_line

# The 20 classic answers, exactly as worded (reported to the website as-is).
ANSWERS = (
    # Positive
    "It is certain",
    "It is decidedly so",
    "Without a doubt",
    "Yes – definitely",
    "You may rely on it",
    "As I see it, yes",
    "Most likely",
    "Outlook good",
    "Yes",
    "Signs point to yes",
    # Neutral
    "Reply hazy, try again",
    "Ask again later",
    "Better not tell you now",
    "Cannot predict now",
    "Concentrate and ask again",
    # Negative
    "Don't count on it",
    "My reply is no",
    "My sources say no",
    "Outlook not so good",
    "Very doubtful",
)

ART_DIR = "/magic8/"
IDLE_ART = "idle.bmp"
ANSWER_ART = "answer.bmp"

SHAKE_SECONDS = 1.2  # length of the shake animation
SHAKE_NS = int(SHAKE_SECONDS * 1_000_000_000)
SHAKE_PIXELS = 10    # how far the ball swings at the start (it settles towards 0)
SHAKE_MIN_PIXELS = 2  # smallest swing, so the shake stays visible to the end

ANSWER_COLOR = 0xFFFFFF
FALLBACK_BG = 0x241C33  # only used when the artwork is missing

# The answer triangle in answer.bmp (measured from the artwork): flat top edge at TRI_TOP_Y
# spanning TRI_CENTER_X +/- TRI_TOP_HALF, pointing down to TRI_APEX_Y. Update if the art changes.
TRI_CENTER_X = 160
TRI_TOP_Y = 22
TRI_TOP_HALF = 96
TRI_APEX_Y = 153
TEXT_SCALE = 2           # every answer uses the same size; long ones wrap onto more lines
TEXT_TOP = TRI_TOP_Y + 2  # first text line starts this far down
TEXT_MARGIN = 2           # keep text this far inside the triangle's slanted edges
TEXT_INK_ROWS = 10        # rows of each 12-row font cell that hold letters (the rest is gap)

_art_cache = {}
random.seed(int.from_bytes(os.urandom(4), "little"))  # hardware randomness, fresh each boot


def _art(name):
    """Bitmap + palette for an artwork file, loaded once and kept in RAM; None if missing."""
    if name not in _art_cache:
        try:
            _art_cache[name] = load_bmp(ART_DIR + name)
        except OSError:
            print("Magic 8: missing artwork {} - showing text only".format(ART_DIR + name))
            _art_cache[name] = None
    return _art_cache[name]


def _display_text(answer):
    return answer.replace("–", "-")  # the built-in font has no en dash


def layout(answer):
    """Wrap the answer, at TEXT_SCALE, into lines that fit inside the triangle."""
    words = _display_text(answer).split()
    lines = []
    y = TEXT_TOP
    while words:
        # The triangle narrows downwards, so the bottom of each line's letters is the tightest spot.
        bottom = y + TEXT_INK_ROWS * TEXT_SCALE
        half = TRI_TOP_HALF * (TRI_APEX_Y - bottom) / (TRI_APEX_Y - TRI_TOP_Y) - TEXT_MARGIN
        limit = int(2 * half // (CHAR_W * TEXT_SCALE))
        line = words.pop(0)  # a word that's too long still gets its own line rather than shrinking
        while words and len(line) + 1 + len(words[0]) <= limit:
            line += " " + words.pop(0)
        lines.append(line)
        y += CHAR_H * TEXT_SCALE
    return lines


class Magic8Screen:
    id = "magic8"  # mode id shared with the website (web/lib/core.js MODES)
    name = "Magic 8 Ball"

    def __init__(self):
        self.state = "idle"
        self.shaker = None       # the group that wiggles during the shake
        self.next_answer = None
        self.last_answer = None  # most recent revealed answer (reported to the website)
        self.count = 0           # answers revealed since the clip started

    @property
    def animating(self):
        return self.state == "shaking"

    def show(self):
        self._show_idle()

    def on_button(self):
        """Bottom button: shake and reveal a new answer. Ignored while already shaking."""
        if self.state == "shaking":
            return
        if self.state == "answer":
            self._show_idle()  # shake the front of the ball again
        self.next_answer = ANSWERS[random.randrange(len(ANSWERS))]
        self.state = "shaking"
        # monotonic_ns: time.monotonic() loses precision after hours of uptime, which would
        # make the shake jump in big steps instead of moving smoothly.
        self.shake_started = time.monotonic_ns()
        self.shake_side = 1

    def tick(self):
        if self.state != "shaking":
            return
        elapsed = time.monotonic_ns() - self.shake_started
        if elapsed >= SHAKE_NS:
            self._show_answer(self.next_answer)
            return
        # Swap sides every frame (a smooth sine would alias at the ~10 fps a full-screen move
        # redraws at) and shrink the swing as the shake settles.
        settle = 1 - elapsed / SHAKE_NS
        self.shake_side = -self.shake_side
        self.shaker.x = self.shake_side * max(SHAKE_MIN_PIXELS, round(SHAKE_PIXELS * settle))

    def _show_idle(self):
        self.state = "idle"
        root = displayio.Group()
        art = _art(IDLE_ART)
        self.shaker = displayio.Group()
        if art:
            bitmap, palette = art
            rect(root, palette[bitmap[0, 0]], 0, 0, WIDTH, HEIGHT)  # fills the edges while shaking
            self.shaker.append(displayio.TileGrid(bitmap, pixel_shader=palette))
        else:
            rect(root, FALLBACK_BG, 0, 0, WIDTH, HEIGHT)
            message = "Ask a question..."
            self.shaker.append(text_line(message, (WIDTH - len(message) * CHAR_W * 2) // 2,
                                         (HEIGHT - CHAR_H * 2) // 2, 2, ANSWER_COLOR))
        root.append(self.shaker)
        display.root_group = root

    def _show_answer(self, answer):
        self.state = "answer"
        self.last_answer = answer
        self.count += 1
        print("Magic 8:", answer)

        root = displayio.Group()
        art = _art(ANSWER_ART)
        if art:
            bitmap, palette = art
            root.append(displayio.TileGrid(bitmap, pixel_shader=palette))
        else:
            rect(root, FALLBACK_BG, 0, 0, WIDTH, HEIGHT)
        for i, line in enumerate(layout(answer)):
            x = TRI_CENTER_X - len(line) * CHAR_W * TEXT_SCALE // 2
            y = TEXT_TOP + i * CHAR_H * TEXT_SCALE
            root.append(text_line(line, x, y, TEXT_SCALE, ANSWER_COLOR))
        display.root_group = root
