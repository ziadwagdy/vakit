"""Use the five recordings distributed by Diyanet, without redistributing the APK."""
import hashlib
import io
import zipfile

from .core import APK_URL, PRAYERS, data_dir, get_bytes, write_bytes, write_json

# Reviewed upstream artifact downloaded over verified HTTPS on 2026-10-24.
# An upstream change requires an explicit source review and pin update.
OFFICIAL_APK_SHA256 = '056208524ac758ab50b98e7cd4ae6828fdef04a70780100a03591b8485e96afa'


def sound_path(prayer):
    if prayer not in PRAYERS:
        raise ValueError('Unknown prayer')
    return data_dir() / 'sounds' / f'ezan_{prayer}.mp3'


def sounds_ready():
    return all(sound_path(p).is_file() and sound_path(p).stat().st_size > 1000 for p in PRAYERS)


def install_sounds(apk_bytes=None):
    data = apk_bytes if apk_bytes is not None else get_bytes(APK_URL, limit=80_000_000)
    if hashlib.sha256(data).hexdigest() != OFFICIAL_APK_SHA256:
        raise ValueError('The Diyanet download differs from the reviewed APK. No audio was installed. '
                         'Check for a Vakit update; do not bypass the checksum.')
    # Extract only exact known media paths; no APK code is executed or installed.
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        payloads = {}
        for p in PRAYERS:
            name = f'assets/sounds/ezan_{p}.mp3'
            if sum(i.filename == name for i in z.infolist()) != 1:
                raise ValueError('Duplicate or missing recording in official source.')
            info = z.getinfo(name)
            if not 1000 < info.file_size < 20_000_000:
                raise ValueError('Unexpected recording size in official source.')
            payloads[p] = z.read(name)
    hashes = {}
    for p, payload in payloads.items():
        path = sound_path(p)
        write_bytes(path, payload)
        hashes[p] = hashlib.sha256(payload).hexdigest()
    write_json(data_dir() / 'sounds/source.json', dict(source=APK_URL, apk_sha256=hashlib.sha256(data).hexdigest(),
                                                      recordings_sha256=hashes))


class Player:
    def __init__(self, on_error=None, on_end=None):
        import gi
        gi.require_version('Gst', '1.0')
        from gi.repository import Gst
        self.Gst = Gst
        Gst.init(None)
        self.playbin = Gst.ElementFactory.make('playbin', 'ezan-player')
        if not self.playbin:
            raise RuntimeError('GStreamer playbin is missing. Install gstreamer1.0-plugins-base.')
        self.on_error, self.on_end = on_error, on_end
        bus = self.playbin.get_bus()
        bus.add_signal_watch()
        bus.connect('message', self._message)

    def play(self, prayer, volume):
        self.stop()
        path = sound_path(prayer)
        if not path.is_file():
            raise ValueError('Download the official ezan recordings first.')
        self.playbin.set_property('uri', path.resolve().as_uri())
        self.playbin.set_property('volume', float(volume))
        state = self.playbin.set_state(self.Gst.State.PLAYING)
        if state == self.Gst.StateChangeReturn.FAILURE:
            raise RuntimeError('Audio playback could not start. Check your Ubuntu sound output.')

    def stop(self):
        self.playbin.set_state(self.Gst.State.NULL)

    def set_volume(self, volume):
        self.playbin.set_property('volume', float(volume))

    def _message(self, bus, message):
        if message.type == self.Gst.MessageType.ERROR:
            error, _ = message.parse_error()
            self.stop()
            if self.on_error:
                self.on_error(str(error))
        elif message.type == self.Gst.MessageType.EOS:
            self.stop()
            if self.on_end:
                self.on_end()
