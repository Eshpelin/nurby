"""Every database model, grouped by what it is about.

This used to be one 2,300-line module. It is now a package, and this
file re-exports the whole set, so ``from shared.models import Camera``
still works and Alembic still sees every table on ``Base.metadata``.
The grouping is by subject, not by table: look in ``cameras`` for a
camera and anything physically attached to one, in ``identity`` for
anyone Nurby recognises, and so on.
"""

from shared.database import Base  # noqa: F401
from shared.models.accounts import (  # noqa: F401
    ApiKey,
    AppSetting,
    HouseholdModeChange,
    InviteKey,
    Provider,
    PushDevice,
    ResourceShare,
    User,
    UserCameraAccess,
)
from shared.models.agent import (  # noqa: F401
    AgentDailyUsage,
    AgentRun,
    AgentToolCall,
    AgentVlmCall,
    VlmFrameAnalysis,
)
from shared.models.audio import (  # noqa: F401
    AudioAuditLog,
    AudioCapture,
    AudioDetection,
    Conversation,
    SpeechEvent,
    Summary,
    Transcript,
    VoiceSession,
)
from shared.models.cameras import (  # noqa: F401
    Camera,
    CameraStatusLog,
    Device,
    MotionSample,
    PrivacyZone,
    Recording,
    SpeakerCapability,
)
from shared.models.digests import (  # noqa: F401
    DailyDigest,
    DashboardWidget,
    DigestEntry,
    HouseholdFact,
    Notification,
    ScheduledReport,
)
from shared.models.guardian import (  # noqa: F401
    ApprovedPickup,
    Facility,
    GuardianAccessLog,
    GuardianEvent,
    GuardianLink,
)
from shared.models.identity import (  # noqa: F401
    BodyCluster,
    BodyClusterSample,
    EntityAssociation,
    FaceCluster,
    FaceClusterSample,
    FaceEmbedding,
    Person,
    Vehicle,
)
from shared.models.integrations import (  # noqa: F401
    TelegramChannel,
    TelegramDialog,
    TelegramOutboxDedupe,
    WebhookSubscription,
)
from shared.models.observations import (  # noqa: F401
    GroundingResult,
    Incident,
    Journey,
    Observation,
    ObservationAction,
    ObservationIncident,
    ObservationVlmPass,
    PersonActionSegment,
)
from shared.models.rules import (  # noqa: F401
    Event,
    EventNote,
    Rule,
    RuleSequenceInstance,
)

__all__ = [
    "Base",
    "AgentDailyUsage",
    "AgentRun",
    "AgentToolCall",
    "AgentVlmCall",
    "ApiKey",
    "AppSetting",
    "ApprovedPickup",
    "AudioAuditLog",
    "AudioCapture",
    "AudioDetection",
    "BodyCluster",
    "BodyClusterSample",
    "Camera",
    "CameraStatusLog",
    "Conversation",
    "DailyDigest",
    "DashboardWidget",
    "Device",
    "DigestEntry",
    "EntityAssociation",
    "Event",
    "EventNote",
    "FaceCluster",
    "FaceClusterSample",
    "FaceEmbedding",
    "Facility",
    "GroundingResult",
    "GuardianAccessLog",
    "GuardianEvent",
    "GuardianLink",
    "HouseholdModeChange",
    "HouseholdFact",
    "Incident",
    "InviteKey",
    "Journey",
    "MotionSample",
    "Notification",
    "Observation",
    "ObservationAction",
    "ObservationIncident",
    "ObservationVlmPass",
    "Person",
    "PersonActionSegment",
    "PrivacyZone",
    "Provider",
    "PushDevice",
    "Recording",
    "ResourceShare",
    "Rule",
    "RuleSequenceInstance",
    "ScheduledReport",
    "SpeakerCapability",
    "SpeechEvent",
    "Summary",
    "TelegramChannel",
    "TelegramDialog",
    "TelegramOutboxDedupe",
    "Transcript",
    "User",
    "UserCameraAccess",
    "Vehicle",
    "VlmFrameAnalysis",
    "VoiceSession",
    "WebhookSubscription",
]
