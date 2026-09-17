export type Place = "home" | "business";
export type Goal = "entrance" | "deliveries" | "after_hours" | "review" | "explore";
export interface ExperiencePreferences {
  version: 1;
  place: Place | null;
  goal: Goal;
  focus: "daily" | "setup";
  place_label?: string | null;
  paused?: boolean;
}
export interface Experience {
  preferences: ExperiencePreferences | null;
  audience: "administrator" | "viewer" | "guardian";
}

export const GOALS: Record<Goal, {
  title: string;
  description: string;
  needs: string;
  next: string;
  href: string;
  template?: string;
}> = {
  entrance: {
    title: "Know when someone arrives",
    description: "Detect a person at your chosen entrance and send an alert for you to review.",
    needs: "A real entrance camera with person detection. No AI provider is needed for this starter.",
    next: "Choose the entrance camera and notification destination. Review the alert frequency before saving.",
    href: "/rules/new?template=person-at-door",
    template: "person-at-door",
  },
  deliveries: {
    title: "Keep track of deliveries",
    description: "Alert you when a package is detected on your chosen delivery camera.",
    needs: "A real camera watching deliveries and a detector that recognizes packages. No AI provider is needed for this starter.",
    next: "Choose the delivery camera and notification destination. Verify that package detection works on this camera.",
    href: "/rules/new?template=package-at-door",
    template: "package-at-door",
  },
  after_hours: {
    title: "Review activity after closing",
    description: "Detect a person outside working hours, ask AI to check the frame, then send an alert for review.",
    needs: "A real camera with person detection and a working vision AI provider for the verification step.",
    next: "Choose the camera, set your closing hours and notification destination. The starter uses 7 pm–6 am; change this to your schedule and check the system time zone.",
    href: "/rules/new?template=after-hours-office",
    template: "after-hours-office",
  },
  review: {
    title: "Find and review what happened",
    description: "Open the timeline, choose a camera and time, and review the available evidence.",
    needs: "Access to a camera with recorded activity. An AI provider is not required to browse the timeline.",
    next: "Find a recent event and open its evidence. If footage is missing, check the camera's recording coverage.",
    href: "/timeline",
  },
  explore: {
    title: "Explore Nurby",
    description: "Look around first and choose a monitoring goal when you are ready.",
    needs: "Only cameras and evidence your account can access are available.",
    next: "You can choose or change your goal from this card at any time.",
    href: "/timeline",
  },
};

export function goalsForPlace(place: Place): Goal[] {
  return place === "business" ? ["after_hours", "entrance", "review"] : ["entrance", "deliveries", "review"];
}
