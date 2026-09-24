"""Tool registry for the agent loop.

Five Phase 1 tools, all read-only. Each tool is an async callable that
takes a ``ctx`` dict + keyword params validated against the tool's
JSON schema, and returns a JSON-serializable dict.

``ctx`` shape (Wave 2 driver populates this).

    {
        "user": shared.models.User,          # current authenticated user
        "run_id": uuid.UUID | None,          # the AgentRun row id, may be None
        "db": sqlalchemy AsyncSession,       # request-scoped DB session
    }

Every tool funnels its result set through ``accessible_camera_ids`` so
users never see data outside their access scope. Window arguments are
clamped (1..720 hours) and result counts are bounded.

Wave 1A owns the AgentRun + budget + AgentVlmCall persistence. Wave 1C
owns the actual VLM analyzer that ``analyze_clip`` and ``analyze_frame``
delegate to. Both are imported lazily so this module loads even when
the sibling waves have not landed yet. The analyzer tools return a
clean ``analyzer_not_ready`` payload in that case.
"""

from services.agent.tools._common import (  # noqa: F401
    WIDEN_LADDER,
    _alias_map,
    _clamp_hours,
    _clamp_limit,
    _embed_query,
    _infer_role,
    _person_journeys,
    _seg_camera_id,
    _subject_names,
    _thumbnail_url,
    _to_uuid_set,
    widen_ladder,
)
from services.agent.tools.activity import summarize_activity  # noqa: F401
from services.agent.tools.analysis import (  # noqa: F401
    analyze_clip,
    analyze_frame,
    summarize_window,
)
from services.agent.tools.household import (  # noqa: F401
    get_camera_layout,
    get_household_snapshot,
)
from services.agent.tools.lookups import (  # noqa: F401
    get_daily_digest,
    get_incidents,
    get_vehicles,
    list_rules,
)
from services.agent.tools.observations import (  # noqa: F401
    get_journeys,
    query_observations,
)
from services.agent.tools.registry import (  # noqa: F401
    _REGISTRY_BY_NAME,
    TOOL_REGISTRY,
    ToolFn,
    all_tools_for_provider,
    get_tool,
)
from services.agent.tools.relationships import (  # noqa: F401
    _token_match,
    get_associations,
    query_relationships,
)
from services.agent.tools.setup_tools import (  # noqa: F401
    draft_rule,
    get_rule_schema,
    run_doctor,
    suggest_rule,
    test_camera_connection,
)
from services.agent.tools.sightings import (  # noqa: F401
    get_events,
    get_last_sightings,
)
from services.agent.tools.voice import speak_on_camera  # noqa: F401

__all__ = [
    "TOOL_REGISTRY",
    "ToolFn",
    "WIDEN_LADDER",
    "all_tools_for_provider",
    "analyze_clip",
    "analyze_frame",
    "get_associations",
    "get_camera_layout",
    "get_daily_digest",
    "get_events",
    "get_household_snapshot",
    "get_incidents",
    "get_journeys",
    "get_last_sightings",
    "get_rule_schema",
    "get_tool",
    "get_vehicles",
    "list_rules",
    "query_observations",
    "query_relationships",
    "run_doctor",
    "speak_on_camera",
    "draft_rule",
    "suggest_rule",
    "summarize_activity",
    "summarize_window",
    "test_camera_connection",
    "widen_ladder",
]
