"""TTS abstraction and camera-ready audio encoding (issue #154).

Text in, correctly encoded audio out, with no camera involved. The codec
work matters more than it looks: cameras want G.711 at 8 kHz and Piper
emits 16-bit PCM at 22.05 kHz, so every utterance crosses this code.
"""

import array
import bisect
import math
import struct

import pytest

from services.voice.audio import (
    TELEPHONY_SAMPLE_RATE,
    decode_alaw,
    decode_mulaw,
    encode_alaw,
    encode_mulaw,
    for_backchannel,
    resample,
    to_mono,
)
from services.voice.providers.piper_provider import PiperProvider, parse_wav
from services.voice.tts import (
    MAX_TEXT_CHARS,
    SynthesisCache,
    build_provider,
    cache_key,
    known_kinds,
    normalize_text,
    synthesize,
)
from services.voice.types import AudioClip


def _sine(seconds=0.5, rate=22050, hz=440, amplitude=20000, channels=1):
    frames = int(rate * seconds)
    samples = array.array("h")
    for i in range(frames):
        value = int(amplitude * math.sin(2 * math.pi * hz * i / rate))
        samples.extend([value] * channels)
    return AudioClip(samples.tobytes(), rate, channels, 2)


# ---- clip arithmetic -----------------------------------------------------


def test_duration_is_derived_from_the_pcm():
    clip = AudioClip(b"\x00\x00" * 8000, 8000)
    assert clip.frame_count == 8000
    assert clip.duration_seconds == 1.0


def test_a_stereo_clip_counts_frames_not_samples():
    clip = AudioClip(b"\x00\x00" * 16000, 8000, channels=2)
    assert clip.frame_count == 8000
    assert clip.duration_seconds == 1.0


# ---- resampling ----------------------------------------------------------


def test_resampling_preserves_duration():
    """The property that matters: a two-second announcement must still
    take two seconds after conversion, or the transport's timing is
    wrong."""
    clip = _sine(seconds=2.0)
    out = resample(clip, TELEPHONY_SAMPLE_RATE)

    assert out.sample_rate == TELEPHONY_SAMPLE_RATE
    assert abs(out.duration_seconds - 2.0) < 0.01


def test_resampling_to_the_same_rate_is_a_no_op():
    clip = _sine(rate=8000)
    assert resample(clip, 8000) is clip


def test_resampling_an_empty_clip_does_not_crash():
    out = resample(AudioClip(b"", 22050), 8000)
    assert out.pcm == b""
    assert out.sample_rate == 8000


def test_a_zero_target_rate_is_rejected():
    with pytest.raises(ValueError):
        resample(_sine(), 0)


def test_upsampling_works_too():
    out = resample(_sine(seconds=0.2, rate=8000), 16000)
    assert abs(out.duration_seconds - 0.2) < 0.01


# ---- channels ------------------------------------------------------------


def test_stereo_is_mixed_to_mono():
    clip = _sine(channels=2)
    out = to_mono(clip)

    assert out.channels == 1
    assert out.frame_count == clip.frame_count


def test_mono_passes_through_untouched():
    clip = _sine()
    assert to_mono(clip) is clip


# ---- G.711 ---------------------------------------------------------------


def test_mulaw_is_one_byte_per_sample():
    clip = resample(_sine(seconds=1.0), TELEPHONY_SAMPLE_RATE)
    assert len(encode_mulaw(clip)) == clip.frame_count


def test_mulaw_round_trips_within_companding_error():
    """8-bit companding is lossy by construction. A couple of percent is
    correct; an order of magnitude more would mean the tables are wrong."""
    clip = resample(_sine(seconds=0.5), TELEPHONY_SAMPLE_RATE)
    back = decode_mulaw(encode_mulaw(clip))

    original = array.array("h")
    original.frombytes(clip.pcm)
    restored = array.array("h")
    restored.frombytes(back.pcm)

    worst = max(abs(a - b) for a, b in zip(original, restored)) / 32768
    assert worst < 0.05


@pytest.mark.parametrize("codec", ["mulaw", "alaw"])
def test_silence_encodes_to_a_code_that_decodes_back_to_silence(codec):
    """Asserted as a property rather than as a byte value on purpose.
    mu-law has TWO codes decoding to exactly zero (0x7F and 0xFF), both
    equally correct, and pinning whichever one this implementation
    happens to choose would be testing an accident."""
    encode = encode_mulaw if codec == "mulaw" else encode_alaw
    decode = decode_mulaw if codec == "mulaw" else decode_alaw

    encoded = encode(AudioClip(b"\x00\x00" * 100, TELEPHONY_SAMPLE_RATE))
    restored = array.array("h")
    restored.frombytes(decode(encoded).pcm)

    assert len(set(encoded)) == 1  # one steady code, not chatter

    # mu-law has codes for exact zero; A-law does not. Its quantizer is
    # mid-rise near the origin, so the quietest thing it can represent is
    # +/-8 out of 32768, about -72 dBFS. Asserting "exactly zero" would
    # be asserting something A-law cannot do.
    assert all(abs(sample) <= 8 for sample in restored)


def test_extremes_do_not_wrap_around():
    """Clipping has to saturate. Wrapping turns a loud sound into a loud
    sound of the opposite sign, which is audible as a crack."""
    loud = array.array("h", [32767, -32768, 32767, -32768])
    encoded = encode_mulaw(AudioClip(loud.tobytes(), 8000))
    restored = array.array("h")
    restored.frombytes(decode_mulaw(encoded).pcm)

    assert restored[0] > 30000 and restored[1] < -30000


def test_alaw_is_also_one_byte_per_sample():
    """Some cameras offer only A-law, so both exist rather than assuming
    a region."""
    clip = resample(_sine(seconds=0.2), TELEPHONY_SAMPLE_RATE)
    assert len(encode_alaw(clip)) == clip.frame_count


def test_alaw_round_trips_within_companding_error():
    clip = resample(_sine(seconds=0.3), TELEPHONY_SAMPLE_RATE)
    back = decode_alaw(encode_alaw(clip))

    original = array.array("h")
    original.frombytes(clip.pcm)
    restored = array.array("h")
    restored.frombytes(back.pcm)

    worst = max(abs(a - b) for a, b in zip(original, restored)) / 32768
    assert worst < 0.05


@pytest.mark.parametrize("codec", ["mulaw", "alaw"])
def test_every_input_maps_to_the_nearest_available_code(codec):
    """The property the encoders are built on, checked exhaustively over
    all 65536 possible samples rather than over a signal that happens to
    exercise the easy cases.

    This test exists because the first version of this module was a
    hand-transcribed ITU encoder. It round-tripped fine and was wrong on
    1.3% of inputs, at segment boundaries a sine sweep never visits.
    Deriving the encoder from the decoder makes the property provable, so
    it is proven here rather than assumed.
    """
    encode = encode_mulaw if codec == "mulaw" else encode_alaw
    decode = decode_mulaw if codec == "mulaw" else decode_alaw

    levels = array.array("h")
    levels.frombytes(decode(bytes(range(256))).pcm)

    everything = array.array("h", range(-32768, 32768))
    encoded = encode(AudioClip(everything.tobytes(), 8000))

    ladder = sorted(levels)
    for value in range(-32768, 32768):
        chosen = abs(value - levels[encoded[value + 32768]])
        position = bisect.bisect_left(ladder, value)
        candidates = ladder[max(0, position - 1):position + 1] or [ladder[0]]
        assert chosen == min(abs(value - c) for c in candidates)


# ---- the whole conversion ------------------------------------------------


def test_for_backchannel_produces_telephony_audio():
    """The end-to-end shape a camera expects: mu-law, 8 kHz, mono."""
    payload = for_backchannel(_sine(seconds=1.0, channels=2))
    assert len(payload) == TELEPHONY_SAMPLE_RATE


def test_for_backchannel_supports_the_codecs_cameras_offer():
    clip = _sine(seconds=0.1)
    assert len(for_backchannel(clip, "pcma")) == 800
    assert len(for_backchannel(clip, "l16")) == 1600  # 16-bit, so two bytes


def test_an_unknown_codec_is_refused_loudly():
    """Silently sending the wrong bytes to a speaker is worse than
    failing."""
    with pytest.raises(ValueError):
        for_backchannel(_sine(), "opus")


# ---- text guarding -------------------------------------------------------


def test_whitespace_is_collapsed():
    assert normalize_text("  please   step \n back ") == "please step back"


def test_empty_text_is_not_speakable():
    assert normalize_text("   \n ") == ""
    assert normalize_text(None) == ""


def test_long_text_is_capped_at_a_word_boundary():
    """A runaway template that interpolated a whole VLM description would
    otherwise hold the speaker for minutes."""
    out = normalize_text("word " * 400)
    assert len(out) <= MAX_TEXT_CHARS
    assert not out.endswith("wor")


@pytest.mark.asyncio
async def test_nothing_speakable_synthesizes_nothing():
    provider = await build_provider("mock")
    assert await synthesize(provider, "   ") is None


# ---- caching -------------------------------------------------------------


def test_the_cache_key_separates_voices():
    assert cache_key("hello", "amy") != cache_key("hello", "ryan")
    assert cache_key("hello", "amy") == cache_key("hello", "amy")


def test_the_cache_evicts_least_recently_used():
    cache = SynthesisCache(capacity=2)
    clip = AudioClip(b"\x00\x00", 8000)
    cache.put("a", clip)
    cache.put("b", clip)
    cache.get("a")          # a is now the most recent
    cache.put("c", clip)    # evicts b

    assert cache.get("a") is not None
    assert cache.get("b") is None
    assert len(cache) == 2


@pytest.mark.asyncio
async def test_a_repeated_announcement_is_synthesized_once():
    """The reason the cache exists: an announcement repeats verbatim
    thousands of times over a camera's life."""
    provider = await build_provider("mock")
    calls = {"n": 0}
    original = provider.synthesize

    async def counting(text, voice=None):
        calls["n"] += 1
        return await original(text, voice)

    provider.synthesize = counting

    from services.voice import tts as tts_mod
    tts_mod.cache().clear()

    for _ in range(5):
        await synthesize(provider, "Please step back.")

    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_caching_can_be_bypassed():
    provider = await build_provider("mock")
    from services.voice import tts as tts_mod
    tts_mod.cache().clear()

    await synthesize(provider, "x", use_cache=False)
    assert len(tts_mod.cache()) == 0


# ---- the registry --------------------------------------------------------


def test_both_backends_are_registered():
    assert "piper" in known_kinds()
    assert "mock" in known_kinds()


@pytest.mark.asyncio
async def test_an_unknown_kind_is_a_keyerror():
    with pytest.raises(KeyError):
        await build_provider("nope")


@pytest.mark.asyncio
async def test_the_mock_scales_its_duration_with_the_text():
    """So a test asserting the speaker was busy for about this long is
    exercising something real."""
    provider = await build_provider("mock")
    short = await provider.synthesize("hi")
    long = await provider.synthesize("hi " * 50)

    assert long.duration_seconds > short.duration_seconds


# ---- piper ---------------------------------------------------------------


def test_piper_reports_absence_rather_than_crashing():
    """A household without Piper should get a clear "voice unavailable",
    not a stack trace at rule-fire time."""
    assert PiperProvider(binary="definitely-not-installed").available() is False


@pytest.mark.asyncio
async def test_piper_raises_a_typed_error_when_missing():
    from services.voice.providers.piper_provider import PiperUnavailable

    provider = PiperProvider(binary="definitely-not-installed")
    with pytest.raises(PiperUnavailable):
        await provider.synthesize("hello")


def _wav(pcm: bytes, rate=22050, channels=1, bits=16):
    block = channels * bits // 8
    header = b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVE"
    header += b"fmt " + struct.pack(
        "<IHHIIHH", 16, 1, channels, rate, rate * block, block, bits
    )
    header += b"data" + struct.pack("<I", len(pcm))
    return header + pcm


def test_piper_wav_output_is_parsed():
    pcm = b"\x01\x02" * 100
    clip = parse_wav(_wav(pcm))

    assert clip.pcm == pcm
    assert clip.sample_rate == 22050
    assert clip.channels == 1


def test_a_wav_with_extra_chunks_still_parses():
    """Real encoders interleave LIST and fact chunks; a reader that
    assumed a fixed 44-byte header would break on them."""
    pcm = b"\x01\x02" * 10
    body = b"RIFF" + struct.pack("<I", 0) + b"WAVE"
    body += b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, 8000, 16000, 2, 16)
    body += b"LIST" + struct.pack("<I", 4) + b"INFO"
    body += b"data" + struct.pack("<I", len(pcm)) + pcm

    assert parse_wav(body).pcm == pcm


def test_a_non_wav_payload_is_rejected():
    with pytest.raises(ValueError):
        parse_wav(b"this is not audio at all, not even close")


def test_non_16_bit_audio_is_rejected_rather_than_misread():
    with pytest.raises(ValueError):
        parse_wav(_wav(b"\x00" * 40, bits=8))
