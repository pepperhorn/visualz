"""T2 seam: nonblocking audio worker; neutral until capture is implemented."""

from types import MappingProxyType


class Analyser:
    """Analyser(store): reads settings.audio; start/close own the capture thread.

    snapshot() returns immutable levels, spectrum, beat and stereo waveforms in
    0..1 (waveforms -1..1). devices() returns [{id,name,channels}]. Never blocks GL.
    """

    def __init__(self, store):
        self.store = store

    def start(self):
        pass

    def snapshot(self):
        return MappingProxyType(
            dict(
                level=0.0,
                bass=0.0,
                mid=0.0,
                treble=0.0,
                beat=False,
                left=0.0,
                right=0.0,
                spectrum=(0.0,) * 64,
                waveform_left=(0.0,) * 256,
                waveform_right=(0.0,) * 256,
            )
        )

    def devices(self):
        return []

    def close(self):
        pass
