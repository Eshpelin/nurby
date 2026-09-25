from services.api.routes.system import _percentile
import pytest


def test_percentile_interpolates_and_handles_empty():
    assert _percentile([], 0.5) is None
    assert _percentile([4.0], 0.95) == 4.0
    assert _percentile([1.0, 2.0, 10.0, 20.0], 0.5) == 6.0
    assert _percentile([1.0, 2.0, 10.0, 20.0], 0.95) == pytest.approx(18.5)
