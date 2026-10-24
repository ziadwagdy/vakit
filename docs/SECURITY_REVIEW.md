# Security and sharing review

Review date: **2026-10-24**. Scope: the source in this repository, the user-local installer, upstream timetable/audio handling and the files selected for initial publication. This is a source review plus automated checks, not an independent penetration test or a guarantee that the software has no vulnerabilities.

## Readiness decision

**Suitable for public source sharing as a community preview**, with the limits below made visible. No credentials, APKs, recordings or personal runtime data belong in this repository. This is not an official Diyanet app or an audited production release. No redistribution permission for third-party content has been established by this project.

## How the application runs

Python/PyGObject starts a GTK desktop application under the logged-in user's permissions. A held GTK/Gio application stays alive when its window is hidden. The session D-Bus ID makes repeated launches show the existing instance. A GLib timer checks the saved, dated timetable once per second. Network fetching occurs in a worker thread at launch and on a six-hour refresh cycle, not on every timer tick. The delivery key is written before GStreamer receives the local MP3 URI.

There is no root daemon, system-wide service, web server, remote control endpoint, cloud account or automatic code updater. Closing the window does not exit. Quit does. Optional login startup runs the installed source with `--background`. Suspend, logout and power-off stop playback availability.

## Threat model and fixes

| Area | Finding addressed before publication | Current control |
| --- | --- | --- |
| Network redirects | A redirect was inspected only after following it | Initial URL and each redirect are checked before connecting: HTTPS only, two exact official hostnames, no embedded credentials or unexpected ports |
| Network resource use | Untrusted responses can be too large or stall | Per-request timeout and bounded reads; OS certificate validation remains enabled |
| Cache paths | Upstream location IDs could influence local filenames | Positive numeric IDs, restricted location paths and matching district ID/path; no archive path extraction |
| Audio supply chain | A mutable URL alone did not identify the reviewed APK | SHA-256 pin checked before ZIP parsing; only five exact entries with size bounds; duplicate entries rejected; Android code never executed |
| Local writes | Predictable audio temporary paths could follow an existing symlink | Unpredictable temporary files, user-only permissions, atomic replacement; regression test confirms destination symlinks are replaced without modifying their target |
| Local privacy | New directories could inherit group/other read access | App data directories `0700`; newly written JSON/MP3 files `0600`; installer tightens the data directory |
| Damaged local state | Malformed preferences/cache/history could stop scheduling | Validate stored types, dates, times, timezone and location; reject unsafe paths; invalid location/timezone disables calls until corrected |
| Command execution | Installer uses subprocesses | Fixed absolute Ubuntu executable paths, argument arrays, no shell; desktop Exec quoting escapes special characters and rejects newlines |
| Background behavior | Installation had enabled startup and fetched audio by default | Both now require explicit options or Settings selections; updates preserve existing preferences |
| Repository exposure | Runtime data or tokens could accidentally be published | Scoped initial Git repository, ignore rules, tracked-file content checks, manual staged-file review and a GitHub noreply commit identity |

## Verification

The reproducible checks are in the README and GitHub Actions workflow:

- **26 unit/security regression tests** cover prayer scheduling, timezone/DST behavior, duplicates, missing/invalid timetable rows, resume handling, path traversal, redirects, oversized responses, APK checksum/size rejection, private writes, desktop quoting and corrupted state.
- GTK smoke test uses isolated settings and synthetic location data; checks selection/save, timetable display, master pause, hide/reopen and window construction. It does not alter a user's saved location or startup preference.
- An isolated installer check covered fresh-install defaults, explicit startup enable/disable, preserving preferences across updates, customized XDG paths, and desktop command paths containing spaces/percent signs. Desktop entry validation passed.
- Live check reads official country/province/district lists and the dated Istanbul timetable. It is opt-in and is not a complete validation of every location Diyanet publishes.
- Audio check silently decodes all five downloaded MP3s to a GStreamer test sink. This verifies decoding, **not** physical speaker audibility or unattended delivery across every desktop environment.
- Bandit 1.9.4 scans the runtime and installer. No medium/high findings were identified. Low-severity subprocess/import warnings are retained and reviewed: the installer invokes fixed system programs without a shell. The CI gate checks medium/high findings; this distinction is intentional and is not a zero-warning claim.
- `scripts/check_public.py` checks tracked file types, common credential formats and accidental personal data. It does not recognize every possible secret; manual review remains necessary. It never prints matched credential values.

Local checks ran with Python 3.14 and the installed Ubuntu GTK/GStreamer stack. CI additionally targets Ubuntu 22.04 and 24.04; consult the actual workflow results for their current status. The workflow uses a commit-pinned checkout action, read-only repository permissions and no persisted checkout credentials.

## Remaining limits

1. **Third-party trust:** HTTPS and the APK pin do not replace an independent upstream security audit or APK signature verification. System Python, GTK, GStreamer, MP3 decoders, Ubuntu packages, DNS, proxies and CA trust remain dependencies. Keep Ubuntu security updates installed.
2. **Same-user access:** this is an unsandboxed desktop app. Someone who controls the same user account can modify the app, cache or settings. It provides no defense against a compromised account/root user. Other applications in the same desktop session can invoke its exported open/stop/quit actions; these do not provide shell execution.
3. **Timing:** no wake-from-suspend, powered-off alarms, guaranteed notification delivery or missed-call recovery. A system-clock error affects scheduling. Correct timezone and audio output must be checked by the user. Calls whose delivery record cannot be saved are skipped.
4. **Public timetable dependency:** page markup/endpoints can change or be unavailable. The app may then have only its saved dated rows. Approved Diyanet API integration is not implemented. Missing dates are never filled with estimates.
5. **Audio pin updates:** a changed official APK intentionally blocks fresh audio installation. A maintainer must review and update the pin; the app never accepts a server-provided checksum automatically. Previously downloaded recordings remain local.
6. **Content rights:** the MIT license covers this project's code/icon only. No Diyanet content is shipped here, and no third-party redistribution authorization is claimed. Establish appropriate rights before shipping bundled recordings/data or offering a broader service.
7. **Review scope:** this is a small initial source review, not a formal certification, fuzzing campaign, dependency-CVE audit or long-running reliability study. Report newly discovered issues privately via SECURITY.md.
