import pytest

from bodyrig.recovery import BodyprintExtractor, RecoveryError, parse_recovery_result


def frame(ts, shift=0.0):
    return {
        "timestamp_ms": ts,
        "confidence": 0.9,
        "joints": {
            "head": [0.0 + shift, 1.8, 0.0],
            "left_shoulder": [-0.22 + shift, 1.45, 0.0],
            "right_shoulder": [0.22 + shift, 1.45, 0.0],
            "left_hip": [-0.16 + shift, 1.0, 0.0],
            "right_hip": [0.16 + shift, 1.0, 0.0],
            "left_wrist": [-0.55 - shift, 1.15, 0.0],
            "right_wrist": [0.55 + shift, 1.15, 0.0],
            "left_ankle": [-0.12 + shift, 0.0, 0.0],
            "right_ankle": [0.12 + shift, 0.0, 0.0],
        },
    }


def payload(frames):
    return {
        "format": "bodyrig-recovery",
        "version": 1,
        "adapter": "fixture",
        "revision": "fixture-v1",
        "tracks": [{"track_id": "person-1", "frames": frames}],
    }


def test_parse_and_extract_observed_bodyprint():
    result = parse_recovery_result(payload([frame(0), frame(500, 0.08), frame(1000, 0.16)]))
    bodyprint = BodyprintExtractor().extract(result.tracks[0])
    assert bodyprint["format"] == "modelrig-bodyprint"
    assert 0.20 < bodyprint["shape"]["shoulder_to_height"] < 0.30
    assert 0.0 <= bodyprint["motion"]["energy"] <= 1.0
    assert "height_scale" not in bodyprint["shape"]


def test_recovery_rejects_non_finite_joint():
    bad = payload([frame(0), frame(100)])
    bad["tracks"][0]["frames"][1]["joints"]["head"][0] = float("nan")
    with pytest.raises(RecoveryError, match="finite"):
        parse_recovery_result(bad)


def test_recovery_rejects_out_of_order_time():
    with pytest.raises(RecoveryError, match="strictly increasing"):
        parse_recovery_result(payload([frame(100), frame(100)]))


def test_recovery_identity_is_pinned():
    with pytest.raises(RecoveryError, match="identity mismatch"):
        parse_recovery_result(payload([frame(0), frame(100)]), expected_adapter="hmr2")
