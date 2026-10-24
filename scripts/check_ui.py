#!/usr/bin/python3
"""Exercise native GTK widgets with isolated settings and deterministic data."""
from datetime import datetime
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
temporary = tempfile.TemporaryDirectory()
os.environ['XDG_CONFIG_HOME'] = temporary.name + '/config'
os.environ['XDG_DATA_HOME'] = temporary.name + '/data'
from ezan.app import Vakit, Gtk, GLib, Gdk
from ezan.core import write_json, data_dir

app = Vakit()
app.set_application_id('io.github.vakit.Vakit.Test')
app.config['enabled'] = False
app.config['timezone'] = 'Europe/Istanbul'
today = datetime.now().date().isoformat()
times = dict(sabah='05:53', gunes='07:18', ogle='12:53', ikindi='15:49', aksam='18:19', yatsi='19:38')
district = dict(id='9541', name='İSTANBUL', path='/tr-TR/9541/istanbul-icin-namaz-vakti')
app.service.countries = lambda: [dict(id='2', name='TÜRKİYE')]
app.service.regions = lambda country, state=None: dict(states=[] if state else [dict(id='539', name='İSTANBUL')], districts=[district] if state else [])
app.service.refresh = lambda location: dict(rows={today: dict(times=times, hijri='13 Cemaziyelevvel 1448')})
failures = []
stage = [0]
ticks = [0]


def capture(widget, path):
    window = widget.get_window()
    allocation = widget.get_allocation()
    pixbuf = Gdk.pixbuf_get_from_window(window, 0, 0, allocation.width, allocation.height)
    if pixbuf:
        pixbuf.savev(path, 'png', [], [])


def drive():
    try:
        ticks[0] += 1
        assert ticks[0] < 150, 'GTK callback did not finish'
        if stage[0] == 0:
            assert app.window is not None
            app.show_settings()
            stage[0] = 1
        elif stage[0] == 1 and len(app.settings.state.get_model()):
            app.settings.state.set_active_id('539')
            stage[0] = 2
        elif stage[0] == 2 and app.settings.districts:
            app.settings.district.set_active_id('9541')
            assert app.settings.save_button.get_sensitive()
            stage[0] = 4
        elif stage[0] == 4:
            capture(app.settings, '/tmp/vakit-settings.png')
            with patch('ezan.app.set_autostart'):
                app.settings.response(Gtk.ResponseType.OK)
            stage[0] = 3
        elif stage[0] == 3 and app.saved.get('rows'):
            assert app.config['location']['id'] == '9541'
            assert app.time_labels['ogle'].get_text() == '12:53'
            assert app.place_label.get_text() == 'İSTANBUL'
            assert app.config['timezone'] == 'Europe/Istanbul'
            assert not app.stop_button.get_sensitive()
            capture(app.window, '/tmp/vakit-main.png')
            app.hide_window()
            assert not app.window.get_visible()
            assert app.get_is_registered()
            app.activate()
            assert app.window.get_visible()
            app.enabled_switch.set_active(True)
            assert app.config['enabled']
            app.enabled_switch.set_active(False)
            assert not app.config['enabled']
            print('GTK UI OK: location selection, save, timetable, pause/resume, hide/reopen.')
            print('Screenshots: /tmp/vakit-main.png and /tmp/vakit-settings.png')
            app.quit()
            return False
    except Exception as e:
        failures.append(e)
        app.quit()
        return False
    return True


GLib.timeout_add(100, drive)
app.run([sys.argv[0]])
temporary.cleanup()
if failures:
    raise failures[0]
