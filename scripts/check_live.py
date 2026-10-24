#!/usr/bin/python3
"""Opt-in live check against official Diyanet sources (makes real requests)."""
from datetime import datetime
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ezan.core import Diyanet

with tempfile.TemporaryDirectory() as d:
    client = Diyanet(d)
    countries = client.countries()
    assert any(c['id'] == '2' for c in countries)
    provinces = client.regions('2')['states']
    assert any(s['id'] == '539' for s in provinces)
    districts = client.regions('2', '539')['districts']
    city = next(x for x in districts if x['id'] == '9541')
    data = client.refresh(city)
    today = datetime.now().date().isoformat()
    assert today in data['rows'], f'No data for today: {today}'
    assert len(data['rows'][today]['times']) == 6
    print(f'Official source OK: {len(countries)} countries, {len(provinces)} provinces, {len(districts)} Istanbul districts')
    print(f'Istanbul {today}: {data["rows"][today]["times"]}')
    print(f'Saved {len(data["rows"])} dated rows; missing dates never use estimated times.')
