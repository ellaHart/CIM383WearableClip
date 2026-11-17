# Mood Clip: switches between screens (moods, Spotify, later drawings/photos/games).
#
# Buttons:  MOOD button   = next mood (or jump back to the mood screen)
#           SCREEN button = next screen
# The current mood and screen are saved in non-volatile memory, so they survive restarts.
import time

import board
import keypad
import microcontroller

from billboard import Billboard

# If the buttons feel backwards on the clip, swap these two pins.
MOOD_BUTTON = microcontroller.pin.GPIO0     # BOOT
SCREEN_BUTTON = microcontroller.pin.GPIO14  # IO14

FPS = 18  # measured max is ~19 fps for the billboard at TEXT_SCALE 5

# Mood number = position in this list (1-9). Colours come from the Figma design.
STATES = (
    {"text": "Hope you have a great day!", "bg": 0xFFBB67, "sprite": "cheer"},          # 1
    {"text": "Hi! Nice to meet you!", "bg": 0xFFFFFF, "sprite": "friendly", "border": True},  # 2
    {"text": "Not Friendly!!! DO NOT APPROACH", "bg": 0xA24A4A, "sprite": "alert"},     # 3
    {"text": "How you doinnnnnnn <3", "bg": 0xFFA7BA, "sprite": "love"},                # 4
    {"text": "Nap Time Nap Time Nap Time", "bg": 0xBC99D4, "sprite": "sleepy"},         # 5
    {"text": "Locked in! Do not disturb", "bg": 0xB8B8B8, "sprite": "laptop"},          # 6
    {"text": "I'm judging you rn", "bg": 0xD9D9D9, "sprite": "judging"},      # 7
    {"text": "Snack Time! Snack Time! Snack Time!", "bg": 0xF7E9AE, "sprite": "eating"},  # 8
)

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
# A screen needs: name, show() to draw itself, tick() called every frame.
# To add one (drawings, photos, a game...), write a class like these and add it to SCREENS.

class MoodScreen:
    name = "Moods"

    def __init__(self):
        self.index = load_saved(NVM_MOOD, len(STATES))

    def show(self):
        self.view = Billboard(STATES[self.index])
        print("Mood", self.index + 1, "-", STATES[self.index]["text"])

    def next_mood(self):
        self.index = (self.index + 1) % len(STATES)
        save(NVM_MOOD, self.index)
        self.show()

    def tick(self):
        self.view.tick()


class SpotifyScreen:
    name = "Spotify"

    def show(self):
        # Placeholder until the Spotify integration exists.
        self.view = Billboard({"text": "Spotify not connected yet", "bg": 0x93BA9B, "sprite": "music"})

    def tick(self):
        self.view.tick()


mood_screen = MoodScreen()
SCREENS = (mood_screen, SpotifyScreen())


def show_screen(index):
    save(NVM_SCREEN, index)
    print("Screen", index + 1, "-", SCREENS[index].name)
    SCREENS[index].show()


keys = keypad.Keys((MOOD_BUTTON, SCREEN_BUTTON), value_when_pressed=False, pull=True)
MOOD_KEY, SCREEN_KEY = 0, 1

board.DISPLAY.auto_refresh = False
current = load_saved(NVM_SCREEN, len(SCREENS))
show_screen(current)

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
        else:  # mood button on another screen: go back to the moods, same mood as before
            current = SCREENS.index(mood_screen)
            show_screen(current)

    SCREENS[current].tick()
    board.DISPLAY.refresh()

    leftover = frame_time - (time.monotonic() - started)
    if leftover > 0:
        time.sleep(leftover)
