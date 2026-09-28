"""Conservative transcript name-mention parsing (#255/#261)."""

from types import SimpleNamespace

from services.perception.audio.name_mentions import (
    _visual_subjects,
    extract_name_mentions,
    timing_for_span,
)


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
    assert mention["name_span"] == "Simon"
    assert (mention["name_span_start"], mention["name_span_end"]) == ("4", "9")


def test_name_timing_can_be_scoped_to_the_name_without_context_words():
    text = "Hey Simon, can you come?"
    mention = extract_name_mentions(text)[0]
    words = [
        {"word": "Hey", "start": 0.0, "end": 0.2},
        {"word": "Simon", "start": 0.2, "end": 0.6},
        {"word": "can", "start": 0.7, "end": 0.8},
    ]

    result = timing_for_span(
        words, text, int(mention["name_span_start"]), int(mention["name_span_end"])
    )

    assert [item["word"] for item in result] == ["Simon"]


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


def test_visual_subjects_include_body_only_clusters_without_picking_a_winner():
    rows = [
        SimpleNamespace(
            id="obs-1",
            person_detections={
                "faces": [{"cluster_id": "face-1"}],
                "bodies": [{"body_cluster_id": "body-1"}, {"body_cluster_id": "body-2"}],
            },
        ),
        SimpleNamespace(
            id="obs-2",
            person_detections={"bodies": [{"body_cluster_id": "body-1"}]},
        ),
    ]

    subjects = _visual_subjects(rows, {})

    assert {(item["kind"], item["key"]) for item in subjects} == {
        ("cluster", "face-1"),
        ("cluster", "body-1"),
        ("cluster", "body-2"),
    }
    body_one = next(item for item in subjects if item["key"] == "body-1")
    assert body_one["observation_ids"] == ["obs-1", "obs-2"]
