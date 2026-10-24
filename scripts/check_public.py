#!/usr/bin/python3
"""Inspect tracked files without printing any matched secret content."""
from pathlib import Path
import re
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
tracked = subprocess.run(['git', '-C', str(root), 'ls-files', '-z'], check=True, capture_output=True).stdout
files = [Path(p.decode()) for p in tracked.split(b'\0') if p]
if not files:
    raise SystemExit('No tracked files to inspect; stage the intended public files first.')
patterns = {
    'GitHub token': rb'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b',
    'private key': rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
    'AWS access ID': rb'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b',
    'credential URL': rb'https?://[^\s/@:]+:[^\s/@]+@',
    'private workstation path': rb'/home/[A-Za-z0-9_.-]+/(?:Developer|Documents|Downloads)/',
}
forbidden = {'.apk', '.mp3', '.ogg', '.wav', '.pem', '.key', '.pyc', '.log'}
problems = []
for relative in files:
    path = root / relative
    if path.is_symlink():
        problems.append((str(relative), 'tracked symlink requires manual review'))
        continue
    if relative.name.startswith('.env') or relative.suffix.lower() in forbidden:
        problems.append((str(relative), 'private/generated/media file'))
    if relative.name in {'settings.json', 'fired.json'} or relative.name.startswith('times-'):
        problems.append((str(relative), 'personal runtime data'))
    if not path.is_file():
        continue
    if path.stat().st_size > 1_000_000:
        problems.append((str(relative), 'unexpected large artifact'))
        continue
    data = path.read_bytes()
    for kind, pattern in patterns.items():
        if re.search(pattern, data):
            problems.append((str(relative), kind))
for path, kind in problems:
    print(f'{path}: {kind}')  # Never print the matching value.
print(f'Inspected {len(files)} tracked files; {len(problems)} public-content findings.')
sys.exit(bool(problems))
