# Cloud sync: the clip checks in with the Mood Clip API (web/api on Vercel) over HTTPS.
#
# settings.toml on the board (never committed):
#   MOODCLIP_API_URL = "https://<your-project>.vercel.app"
#   MOODCLIP_DEVICE_TOKEN = "..."
# Every SYNC_INTERVAL seconds it POSTs what the clip is showing and gets back the latest
# command from the website. Each command has a version number; the clip applies a version
# once and remembers it in NVM, so a restart doesn't undo later button presses.
# One HTTPS connection is kept open between syncs, so most syncs pause the display briefly.
import json
import os
import ssl
import time

import microcontroller
import socketpool
import wifi

import clock

SYNC_INTERVAL = 5                # seconds between check-ins while things work
REQUEST_TIMEOUT = 5              # seconds; longest a single sync can pause the display
ERROR_DELAYS = (10, 20, 40, 60)  # seconds between attempts after failures
SLOW_SYNC = 1.5                  # print a note when a sync pauses the display longer than this
NVM_VERSION = slice(2, 6)        # bytes 0-1 are mood/screen (code.py)
ROOTS_FILE = "/certs/api_roots.pem"  # CAs for the API; CircuitPython's built-in list misses Vercel's


def _load_roots():
    try:
        with open(ROOTS_FILE) as roots:
            return roots.read()
    except OSError:
        print("Cloud: {} missing - using CircuitPython's built-in certificates".format(ROOTS_FILE))
        return None


class HttpsConnection:
    """Minimal HTTP/1.1 client over one kept-alive TLS socket, using only built-in modules."""

    def __init__(self, host, cadata=None):
        self.host = host
        self.cadata = cadata  # PEM root certificates to trust instead of the built-in list
        self.pool = None
        self.context = None
        self.sock = None
        self.buffer = b""
        self.last_date = None  # "Date" header of the latest response (server's real-world time)

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None
        self.buffer = b""

    def _connect(self):
        if self.pool is None:
            self.pool = socketpool.SocketPool(wifi.radio)
            self.context = ssl.create_default_context()
            if self.cadata:
                self.context.load_verify_locations(cadata=self.cadata)
        sock = self.context.wrap_socket(
            self.pool.socket(self.pool.AF_INET, self.pool.SOCK_STREAM), server_hostname=self.host
        )
        sock.settimeout(REQUEST_TIMEOUT)
        sock.connect((self.host, 443))
        self.sock = sock
        self.buffer = b""

    def _recv(self):
        chunk = bytearray(1024)
        count = self.sock.recv_into(chunk)
        if count == 0:
            raise OSError("connection closed by server")
        self.buffer += bytes(chunk[:count])

    def _read_until(self, marker):
        while marker not in self.buffer:
            self._recv()
        end = self.buffer.index(marker)
        data = self.buffer[:end]
        self.buffer = self.buffer[end + len(marker):]
        return data

    def _read_exact(self, size):
        while len(self.buffer) < size:
            self._recv()
        data = self.buffer[:size]
        self.buffer = self.buffer[size:]
        return data

    def _read_chunked(self):
        body = b""
        while True:
            size = int(self._read_until(b"\r\n").split(b";")[0], 16)
            if size == 0:
                self._read_until(b"\r\n")
                return body
            body += self._read_exact(size)
            self._read_until(b"\r\n")

    def _send(self, data):
        view = memoryview(data)
        while len(view):
            sent = self.sock.send(view)
            view = view[sent:]

    def request(self, method, path, body=b"", headers=None):
        """Returns (status, body bytes). Retries once if a kept-alive socket went stale."""
        lines = ["{} {} HTTP/1.1".format(method, path), "Host: " + self.host,
                 "User-Agent: MoodClip", "Connection: keep-alive",
                 "Content-Length: {}".format(len(body))]
        for name, value in (headers or {}).items():
            lines.append("{}: {}".format(name, value))
        request = ("\r\n".join(lines) + "\r\n\r\n").encode() + body

        for attempt in range(2):
            fresh = self.sock is None
            try:
                if fresh:
                    self._connect()
                self._send(request)
                head = self._read_until(b"\r\n\r\n").decode().split("\r\n")
                status = int(head[0].split(" ")[1])
                response_headers = {}
                for line in head[1:]:
                    name, _, value = line.partition(":")
                    response_headers[name.strip().lower()] = value.strip()

                if "content-length" in response_headers:
                    data = self._read_exact(int(response_headers["content-length"]))
                elif response_headers.get("transfer-encoding", "").lower() == "chunked":
                    data = self._read_chunked()
                else:
                    raise OSError("response without a length")
                self.last_date = response_headers.get("date")
                if response_headers.get("connection", "").lower() == "close":
                    self.close()
                return status, data
            except OSError:
                self.close()
                if fresh or attempt == 1:
                    raise


def _host_from_url(url):
    url = url.strip().rstrip("/")
    if not url.startswith("https://"):
        raise ValueError("MOODCLIP_API_URL must start with https://")
    return url[len("https://"):].split("/")[0]


class CloudSync:
    def __init__(self, wifi_link, get_status, apply_command, apply_drawing=None, on_reply=None):
        """get_status() -> {"mode": ..., "mood": ...}; apply_command(dict) -> True if applied;
        apply_drawing(rev, data) -> True if a downloaded whiteboard drawing was accepted;
        on_reply(dict) is called with every check-in reply (e.g. Spotify song info)."""
        self.wifi_link = wifi_link
        self.get_status = get_status
        self.apply_command = apply_command
        self.apply_drawing = apply_drawing
        self.on_reply = on_reply
        self.drawing_rev = 0  # whiteboard drawing we have (RAM only: re-downloaded after a restart)
        self.failures = 0
        self.next_sync = 0
        self.synced_once = False
        self.started = time.monotonic()

        url = os.getenv("MOODCLIP_API_URL")
        self.token = os.getenv("MOODCLIP_DEVICE_TOKEN")
        self.enabled = False
        if not url or not self.token:
            print("Cloud: MOODCLIP_API_URL / MOODCLIP_DEVICE_TOKEN not set - remote control off")
            return
        try:
            self.connection = HttpsConnection(_host_from_url(url), _load_roots())
        except ValueError as error:
            print("Cloud:", error)
            return
        self.enabled = True

        saved = int.from_bytes(microcontroller.nvm[NVM_VERSION], "little")
        self.applied_version = 0 if saved == 0xFFFFFFFF else saved
        print("Cloud: will sync with {} every {} s".format(self.connection.host, SYNC_INTERVAL))

    def sync_soon(self):
        """Report a local change (e.g. a button press) on the next frame."""
        self.next_sync = 0

    def tick(self):
        if not self.enabled or not self.wifi_link.connected:
            return
        if time.monotonic() < self.next_sync:
            return
        started = time.monotonic()
        self.next_sync = started + SYNC_INTERVAL  # _sync() may set 0 to report a change at once
        try:
            self._sync()
            self.failures = 0
        except Exception as error:  # never let the network crash the display loop
            delay = ERROR_DELAYS[min(self.failures, len(ERROR_DELAYS) - 1)]
            self.failures += 1
            self.next_sync = time.monotonic() + delay
            print("Cloud: sync failed ({}); next try in {} s".format(repr(error), delay))
            if "X509" in repr(error):
                print("       The clip doesn't trust the server's certificate. Check " + ROOTS_FILE)
        took = time.monotonic() - started
        if took > SLOW_SYNC:
            print("Cloud: sync paused the display for {:.1f} s".format(took))

    def _save_version(self, version):
        self.applied_version = version
        microcontroller.nvm[NVM_VERSION] = version.to_bytes(4, "little")

    def _sync(self):
        report = self.get_status()
        info = wifi.radio.ap_info
        report.update({
            "applied_version": self.applied_version,
            "rssi": info.rssi if info else None,
            "ip": str(wifi.radio.ipv4_address),
            "uptime": int(time.monotonic() - self.started),
            "firmware": "circuitpython-" + os.uname().release,
        })
        status, body = self.connection.request(
            "POST", "/api/device/sync", json.dumps(report).encode(),
            {"Authorization": "Bearer " + self.token, "Content-Type": "application/json"},
        )
        clock.set_from_http_date(self.connection.last_date)  # real-world time for the aquarium
        if status == 401:
            raise RuntimeError("server rejected MOODCLIP_DEVICE_TOKEN")
        if status != 200:
            raise RuntimeError("HTTP {}: {}".format(status, body[:80]))
        command = json.loads(body)

        if not self.synced_once:
            self.synced_once = True
            print("Cloud: connected; latest command v{}, clip has applied v{}".format(
                command["version"], self.applied_version))

        if self.on_reply:
            self.on_reply(command)

        # A new whiteboard drawing? Download it (once per revision) before applying the command,
        # so switching to the whiteboard shows the new drawing straight away.
        drawing = command.get("drawing", 0)
        if self.apply_drawing and drawing and drawing != self.drawing_rev:
            self._fetch_drawing(drawing)

        version = command["version"]
        if version < self.applied_version:  # the server's state was reset
            self._save_version(version)
        elif version > self.applied_version:
            applied = self.apply_command(command)
            self._save_version(version)
            print("Cloud: command v{} {}: {} {}".format(
                version, "applied" if applied else "ignored", command.get("mode"), command.get("mood")))
            self.next_sync = 0  # report the new screen straight away

    def _fetch_drawing(self, rev):
        status, data = self.connection.request(
            "GET", "/api/device/drawing", b"", {"Authorization": "Bearer " + self.token})
        if status != 200:
            print("Cloud: drawing {} not available (HTTP {})".format(rev, status))
            return
        if self.apply_drawing(rev, data):
            self.drawing_rev = rev
            self.next_sync = 0  # tell the website we have it
