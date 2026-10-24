"""Best-effort local media interruption while ezan plays; never auto-resume."""
import json
import os
from pathlib import Path
import re
import socket
import stat
import struct
import tempfile
import threading
import time


def living_room_sockets():
    base = Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}'))
    bases = [base, Path(tempfile.gettempdir()) / f'living-room-{os.getuid()}']
    for base in dict.fromkeys(bases):
        if not private_owned(base, directory=True):
            continue
        for directory in list(base.glob('living-room-*'))[:32]:
            if not re.fullmatch(r'living-room-[a-f0-9]{12}', directory.name):
                continue
            if not private_owned(directory, directory=True):
                continue
            path = directory / 'control.sock'
            if private_owned(path):
                yield path


def private_owned(path, directory=False):
    try:
        info = path.lstat()
        kind = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISSOCK(info.st_mode)
        return kind and info.st_uid == os.getuid() and not info.st_mode & 0o077
    except OSError:
        return False


def pause_living_room(path, timeout=1.5):
    if not private_owned(path.parent, directory=True) or not private_owned(path):
        return False
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(timeout)
        connection.connect(str(path))
        _, uid, _ = struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))
        if uid != os.getuid():
            return False
        connection.sendall(b'{"action":"pause_media"}\n')
        message = b''
        while len(message) < 4096:
            part = connection.recv(4096 - len(message))
            if not part:
                break
            message += part
            try:
                result = json.loads(message)
                return isinstance(result, dict) and result.get('ok') is True
            except ValueError:
                continue
    return False


def pause_mpris(deadline):
    # Session bus only; never activate a player that was not already running.
    from gi.repository import Gio, GLib
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    flags = Gio.DBusCallFlags.NO_AUTO_START
    def call(name, path, interface, method, params=None):
        return bus.call_sync(name, path, interface, method, params, None, flags, 150, None)
    names = call('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus', 'ListNames').unpack()[0]
    paused = 0
    for name in sorted(names):
        if time.monotonic() >= deadline:
            break
        if not name.startswith('org.mpris.MediaPlayer2.') or name.lower().startswith('org.mpris.MediaPlayer2.vakit'.lower()):
            continue
        try:
            properties = call(name, '/org/mpris/MediaPlayer2', 'org.freedesktop.DBus.Properties', 'GetAll',
                              GLib.Variant('(s)', ('org.mpris.MediaPlayer2.Player',))).unpack()[0]
            if properties.get('PlaybackStatus') != 'Playing':
                continue
            method = 'Pause' if properties.get('CanPause') else 'Stop' if properties.get('CanControl') else None
            if method:
                call(name, '/org/mpris/MediaPlayer2', 'org.mpris.MediaPlayer2.Player', method)
                paused += 1
        except GLib.Error:
            continue
    return paused


class MediaInterrupter:
    def __init__(self):
        self._stop = None

    @property
    def active(self):
        return self._stop is not None

    def stop(self):
        if self._stop:
            self._stop.set()
            self._stop = None

    def pause_once(self, stop):
        warnings = []
        deadline = time.monotonic() + 2
        for path in living_room_sockets():
            if stop.is_set() or time.monotonic() >= deadline:
                return warnings
            try:
                if not pause_living_room(path, timeout=min(1.5, max(.1, deadline - time.monotonic()))):
                    warnings.append('Living Room could not pause; update or restart it.')
            except (OSError, ValueError):
                warnings.append('Living Room media control is unavailable.')
        if not stop.is_set():
            try:
                pause_mpris(time.monotonic() + 1)
            except Exception:
                # A desktop without session media controls must still hear ezan.
                warnings.append('Desktop media controls are unavailable.')
        return warnings

    def begin(self, ready):
        self.stop()
        stop = threading.Event()
        self._stop = stop
        def run():
            try:
                warnings = self.pause_once(stop)
            except Exception:
                warnings = ['Other media could not be paused.']
            if not stop.is_set():
                ready(warnings)
            while not stop.wait(1):
                try:
                    self.pause_once(stop)
                except Exception:
                    # Back off before retrying unavailable/disappearing players.
                    stop.wait(.1)
        threading.Thread(target=run, daemon=True, name='vakit-media-pause').start()
