# Spotify Now Playing screen (display only: no playback controls).
#
# The clip never talks to Spotify. While this screen is showing, the API adds
#   "spotify": {"state": "playing"|"paused"|"idle"|"disconnected", "title": ..., "artist": ...}
# to the clip's normal check-in reply (web/lib/core.js), and code.py passes it to update().
# Text is plain ASCII (the server strips accents). The screen only redraws when the song or its
# state changes; a title or artist too wide for the screen scrolls, shorter ones stay still.
#
# Bottom button: does nothing here.
import displayio

from billboard import CHAR_H, CHAR_W, WIDTH, display, load_bmp, rect, text_line

BACKGROUND = 0x121212
GREEN = 0x1DB954
WHITE = 0xFFFFFF
GREY = 0xB3B3B3
MARGIN = 12
SCROLL_STEP = 4   # pixels per frame for long text (~12 fps when both lines scroll, so ~50 px/s)
SCROLL_GAP = 48   # blank pixels before scrolling text comes round again

# (label, colour, text scale, y) for the three lines
LABEL = (GREEN, 2, 10)
TITLE = (WHITE, 3, 56)
ARTIST = (GREY, 2, 110)

MESSAGES = {
    None: ("SPOTIFY", "Loading...", "Waiting for the website"),
    "disconnected": ("SPOTIFY", "Not connected", "Connect it on the website"),
    "idle": ("NOTHING PLAYING", "Play a song", "on Spotify"),
}


class SpotifyScreen:
    id = "spotify"  # mode id shared with the website (web/lib/core.js MODES)
    name = "Spotify"

    def __init__(self):
        self.now = None      # latest {"state", "title", "artist"} from the API
        self.scrollers = []  # (group, width) for lines that scroll
        self.icon = None

    def update(self, spotify, showing):
        """New data from a check-in. Redraws only if something changed and the screen is showing."""
        now = {"state": spotify.get("state"), "title": spotify.get("title") or "", "artist": spotify.get("artist") or ""}
        if now == self.now:
            return
        self.now = now
        if now["state"] in ("playing", "paused"):
            print("Spotify:", now["state"], "-", now["title"], "by", now["artist"])
        if showing:
            self.show()

    def _lines(self):
        state = self.now["state"] if self.now else None
        if state in ("playing", "paused"):
            label = "NOW PLAYING" if state == "playing" else "PAUSED"
            return label, self.now["title"], self.now["artist"]
        return MESSAGES.get(state, MESSAGES[None])

    def show(self):
        root = displayio.Group()
        rect(root, BACKGROUND, 0, 0, WIDTH, 170)
        if self.icon is None:
            try:
                self.icon = load_bmp("/sprites/music.bmp")  # the headphones sprite as the music icon
            except OSError:
                self.icon = False
        if self.icon:
            bitmap, palette = self.icon
            root.append(displayio.TileGrid(bitmap, pixel_shader=palette, x=WIDTH - 44, y=2))

        self.scrollers = []
        for text, (color, scale, y) in zip(self._lines(), (LABEL, TITLE, ARTIST)):
            if not text:
                continue
            width = len(text) * CHAR_W * scale
            group = text_line(text, MARGIN, y, scale, color)
            root.append(group)
            if width > WIDTH - 2 * MARGIN:  # too wide: scroll it
                self.scrollers.append((group, width))
        display.root_group = root

    def on_button(self):
        """Bottom button: nothing on the Spotify screen."""

    def tick(self):
        for group, width in self.scrollers:
            group.x -= SCROLL_STEP
            if group.x < -width:
                group.x = WIDTH + SCROLL_GAP - SCROLL_STEP
