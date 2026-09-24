"""Conservative transcript name-mention parsing (#255)."""

from services.perception.audio.name_mentions import extract_name_mentions


def test_direct_address_is_a_candidate():
    mentions = extract_name_mentions("Hey Simon, can you bring that inside?")
    assert [(m["normalized"], m["kind"]) for m in mentions] == [("simon", "direct_address")]


def test_third_person_reference_is_distinct_from_direct_address():
    mentions = extract_name_mentions("Please tell Linda that Simon is here.")
    assert [(m["normalized"], m["kind"]) for m in mentions] == [("linda", "third_person")]


def test_unrelated_sentence_does_not_turn_every_word_into_a_name():
    assert extract_name_mentions("The car is outside and the light is on.") == []


def test_duplicate_mentions_are_deduplicated_by_context():
    mentions = extract_name_mentions("Hey Simon, wait Simon, can you look?")
    assert [m["normalized"] for m in mentions] == ["simon"]
