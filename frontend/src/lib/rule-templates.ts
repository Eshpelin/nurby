// Starter rule templates for the gallery and onboarding deep links.
//
// Each template builds a synthetic Rule whose shape matches what
// RuleBuilder.hydrate expects. The id is "" so the builder treats it as
// a NEW rule (POST on save). Light parameterization (camera/person)
// happens on the gallery card; everything else is edited in the builder.

import type { Camera, Person, Rule, TelegramChannelOption } from "@/components/rules/types";

export interface TemplateContext {
  cameras: Camera[];
  persons: Person[];
  telegramChannels: TelegramChannelOption[];
}

export type TemplateParamName = "camera_id" | "person_id";

export interface TemplateParam {
  name: TemplateParamName;
  label: string;
  required: boolean;
}

export type TemplateCategory = "delivery" | "security" | "vehicles" | "audio" | "system";

export const CATEGORY_LABELS: Record<TemplateCategory, string> = {
  delivery: "Deliveries",
  security: "Security",
  vehicles: "Vehicles",
  audio: "Sound",
  system: "System health",
};

export interface RuleTemplate {
  key: string;
  icon: string;
  title: string;
  blurb: string;
  category: TemplateCategory;
  params: TemplateParam[];
  build: (
    ctx: TemplateContext,
    picked?: Partial<Record<TemplateParamName, string>>,
  ) => Rule;
}

function synthRule(
  name: string,
  trigger_pattern: Record<string, unknown>,
  actions: Record<string, unknown>[],
  conditions: Record<string, unknown> | null = null,
  cooldown_seconds = 300,
  severity?: string,
): Rule {
  return {
    id: "",
    name,
    enabled: true,
    trigger_pattern,
    conditions,
    actions,
    cooldown_seconds,
    ...(severity ? { severity } : {}),
    created_at: new Date().toISOString(),
  };
}

// Telegram to the paired channel when one exists, else an in-app
// notification. Same fallback the original empty-state personas used.
function alertAction(
  ctx: TemplateContext,
  template: string,
  notifyMessage: string,
  severity: "info" | "warning" = "info",
  includeThumbnail = true,
): Record<string, unknown> {
  const paired = ctx.telegramChannels.find(
    (c) => c.enabled && c.pairing_status === "paired",
  );
  return paired
    ? {
        type: "telegram",
        channel_id: paired.id,
        template,
        silent: false,
        include_thumbnail: includeThumbnail,
      }
    : { type: "notify", message: notifyMessage, severity };
}

function guessCamera(cameras: Camera[], pattern: RegExp): Camera | undefined {
  return cameras.find((c) => pattern.test(c.name));
}

function cameraConditions(
  ctx: TemplateContext,
  picked: Partial<Record<TemplateParamName, string>> | undefined,
  guess: RegExp,
): Record<string, unknown> | null {
  const id = picked?.camera_id || guessCamera(ctx.cameras, guess)?.id;
  return id ? { camera_ids: [id] } : null;
}

export const RULE_TEMPLATES: RuleTemplate[] = [
  {
    key: "package-at-door",
    icon: "📦",
    title: "Tell me when a package arrives",
    blurb: "Package detected → Telegram or notification",
    category: "delivery",
    params: [{ name: "camera_id", label: "Which camera watches deliveries?", required: false }],
    build: (ctx, picked) =>
      synthRule(
        "Package at front door",
        { type: "object_detected", label: "package" },
        [alertAction(ctx, "📦 Package at {camera_name} ({timestamp_local})", "Package detected")],
        cameraConditions(ctx, picked, /front\s*door|porch|entrance/i),
      ),
  },
  {
    key: "stranger-at-night",
    icon: "🚨",
    title: "Alert me if an unknown face shows up at night",
    blurb: "Unknown face between 10pm and 6am → alert",
    category: "security",
    params: [],
    build: (ctx) =>
      synthRule(
        "Unknown face at night",
        { type: "face_unknown" },
        [
          alertAction(
            ctx,
            "🚨 Unknown face on {camera_name} at {timestamp_local}",
            "Unknown face detected at night",
            "warning",
          ),
        ],
        { time_after: "22:00", time_before: "06:00" },
        300,
        "alert",
      ),
  },
  {
    key: "person-at-door",
    icon: "🚶",
    title: "Someone is at the door",
    blurb: "Person detected on the door camera → notification",
    category: "security",
    params: [{ name: "camera_id", label: "Which camera watches the door?", required: false }],
    build: (ctx, picked) =>
      synthRule(
        "Person at the door",
        { type: "object_detected", label: "person" },
        [alertAction(ctx, "🚶 Someone at {camera_name} ({timestamp_local})", "Person at the door")],
        cameraConditions(ctx, picked, /front\s*door|porch|entrance|doorbell/i),
        600,
      ),
  },
  {
    key: "vehicle-in-driveway",
    icon: "🚗",
    title: "A car pulls into the driveway",
    blurb: "Car or truck detected → notification",
    category: "vehicles",
    params: [{ name: "camera_id", label: "Which camera sees the driveway?", required: false }],
    build: (ctx, picked) =>
      synthRule(
        "Vehicle in driveway",
        { type: "object_detected", label: "car" },
        [alertAction(ctx, "🚗 Vehicle at {camera_name} ({timestamp_local})", "Vehicle in driveway")],
        cameraConditions(ctx, picked, /driveway|garage|gate/i),
        600,
      ),
  },
  {
    key: "unknown-plate",
    icon: "🚙",
    title: "A car not on my list shows up",
    blurb: "Plate allow-list: alert on unlisted vehicles",
    category: "vehicles",
    params: [{ name: "camera_id", label: "Which camera reads plates?", required: false }],
    build: (ctx, picked) =>
      synthRule(
        "Unlisted vehicle",
        { type: "plate_list", mode: "whitelist", plates: [] },
        [
          alertAction(
            ctx,
            "🚙 Unlisted vehicle on {camera_name} ({timestamp_local})",
            "Unlisted vehicle spotted",
            "warning",
          ),
        ],
        cameraConditions(ctx, picked, /driveway|garage|gate|street/i),
        600,
        "alert",
      ),
  },
  {
    key: "baby-cry",
    icon: "🍼",
    title: "The baby is crying",
    blurb: "Baby-cry sound detected → alert",
    category: "audio",
    params: [{ name: "camera_id", label: "Which camera is in the nursery?", required: false }],
    build: (ctx, picked) =>
      synthRule(
        "Baby cry",
        { type: "audio_event", label: "baby_cry", min_score: 0.35 },
        [alertAction(ctx, "🍼 Baby crying on {camera_name}", "Baby cry detected", "warning", false)],
        cameraConditions(ctx, picked, /nursery|baby|crib|kids?/i),
        60,
      ),
  },
  {
    key: "help-phrase",
    icon: "🗣️",
    title: "Someone calls for help",
    blurb: 'Spoken phrase "help" detected → alert',
    category: "audio",
    params: [],
    build: (ctx) =>
      synthRule(
        "Help phrase",
        { type: "speech_phrase", phrases: ["help"] },
        [
          alertAction(
            ctx,
            "🗣️ \"Help\" heard on {camera_name} ({timestamp_local})",
            "Someone called for help",
            "warning",
            false,
          ),
        ],
        null,
        60,
        "alert",
      ),
  },
  {
    key: "known-person-arrives",
    icon: "👋",
    title: "Tell me when someone I know arrives",
    blurb: "A specific person is recognized → notification",
    category: "security",
    params: [{ name: "person_id", label: "Who should I watch for?", required: false }],
    build: (ctx, picked) =>
      synthRule(
        "Known person arrives",
        picked?.person_id
          ? { type: "face_recognized", person_id: picked.person_id }
          : { type: "face_recognized" },
        [alertAction(ctx, "👋 {rule_name} at {timestamp_local}", "Known person arrived", "info", false)],
        null,
        900,
      ),
  },
  {
    key: "camera-offline",
    icon: "📵",
    title: "A camera goes offline",
    blurb: "Camera stops responding (power, network, tamper) → alert",
    category: "system",
    params: [],
    build: (ctx) =>
      synthRule(
        "Camera went offline",
        { type: "camera_offline" },
        [
          alertAction(
            ctx,
            "📵 {camera_name} went offline at {timestamp_local}",
            "A camera went offline",
            "warning",
            false,
          ),
        ],
        null,
        600,
        "alert",
      ),
  },
];

export function findTemplate(key: string): RuleTemplate | undefined {
  return RULE_TEMPLATES.find((t) => t.key === key);
}
