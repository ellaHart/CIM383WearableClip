# boot.py runs once after a hard reset (RST button or plugging in), before code.py.
#
# Normal boot:          your PC can edit files on CIRCUITPY; code.py cannot write.
# Hold IO14 at reset:   code.py can write (to cache status/images); the PC sees
#                       CIRCUITPY as read-only. Reset without holding to go back.
import digitalio
import microcontroller
import storage

button = digitalio.DigitalInOut(microcontroller.pin.GPIO14)
button.switch_to_input(pull=digitalio.Pull.UP)

if not button.value:  # pressed = pulled low
    storage.remount("/", readonly=False)
    print("boot.py: code.py can write to flash (USB read-only)")
else:
    print("boot.py: USB can write (code.py read-only)")

button.deinit()
