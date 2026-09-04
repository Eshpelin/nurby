"""Speaker transports: the drivers that get audio into a camera (#155).

One protocol, several implementations, chosen per camera from what the
probe found. The registry mirrors ``services/voice/tts.py`` and
``services/perception/audio/stt.py``: factories keyed by kind, heavy
imports inside the factory bodies, so adding a vendor is one file and one
line rather than a change to the action.

Nurby has to work with whatever cameras a household already owns, so
breadth matters more here than depth on any one vendor. A transport that
cannot work reports that clearly instead of failing at the socket.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable, Protocol

logger = logging.getLogger("nurby.voice.transport")


class SpeakerTransport(Protocol):
    kind: str
    name: str

    async def speak(
        self, camera, payload: bytes, *, codec: str, sample_rate: int,
        volume: int = 70, timeout: float = 15.0,
    ) -> None:
        """Play ``payload`` through the camera. Raises TransportError."""


class TransportError(RuntimeError):
    """A transport could not deliver audio. Carries a human sentence."""


class TransportUnsupported(TransportError):
    """This camera cannot be spoken through by this driver.

    Distinct from a delivery failure on purpose: unsupported is a
    permanent fact worth recording against the camera, while a failure is
    worth retrying later.
    """


_FACTORIES: dict[str, Callable[..., Awaitable[SpeakerTransport]]] = {}


def register_factory(kind: str, factory: Callable[..., Awaitable[SpeakerTransport]]) -> None:
    _FACTORIES[kind] = factory


async def build_transport(kind: str, **kwargs) -> SpeakerTransport:
    if kind not in _FACTORIES:
        raise TransportUnsupported(f"no speaker transport for {kind!r}")
    return await _FACTORIES[kind](**kwargs)


def known_kinds() -> list[str]:
    return sorted(_FACTORIES.keys())


async def _onvif_factory() -> SpeakerTransport:
    from services.voice.transport.onvif_backchannel import OnvifBackchannelTransport

    return OnvifBackchannelTransport()


async def _hikvision_factory() -> SpeakerTransport:
    from services.voice.transport.vendor_http import HikvisionTransport

    return HikvisionTransport()


async def _dahua_factory() -> SpeakerTransport:
    from services.voice.transport.vendor_http import DahuaTransport

    return DahuaTransport()


async def _device_factory() -> SpeakerTransport:
    from services.voice.transport.http_device import HttpDeviceTransport

    return HttpDeviceTransport()


async def _mock_factory() -> SpeakerTransport:
    from services.voice.transport.mock import MockTransport

    return MockTransport()


register_factory("onvif_backchannel", _onvif_factory)
register_factory("hikvision", _hikvision_factory)
register_factory("dahua", _dahua_factory)
register_factory("http_device", _device_factory)
async def _tapo_factory() -> SpeakerTransport:
    from services.voice.transport.tapo import TapoTransport

    return TapoTransport()


register_factory("mock", _mock_factory)
register_factory("tapo", _tapo_factory)
