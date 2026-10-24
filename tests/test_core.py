from datetime import datetime, timezone
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from ezan.core import Diyanet, PrayerPage, default_config, due_events, events, parse_times, read_json, write_json


def html_row(day='24 Ekim 2026 Cumartesi', values=None):
    values = values or ['05:50', '07:20', '12:50', '15:40', '18:10', '19:30']
    return '<tr>' + ''.join('<td>' + v + '</td>' for v in [day, '13 Cemaziyelevvel 1448', *values]) + '</tr>'


class TimetableTests(unittest.TestCase):
    def test_reads_dated_tables_and_html_entities(self):
        text = '<p>Incorrect summary 09:00</p><table>' + html_row() + html_row('25 Ekim 2026 Pazar') + '</table>'
        data = parse_times(text)
        self.assertEqual(len(data), 2)
        self.assertEqual(data['2026-10-24']['times']['sabah'], '05:50')
        p = PrayerPage('<select name="country"><option value="2">T&#220;RKİYE</option></select>')
        self.assertEqual(p.countries, [dict(id='2', name='TÜRKİYE')])

    def test_missing_or_malformed_rows_fail_closed(self):
        for text in ['<h1>Unavailable</h1>', html_row(values=['99:99'] * 6), html_row(values=['07:30', '07:20', '12:50', '15:40', '18:10', '19:30'])]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_times(text)

    def test_conflicting_rows_are_rejected(self):
        with self.assertRaises(ValueError):
            parse_times(html_row() + html_row(values=['05:51', '07:20', '12:50', '15:40', '18:10', '19:30']))

    def test_network_failure_preserves_cache(self):
        with tempfile.TemporaryDirectory() as d:
            client = Diyanet(d)
            location = dict(id='9541', path='/tr-TR/9541/istanbul-icin-namaz-vakti')
            old = dict(rows=parse_times(html_row()))
            write_json(client.cache(location), old)
            with patch('ezan.core.get_bytes', side_effect=OSError('offline')):
                with self.assertRaises(OSError):
                    client.refresh(location)
            self.assertEqual(client.load(location), old)
            with patch('ezan.core.get_bytes', return_value=b'<h1>Maintenance</h1>'):
                with self.assertRaises(ValueError):
                    client.refresh(location)
            self.assertEqual(client.load(location), old)


class SchedulingTests(unittest.TestCase):
    def setUp(self):
        self.config = default_config()
        self.config.update(location=dict(id='9541'), timezone='Europe/Istanbul')
        self.rows = parse_times(html_row() + html_row('25 Ekim 2026 Pazar'))

    def at(self, hour, minute, second=0):
        return datetime(2026, 10, 24, hour, minute, second, tzinfo=timezone.utc)

    def test_exact_prayer_time_and_no_sunrise_ezan(self):
        # 09:50 UTC is 12:50 in Istanbul.
        due = due_events(self.config, self.rows, self.at(9, 50), {})
        self.assertEqual([e.prayer for e in due], ['ogle'])
        self.assertFalse(due_events(self.config, self.rows, self.at(4, 20), {}))
        self.assertFalse(due_events(self.config, self.rows, self.at(9, 49, 59), {}))

    def test_restart_and_clock_backwards_cannot_repeat(self):
        now = self.at(9, 50)
        e = due_events(self.config, self.rows, now, {})[0]
        self.assertFalse(due_events(self.config, self.rows, now, {e.key: now.isoformat()}))

    def test_resume_does_not_play_old_prayers(self):
        self.assertTrue(due_events(self.config, self.rows, self.at(9, 50, 59), {}))
        self.assertFalse(due_events(self.config, self.rows, self.at(9, 51), {}))
        self.assertFalse(due_events(self.config, self.rows, self.at(10, 0), {}))

    def test_disabled_prayer_and_master_pause(self):
        self.config['prayers']['ogle'] = False
        self.assertFalse(due_events(self.config, self.rows, self.at(9, 50), {}))
        self.config['prayers']['ogle'] = True
        self.config['enabled'] = False
        self.assertFalse(due_events(self.config, self.rows, self.at(9, 50), {}))

    def test_next_day_uses_its_own_dated_values(self):
        self.rows['2026-10-25']['times']['sabah'] = '05:51'
        future = events(self.config, self.rows, self.at(20, 0))
        next_day = [e for e in future if e.at.day == 25 and e.prayer == 'sabah'][0]
        self.assertEqual(next_day.at.strftime('%H:%M'), '05:51')
        self.assertFalse(events(self.config, {}, self.at(20, 0)))

    def test_morning_offset_and_sunrise_guard(self):
        self.config['morning_offset'] = 30
        dawn = [e for e in events(self.config, self.rows, self.at(0, 0)) if e.prayer == 'sabah'][0]
        self.assertEqual(dawn.at.strftime('%H:%M'), '06:20')
        self.config['morning_offset'] = 90
        self.assertNotIn('sabah', [e.prayer for e in events(self.config, self.rows, self.at(0, 0))])

    def test_timezone_dst_uses_selected_location_not_computer_offset(self):
        self.config['timezone'] = 'Europe/Berlin'
        days = events(self.config, self.rows, self.at(20, 0))
        noon = {e.at.day: e.at.utcoffset().total_seconds() for e in days if e.prayer == 'ogle'}
        self.assertEqual(noon, {24: 7200, 25: 3600})

    def test_new_location_has_a_distinct_deduplication_key(self):
        old = events(self.config, self.rows, self.at(0, 0))[0].key
        self.config['location']['id'] = '9206'
        self.assertNotEqual(events(self.config, self.rows, self.at(0, 0))[0].key, old)


if __name__ == '__main__':
    unittest.main()
