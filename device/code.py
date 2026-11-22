# Mood Clip: switches between screens (moods, Spotify, later drawings/photos/games).
#
# Buttons:  MOOD button   = bottom button: next mood on the Moods screen, the screen's own
#                           action where it has one (Magic 8 Ball: shake), else back to Moods
#           SCREEN button = top button: next screen (Moods -> Spotify -> Magic 8 Ball -> Aquarium)
# The current mood and screen are saved in non-volatile memory, so they survive restarts.
# Wi-Fi (wifi_link.py) and remote control (cloud_sync.py) are optional:
# everything above keeps working without them.
import json
import os
import time

import board
import keypad
import microcontroller

from billboard import Billboard
from aquarium import AquariumScreen
from magic8 import Magic8Screen

try:
    from wifi_link import WifiLink
    from cloud_sync import CloudSync
except ImportError as error:  # e.g. a build without wifi; the clip still works offline
    print("Wi-Fi disabled:", error)
    WifiLink = CloudSync = None

# If the buttons feel backwards on the clip, swap these two pins.
MOOD_BUTTON = microcontroller.pin.GPIO0     # BOOT
SCREEN_BUTTON = microcontroller.pin.GPIO14  # IO14

FPS = 18  # measured max is ~19 fps for the billboard at TEXT_SCALE 5

# Moods live in moods.json (shared with the website). Mood number = position in that list.
# Edit text/colours there; "id" is how the website refers to a mood, so keep it stable.
with open("/moods.json") as moods_file:
    STATES = json.load(moods_file)
for mood in STATES:
    mood["bg"] = int(mood["bg"].lstrip("#"), 16)

# Bytes in microcontroller.nvm (unwritten bytes read as 255).
NVM_MOOD = 0
NVM_SCREEN = 1


def load_saved(slot, count):
    saved = microcontroller.nvm[slot]
    return saved if saved < count else 0


def save(slot, value):
    if microcontroller.nvm[slot] != value:
        microcontroller.nvm[slot] = value


# --- Screens ---
# A screen needs: id, name, show() to draw itself, tick() called every frame.
# Optional: on_button() for the bottom button, and an `animating` flag that pauses
# Wi-Fi/cloud work while it's True (so animations stay smooth).
# To add one (drawings, photos, a game...), write a class like these and add it to SCREENS.

class MoodScreen:
    id = "moods"  # mode id shared with the website (web/lib/core.js MODES)
    name = "Moods"

    def __init__(self):
        self.index = load_saved(NVM_MOOD, len(STATES))

    def show(self):
        self.view = Billboard(STATES[self.index])
        print("Mood", self.index + 1, "-", STATES[self.index]["text"])

    def set_mood(self, index):
        self.index = index
        save(NVM_MOOD, index)

    def next_mood(self):
        self.set_mood((self.index + 1) % len(STATES))
        self.show()

    def tick(self):
        self.view.tick()


class SpotifyScreen:
    id = "spotify"
    name = "Spotify"

    def show(self):
        # Placeholder until the Spotify integration exists.
        self.view = Billboard({"text": "Spotify not connected yet", "bg": 0x93BA9B, "sprite": "music"})

    def tick(self):
        self.view.tick()


mood_screen = MoodScreen()
magic8_screen = Magic8Screen()
SCREENS = (mood_screen, SpotifyScreen(), magic8_screen, AquariumScreen())  # new screens go at the end (NVM index)


def show_screen(index):
    save(NVM_SCREEN, index)
    print("Screen", index + 1, "-", SCREENS[index].name)
    SCREENS[index].show()


keys = keypad.Keys((MOOD_BUTTON, SCREEN_BUTTON), value_when_pressed=False, pull=True)
MOOD_KEY, SCREEN_KEY = 0, 1

board.DISPLAY.auto_refresh = False
current = load_saved(NVM_SCREEN, len(SCREENS))
show_screen(current)
board.DISPLAY.refresh()



# --- Remote control (website -> API -> clip) ---
def current_status():
    status = {"mode": SCREENS[current].id, "mood": STATES[mood_screen.index]["id"]}
    if magic8_screen.last_answer or SCREENS[current] is magic8_screen:
        status["magic8"] = {"state": magic8_screen.state, "answer": magic8_screen.last_answer,
                            "count": magic8_screen.count}
    return status


def apply_remote(command):
    """Show what the website asked for. Returns False for modes the clip doesn't have yet."""
    global current
    mode = command.get("mode")
    if mode != "moods":  # other modes have no settings yet: just switch to that screen
        for index, screen in enumerate(SCREENS):
            if screen.id == mode:
                current = index
                show_screen(current)
                return True
        return False
    for index, mood in enumerate(STATES):
        if mood["id"] == command.get("mood"):
            mood_screen.set_mood(index)
            current = SCREENS.index(mood_screen)
            show_screen(current)
            return True
    return False


cloud_configured = bool(os.getenv("MOODCLIP_API_URL"))
wifi_link = WifiLink(https_test=not cloud_configured) if WifiLink else None
cloud = CloudSync(wifi_link, current_status, apply_remote) if wifi_link and wifi_link.ssid else None

frame_time = 1 / FPS
while True:
    started = time.monotonic()

    event = keys.events.get()
    if event and event.pressed:
        if event.key_number == SCREEN_KEY:
            current = (current + 1) % len(SCREENS)
            show_screen(current)
        elif SCREENS[current] is mood_screen:
            mood_screen.next_mood()
        elif hasattr(SCREENS[current], "on_button"):  # e.g. Magic 8 Ball: shake
            SCREENS[current].on_button()
        else:  # mood button on another screen: go back to the moods, same mood as before
            current = SCREENS.index(mood_screen)
            show_screen(current)
        if cloud:
            cloud.sync_soon()  # tell the website about the button press (after any animation)

    # Network calls can pause the loop briefly, so skip them while a screen is animating;
    # they run again on the first frame after (e.g. reporting a new Magic 8 answer).
    if not getattr(SCREENS[current], "animating", False):
        if wifi_link:
            wifi_link.tick()  # returns at once, except during a (time-limited) connect attempt
        if cloud:
            cloud.tick()  # returns at once, except every few seconds for a short HTTPS check-in

    SCREENS[current].tick()
    board.DISPLAY.refresh()

    leftover = frame_time - (time.monotonic() - started)
    if leftover > 0:
        time.sleep(leftover)
