from pathlib import Path
import os


APP_ID = 'io.github.vakit.Vakit'


def desktop_quote(value):
    if '\n' in value or '\r' in value:
        raise ValueError('Desktop command paths cannot contain newlines.')
    # Percent escapes are expanded by the desktop launcher even inside quotes.
    value = value.replace('%', '%%')
    for char in ('\\', '"', '`', '$'):
        value = value.replace(char, '\\' + char)
    return '"' + value + '"'


def autostart_path():
    return Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'autostart' / f'{APP_ID}.desktop'


def set_autostart(enabled):
    target = autostart_path()
    if enabled:
        source = Path(__file__).resolve().parent.parent / 'main.py'
        target.parent.mkdir(parents=True, exist_ok=True)
        # Desktop entries use their own quoting, not shell command parsing.
        quoted = desktop_quote(str(source))
        target.write_text('[Desktop Entry]\nType=Application\nName=Vakit Prayer Reminders\n'
                          f'Exec=/usr/bin/python3 {quoted} --background\n'
                          'X-GNOME-Autostart-enabled=true\nNoDisplay=true\n')
    else:
        target.unlink(missing_ok=True)
