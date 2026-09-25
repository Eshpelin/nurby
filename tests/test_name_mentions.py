"""Conservative transcript name-mention parsing (#255)."""

from services.perception.audio.name_mentions import extract_name_mentions, timing_for_span


def test_direct_address_is_a_candidate():
    mentions = extract_name_mentions("Hey Simon, can you bring that inside?")
    assert [(m["normalized"], m["kind"]) for m in mentions] == [("simon", "direct_address")]


def test_third_person_reference_is_distinct_from_direct_address():
    mentions = extract_name_mentions("Please tell Linda that Simon is here.")
    assert [(m["normalized"], m["kind"]) for m in mentions] == [("linda", "third_person")]


def test_unrelated_sentence_does_not_turn_every_word_into_a_name():
    assert extract_name_mentions("The car is outside and the light is on.") == []


def test_negated_request_is_not_a_name_hypothesis():
    assert extract_name_mentions("Don't tell Simon that I am here.") == []


def test_duplicate_mentions_are_deduplicated_by_context():
    mentions = extract_name_mentions("Hey Simon, wait Simon, can you look?")
    assert [m["normalized"] for m in mentions] == ["simon"]


def test_name_mention_preserves_exact_span_offsets():
    mention = extract_name_mentions("Hey Simon, can you come?")[0]
    assert mention["span"] == "Hey Simon"
    assert (mention["span_start"], mention["span_end"]) == ("0", "9")


def test_timing_for_span_returns_only_overlapping_words():
    text = "Hey Simon, can you come?"
    mention = extract_name_mentions(text)[0]
    words = [
        {"word": "Hey", "start": 0.0, "end": 0.2},
        {"word": "Simon", "start": 0.2, "end": 0.6},
        {"word": "can", "start": 0.7, "end": 0.8},
    ]

    result = timing_for_span(words, text, int(mention["span_start"]), int(mention["span_end"]))

    assert [item["word"] for item in result] == ["Hey", "Simon"]
