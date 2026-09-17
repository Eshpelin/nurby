"""Personal presentation preferences; roles and camera grants are independent."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


class ExperiencePreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    place: Literal["home", "business"] | None = None
    goal: Literal["entrance", "deliveries", "after_hours", "review", "explore"]
    focus: Literal["daily", "setup"] = "daily"
    # An optional label for the place this workspace watches. A single free
    # text name only. It is not a workspace/tenant id and grants nothing;
    # real multi-site support is deliberately out of phase 1/3 scope.
    place_label: str | None = None
    # Pauses daily-workflow nudges without touching any rule or grant.
    paused: bool = False

    @model_validator(mode="after")
    def compatible_goal(self):
        if self.goal in {"entrance", "deliveries", "after_hours"} and self.place is None:
            raise ValueError("Choose a place for this monitoring goal")
        if self.goal == "after_hours" and self.place != "business":
            raise ValueError("After-hours monitoring requires a business context")
        if self.place_label is not None:
            self.place_label = self.place_label.strip() or None
            if self.place_label and len(self.place_label) > 80:
                raise ValueError("Place name is too long")
        return self


class ExperienceResponse(BaseModel):
    preferences: ExperiencePreferences | None
    audience: Literal["administrator", "viewer", "guardian"]


def experience_response(user) -> ExperienceResponse:
    audience = "administrator" if user.role == "admin" else "guardian" if user.role == "guardian" else "viewer"
    preferences = getattr(user, "onboarding_preferences", None)
    # A role change must immediately remove setup recommendations even when
    # the account previously saved an administrator's preferences.
    if audience != "administrator" and preferences is not None:
        preferences = {"goal": "review", "place": None, "focus": "daily", "version": 1}
    return ExperienceResponse(preferences=preferences, audience=audience)
