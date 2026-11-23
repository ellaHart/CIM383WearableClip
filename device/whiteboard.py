# Whiteboard screen: shows the latest drawing sent from the website, full screen.
#
# Drawing format (must match web/public/app.js and web/lib/core.js): 320x170, 1 bit per pixel,
# 1 = black, 0 = white. Rows top to bottom, 40 bytes per row; in each byte the leftmost pixel is
# the most significant bit. 6800 bytes in total.
#
# cloud_sync.py downloads a drawing only when its revision number changes and passes it to
# set_drawing(). The drawing is kept in RAM (no flash writes): after a restart the clip simply
# downloads the latest one again on its first check-in.
#
# Bottom button: does nothing here.
import io

import bitmaptools
import displayio

from billboard import CHAR_H, CHAR_W, HEIGHT, WIDTH, display, rect, text_line

DRAWING_BYTES = (WIDTH // 8) * HEIGHT  # 6800
WHITE = 0xFFFFFF
BLACK = 0x000000
PLACEHOLDER = ("Draw something", "on your phone!")


class WhiteboardScreen:
    id = "whiteboard"  # mode id shared with the website (web/lib/core.js MODES)
    name = "Whiteboard"

    def __init__(self):
        self.rev = 0          # revision of the drawing we have (0 = none yet)
        self.bitmap = None    # 1 bit per pixel, created on the first drawing and reused after
        self.palette = displayio.Palette(2)
        self.palette[0] = WHITE
        self.palette[1] = BLACK

    def set_drawing(self, rev, data):
        """Replace the drawing. Returns False (keeping the old one) if the data is malformed."""
        if len(data) != DRAWING_BYTES:
            print("Whiteboard: ignored drawing {} ({} bytes, expected {})".format(rev, len(data), DRAWING_BYTES))
            return False
        if self.bitmap is None:
            self.bitmap = displayio.Bitmap(WIDTH, HEIGHT, 2)
        # Rows top to bottom; reverse_pixels_in_element=True = leftmost pixel in the high bit
        # (verified on the clip with an asymmetric test pattern).
        bitmaptools.readinto(self.bitmap, io.BytesIO(data), 1, reverse_pixels_in_element=True)
        self.rev = rev
        print("Whiteboard: new drawing", rev)
        return True

    def show(self):
        root = displayio.Group()
        if self.bitmap:
            root.append(displayio.TileGrid(self.bitmap, pixel_shader=self.palette))
        else:
            rect(root, WHITE, 0, 0, WIDTH, HEIGHT)
            top = (HEIGHT - len(PLACEHOLDER) * CHAR_H * 2) // 2
            for i, line in enumerate(PLACEHOLDER):
                x = (WIDTH - len(line) * CHAR_W * 2) // 2
                root.append(text_line(line, x, top + i * CHAR_H * 2, 2, BLACK))
        display.root_group = root

    def on_button(self):
        """Bottom button: nothing on the whiteboard."""

    def tick(self):
        pass  # nothing moves; the bitmap is updated in place when a new drawing arrives
