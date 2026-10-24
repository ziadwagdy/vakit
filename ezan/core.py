"""Official-source data, local storage and timezone-aware prayer scheduling."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from html.parser import HTMLParser
import json
import math
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener
from zoneinfo import ZoneInfo

BASE = 'https://namazvakitleri.diyanet.gov.tr'
APK_URL = 'https://mobilhizmetler.diyanet.gov.tr/apk/namaz_vakim.apk'
TRUSTED_HOSTS = frozenset(('namazvakitleri.diyanet.gov.tr', 'mobilhizmetler.diyanet.gov.tr'))
PRAYERS = ('sabah', 'ogle', 'ikindi', 'aksam', 'yatsi')
LABELS = {'sabah': 'Sabah / İmsak', 'gunes': 'Güneş', 'ogle': 'Öğle',
          'ikindi': 'İkindi', 'aksam': 'Akşam', 'yatsi': 'Yatsı'}
MAKAMS = {'sabah': 'Sabâ', 'ogle': 'Uşşak', 'ikindi': 'Rast',
          'aksam': 'Segâh', 'yatsi': 'Hicaz'}
MONTHS = dict(zip(('Ocak Şubat Mart Nisan Mayıs Haziran Temmuz Ağustos Eylül Ekim Kasım Aralık').split(), range(1, 13)))


def config_dir():
    return Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'vakit'


def data_dir():
    return Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'vakit'


def private_directory(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


def write_bytes(path: Path, payload):
    private_directory(path.parent)
    fd, name = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def write_json(path: Path, data):
    write_bytes(path, json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8'))


def read_json(path, default):
    try:
        if path.stat().st_size > 5_000_000:
            return default
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def local_timezone():
    try:
        value = Path('/etc/timezone').read_text().strip()
        ZoneInfo(value)
        return value
    except (OSError, ValueError, KeyError):
        try:
            return str(Path('/etc/localtime').resolve()).split('/zoneinfo/')[1]
        except IndexError:
            return 'Europe/Istanbul'


def default_config():
    return dict(location=None, timezone=local_timezone(), enabled=True, volume=0.7,
                prayers={p: True for p in PRAYERS}, morning_offset=0, pause_media=True)


def location_id(value):
    if not isinstance(value, (str, int)) or isinstance(value, bool) or not re.fullmatch(r'[1-9]\d{0,9}', str(value)):
        raise ValueError('Invalid Diyanet location identifier.')
    return str(value)


def location_path(path, identifier=None):
    if not isinstance(path, str) or not re.fullmatch(r'/tr-TR/[1-9]\d{0,9}/[a-zA-Z0-9_-]{1,200}', path):
        raise ValueError('Invalid Diyanet location URL.')
    if identifier is not None and path.split('/')[2] != location_id(identifier):
        raise ValueError('Diyanet location ID and URL do not match.')
    return path


def load_config():
    config = default_config()
    saved = read_json(config_dir() / 'settings.json', {})
    if not isinstance(saved, dict):
        return config
    for name in ('enabled', 'pause_media'):
        if isinstance(saved.get(name), bool):
            config[name] = saved[name]
    if isinstance(saved.get('prayers'), dict):
        config['prayers'].update({p: v for p, v in saved['prayers'].items() if p in PRAYERS and isinstance(v, bool)})
    volume = saved.get('volume')
    if isinstance(volume, (float, int)) and not isinstance(volume, bool) and math.isfinite(volume) and 0 <= volume <= 1:
        config['volume'] = volume
    offset = saved.get('morning_offset')
    if isinstance(offset, int) and not isinstance(offset, bool) and 0 <= offset <= 90:
        config['morning_offset'] = offset
    try:
        zone = saved.get('timezone', config['timezone'])
        if not isinstance(zone, str):
            raise ValueError('Invalid timezone')
        ZoneInfo(zone)
        config['timezone'] = zone
        location = saved.get('location')
        if location is not None:
            if not isinstance(location, dict) or not isinstance(location.get('name'), str) or not 0 < len(location['name']) <= 200:
                raise ValueError('Invalid location')
            location_id(location.get('id'))
            location_path(location.get('path'), location['id'])
            config['location'] = location
    except (ValueError, KeyError, TypeError):
        config['enabled'] = False
        config['location'] = None
    return config


def validate_source_url(url):
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname not in TRUSTED_HOSTS
            or parsed.username is not None or parsed.password is not None
            or parsed.port not in (None, 443) or parsed.fragment):
        raise ValueError('Only approved Diyanet HTTPS sources are allowed.')
    return url


class DiyanetRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Validate BEFORE following; never contact a redirect's arbitrary host.
        validate_source_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def get_bytes(url: str, limit=5_000_000):
    validate_source_url(url)
    req = Request(url, headers={'User-Agent': 'Vakit/1.0 (Ubuntu prayer-time desktop app)'})
    with build_opener(DiyanetRedirectHandler()).open(req, timeout=25) as r:
        validate_source_url(r.url)
        payload = r.read(limit + 1)
    if len(payload) > limit:
        raise ValueError('Source response is too large.')
    return payload


def valid_rows(rows):
    if not isinstance(rows, dict):
        return {}
    result = {}
    for day, row in rows.items():
        try:
            if date.fromisoformat(day).isoformat() != day or not isinstance(row, dict):
                continue
            times = row['times']
            ordered = [times[p] for p in ('sabah', 'gunes', 'ogle', 'ikindi', 'aksam', 'yatsi')]
            if not all(isinstance(t, str) and re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', t) for t in ordered):
                continue
            if ordered != sorted(ordered) or not isinstance(row.get('hijri'), str):
                continue
            result[day] = row
        except (ValueError, TypeError, KeyError):
            continue
    return result


def load_fired():
    saved = read_json(data_dir() / 'fired.json', {})
    out = {}
    if isinstance(saved, dict):
        for key, value in saved.items():
            try:
                if not isinstance(key, str) or not isinstance(value, str):
                    continue
                if datetime.fromisoformat(value).utcoffset() is not None:
                    out[key] = value
            except ValueError:
                continue
    return out


class PrayerPage(HTMLParser):
    """Read actual table rows; never use the page's possibly stale summary text."""
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.countries, self.rows = [], []
        self.select = None
        self.option = None
        self.row = None
        self.cell = None
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'select':
            self.select = a.get('name')
        elif tag == 'option' and self.select == 'country':
            self.option = [a.get('value'), '']
        elif tag == 'tr':
            self.row = []
        elif tag == 'td' and self.row is not None:
            self.cell = ''

    def handle_data(self, text):
        if self.option is not None:
            self.option[1] += text
        if self.cell is not None:
            self.cell += text

    def handle_endtag(self, tag):
        if tag == 'select':
            self.select = None
        elif tag == 'option' and self.option is not None:
            self.countries.append({'id': self.option[0], 'name': self.option[1].strip()})
            self.option = None
        elif tag == 'td' and self.cell is not None:
            self.row.append(' '.join(self.cell.split()))
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            self.rows.append(self.row)
            self.row = None


def parse_times(text: str):
    result = {}
    for row in PrayerPage(text).rows:
        if len(row) != 8:
            continue
        parts = row[0].split()
        if len(parts) < 3 or parts[1] not in MONTHS:
            continue
        try:
            day = date(int(parts[2]), MONTHS[parts[1]], int(parts[0])).isoformat()
            if not all(re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', t) for t in row[2:]):
                continue
            values = dict(zip(('sabah', 'gunes', 'ogle', 'ikindi', 'aksam', 'yatsi'), row[2:]))
            if list(values.values()) != sorted(values.values()):
                continue
            entry = dict(times=values, hijri=row[1])
            if day in result and result[day] != entry:
                raise ValueError(f'Diyanet returned conflicting prayer rows for {day}.')
            result[day] = entry
        except (ValueError, IndexError) as e:
            if 'conflicting' in str(e):
                raise
    if not result:
        raise ValueError('Diyanet returned no readable prayer timetable. Saved times have been preserved.')
    return result


class Diyanet:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory else data_dir()

    def countries(self):
        cache = self.directory / 'countries.json'
        saved = read_json(cache, [])
        if saved:
            return saved
        data = PrayerPage(get_bytes(BASE + '/tr-TR/').decode('utf-8-sig')).countries
        if not data:
            raise ValueError('Diyanet location list is temporarily unavailable.')
        write_json(cache, data)
        return data

    def regions(self, country, state=None):
        country = location_id(country)
        state = location_id(state) if state is not None else None
        params = dict(ChangeType='state' if state else 'country', CountryId=country, Culture='tr-TR')
        if state:
            params['StateId'] = state
        cache = self.directory / f'regions-{country}-{state or "all"}.json'
        saved = read_json(cache, None)
        if saved is not None:
            return saved
        data = json.loads(get_bytes(BASE + '/tr-TR/home/GetRegList?' + urlencode(params)))
        if data.get('Result') == 'error':
            raise ValueError('Diyanet could not load the selected region.')
        out = dict(states=[dict(id=location_id(x['SehirID']), name=x['SehirAdi']) for x in data.get('StateList') or []],
                   districts=[dict(id=location_id(x['IlceID']), name=x['IlceAdi'], path=location_path(x['IlceUrl'], x['IlceID']))
                              for x in data.get('StateRegionList') or []])
        if not out['states'] and not out['districts']:
            raise ValueError('No locations returned. Please try another region.')
        write_json(cache, out)
        return out

    def cache(self, location):
        return self.directory / f'times-{location_id(location["id"])}.json'

    def load(self, location):
        saved = read_json(self.cache(location), {})
        if not isinstance(saved, dict):
            return {}
        saved['rows'] = valid_rows(saved.get('rows'))
        return saved

    def refresh(self, location):
        path = location_path(location['path'], location['id'])
        rows = parse_times(get_bytes(BASE + path).decode('utf-8-sig'))
        saved = self.load(location)
        saved.update(rows=rows, fetched_at=datetime.now().astimezone().isoformat(), source=BASE + path)
        write_json(self.cache(location), saved)
        return saved


@dataclass(frozen=True)
class Event:
    key: str
    prayer: str
    at: datetime


def events(config, rows, now):
    location = config.get('location')
    if not location:
        return []
    zone = ZoneInfo(config['timezone'])
    today = now.astimezone(zone).date()
    out = []
    for delta in (-1, 0, 1, 2):
        day = today + timedelta(days=delta)
        row = rows.get(day.isoformat())
        if not row:
            continue
        for p in PRAYERS:
            at = datetime.combine(day, time.fromisoformat(row['times'][p]), zone)
            if p == 'sabah':
                at += timedelta(minutes=int(config.get('morning_offset', 0)))
                sunrise = datetime.combine(day, time.fromisoformat(row['times']['gunes']), zone)
                if at >= sunrise:  # Never schedule a dawn prayer after sunrise.
                    continue
            out.append(Event(f'{location["id"]}:{day}:{p}', p, at))
    return sorted(out, key=lambda e: e.at.timestamp())


def due_events(config, rows, now, fired):
    if not config.get('enabled'):
        return []
    return [e for e in events(config, rows, now)
            if config['prayers'].get(e.prayer, False) and e.key not in fired
            and 0 <= now.timestamp() - e.at.timestamp() < 60]
