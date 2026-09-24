from __future__ import annotations

import uuid

from services.perception.audio.capture import AudioCapture
from services.perception.audio.router import CameraAudioRouter


def test_local_demo_audio_sources_are_paced():
    router = CameraAudioRouter(
        uuid.uuid4(), "/demo/qa_pipeline.mp4", "mock", {}, lambda *args: None
    )
    capture = router._capture
    assert capture.realtime is True


def test_network_audio_sources_are_not_artificially_paced():
    router = CameraAudioRouter(
        uuid.uuid4(), "rtsp://camera.example/live", "mock", {}, lambda *args: None
    )
    capture = router._capture
    assert capture.realtime is False
