from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_compose_keeps_webrtc_ice_loopback_by_default():
    compose = (ROOT / "docker-compose.yml").read_text()
    assert '${NURBY_WEBRTC_UDP_BIND:-127.0.0.1}:8189:8189/udp' in compose
    assert 'MTX_WEBRTCADDITIONALHOSTS: "${NURBY_WEBRTC_ADDITIONAL_HOSTS:-127.0.0.1}"' in compose


def test_remote_access_docs_call_out_explicit_ice_override():
    docs = (ROOT / "docs/remote-access-design.md").read_text()
    assert "NURBY_WEBRTC_UDP_BIND" in docs
    assert "camera ACL" in docs
