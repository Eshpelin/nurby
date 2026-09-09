"""Camera personas: a bundle of settings for a common use-case.

One source of truth for both clients. These used to live only in
``frontend/src/lib/camera-personas.ts``; a second copy on mobile would have
drifted the first time someone tuned one on web. Served by
``GET /api/cameras/personas``.

A persona is applied by PATCHing its ``patch`` onto the camera. Two
fields need care on the client side:

- ``audio_*`` and ``transcript_retention_days`` are not on ``CameraUpdate``;
  they go through ``PATCH /api/audio/cameras/{id}/audio``, which also
  writes the privacy audit row. Clients split the patch accordingly.
- ``icon_path`` is an SVG path for a 24x24 icon, for clients that draw one.
- Everything in a persona is a starting point. The user can change any
  field afterwards and nothing here is required.
"""

from __future__ import annotations

from typing import Any

# Fields that must be written through the audio endpoint, not the camera
# PATCH. Exposed so a client can split a patch without guessing.
AUDIO_FIELDS: frozenset[str] = frozenset({
    "audio_capture_enabled",
    "audio_transcribe_enabled",
    "audio_store_raw",
    "audio_retention_days",
    "transcript_retention_days",
})

CAMERA_PERSONAS: list[dict[str, Any]] = [
    {
        "id": "front-door",
        "label": "Front Door",
        "hint": "Person and package detection. Records when someone arrives. Event recap when a visit closes.",
        "icon_path": "M3 21h18M5 21V7l7-4 7 4v14M9 21V12h6v9",
        "patch": {
            "detect_objects": True,
            "detect_faces": True,
            "scene_mode": "outdoor",
            "object_confidence": 0.4,
            "detection_models": [
                {
                    "model": "yolov8x-worldv2.pt",
                    "confidence": 0.4,
                    "enabled": True,
                    "label_filter": []
                }
            ],
            "yolo_world_prompts": [
                "person",
                "package",
                "delivery driver",
                "mail truck",
                "bicycle",
                "stroller",
                "dog",
                "cat",
                "weapon"
            ],
            "vlm_trigger": "on_object",
            "vlm_trigger_objects": [
                "person",
                "package",
                "delivery driver"
            ],
            "vlm_max_tokens": 200,
            "recording_mode": "on_object",
            "recording_trigger_objects": [
                "person"
            ],
            "recording_clip_pre": 5,
            "recording_clip_post": 15,
            "retention_mode": "time",
            "retention_days": 30,
            "summary_mode": "event",
            "summary_event_quiet_seconds": 60,
            "summary_event_trigger_objects": [
                "person"
            ],
            "summary_event_min_duration_seconds": 5,
            "audio_capture_enabled": True,
            "audio_transcribe_enabled": True,
            "conversation_gap_seconds": 30,
            "conversation_summary_enabled": True,
            "privacy_zone_targets": [
                "window"
            ]
        }
    },
    {
        "id": "baby-cam",
        "label": "Baby Cam",
        "hint": "Continuous recording. Audio capture for cries. Periodic recap of the room.",
        "icon_path": "M12 3a4 4 0 0 1 4 4v1a4 4 0 0 1-8 0V7a4 4 0 0 1 4-4zM6 21v-2a6 6 0 0 1 12 0v2",
        "patch": {
            "detect_objects": True,
            "detect_faces": True,
            "scene_mode": "indoor",
            "object_confidence": 0.3,
            "detection_models": [
                {
                    "model": "yolov8n.pt",
                    "confidence": 0.3,
                    "enabled": True,
                    "label_filter": []
                }
            ],
            "vlm_trigger": "always",
            "vlm_max_tokens": 200,
            "recording_mode": "always",
            "recording_clip_pre": 0,
            "recording_clip_post": 0,
            "retention_mode": "time",
            "retention_days": 7,
            "audio_capture_enabled": True,
            "audio_transcribe_enabled": True,
            "audio_store_raw": True,
            "audio_retention_days": 7,
            "transcript_retention_days": 30,
            "summary_mode": "periodic",
            "summary_period_seconds": 1800,
            "summary_event_trigger_objects": [
                "person"
            ],
            "conversation_gap_seconds": 45,
            "conversation_summary_enabled": True
        }
    },
    {
        "id": "pet-cam",
        "label": "Pet Cam",
        "hint": "Cat and dog triggers. No face recognition. Event recap per pet visit.",
        "icon_path": "M4 8a3 3 0 1 1 3 3M17 8a3 3 0 1 0-3 3M9 13a3 3 0 1 1-3 3M15 13a3 3 0 1 0 3 3M12 14c-3 0-5 2-5 4s2 3 5 3 5-1 5-3-2-4-5-4z",
        "patch": {
            "detect_objects": True,
            "detect_faces": False,
            "scene_mode": "indoor",
            "object_confidence": 0.3,
            "detection_models": [
                {
                    "model": "yolov8n.pt",
                    "confidence": 0.3,
                    "enabled": True,
                    "label_filter": []
                }
            ],
            "vlm_trigger": "on_object",
            "vlm_trigger_objects": [
                "cat",
                "dog",
                "bird"
            ],
            "vlm_max_tokens": 150,
            "recording_mode": "on_object",
            "recording_trigger_objects": [
                "cat",
                "dog"
            ],
            "recording_clip_pre": 3,
            "recording_clip_post": 10,
            "retention_mode": "time",
            "retention_days": 14,
            "summary_mode": "event",
            "summary_event_quiet_seconds": 90,
            "summary_event_trigger_objects": [
                "cat",
                "dog"
            ],
            "summary_event_min_duration_seconds": 3,
            "audio_capture_enabled": False,
            "audio_transcribe_enabled": False,
            "conversation_summary_enabled": False
        }
    },
    {
        "id": "wildlife",
        "label": "Wildlife",
        "hint": "Animal detection (deer, bear, coyote, bird). Outdoor scene mode. Generous storage.",
        "icon_path": "M4 12c0-4 3-7 8-7s8 3 8 7-3 8-8 8c-3 0-5-1-7-3M9 8l-2-3M15 8l2-3",
        "patch": {
            "detect_objects": True,
            "detect_faces": False,
            "scene_mode": "outdoor",
            "object_confidence": 0.35,
            "detection_models": [
                {
                    "model": "yolov8s-oiv7.pt",
                    "confidence": 0.35,
                    "enabled": True,
                    "label_filter": []
                }
            ],
            "vlm_trigger": "on_object",
            "vlm_trigger_objects": [
                "bird",
                "cat",
                "dog",
                "deer",
                "bear",
                "fox",
                "raccoon",
                "rabbit",
                "squirrel"
            ],
            "vlm_max_tokens": 200,
            "recording_mode": "on_object",
            "recording_trigger_objects": [
                "bird",
                "cat",
                "dog",
                "deer",
                "bear",
                "fox",
                "raccoon"
            ],
            "recording_clip_pre": 5,
            "recording_clip_post": 15,
            "retention_mode": "size",
            "retention_gb": 100,
            "summary_mode": "event",
            "summary_event_quiet_seconds": 120,
            "summary_event_trigger_objects": [
                "deer",
                "bear",
                "fox",
                "coyote",
                "raccoon"
            ],
            "summary_event_min_duration_seconds": 5,
            "audio_capture_enabled": False,
            "audio_transcribe_enabled": False,
            "conversation_summary_enabled": False
        }
    },
    {
        "id": "driveway",
        "label": "Driveway",
        "hint": "Vehicle and plate detection. Recording on car arrival. Outdoor.",
        "icon_path": "M3 17h18M5 17l1-5h12l1 5M7 12V8h10v4M8 17v3M16 17v3",
        "patch": {
            "detect_objects": True,
            "detect_faces": False,
            "scene_mode": "outdoor",
            "object_confidence": 0.4,
            "detection_models": [
                {
                    "model": "yolov8s.pt",
                    "confidence": 0.4,
                    "enabled": True,
                    "label_filter": []
                }
            ],
            "vlm_trigger": "on_object",
            "vlm_trigger_objects": [
                "car",
                "truck",
                "motorcycle",
                "bus",
                "person"
            ],
            "vlm_max_tokens": 200,
            "recording_mode": "on_object",
            "recording_trigger_objects": [
                "car",
                "truck",
                "motorcycle"
            ],
            "recording_clip_pre": 5,
            "recording_clip_post": 30,
            "retention_mode": "time",
            "retention_days": 30,
            "summary_mode": "event",
            "summary_event_quiet_seconds": 90,
            "summary_event_trigger_objects": [
                "car",
                "truck",
                "person"
            ],
            "summary_event_min_duration_seconds": 5,
            "audio_capture_enabled": False,
            "audio_transcribe_enabled": False,
            "conversation_summary_enabled": False
        }
    },
    {
        "id": "traffic",
        "label": "Traffic / parking",
        "hint": "Vehicles, plates, lanes, and parking spots. For monitoring a street, driveway, or garage. Outdoor.",
        "icon_path": "M5 11l1.5-4.5A2 2 0 018.4 5h7.2a2 2 0 011.9 1.5L19 11m-14 0h14m-14 0v6m14-6v6M7 17v2m10-2v2M7 14h.01M17 14h.01",
        "patch": {
            "detect_objects": True,
            "detect_faces": False,
            "scene_mode": "outdoor",
            "object_confidence": 0.4,
            "detection_models": [
                {
                    "model": "yolov8s.pt",
                    "confidence": 0.4,
                    "enabled": True,
                    "label_filter": []
                }
            ],
            "vlm_trigger": "on_object",
            "vlm_trigger_objects": [
                "car",
                "truck",
                "motorcycle",
                "bus",
                "van"
            ],
            "vlm_max_tokens": 200,
            "recording_mode": "on_object",
            "recording_trigger_objects": [
                "car",
                "truck",
                "motorcycle",
                "bus",
                "van"
            ],
            "recording_clip_pre": 4,
            "recording_clip_post": 20,
            "retention_mode": "time",
            "retention_days": 30,
            "summary_mode": "event",
            "summary_event_quiet_seconds": 90,
            "summary_event_trigger_objects": [
                "car",
                "truck",
                "motorcycle",
                "bus",
                "van"
            ],
            "summary_event_min_duration_seconds": 4,
            "audio_capture_enabled": False,
            "audio_transcribe_enabled": False,
            "conversation_summary_enabled": False
        }
    }
]


def split_patch(patch: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """(camera_fields, audio_fields). Pure."""
    camera = {k: v for k, v in patch.items() if k not in AUDIO_FIELDS}
    audio = {k: v for k, v in patch.items() if k in AUDIO_FIELDS}
    return camera, audio
