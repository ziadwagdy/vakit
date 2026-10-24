#!/usr/bin/python3
"""Decode all five local MP3s to a silent sink; never play sound during checks."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst
from ezan.core import PRAYERS
from ezan.audio import sound_path

Gst.init(None)
for prayer in PRAYERS:
    player = Gst.ElementFactory.make('playbin')
    sink = Gst.ElementFactory.make('fakesink')
    sink.set_property('sync', False)
    player.set_property('audio-sink', sink)
    player.set_property('video-sink', Gst.ElementFactory.make('fakesink'))
    player.set_property('uri', sound_path(prayer).resolve().as_uri())
    player.set_state(Gst.State.PLAYING)
    message = player.get_bus().timed_pop_filtered(30 * Gst.SECOND, Gst.MessageType.EOS | Gst.MessageType.ERROR)
    try:
        assert message is not None, f'{prayer}: decoder timeout'
        if message.type == Gst.MessageType.ERROR:
            raise RuntimeError(str(message.parse_error()))
        print(prayer + ': full MP3 decoded successfully (silent verification)')
    finally:
        player.set_state(Gst.State.NULL)
