from datetime import datetime
import threading
import time
from zoneinfo import ZoneInfo, available_timezones

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gio, GLib, Gdk

from .core import (BASE, Diyanet, LABELS, MAKAMS, PRAYERS, config_dir, data_dir,
                   load_config, load_fired, write_json, events, due_events)
from .audio import Player, install_sounds, sound_path, sounds_ready
from .desktop import APP_ID, autostart_path, set_autostart
from .media import MediaInterrupter

CSS = b'''
window { background: #f5f4ef; color: #193b35; }
headerbar { background: #123e34; color: white; border: none; }
headerbar button { color: white; background: #235548; border: none; }
headerbar .subtitle { color: #ceded4; }
.hero { background: #164b3f; color: #fbf6e9; border-radius: 18px; padding: 26px; }
.hero-title { font-size: 15px; color: #d3dfd6; }
.countdown { font-size: 42px; font-weight: 600; font-family: monospace; }
.title { font-size: 25px; font-weight: 700; }
.subtitle { color: #61766c; }
.prayer { background: white; border-radius: 12px; padding: 14px; }
.prayer-name { font-size: 15px; font-weight: 600; }
.prayer-time { font-size: 23px; font-weight: 500; font-family: monospace; }
.source { font-size: 12px; color: #61766c; }
.section { font-size: 15px; font-weight: 600; }
.status { background: #e5ece2; border-radius: 9px; padding: 10px; }
button { border-radius: 8px; padding: 7px 12px; }
button.suggested-action { background: #196049; color: white; }
'''


def label(text='', style=None, xalign=0):
    w = Gtk.Label(label=text, xalign=xalign)
    if style:
        w.get_style_context().add_class(style)
    return w


def box(vertical=True, spacing=10):
    return Gtk.Box(orientation=Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL, spacing=spacing)


class Vakit(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.window = None
        self.settings = None
        self.config = load_config()
        self.service = Diyanet()
        self.saved = self.service.load(self.config['location']) if self.config['location'] else {}
        self.fired = load_fired()
        self.fetching = False
        self.next_fetch = 0
        self.status_text = 'Choose your Diyanet location to get started.'
        self.playing = False
        self.media = MediaInterrupter()
        self.play_request = 0

    def do_startup(self):
        Gtk.Application.do_startup(self)
        self.hold()  # Closing the window keeps the scheduler alive in this login session.
        style = Gtk.CssProvider()
        style.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), style, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.player = Player(self.audio_error, self.audio_ended)
        GLib.timeout_add_seconds(1, self.tick)
        for name, callback in [('stop', lambda *_: self.stop()), ('open', lambda *_: self.activate()),
                               ('quit', lambda *_: self.quit())]:
            action = Gio.SimpleAction.new(name, None)
            action.connect('activate', callback)
            self.add_action(action)
        self.tick()

    def do_command_line(self, command_line):
        args = command_line.get_arguments()[1:]
        if '--quit' in args:
            self.quit()
        elif '--background' not in args:
            self.activate()
        return 0

    def do_activate(self):
        if not self.window:
            self.build_window()
        self.window.show_all()
        self.window.present()
        self.update_view()
        if not self.config['location'] and not self.settings:
            self.show_settings()

    def do_shutdown(self):
        self.play_request += 1
        self.media.stop()
        self.player.stop()
        Gtk.Application.do_shutdown(self)

    def persist(self):
        write_json(config_dir() / 'settings.json', self.config)

    def background(self, job, done):
        def run():
            try:
                value, error = job(), None
            except Exception as e:
                value, error = None, str(e)
            GLib.idle_add(done, value, error)
        threading.Thread(target=run, daemon=True).start()

    def status(self, text):
        self.status_text = text
        if self.window:
            self.status_label.set_text(text)

    def build_window(self):
        self.window = Gtk.ApplicationWindow(application=self, title='Vakit · Diyanet Prayer Times')
        self.window.set_default_size(690, 780)
        self.window.set_icon_name('vakit')
        self.window.connect('delete-event', self.hide_window)
        header = Gtk.HeaderBar(title='Vakit', subtitle='Prayer times • Turkish ezan', show_close_button=True)
        self.window.set_titlebar(header)
        settings = Gtk.Button.new_from_icon_name('emblem-system-symbolic', Gtk.IconSize.BUTTON)
        settings.set_tooltip_text('Location and settings')
        settings.connect('clicked', lambda *_: self.show_settings())
        header.pack_end(settings)
        quit_button = Gtk.Button(label='Quit')
        quit_button.set_tooltip_text('Exit Vakit and stop all reminders')
        quit_button.connect('clicked', lambda *_: self.quit())
        header.pack_start(quit_button)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.window.add(scroll)
        content = box(spacing=16)
        content.set_border_width(25)
        scroll.add(content)
        self.place_label = label('Your place of prayer', 'title')
        content.pack_start(self.place_label, False, False, 0)
        self.date_label = label('', 'subtitle')
        content.pack_start(self.date_label, False, False, 0)

        hero = box(spacing=7)
        hero.get_style_context().add_class('hero')
        self.next_label = label('Select a location', 'hero-title')
        self.countdown = label('—:—:—', 'countdown')
        self.clock_label = label('')
        for w in [self.next_label, self.countdown, self.clock_label]:
            hero.pack_start(w, False, False, 0)
        content.pack_start(hero, False, False, 0)

        row = box(False)
        row.pack_start(label('TODAY’S PRAYER TIMES', 'section'), True, True, 0)
        refresh = Gtk.Button.new_from_icon_name('view-refresh-symbolic', Gtk.IconSize.BUTTON)
        refresh.set_tooltip_text('Refresh from Diyanet')
        refresh.connect('clicked', lambda *_: self.refresh(force=True))
        row.pack_end(refresh, False, False, 0)
        content.pack_start(row, False, False, 0)

        grid = Gtk.Grid(column_spacing=10, row_spacing=10, column_homogeneous=True)
        self.time_labels = {}
        for i, p in enumerate(('sabah', 'gunes', 'ogle', 'ikindi', 'aksam', 'yatsi')):
            tile = box(spacing=5)
            tile.get_style_context().add_class('prayer')
            tile.pack_start(label(LABELS[p], 'prayer-name'), False, False, 0)
            self.time_labels[p] = label('—:—', 'prayer-time')
            tile.pack_start(self.time_labels[p], False, False, 0)
            subtitle = 'Sunrise · no ezan' if p == 'gunes' else MAKAMS[p] + ' makamı'
            tile.pack_start(label(subtitle, 'source'), False, False, 0)
            grid.attach(tile, i % 3, i // 3, 1, 1)
        content.pack_start(grid, False, False, 0)

        controls = box(False)
        controls.pack_start(label('Automatic ezan', 'section'), True, True, 0)
        self.enabled_switch = Gtk.Switch(active=self.config['enabled'])
        self.enabled_switch.set_valign(Gtk.Align.CENTER)
        self.enabled_switch.connect('notify::active', self.toggle_enabled)
        controls.pack_end(self.enabled_switch, False, False, 0)
        content.pack_start(controls, False, False, 0)

        preview = box(False, 5)
        preview.pack_start(label('Listen'), False, False, 3)
        for p in PRAYERS:
            button = Gtk.Button(label=LABELS[p].split(' /')[0])
            button.set_tooltip_text('Preview Diyanet’s ' + MAKAMS[p] + ' recording')
            button.connect('clicked', lambda _, prayer=p: self.play(prayer))
            preview.pack_start(button, True, True, 0)
        content.pack_start(preview, False, False, 0)
        volume_row = box(False)
        volume_row.pack_start(label('Volume'), False, False, 0)
        volume = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        volume.set_value(self.config['volume'] * 100)
        volume.set_digits(0)
        volume.connect('value-changed', self.change_volume)
        volume_row.pack_start(volume, True, True, 0)
        self.stop_button = Gtk.Button(label='Stop ezan')
        self.stop_button.connect('clicked', lambda *_: self.stop())
        volume_row.pack_end(self.stop_button, False, False, 0)
        content.pack_start(volume_row, False, False, 0)

        self.status_label = label(self.status_text, 'status')
        self.status_label.set_line_wrap(True)
        self.status_label.set_max_width_chars(70)
        content.pack_start(self.status_label, False, False, 0)
        choose = Gtk.Button(label='Choose location & settings')
        choose.get_style_context().add_class('suggested-action')
        choose.connect('clicked', lambda *_: self.show_settings())
        content.pack_start(choose, False, False, 0)
        source = Gtk.LinkButton.new_with_label(BASE + '/tr-TR/', 'Times & recordings sourced from Diyanet İşleri Başkanlığı ↗')
        content.pack_start(source, False, False, 0)
        footer = label('Runs after this window closes. Computer must be awake and logged in.\nIndependent desktop app; not an official Diyanet product.', 'source')
        footer.set_line_wrap(True)
        content.pack_start(footer, False, False, 0)

    def hide_window(self, *_):
        self.window.hide()
        return True

    def change_volume(self, scale):
        self.config['volume'] = scale.get_value() / 100
        self.player.set_volume(self.config['volume'])
        self.persist()

    def toggle_enabled(self, switch, _):
        self.config['enabled'] = switch.get_active()
        self.persist()
        if not self.config['enabled']:
            self.stop()
            self.status('Automatic ezan paused.')
        else:
            self.status('Automatic ezan enabled.' if self.config['location'] else 'Choose your Diyanet location first.')
        self.update_view()

    def play(self, prayer, scheduled=False):
        self.play_request += 1
        request = self.play_request
        self.player.stop()
        self.media.stop()
        self.playing = False
        if not sound_path(prayer).is_file():
            self.audio_error('Download the official ezan recordings first.')
            return
        def start(warnings=None):
            if request != self.play_request:
                return False
            try:
                self.player.play(prayer, self.config['volume'])
                self.playing = True
                message = 'Playing Diyanet’s ' + LABELS[prayer] + ' ezan · ' + MAKAMS[prayer]
                if warnings:
                    message += '. ' + ' '.join(dict.fromkeys(warnings))
                self.status(message)
                if scheduled:
                    self.notify('Vakit · ' + LABELS[prayer], self.config['location']['name'] + ' · Diyanet prayer time')
            except Exception as e:
                self.audio_error(str(e))
            self.update_view()
            return False
        if self.config.get('pause_media', True):
            self.status('Pausing other media before ezan…')
            self.media.begin(lambda warnings: GLib.idle_add(start, warnings))
        else:
            start()
        self.update_view()

    def stop(self):
        self.play_request += 1
        self.media.stop()
        self.player.stop()
        self.playing = False
        self.status('Ezan stopped.')
        self.update_view()

    def audio_error(self, error):
        self.play_request += 1
        self.media.stop()
        self.playing = False
        self.status('Audio error: ' + error)
        self.notify('Ezan audio needs attention', error)
        self.update_view()

    def audio_ended(self):
        self.media.stop()
        self.playing = False
        self.status('Ezan finished.')
        self.update_view()

    def notify(self, title, body):
        notification = Gio.Notification.new(title)
        notification.set_body(body)
        notification.set_default_action('app.open')
        if self.playing:
            notification.add_button('Stop ezan', 'app.stop')
        self.send_notification('prayer', notification)

    def refresh(self, force=False):
        if self.fetching or not self.config['location']:
            return
        if not force and time.monotonic() < self.next_fetch:
            return
        self.fetching = True
        location = dict(self.config['location'])
        self.status('Refreshing the official Diyanet timetable…')
        def done(value, error):
            self.fetching = False
            if location != self.config['location']:
                self.next_fetch = 0
                return False
            if error:
                self.next_fetch = time.monotonic() + 900
                self.status('Diyanet is unavailable. Using saved dated times where available. ' + error)
            else:
                self.saved = value
                self.next_fetch = time.monotonic() + 6 * 3600
                self.status('Official Diyanet timetable updated. Saved for offline use.')
                today = datetime.now(ZoneInfo(self.config['timezone'])).date().isoformat()
                if today not in value.get('rows', {}):
                    self.status('Diyanet returned no timetable for today. No ezan will be scheduled for missing dates.')
            self.update_view()
            return False
        self.background(lambda: self.service.refresh(location), done)

    def tick(self):
        self.refresh()
        now = datetime.now().astimezone()
        for event in due_events(self.config, self.saved.get('rows', {}), now, self.fired):
            # Persist before playing: restart, clock changes and resume cannot repeat an ezan.
            self.fired[event.key] = now.isoformat()
            self.fired = {k: v for k, v in self.fired.items() if (now - datetime.fromisoformat(v)).days < 35}
            try:
                write_json(data_dir() / 'fired.json', self.fired)
            except OSError:
                self.status('Cannot save delivery history. Ezan skipped to prevent repeated playback. Check free disk space and file permissions.')
                continue
            self.play(event.prayer, scheduled=True)
        self.update_view()
        return True

    def update_view(self):
        if not self.window:
            return
        now = datetime.now(ZoneInfo(self.config['timezone']))
        location = self.config['location']
        self.place_label.set_text(location['name'] if location else 'Your place of prayer')
        today = self.saved.get('rows', {}).get(now.date().isoformat(), {})
        self.date_label.set_text(now.strftime('%A, %d %B %Y') + ('  ·  ' + today['hijri'] if today else ''))
        for p, w in self.time_labels.items():
            w.set_text(today.get('times', {}).get(p, '—:—'))
        upcoming = [e for e in events(self.config, self.saved.get('rows', {}), now) if e.at.timestamp() > now.timestamp()
                    and self.config['prayers'].get(e.prayer, False)]
        if upcoming:
            e = upcoming[0]
            delta = int(e.at.timestamp() - now.timestamp())
            self.next_label.set_text(('Next ezan · ' if self.config['enabled'] else 'Paused · next prayer ') + LABELS[e.prayer] + ' at ' + e.at.strftime('%H:%M'))
            self.countdown.set_text(f'{delta // 3600:02}:{delta % 3600 // 60:02}:{delta % 60:02}')
        else:
            self.next_label.set_text('Choose a Diyanet location' if not location else 'No upcoming enabled prayer in the saved timetable')
            self.countdown.set_text('—:—:—')
        self.clock_label.set_text(now.strftime('%H:%M:%S') + '  ·  ' + self.config['timezone'])
        self.stop_button.set_sensitive(self.playing or self.media.active)

    def show_settings(self):
        if self.settings:
            self.settings.present()
            return
        self.settings = Settings(self)
        self.settings.show_all()


class Settings(Gtk.Dialog):
    def __init__(self, app):
        super().__init__(title='Location & settings', transient_for=app.window, modal=True)
        self.app = app
        self.generation = 0
        self.closed = False
        self.pending = app.config.get('location') or {}
        self.set_default_size(530, 660)
        self.add_button('Cancel', Gtk.ResponseType.CANCEL)
        self.save_button = self.add_button('Save settings', Gtk.ResponseType.OK)
        self.save_button.get_style_context().add_class('suggested-action')
        self.save_button.set_sensitive(False)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.get_content_area().pack_start(scroll, True, True, 0)
        content = box(spacing=12)
        scroll.add(content)
        content.set_border_width(22)
        content.pack_start(label('Your Diyanet location', 'title'), False, False, 0)
        info = label('Choose the country, city and district from Diyanet’s own location list.', 'subtitle')
        info.set_line_wrap(True)
        content.pack_start(info, False, False, 0)
        self.country, self.state, self.district = [Gtk.ComboBoxText() for _ in range(3)]
        for title, combo in [('Country', self.country), ('City / province', self.state), ('District / town', self.district)]:
            content.pack_start(label(title), False, False, 0)
            content.pack_start(combo, False, False, 0)
        self.districts = {}
        self.country.connect('changed', self.country_changed)
        self.state.connect('changed', self.state_changed)
        self.district.connect('changed', lambda *_: self.save_button.set_sensitive(bool(self.district.get_active_id())))

        content.pack_start(label('Timezone of the selected location'), False, False, 0)
        self.timezone = Gtk.Entry(text=app.config['timezone'])
        completion = Gtk.EntryCompletion()
        model = Gtk.ListStore(str)
        for z in sorted(available_timezones()):
            model.append([z])
        completion.set_model(model)
        completion.set_text_column(0)
        self.timezone.set_completion(completion)
        content.pack_start(self.timezone, False, False, 0)
        self.timezone_note = label('For Turkey: Europe/Istanbul. For other countries, choose the local timezone.', 'source')
        self.timezone_note.set_line_wrap(True)
        content.pack_start(self.timezone_note, False, False, 0)

        morning_row = box(False)
        morning_row.pack_start(label('Sabah ezan after İmsak (minutes)'), True, True, 0)
        self.morning = Gtk.SpinButton.new_with_range(0, 90, 1)
        self.morning.set_value(app.config.get('morning_offset', 0))
        morning_row.pack_end(self.morning, False, False, 0)
        content.pack_start(morning_row, False, False, 0)
        morning_note = label('0 = at Diyanet İmsak. Mosques may call later outside Ramadan.\nAn offset at or beyond sunrise is skipped.', 'source')
        content.pack_start(morning_note, False, False, 0)
        prayers = box(False, 5)
        self.checks = {}
        for p in PRAYERS:
            check = Gtk.CheckButton(label=LABELS[p].split(' /')[0])
            check.set_active(app.config['prayers'].get(p, True))
            self.checks[p] = check
            prayers.pack_start(check, True, True, 0)
        content.pack_start(prayers, False, False, 0)
        self.autostart = Gtk.CheckButton(label='Start prayer reminders when I log in to Ubuntu')
        self.autostart.set_active(autostart_path().exists())
        content.pack_start(self.autostart, False, False, 0)
        self.pause_media = Gtk.CheckButton(label='Pause other media during ezan (Living Room + desktop players)')
        self.pause_media.set_active(app.config.get('pause_media', True))
        content.pack_start(self.pause_media, False, False, 0)
        self.sound_button = Gtk.Button(label='Download official Diyanet ezan recordings' if not sounds_ready() else 'Official recordings downloaded ✓ · Download again')
        self.sound_button.connect('clicked', self.download_sounds)
        content.pack_start(self.sound_button, False, False, 0)
        self.message = label('Loading Diyanet locations…', 'source')
        self.message.set_line_wrap(True)
        self.message.set_max_width_chars(65)
        content.pack_start(self.message, False, False, 0)
        self.connect('response', self.respond)
        self.connect('destroy', self.on_destroy)
        app.background(app.service.countries, self.countries_loaded)

    def on_destroy(self, *_):
        self.closed = True
        self.app.settings = None

    def countries_loaded(self, data, error):
        if self.closed:
            return False
        if error:
            self.message.set_text(error + ' Close settings and try again.')
        else:
            for item in data:
                self.country.append(item['id'], item['name'])
            self.country.set_active_id(self.pending.get('country_id', '2'))
        return False

    def country_changed(self, *_):
        self.generation += 1
        self.state.remove_all()
        self.district.remove_all()
        country = self.country.get_active_id()
        if not country:
            return
        self.timezone.set_text('Europe/Istanbul' if country == '2' else self.app.config['timezone'])
        self.load_regions(country)

    def state_changed(self, *_):
        self.generation += 1
        self.district.remove_all()
        state = self.state.get_active_id()
        if state:
            self.load_regions(self.country.get_active_id(), state)

    def load_regions(self, country, state=None):
        token = self.generation
        self.message.set_text('Loading locations from Diyanet…')
        def done(data, error):
            if self.closed or token != self.generation:
                return False
            if error:
                self.message.set_text(error)
                return False
            if state is None:
                for item in data['states']:
                    self.state.append(item['id'], item['name'])
            self.districts = {d['id']: d for d in data['districts']}
            for item in data['districts']:
                self.district.append(item['id'], item['name'])
            self.message.set_text('Choose your district, then save. Lists are cached for offline access.')
            if state is None and self.pending.get('country_id') == country:
                self.state.set_active_id(self.pending.get('state_id', ''))
            if self.pending.get('id') in self.districts:
                self.district.set_active_id(self.pending['id'])
            return False
        self.app.background(lambda: self.app.service.regions(country, state), done)

    def download_sounds(self, *_):
        self.sound_button.set_sensitive(False)
        self.message.set_text('Downloading Diyanet’s app and extracting only its five ezan recordings…')
        def done(_, error):
            if not self.closed:
                self.sound_button.set_sensitive(True)
                self.sound_button.set_label('Official recordings downloaded ✓' if not error else 'Retry download')
                self.message.set_text(error or 'Five official recordings saved. Audio works offline.')
            return False
        self.app.background(install_sounds, done)

    def respond(self, _, response):
        if response != Gtk.ResponseType.OK:
            self.destroy()
            return
        district = self.districts.get(self.district.get_active_id())
        if not district:
            self.message.set_text('Select a district from the Diyanet list.')
            return
        zone = self.timezone.get_text().strip()
        try:
            ZoneInfo(zone)
        except (ValueError, KeyError):
            self.message.set_text('Choose a valid timezone, such as Europe/Istanbul or Europe/Berlin.')
            return
        location = dict(district, country_id=self.country.get_active_id(), state_id=self.state.get_active_id(),
                        country_name=self.country.get_active_text(), state_name=self.state.get_active_text())
        self.app.stop()
        self.app.config.update(location=location, timezone=zone, morning_offset=self.morning.get_value_as_int(),
                               prayers={p: c.get_active() for p, c in self.checks.items()}, pause_media=self.pause_media.get_active())
        self.app.persist()
        try:
            set_autostart(self.autostart.get_active())
        except (OSError, ValueError) as e:
            self.message.set_text('Settings saved, but login startup could not be changed: ' + str(e))
            return
        self.app.saved = self.app.service.load(location)
        self.app.next_fetch = 0
        self.app.refresh(force=True)
        self.app.update_view()
        self.destroy()
