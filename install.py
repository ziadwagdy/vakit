#!/usr/bin/python3
"""User-local installation; no root access and no third-party Python packages."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from ezan.audio import install_sounds, sounds_ready
from ezan.core import data_dir, private_directory
from ezan.desktop import autostart_path, desktop_quote


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--download-audio', action='store_true', help='Download the reviewed Diyanet recordings (about 36 MB)')
    parser.add_argument('--skip-audio', action='store_true', help=argparse.SUPPRESS)
    startup = parser.add_mutually_exclusive_group()
    startup.add_argument('--autostart', action='store_true', help='Enable reminders at desktop login')
    startup.add_argument('--no-autostart', action='store_true', help='Disable an existing login entry')
    args = parser.parse_args()
    if os.geteuid() == 0:
        raise SystemExit('Run the installer as your normal desktop user, without sudo.')
    import gi
    gi.require_version('Gtk', '3.0')
    gi.require_version('Gst', '1.0')
    from gi.repository import Gst
    Gst.init(None)
    if not Gst.ElementFactory.find('mpg123audiodec') and not Gst.ElementFactory.find('avdec_mp3'):
        raise SystemExit('Install an MP3 decoder: sudo apt install gstreamer1.0-plugins-good')
    # Gracefully stop a previously running version before replacing its source.
    if Path('/usr/bin/gapplication').is_file():
        subprocess.run(['/usr/bin/gapplication', 'action', 'io.github.vakit.Vakit', 'quit'], capture_output=True, timeout=10)
    private_directory(data_dir())
    target = data_dir() / 'app'
    target.mkdir(parents=True, exist_ok=True)
    for name in ['main.py', 'vakit.svg']:
        shutil.copy2(ROOT / name, target / name)
    shutil.copytree(ROOT / 'ezan', target / 'ezan', dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__'))
    launcher = Path.home() / '.local/bin/vakit'
    launcher.parent.mkdir(parents=True, exist_ok=True)
    # Fixed wrapper path is shell-quoted, not interpolated into a command string.
    import shlex
    launcher.write_text('#!/bin/sh\nexec /usr/bin/python3 ' + shlex.quote(str(target / 'main.py')) + ' "$@"\n')
    launcher.chmod(0o755)
    applications = data_dir().parent / 'applications'
    applications.mkdir(parents=True, exist_ok=True)
    (applications / 'io.github.vakit.Vakit.desktop').write_text(
        '[Desktop Entry]\nType=Application\nName=Vakit\nComment=Diyanet prayer times and Turkish ezan\n'
        f'Exec={desktop_quote(str(launcher))}\nIcon=vakit\nTerminal=false\nCategories=Utility;\n'
        'StartupWMClass=io.github.vakit.Vakit\nKeywords=prayer;ezan;azan;diyanet;namaz;\n')
    icon = data_dir().parent / 'icons/hicolor/scalable/apps/vakit.svg'
    icon.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / 'vakit.svg', icon)
    # Generate autostart pointing at the installed copy rather than this checkout.
    if args.autostart or args.no_autostart:
        subprocess.run(['/usr/bin/python3', '-c', f'from ezan.desktop import set_autostart; set_autostart({args.autostart!r})'],
                       cwd=target, check=True)
    if args.download_audio and not args.skip_audio and not sounds_ready():
        print('Downloading the five original ezan recordings from Diyanet…', flush=True)
        install_sounds()
    if Path('/usr/bin/update-desktop-database').is_file():
        subprocess.run(['/usr/bin/update-desktop-database', str(applications)], check=False)
    print(f'Installed Vakit. Open it from Applications or run {launcher}')
    print('Login startup:', 'enabled' if autostart_path().exists() else 'disabled (enable in Settings)')
    print('Ezan recordings:', 'ready' if sounds_ready() else 'not downloaded (download in Settings)')


if __name__ == '__main__':
    main()
