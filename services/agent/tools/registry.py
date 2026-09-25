"""The tool registry and the per-provider dialect adapters.

Split out of the single ``tools.py`` module; see that package's
``__init__`` for the public surface.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from services.agent.tools.activity import (
    _SUMMARIZE_ACTIVITY_SCHEMA,
    summarize_activity,
)
from services.agent.tools.analysis import (
    _ANALYZE_CLIP_SCHEMA,
    _ANALYZE_FRAME_SCHEMA,
    _SUMMARIZE_WINDOW_SCHEMA,
    analyze_clip,
    analyze_frame,
    summarize_window,
)
from services.agent.tools.household import (
    _GET_CAMERA_LAYOUT_SCHEMA,
    _GET_HOUSEHOLD_SNAPSHOT_SCHEMA,
    get_camera_layout,
    get_household_snapshot,
)
from services.agent.tools.lookups import (
    _GET_DAILY_DIGEST_SCHEMA,
    _GET_INCIDENTS_SCHEMA,
    _GET_VEHICLES_SCHEMA,
    _LIST_RULES_SCHEMA,
    get_daily_digest,
    get_incidents,
    get_vehicles,
    list_rules,
)
from services.agent.tools.observations import (
    _GET_JOURNEYS_SCHEMA,
    _QUERY_OBSERVATIONS_SCHEMA,
    get_journeys,
    query_observations,
)
from services.agent.tools.relationships import (
    _GET_ASSOCIATIONS_SCHEMA,
    _GET_HOUSEHOLD_FACTS_SCHEMA,
    _QUERY_RELATIONSHIPS_SCHEMA,
    get_associations,
    get_household_facts,
    query_relationships,
)
from services.agent.tools.setup_tools import (
    _DRAFT_RULE_SCHEMA,
    _GET_RULE_SCHEMA_SCHEMA,
    _REMEMBER_SCHEMA,
    _RUN_DOCTOR_SCHEMA,
    _SUGGEST_RULE_SCHEMA,
    _TEST_CAMERA_CONNECTION_SCHEMA,
    draft_rule,
    get_rule_schema,
    remember,
    run_doctor,
    suggest_rule,
    test_camera_connection,
)
from services.agent.tools.sightings import (
    _GET_EVENTS_SCHEMA,
    _GET_LAST_SIGHTINGS_SCHEMA,
    get_events,
    get_last_sightings,
)
from services.agent.tools.voice import (
    _SPEAK_ON_CAMERA_SCHEMA,
    speak_on_camera,
)

# A tool callable: takes ``ctx`` plus keyword params, returns a dict.
ToolFn = Callable[..., Awaitable[dict]]


TOOL_REGISTRY: list[dict[str, Any]] = [
    {
        "name": "query_observations",
        "description": (
            "Semantic + filter search over indexed camera observations. "
            "Cheap. Each result row carries an observation_id, a "
            "timestamp, a thumbnail_url, the VLM description, and the "
            "raw detections. WINDOW. Defaults to the last 24h. If a "
            "question implies older footage, set hours explicitly (168 "
            "= 7 days, 720 = 30 days). If your default-window query "
            "returns zero rows for an entity that probably exists, RE-"
            "QUERY with hours=168 then 720 before concluding it wasn't "
            "seen. Use get_last_sightings as a cheaper alternative when "
            "you only need the most recent timestamp per entity."
        ),
        "input_schema": _QUERY_OBSERVATIONS_SCHEMA,
        "fn": query_observations,
        "side_effect": "read",
        "cost_class": "cheap",
    },
    {
        "name": "get_journeys",
        "description": (
            "Cross-camera Person sighting sessions. A Journey ties one "
            "Person's appearances across one or more cameras into a "
            "single timeline row with started_at + last_seen_at + the "
            "camera path. Best tool for 'when was Aisha here?', 'where "
            "did Dad go after the kitchen?', 'is anyone still around?'. "
            "WINDOW. Defaults to last 24h. Widen via hours=168 or 720 "
            "for older context. Returns disambiguation when person_name "
            "matches more than one Person. Cheap."
        ),
        "input_schema": _GET_JOURNEYS_SCHEMA,
        "fn": get_journeys,
        "side_effect": "read",
        "cost_class": "cheap",
    },
    {
        "name": "get_camera_layout",
        "description": (
            "Static camera inventory. Returns id, name, inferred role "
            "(entry, kitchen, garage, outdoor, nursery, living, other), "
            "scene_mode (indoor/outdoor), online status, and timezone. "
            "Use when you need to know which camera covers which area. "
            "Do not use for 'what do you see now?' or other visual questions; "
            "this returns metadata, not an image or scene description. "
            "Prefer get_household_snapshot when you also want last-"
            "observation freshness per camera. Cheap."
        ),
        "input_schema": _GET_CAMERA_LAYOUT_SCHEMA,
        "fn": get_camera_layout,
        "side_effect": "read",
        "cost_class": "cheap",
    },
    {
        "name": "get_household_snapshot",
        "description": (
            "Bootstrap orientation. Returns every accessible camera with "
            "its last-observation timestamp, every named Person with "
            "their last-seen-at, any Journey still active right now, and "
            "the household mode (home, away or night). Rules can be gated "
            "on mode, so check it before explaining a missing alert. "
            "Cheap; safe to call on the first turn of most questions so "
            "you have grounding before deciding which tool to call next."
        ),
        "input_schema": _GET_HOUSEHOLD_SNAPSHOT_SCHEMA,
        "fn": get_household_snapshot,
        "side_effect": "read",
        "cost_class": "cheap",
    },
    {
        "name": "get_last_sightings",
        "description": (
            "Return last-seen-at timestamps per named Person AND per "
            "common label (person, cat, dog, package, car, bird) across "
            "the last 30 days. Cheap. Use this when the default 24h "
            "query_observations window came back empty so you can "
            "honestly say 'I haven't seen the cat today, but I last saw "
            "it 19h ago at the back door' instead of just 'no data'. "
            "Optional person_name narrows to one Person; optional "
            "labels overrides the curated baseline set."
        ),
        "input_schema": _GET_LAST_SIGHTINGS_SCHEMA,
        "fn": get_last_sightings,
        "side_effect": "read",
        "cost_class": "cheap",
    },
    {
        "name": "get_events",
        "description": (
            "List rule firings (Events) over a time window. Each Event "
            "is a high-confidence semantic fact about something that "
            "happened. the rule's trigger pattern already confirmed it. "
            "Filter by rule_ids, rule_name_contains, action_status. "
            "Use BEFORE analyze_clip for 'how many times did X happen?' "
            "or 'when did rule Y fire?' questions. Cheap; one DB scan. "
            "Default 24h window, max 30d, max 200 rows. Set "
            "include_payload=true when you also need the per-event "
            "camera_id or detection labels."
        ),
        "input_schema": _GET_EVENTS_SCHEMA,
        "fn": get_events,
        "side_effect": "read",
        "cost_class": "cheap",
    },
    {
        "name": "summarize_activity",
        "description": (
            "Pre-aggregated rollup designed for 'what happened today?' "
            "questions. ONE call returns. per-Person sighting counts + "
            "camera path (from Journeys), per-rule firing counts with "
            "first/last fired times (from Events), per-label observation "
            "counts (cat, dog, person, etc), and per-camera activity "
            "ranking. Use this FIRST for any narrative or summary "
            "question before issuing per-entity queries. Cheap; one "
            "DB pass. Default 24h, max 30d."
        ),
        "input_schema": _SUMMARIZE_ACTIVITY_SCHEMA,
        "fn": summarize_activity,
        "side_effect": "read",
        "cost_class": "cheap",
    },
    {
        "name": "summarize_window",
        "description": (
            "Summarize a LONG time window (multiple days/weeks) by "
            "chunking it, summarizing each chunk, then folding into one "
            "narrative. Use for 'summarize the last week/month' or 'what "
            "happened at <camera> over <long period>'. For a single day "
            "use summarize_activity (cheaper). Bounded token cost via "
            "map-reduce. the per-chunk step is deterministic (zero LLM), "
            "only the final reduce calls the model and it is budget-gated."
        ),
        "input_schema": _SUMMARIZE_WINDOW_SCHEMA,
        "fn": summarize_window,
        "side_effect": "read",
        "cost_class": "medium",
    },
    {
        "name": "list_rules",
        "description": (
            "List automation rules (id, name, enabled, trigger type). "
            "Use this FIRST when a question names a rule you have not "
            "seen ('did my porch rule fire?') or asks what automations "
            "exist, then pass the rule_id to get_events. Cheap."
        ),
        "input_schema": _LIST_RULES_SCHEMA,
        "fn": list_rules,
        "side_effect": "read",
        "cost_class": "cheap",
    },
    {
        "name": "get_incidents",
        "description": (
            "Curated incident clusters: repeated sightings of the same "
            "person/vehicle/animal grouped into one semantic event with "
            "start/end, occurrence count, and (once finalized) a one-"
            "line VLM summary. Best tool for 'anything unusual "
            "lately?', 'list notable events this week', or summarizing "
            "a stretch of activity without re-reading raw observations. "
            "Cheap. WINDOW. Defaults to last 24h; widen with hours."
        ),
        "input_schema": _GET_INCIDENTS_SCHEMA,
        "fn": get_incidents,
        "side_effect": "read",
        "cost_class": "cheap",
    },
    {
        "name": "get_daily_digest",
        "description": (
            "The pre-computed household daily digest narrative (the "
            "same one shown on the dashboard each morning). Cheapest "
            "possible answer to 'what happened yesterday/today overall' "
            "questions; prefer it over summarize_activity when the user "
            "wants the day's recap rather than a custom analysis."
        ),
        "input_schema": _GET_DAILY_DIGEST_SCHEMA,
        "fn": get_daily_digest,
        "side_effect": "read",
        "cost_class": "cheap",
    },
    {
        "name": "get_vehicles",
        "description": (
            "Vehicles identified by license plate, each with a short "
            "description (e.g. 'Red Nissan sedan'), the plate, and "
            "first/last-seen timestamps. Best tool for 'when did the red "
            "Nissan arrive', 'what was the plate of that truck', 'which "
            "vehicles came by today'. Filter by plate or by free text "
            "(color/make/model/type). WINDOW defaults to 168h (7 days); "
            "widen with hours=720. Cheap."
        ),
        "input_schema": _GET_VEHICLES_SCHEMA,
        "fn": get_vehicles,
        "side_effect": "read",
        "cost_class": "cheap",
    },
    {
        "name": "get_associations",
        "description": (
            "Learned habits and declared authorizations between "
            "identities. Answers 'which car does Ahmed use', 'who drives "
            "the Harrier', 'who is authorized for forklift 3', 'what time "
            "does he usually leave'. Each row says how many separate DAYS "
            "the pattern held, which is what makes it a habit rather than "
            "a coincidence. Cheap; one indexed lookup."
        ),
        "input_schema": _GET_ASSOCIATIONS_SCHEMA,
        "fn": get_associations,
        "side_effect": "read",
        "cost_class": "cheap",
    },
    {
        "name": "get_household_facts",
        "description": (
            "Household notes: what the household has told Nurby on purpose "
            "('the cleaner comes Thursdays', 'the white van is the "
            "plumber's') plus established facts Nurby learned from "
            "observations. Answers 'what do you know about the cleaner', "
            "'when does the gardener come'. Each row says whether it came "
            "from the household or was learned — keep that distinction "
            "when you answer. Cheap; one indexed lookup."
        ),
        "input_schema": _GET_HOUSEHOLD_FACTS_SCHEMA,
        "fn": get_household_facts,
        "side_effect": "read",
        "cost_class": "cheap",
    },
    {
        "name": "speak_on_camera",
        "description": (
            "Say something out loud through a camera's speaker, to "
            "whoever is standing in front of it. Use ONLY when the user "
            "explicitly asks you to say or announce something at a "
            "camera. This is heard by people in the room, so never use it "
            "to answer the user: reply in chat for that. Off unless the "
            "household enabled it."
        ),
        "input_schema": _SPEAK_ON_CAMERA_SCHEMA,
        "fn": speak_on_camera,
        # The first non-read tool in this registry. It changes something
        # in a room rather than in a database.
        "side_effect": "physical",
        "cost_class": "cheap",
    },
    {
        "name": "query_relationships",
        "description": (
            "Walk relationships between people, animals, vehicles, "
            "cameras, and time. Answers 'who was with X', 'did X come "
            "back later', 'where did X go', 'was X seen with a <label>', "
            "'what's the usual path'. Cheap; one DB pass over the Journey "
            "graph (segments + transitions JSON). Use this BEFORE "
            "stitching multiple get_journeys calls. Relations. "
            "co_present_with, revisited, path, seen_with_label, "
            "transitions. Subject is a Person name/id or a label like "
            "'cat'/'car'. Returns disambiguation when a name matches more "
            "than one Person."
        ),
        "input_schema": _QUERY_RELATIONSHIPS_SCHEMA,
        "fn": query_relationships,
        "side_effect": "read",
        "cost_class": "cheap",
    },
    {
        "name": "analyze_clip",
        "description": (
            "EXPENSIVE. Runs a VLM against actual video frames over a "
            "[time_from, time_to] window on one camera. Use ONLY when "
            "query_observations + get_last_sightings + get_journeys "
            "cannot answer the question because the concept isn't in "
            "our indexed taxonomy ('was he eating?', 'is the package "
            "still there?', 'did anyone come through the gate at 2 "
            "PM?'). Cached per (recording, question, model) forever — "
            "asking the same question about the same window again is "
            "free. Returns a structured answer with verdict, confidence, "
            "evidence frames, and a vlm_call_id you must cite."
        ),
        "input_schema": _ANALYZE_CLIP_SCHEMA,
        "fn": analyze_clip,
        "side_effect": "read",
        "cost_class": "expensive",
    },
    {
        "name": "analyze_frame",
        "description": (
            "MEDIUM cost. Runs a VLM against ONE Observation's "
            "thumbnail. Use when you already have a specific "
            "observation_id (from query_observations or "
            "get_last_sightings) and need to verify or extract a "
            "single detail ('what do you see right now?', 'is the dog in "
            "this frame holding anything?', 'what color is the visitor's "
            "jacket?'). "
            "Cached per (observation, question, model) forever. "
            "Returns the same structured answer schema as analyze_clip."
        ),
        "input_schema": _ANALYZE_FRAME_SCHEMA,
        "fn": analyze_frame,
        "side_effect": "read",
        "cost_class": "medium",
    },
    {
        "name": "get_rule_schema",
        "description": (
            "The complete rule vocabulary: every trigger type, action "
            "type, and condition field. Use it only to judge whether an "
            "automation the user asks about is possible. Never repeat "
            "the internal field names to the user. Cheap."
        ),
        "input_schema": _GET_RULE_SCHEMA_SCHEMA,
        "fn": get_rule_schema,
        "side_effect": "read",
        "cost_class": "cheap",
    },
    {
        "name": "suggest_rule",
        "description": (
            "REQUIRED whenever the user asks to create, set up, or "
            "change an automation rule or alert. You cannot create "
            "rules yourself. This tool takes a plain-English "
            "description of what the user wants and returns a link to "
            "the Rules page with that description pre-filled; relay "
            "the link to the user. Cheap; makes no changes."
        ),
        "input_schema": _SUGGEST_RULE_SCHEMA,
        "fn": suggest_rule,
        "side_effect": "read",
        "cost_class": "cheap",
    },
    {
        "name": "draft_rule",
        "description": (
            "PREFERRED when the user asks to create, set up, add, or change "
            "an automation/alert. Takes a plain-English description and drafts "
            "a real, ready-to-create rule, returning a Confirm proposal shown "
            "to the user. It creates NOTHING on its own — the rule is only made "
            "when the user presses Confirm. Relay the message_for_user; never "
            "print JSON or field names. Prefer this over suggest_rule."
        ),
        "input_schema": _DRAFT_RULE_SCHEMA,
        "fn": draft_rule,
        # 'propose' writes nothing itself; the create happens on the user's
        # explicit confirm via the client. Kept out of the 'write' class so the
        # driver may run it, but it carries a client_action for the confirm gate.
        "side_effect": "read",
        "cost_class": "medium",
    },
    {
        "name": "remember",
        "description": (
            "Use when the user tells you to remember something about their "
            "household ('remember that…', 'note that…', 'keep in mind…'). Takes "
            "one plain-language fact and returns a Confirm card. It saves "
            "NOTHING on its own — the fact is stored only when the user confirms. "
            "Relay message_for_user; never claim it is already saved."
        ),
        "input_schema": _REMEMBER_SCHEMA,
        "fn": remember,
        "side_effect": "read",
        "cost_class": "cheap",
    },
    {
        "name": "test_camera_connection",
        "description": (
            "Network probe of one camera's stream endpoint. Returns a "
            "classified verdict (dns / refused / timeout / auth / "
            "not_found) plus a fix hint. Use when the user says a "
            "camera is black, offline, or won't connect. Cheap."
        ),
        "input_schema": _TEST_CAMERA_CONNECTION_SCHEMA,
        "fn": test_camera_connection,
        "side_effect": "read",
        "cost_class": "cheap",
    },
    {
        "name": "run_doctor",
        "description": (
            "Full system health pass: database, redis, stream relay, "
            "every camera, every AI provider, email config, disk space. "
            "Per-check verdicts with fix hints. Use for 'why isn't this "
            "working?' or general health questions. Medium cost (probes "
            "every camera and provider)."
        ),
        "input_schema": _RUN_DOCTOR_SCHEMA,
        "fn": run_doctor,
        "side_effect": "read",
        "cost_class": "medium",
    },
]


_REGISTRY_BY_NAME: dict[str, dict[str, Any]] = {t["name"]: t for t in TOOL_REGISTRY}


def get_tool(name: str) -> dict[str, Any] | None:
    """Lookup a tool entry by name."""
    return _REGISTRY_BY_NAME.get(name)


# ── Provider dialect adapter ─────────────────────────────────────────


def _to_anthropic(tool: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": tool["name"],
        "description": tool["description"],
        "input_schema": tool["input_schema"],
    }


def _to_openai(tool: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["input_schema"],
        },
    }


def _to_gemini(tool: dict[str, Any]) -> dict[str, Any]:
    # Gemini's functionDeclarations entry. Field naming differs from
    # OpenAI but the schema body is a JSON Schema subset, same content.
    return {
        "name": tool["name"],
        "description": tool["description"],
        "parameters": tool["input_schema"],
    }


_DIALECT_ADAPTERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "anthropic": _to_anthropic,
    "claude": _to_anthropic,
    "openai": _to_openai,
    "gpt": _to_openai,
    "ollama": _to_openai,  # Ollama mimics the OpenAI tool-use schema
    "google": _to_gemini,
    "gemini": _to_gemini,
}


def all_tools_for_provider(provider_kind: str) -> list[dict[str, Any]]:
    """Return the tool registry serialized to the given provider's
    tool-use schema dialect. Wave 2 driver feeds the output straight
    into the provider's request body."""
    kind = (provider_kind or "").lower()
    adapter = _DIALECT_ADAPTERS.get(kind)
    if adapter is None:
        raise ValueError(f"unsupported provider_kind: {provider_kind!r}")
    return [adapter(t) for t in TOOL_REGISTRY]
