# Vakit

**Diyanet prayer times and Turkish-style Arabic ezan for Ubuntu.**

A native GTK desktop app: select your country, province and district from Diyanet's lists, see the next prayer countdown, and hear a separate original Diyanet recording for each prayer.

**Status: community preview.** The app works and has automated checks, but has not received an independent security audit or broad testing across Ubuntu releases. It is independently made, **not an official or endorsed Diyanet product**. [Security review and sharing limitations](docs/SECURITY_REVIEW.md).

## Install

Requires Ubuntu desktop, Python **3.10+**, GTK 3, PyGObject, GStreamer and an MP3 decoder. Use Ubuntu's system Python rather than a virtual environment for the desktop app.

```sh
sudo apt update
sudo apt install git python3-gi gir1.2-gtk-3.0 gir1.2-gstreamer-1.0 gstreamer1.0-plugins-base gstreamer1.0-plugins-good
git clone https://github.com/ziadwagdy/vakit.git
cd vakit
/usr/bin/python3 install.py
~/.local/bin/vakit
```

Run `install.py` **without sudo**. Only Ubuntu dependency installation needs administrator privileges. There are no pip runtime dependencies, accounts, cloud backend, telemetry or listening network server.

The installer copies the app to your user account and adds **Vakit** to Ubuntu Applications. It does **not** launch the app, download audio or enable login startup by default. Updates preserve existing settings and startup preferences.

To explicitly enable both optional features during installation:

```sh
/usr/bin/python3 install.py --download-audio --autostart
```

Use `--no-autostart` to disable an existing login entry. Audio download and login startup are also available in Settings.

## First run

1. Select **country → city / province → district** in the location picker.
2. Check the location's timezone. Turkey uses `Europe/Istanbul`; outside Turkey enter the correct IANA timezone, such as `Europe/Berlin`.
3. Download the five Diyanet recordings in Settings if you have not already done so, and save.
4. Try a **Listen** button to confirm your speakers and volume work. **Stop ezan** ends playback.

No location is inferred from your IP or silently selected. Without a saved district, no calls are scheduled. The master switch pauses all calls; Settings can disable individual prayers.

## How it runs

This is an ordinary **user desktop process**, not a system service or browser app:

```text
Ubuntu Applications / optional login entry
    → ~/.local/bin/vakit (login entry invokes installed Python directly)
    → /usr/bin/python3 ~/.local/share/vakit/app/main.py
    → GTK main loop + one-second scheduler
    → dated Diyanet timetable + selected timezone
    → persist delivery record → GStreamer plays local MP3
```

- **Close the window:** reminders continue in the same process. Reopen Vakit from Applications to show it. A session D-Bus application ID prevents a second scheduler in the same desktop session.
- **Quit:** stops playback and exits. Reminders stop until you reopen the app or log in again with startup enabled.
- **Log out / suspend / turn off:** no playback. Vakit does not wake the computer. It requires an awake machine, active desktop login and working sound output. Prayers at least 60 seconds late are skipped on resume.
- **Login startup:** only if enabled. The entry invokes `main.py --background`; no window opens. A saved location and downloaded audio are still required.
- **Network:** a worker thread fetches Diyanet's public timetable at launch and every six hours, retrying after 15 minutes on failure. The one-second scheduler does **not** make one-second network requests.
- **Offline:** saved dated rows and local recordings remain usable. Missing dates are never estimated or copied from another day.
- **Sabah:** defaults to published **İmsak**. Turkish mosques can call later outside Ramadan. An optional 0–90 minute offset is skipped if it reaches sunrise. The timetable keeps original times; the countdown reflects the offset.
- **Sunrise:** displayed as Güneş; no ezan plays then.
- **Delivery history:** saved before playback to prevent repeats after restart or a backwards clock change. A save failure skips that call; a later audio error is reported rather than automatically retried.

```sh
~/.local/bin/vakit               # show / reopen
~/.local/bin/vakit --background  # run without a window
~/.local/bin/vakit --quit        # stop the running app
pgrep -af '/vakit/app/main.py'    # inspect the installed process
```

## Files and privacy

| Path | Purpose |
| --- | --- |
| `~/.local/share/vakit/app/` | Installed source; independent of the checkout |
| `~/.local/bin/vakit` | Command launcher |
| `~/.local/share/applications/io.github.vakit.Vakit.desktop` | Applications menu entry |
| `~/.config/autostart/io.github.vakit.Vakit.desktop` | Optional login entry |
| `~/.config/vakit/settings.json` | District, timezone, volume and preferences |
| `~/.local/share/vakit/times-*.json` | Dated timetable cache |
| `~/.local/share/vakit/fired.json` | Delivery history; pruned to about 35 days on delivery |
| `~/.local/share/vakit/sounds/` | Local MP3s and source checksums |

Configuration/data respect `XDG_CONFIG_HOME` and `XDG_DATA_HOME`. App data directories use user-only permissions (`0700`); newly written settings, cache and audio files use `0600`.

Requests go to approved Diyanet hosts over certificate-verified HTTPS. Diyanet and your configured proxy can see your network details and requested location IDs. No GPS coordinates, credentials or delivery history are uploaded. Vakit relies on the OS trust store, proxy configuration and installed media decoders.

## Sources and audio rights

- Timetables/location lists: [Diyanet prayer times](https://namazvakitleri.diyanet.gov.tr/tr-TR/).
- Recordings: [Diyanet Namaz Vaktim](https://mobilhizmetler.diyanet.gov.tr/namazvaktim.html) links the [public APK](https://mobilhizmetler.diyanet.gov.tr/apk/namaz_vakim.apk). Vakit extracts only `assets/sounds/ezan_{sabah,ogle,ikindi,aksam,yatsi}.mp3`. It never runs or installs Android code.
- The APK must match the reviewed SHA-256 in [`ezan/audio.py`](ezan/audio.py); an upstream change is rejected until reviewed. This is an integrity pin, not Diyanet signature verification.
- **No APK, recordings or personal timetable cache is included here.** Diyanet audio/data are outside the code license. Public availability does not grant redistribution rights. Establish any required permissions before repackaging or redistributing them.
- The public page/location endpoints are not a stable API contract. For broader service distribution, use Diyanet's [documented API and access process](https://awqatsalah.diyanet.gov.tr/index.html) and establish relevant permissions. Approved API access is not implemented here.

## Development and checks

```sh
/usr/bin/python3 -m unittest discover -s tests -v
/usr/bin/python3 scripts/check_public.py
/usr/bin/python3 scripts/check_ui.py       # graphical session; isolated test settings
/usr/bin/python3 scripts/check_live.py     # opt-in real Diyanet requests
/usr/bin/python3 scripts/check_audio.py    # full silent decode; requires downloaded recordings
uvx --from bandit==1.9.4 bandit -r ezan main.py install.py -ll
```

CI runs deterministic unit/security tests, an isolated GTK smoke check and static analysis on Ubuntu. Live endpoint/audio checks remain separate. See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md). Code and icon are [MIT licensed](LICENSE); third-party content is excluded.

## Update or uninstall

Pull reviewed changes in your checkout, rerun `/usr/bin/python3 install.py`, then reopen Vakit. The installer stops the old instance before replacing code. No automatic update mechanism runs.

For default paths:

```sh
~/.local/bin/vakit --quit
rm -f ~/.local/bin/vakit ~/.local/share/applications/io.github.vakit.Vakit.desktop
rm -f ~/.config/autostart/io.github.vakit.Vakit.desktop
rm -f ~/.local/share/icons/hicolor/scalable/apps/vakit.svg
```

Remove `~/.local/share/vakit/app/` to delete installed code. Optionally remove `~/.config/vakit/` and `~/.local/share/vakit/` to erase all preferences, recordings and history. Use your customized XDG paths if applicable. Deleting the source checkout alone does not uninstall the app.
