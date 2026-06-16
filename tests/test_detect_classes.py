"""Global detection allowlist: the normalize helper that turns the
detect_classes setting into a label set, and the filter semantics applied in
the perception pipeline."""

from shared.app_settings import normalize_class_allowlist, resolve_camera_allowlist


def test_none_and_empty_mean_detect_everything():
    assert normalize_class_allowlist(None) is None
    assert normalize_class_allowlist([]) is None
    assert normalize_class_allowlist("") is None
    assert normalize_class_allowlist(["", "  "]) is None


def test_lowercases_and_dedupes():
    assert normalize_class_allowlist(["Person", "person", "CAT"]) == {"person", "cat"}


def test_accepts_single_string():
    assert normalize_class_allowlist("dog") == {"dog"}


def test_filter_keeps_only_allowed_labels():
    # Mirrors the pipeline filter: keep detections whose lowercased label is in
    # the allowlist; drop everything else.
    allowed = normalize_class_allowlist(["person", "cat", "dog"])
    dets = [
        {"label": "person", "confidence": 0.9},
        {"label": "Cat", "confidence": 0.8},
        {"label": "car", "confidence": 0.95},      # not allowed -> dropped
        {"label": "umbrella", "confidence": 0.7},  # not allowed -> dropped
    ]
    kept = [d for d in dets if str(d.get("label", "")).lower() in allowed]
    assert [d["label"] for d in kept] == ["person", "Cat"]


def test_no_allowlist_keeps_all():
    allowed = normalize_class_allowlist(None)
    dets = [{"label": "car"}, {"label": "boat"}]
    # The pipeline only filters when `allowed` is truthy; None -> everything.
    kept = dets if not allowed else [d for d in dets if d["label"] in allowed]
    assert kept == dets


# ── per-camera override resolution ──

def test_camera_none_inherits_global():
    g = {"person", "cat"}
    assert resolve_camera_allowlist(None, g) == g
    assert resolve_camera_allowlist(None, None) is None


def test_camera_list_overrides_global():
    g = {"person"}
    assert resolve_camera_allowlist(["dog", "Cat"], g) == {"dog", "cat"}


def test_camera_empty_list_means_everything_here():
    # [] is an explicit "detect everything on this camera", ignoring the
    # global restriction (distinct from None = inherit).
    assert resolve_camera_allowlist([], {"person"}) is None
