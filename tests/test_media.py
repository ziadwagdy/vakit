import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from ezan.media import MediaInterrupter, living_room_sockets, pause_living_room, pause_mpris, private_owned


class LocalControlTests(unittest.TestCase):
    def test_only_private_owned_runtime_sockets_are_discovered(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            private = base / 'living-room-123456abcdef'
            private.mkdir(mode=0o700)
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
                path = private / 'control.sock'
                listener.bind(str(path))
                path.chmod(0o600)
                with patch.dict(os.environ, {'XDG_RUNTIME_DIR': str(base)}):
                    self.assertIn(path, list(living_room_sockets()))
                    path.chmod(0o666)
                    self.assertNotIn(path, list(living_room_sockets()))
                    path.chmod(0o600)
                    private.chmod(0o755)
                    self.assertNotIn(path, list(living_room_sockets()))

    def test_private_control_sends_only_fixed_pause_action(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'control.sock'
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
                listener.bind(str(path))
                path.chmod(0o600)
                listener.listen(1)
                received = []
                def serve():
                    connection, _ = listener.accept()
                    with connection:
                        received.append(json.loads(connection.recv(4096)))
                        connection.sendall(b'{"ok":true}\n')
                worker = threading.Thread(target=serve)
                worker.start()
                self.assertTrue(pause_living_room(path))
                worker.join(timeout=2)
                self.assertEqual(received, [{'action': 'pause_media'}])

    def test_symlink_or_regular_file_is_not_a_control_socket(self):
        with tempfile.TemporaryDirectory() as d:
            file = Path(d) / 'plain'
            file.write_text('not a socket')
            link = Path(d) / 'link'
            link.symlink_to(file)
            self.assertFalse(private_owned(file))
            self.assertFalse(private_owned(link))


class StandardMediaTests(unittest.TestCase):
    def test_integration_failure_does_not_prevent_audio_start(self):
        controller = MediaInterrupter()
        ready = threading.Event()
        warnings = []
        with patch.object(controller, 'pause_once', side_effect=RuntimeError('unavailable')):
            controller.begin(lambda value: (warnings.extend(value), ready.set()))
            self.assertTrue(ready.wait(1))
            controller.stop()
        self.assertTrue(warnings)

    def test_only_playing_players_are_paused_and_never_toggled_or_resumed(self):
        from gi.repository import Gio
        calls = []
        def call(name, path, interface, method, params, reply, flags, timeout, cancel):
            calls.append((name, method, flags))
            value = []
            if method == 'ListNames':
                value = ['org.mpris.MediaPlayer2.playing', 'org.mpris.MediaPlayer2.paused', 'org.example.Other']
            elif method == 'GetAll':
                value = dict(PlaybackStatus='Playing' if name.endswith('.playing') else 'Paused', CanPause=True)
            return Mock(unpack=lambda: (value,))
        bus = Mock(call_sync=call)
        with patch.object(Gio, 'bus_get_sync', return_value=bus):
            self.assertEqual(pause_mpris(time.monotonic() + 1), 1)
        self.assertEqual([name for name, method, _ in calls if method == 'Pause'], ['org.mpris.MediaPlayer2.playing'])
        self.assertFalse(any(method in ('Play', 'PlayPause') for _, method, _ in calls))
        self.assertTrue(all(flags == Gio.DBusCallFlags.NO_AUTO_START for _, _, flags in calls))

    def test_cancel_during_initial_pause_never_starts_audio(self):
        controller = MediaInterrupter()
        entered, finished = threading.Event(), threading.Event()
        ready = Mock()
        def slow(stop):
            entered.set()
            stop.wait(2)
            finished.set()
            return []
        with patch.object(controller, 'pause_once', side_effect=slow):
            controller.begin(ready)
            self.assertTrue(entered.wait(1))
            controller.stop()
            self.assertTrue(finished.wait(1))
        ready.assert_not_called()
        self.assertFalse(controller.active)


if __name__ == '__main__':
    unittest.main()
