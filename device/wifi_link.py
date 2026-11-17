# Wi-Fi for the Mood Clip: joins the phone hotspot without stalling the display.
#
# Credentials come from settings.toml on the board (never committed):
#   MOODCLIP_WIFI_SSID = "..."
#   MOODCLIP_WIFI_PASSWORD = "..."
# Call tick() once per frame. A connect attempt pauses the display for at most
# CONNECT_TIMEOUT seconds, then retries later with growing delays. Button presses
# during a pause are queued by keypad, not lost.
import os
import ssl
import time

import socketpool
import wifi

CONNECT_TIMEOUT = 10              # seconds per attempt (longest the display can pause)
FIRST_ATTEMPT_DELAY = 3           # let the mood screen appear before the first try
RETRY_DELAYS = (15, 30, 60, 120)  # seconds between failed attempts, then stays at the last
HTTPS_TIMEOUT = 10
TEST_HOST = "example.com"


def _hint(message):
    message = message.lower()
    if "ssid" in message or "no network" in message:
        return "Hotspot not found. Is it on, and set to 2.4 GHz? (iPhone: turn on Maximize Compatibility.)"
    if "auth" in message or "password" in message or "handshake" in message:
        return "Wrong password? Check MOODCLIP_WIFI_PASSWORD in settings.toml."
    if "timed out" in message or "timeout" in message:
        return "Timed out. Keep the phone's hotspot settings screen open and the clip close by."
    return "Unexpected error; will retry."


class WifiLink:
    def __init__(self):
        self.ssid = os.getenv("MOODCLIP_WIFI_SSID")
        self.password = os.getenv("MOODCLIP_WIFI_PASSWORD") or ""
        self.failures = 0
        self.next_attempt = time.monotonic() + FIRST_ATTEMPT_DELAY
        self.was_connected = False
        self.https_tested = False
        self.scanned = False
        self.pool = None
        if self.ssid:
            print("Wi-Fi: will connect to '{}' in {} s".format(self.ssid, FIRST_ATTEMPT_DELAY))
            if not self.password:
                print("Wi-Fi: MOODCLIP_WIFI_PASSWORD not set (or still commented out with #) - trying with no password")
        else:
            print("Wi-Fi: MOODCLIP_WIFI_SSID not set in settings.toml - running offline")

    @property
    def connected(self):
        return wifi.radio.connected

    def tick(self):
        if not self.ssid:
            return
        try:
            self._tick()
        except Exception as error:  # never let networking crash the display loop
            print("Wi-Fi: unexpected error:", repr(error))
            self._schedule_retry()

    def _tick(self):
        if wifi.radio.connected:
            if not self.was_connected:
                self.was_connected = True
                self.failures = 0
                self._report_connected()
            elif not self.https_tested:  # a frame after connecting, so pauses don't stack
                self.https_tested = True
                self.https_get_test()
            return

        if self.was_connected:
            self.was_connected = False
            self.https_tested = False
            print("Wi-Fi: connection lost")
            self._schedule_retry()
        elif time.monotonic() >= self.next_attempt:
            self._attempt()

    def _attempt(self):
        print("Wi-Fi: connecting to '{}' (up to {} s)...".format(self.ssid, CONNECT_TIMEOUT))
        started = time.monotonic()
        try:
            wifi.radio.enabled = True
            if self.password:
                wifi.radio.connect(self.ssid, self.password, timeout=CONNECT_TIMEOUT)
            else:
                wifi.radio.connect(self.ssid, timeout=CONNECT_TIMEOUT)
        except Exception as error:  # usually ConnectionError
            print("Wi-Fi: failed after {:.1f} s: {}".format(time.monotonic() - started, error))
            print("       " + _hint(str(error)))
            if not self.scanned:
                self.scanned = True
                self._scan()
            self._schedule_retry()

    def _schedule_retry(self):
        delay = RETRY_DELAYS[min(self.failures, len(RETRY_DELAYS) - 1)]
        self.failures += 1
        self.next_attempt = time.monotonic() + delay
        print("Wi-Fi: next try in {} s".format(delay))

    def _scan(self):
        """List the networks the clip can see (it only sees 2.4 GHz ones)."""
        names = set()
        for network in wifi.radio.start_scanning_networks():
            names.add("{} ({} dBm)".format(network.ssid or "<hidden>", network.rssi))
        wifi.radio.stop_scanning_networks()
        print("Wi-Fi: networks the clip can see:", ", ".join(sorted(names)) or "none")

    def _report_connected(self):
        info = wifi.radio.ap_info
        signal = "{} dBm".format(info.rssi) if info else "?"
        print("Wi-Fi: connected to '{}'  IP {}  signal {}".format(self.ssid, wifi.radio.ipv4_address, signal))

    def https_get_test(self, host=TEST_HOST, path="/"):
        """Minimal HTTPS GET using only built-in modules. Returns True on success."""
        print("HTTPS: GET https://{}{} ...".format(host, path))
        started = time.monotonic()
        if self.pool is None:
            self.pool = socketpool.SocketPool(wifi.radio)
        sock = None
        try:
            context = ssl.create_default_context()
            sock = context.wrap_socket(
                self.pool.socket(self.pool.AF_INET, self.pool.SOCK_STREAM), server_hostname=host
            )
            sock.settimeout(HTTPS_TIMEOUT)
            sock.connect((host, 443))
            request = "GET {} HTTP/1.1\r\nHost: {}\r\nUser-Agent: MoodClip\r\nConnection: close\r\n\r\n"
            sock.send(request.format(path, host).encode())
            buffer = bytearray(256)
            count = sock.recv_into(buffer)
            status = bytes(buffer[:count]).split(b"\r\n", 1)[0].decode()
            print("HTTPS: ok in {:.1f} s -> {}".format(time.monotonic() - started, status))
            return True
        except Exception as error:
            print("HTTPS: failed after {:.1f} s: {}".format(time.monotonic() - started, repr(error)))
            print("       Wi-Fi is up but the internet isn't reachable. Does the phone have mobile data?")
            return False
        finally:
            if sock:
                sock.close()
