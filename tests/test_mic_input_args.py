"""The mic publisher's declared input format, mapped to ffmpeg flags.

A wrong answer here does not fail loudly. ffmpeg happily decodes raw PCM
at the wrong rate into chipmunk audio, and the STT path then confidently
transcribes it. So the mapping is pure and pinned.
"""
import pytest

from services.api.ws import mic_input_args


def test_browser_default_probes_the_container():
    assert mic_input_args(None, None, None) == ()
    assert mic_input_args("container", None, None) == ()


def test_pcm_defaults_to_16k_mono():
    assert mic_input_args("pcm", None, None) == ("-f", "s16le", "-ar", "16000", "-ac", "1")


def test_pcm_carries_rate_and_channels():
    assert mic_input_args("pcm", 48000, 2) == ("-f", "s16le", "-ar", "48000", "-ac", "2")


@pytest.mark.parametrize("rate", [0, 11025, 96000, -1])
def test_pcm_rejects_rates_ffmpeg_would_resample_wrongly(rate):
    with pytest.raises(ValueError):
        mic_input_args("pcm", rate, 1)


@pytest.mark.parametrize("channels", [0, 3, 6])
def test_pcm_rejects_odd_channel_counts(channels):
    with pytest.raises(ValueError):
        mic_input_args("pcm", 16000, channels)


def test_unknown_format_is_refused_not_guessed():
    with pytest.raises(ValueError):
        mic_input_args("aac", None, None)


def test_rate_and_channels_are_ignored_for_container_input():
    # A browser sending rate=48000 on a webm stream must not get s16le.
    assert mic_input_args(None, 48000, 2) == ()
