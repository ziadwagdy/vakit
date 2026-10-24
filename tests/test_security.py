from datetime import datetime
import io
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
from urllib.request import Request
import zipfile

from ezan import audio
from ezan.core import (BASE, APK_URL, Diyanet, DiyanetRedirectHandler, data_dir, config_dir,
                       get_bytes, load_config, load_fired, location_id, location_path,
                       validate_source_url, valid_rows, write_bytes, write_json)
from ezan.desktop import desktop_quote


class NetworkBoundaryTests(unittest.TestCase):
    def test_only_official_https_hosts(self):
        for url in [BASE + '/tr-TR/', APK_URL]:
            self.assertEqual(validate_source_url(url), url)
        forbidden = ['http://namazvakitleri.diyanet.gov.tr/', 'https://localhost/',
                     'file:///etc/passwd', 'https://127.0.0.1/',
                     BASE + '.evil.example/', BASE + ':444/', BASE + '/#fragment',
                     ''.join(('https://user', ':pass@namazvakitleri.diyanet.gov.tr/'))]
        for url in forbidden:
            with self.subTest(url=url), patch('ezan.core.build_opener') as opener:
                with self.assertRaises(ValueError):
                    get_bytes(url)
                opener.assert_not_called()

    def test_redirect_is_rejected_before_following(self):
        handler = DiyanetRedirectHandler()
        for target in ['http://127.0.0.1/private', 'https://evil.example/', 'file:///etc/passwd']:
            with self.subTest(target=target), self.assertRaises(ValueError):
                handler.redirect_request(Request(BASE), None, 302, 'Found', {}, target)
        request = handler.redirect_request(Request(BASE), None, 302, 'Found', {}, BASE + '/tr-TR/')
        self.assertEqual(request.full_url, BASE + '/tr-TR/')

    def test_response_size_is_bounded(self):
        with patch('ezan.core.build_opener') as opener:
            response = opener.return_value.open.return_value.__enter__.return_value
            response.url = BASE
            response.read.return_value = b'x' * 11
            with self.assertRaises(ValueError):
                get_bytes(BASE, limit=10)
            response.read.assert_called_once_with(11)


class StorageBoundaryTests(unittest.TestCase):
    def test_location_ids_cannot_escape_cache_directory(self):
        for value in ['../1', '../../tmp/pwn', '1/../../x', '-1', True, None, '1\n', '1?x', '0']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                location_id(value)
        with tempfile.TemporaryDirectory() as d:
            client = Diyanet(d)
            with self.assertRaises(ValueError):
                client.cache({'id': '../../x'})
            self.assertEqual(client.cache({'id': '9541'}).parent, Path(d))

    def test_location_url_must_match_its_id(self):
        for path in ['//evil.example/', '/tr-TR/9541/../../x', '/tr-TR/9541/x?q=y', '/tr-TR/9206/ankara']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                location_path(path, '9541')

    def test_files_are_private_and_existing_symlink_is_not_followed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            target = root / 'private/settings.json'
            other = root / 'unrelated.txt'
            other.write_bytes(b'unchanged')
            target.parent.mkdir()
            target.symlink_to(other)
            write_bytes(target, b'new settings')
            self.assertEqual(other.read_bytes(), b'unchanged')
            self.assertFalse(target.is_symlink())
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(target.parent.stat().st_mode), 0o700)

    def test_desktop_paths_escape_expansion_and_reject_newlines(self):
        result = desktop_quote('/tmp/A %f "quoted" $name `command`/main.py')
        self.assertIn('%%f', result)
        self.assertIn('\\"quoted\\"', result)
        self.assertIn('\\$name', result)
        for value in ['/tmp/a\nExec=bad', '/tmp/a\rExec=bad']:
            with self.assertRaises(ValueError):
                desktop_quote(value)


class DamagedStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {'XDG_CONFIG_HOME': self.temp.name + '/config', 'XDG_DATA_HOME': self.temp.name + '/data'})
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    def test_invalid_timezone_disables_automatic_calls(self):
        write_json(config_dir() / 'settings.json', dict(timezone='not/a/timezone', enabled=True))
        self.assertFalse(load_config()['enabled'])

    def test_invalid_location_cannot_reach_filesystem_or_network(self):
        write_json(config_dir() / 'settings.json', dict(location=dict(id='../../x', name='X', path='/tr-TR/1/x')))
        self.assertIsNone(load_config()['location'])
        self.assertFalse(load_config()['enabled'])

    def test_invalid_json_shapes_and_numbers_recover(self):
        for value in [[], 'broken', None, dict(volume=float('nan'), prayers=[], morning_offset='many')]:
            with self.subTest(value=value):
                write_json(config_dir() / 'settings.json', value)
                config = load_config()
                self.assertIsInstance(config['prayers'], dict)
                self.assertEqual(config['volume'], 0.7)
                self.assertEqual(config['morning_offset'], 0)

    def test_bad_cache_rows_are_ignored(self):
        self.assertEqual(valid_rows({'2026-10-24': dict(times={'sabah': '99:99'})}), {})
        self.assertEqual(valid_rows([]), {})
        self.assertEqual(valid_rows({'bad-date': []}), {})

    def test_bad_ledger_entries_do_not_kill_scheduler(self):
        write_json(data_dir() / 'fired.json', {'valid': '2026-10-24T12:00:00+03:00', 'bad': 'oops', 'naive': '2026-10-24T12:00:00', 'wrong': []})
        self.assertEqual(list(load_fired()), ['valid'])


class AudioIntegrityTests(unittest.TestCase):
    def test_unreviewed_apk_is_rejected_before_extraction_or_writes(self):
        with patch('ezan.audio.zipfile.ZipFile') as unzip, patch('ezan.audio.write_bytes') as write:
            with self.assertRaises(ValueError):
                audio.install_sounds(b'unreviewed download')
            unzip.assert_not_called()
            write.assert_not_called()

    def test_oversized_archive_entry_is_rejected(self):
        with patch('ezan.audio.hashlib.sha256') as sha, patch('ezan.audio.zipfile.ZipFile') as unzip:
            sha.return_value.hexdigest.return_value = audio.OFFICIAL_APK_SHA256
            archive = unzip.return_value.__enter__.return_value
            entry = zipfile.ZipInfo('assets/sounds/ezan_sabah.mp3')
            entry.file_size = 30_000_000
            archive.infolist.return_value = [entry]
            archive.getinfo.return_value = entry
            with self.assertRaises(ValueError):
                audio.install_sounds(b'test-only mocked digest')
            archive.read.assert_not_called()


if __name__ == '__main__':
    unittest.main()
