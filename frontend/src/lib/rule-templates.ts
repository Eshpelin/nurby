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

export type TemplateCategory =
  | "delivery"
  | "security"
  | "vehicles"
  | "audio"
  | "system"
  | "workplace"
  | "industrial";

export const CATEGORY_LABELS: Record<TemplateCategory, string> = {
  delivery: "Deliveries",
  security: "Security",
  vehicles: "Vehicles",
  audio: "Sound",
  system: "System health",
  workplace: "At work",
  industrial: "On the floor",
};

// Placeholder endpoints for the templates whose whole point is writing into
// another system. api_call requires a url, so a template cannot ship blank.
// These are obvious stand-ins that fail closed (bad host = failed action,
// logged, chain continues) and the card blurb tells the user to swap them.
const PLACEHOLDER_WMS = "https://your-wms.example.com/api/tasks";
const PLACEHOLDER_CRM = "https://your-crm.example.com/api/members/charges";
const PLACEHOLDER_CMMS = "https://your-cmms.example.com/api/work-orders";

export interface RuleTemplate {
  key: string;
  icon: string;
  title: string;
  blurb: string;
  category: TemplateCategory;
  params: TemplateParam[];
  // Loitering and line_cross triggers are rejected server-side without a
  // polygon/segment plus a camera (shared/schemas.py _validate_trigger_pattern).
  // The builder opens the inline editor, but the card says so up front rather
  // than letting the user find out on save.
  needsGeometry?: boolean;
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

  // ---- At work ---------------------------------------------------------
  //
  // Everything below is built from triggers and actions that already ship.
  // Templates that need a zone or a tripwire leave `points` unset on purpose:
  // the builder omits geometry it does not have and opens the inline editor
  // so the user draws the line on their own feed. Same for device actions,
  // which need a registered device id we cannot guess.
  {
    key: "tailgate-badge-door",
    icon: "🚪",
    title: "Someone tailgated through the badge door",
    blurb: "Two people across the entry tripwire within 5s → alert with clip",
    category: "workplace",
    needsGeometry: true,
    params: [{ name: "camera_id", label: "Which camera watches the entry?", required: false }],
    build: (ctx, picked) =>
      synthRule(
        "Tailgate at the badge door",
        {
          type: "line_cross",
          direction: "in",
          label: "person",
          sequence: {
            steps: [{ check: { type: "object_detected", label: "person" }, within_seconds: 5 }],
            correlate_by: "camera",
            on_refire: "ignore",
          },
        },
        [
          alertAction(
            ctx,
            "🚪 Tailgate at {camera_name} ({timestamp_local}). Two people, one entry.",
            "Possible tailgate at the entry",
            "warning",
          ),
        ],
        cameraConditions(ctx, picked, /lobby|entry|entrance|door|gate|reception/i),
        120,
        "alert",
      ),
  },
  {
    key: "tailgate-guest-fee",
    icon: "💳",
    title: "Bill a tailgated entry as a guest visit",
    blurb: "Same tailgate detection → post a charge to your CRM + email the report",
    category: "workplace",
    needsGeometry: true,
    params: [{ name: "camera_id", label: "Which camera watches the member gate?", required: false }],
    build: (ctx, picked) =>
      synthRule(
        "Guest fee for a tailgated entry",
        {
          type: "line_cross",
          direction: "in",
          label: "person",
          sequence: {
            steps: [{ check: { type: "object_detected", label: "person" }, within_seconds: 5 }],
            correlate_by: "camera",
            on_refire: "ignore",
          },
        },
        [
          {
            type: "api_call",
            method: "POST",
            url: PLACEHOLDER_CRM,
            payload_template: {
              reason: "tailgate_guest_fee",
              camera: "{{camera_name}}",
              occurred_at: "{{timestamp}}",
              event_id: "{{event_id}}",
            },
          },
          alertAction(
            ctx,
            "💳 Guest fee raised for a tailgate at {camera_name} ({timestamp_local})",
            "Guest fee raised for a tailgated entry",
            "warning",
          ),
        ],
        cameraConditions(ctx, picked, /lobby|entry|entrance|door|gate|member/i),
        120,
        "alert",
      ),
  },
  {
    key: "allowlisted-plate-at-gate",
    icon: "🛂",
    title: "A vehicle on my list arrives at the gate",
    blurb: "Plate allow-list match → notify (add a Device action to drive the barrier relay)",
    category: "workplace",
    params: [{ name: "camera_id", label: "Which camera reads the gate?", required: false }],
    build: (ctx, picked) =>
      synthRule(
        "Allow-listed vehicle at the gate",
        { type: "plate_list", mode: "whitelist", plates: [] },
        [
          alertAction(
            ctx,
            "🛂 {rule_name}: known plate at {camera_name} ({timestamp_local})",
            "Allow-listed vehicle at the gate",
            "info",
          ),
        ],
        cameraConditions(ctx, picked, /gate|yard|barrier|entrance|lane/i),
        60,
      ),
  },
  {
    key: "after-hours-office",
    icon: "🌙",
    title: "Somebody is in the building after hours",
    blurb: "Person seen 7pm–6am → AI double-check → alert",
    category: "workplace",
    params: [{ name: "camera_id", label: "Which camera watches the floor?", required: false }],
    build: (ctx, picked) =>
      synthRule(
        "After-hours presence",
        { type: "object_detected", label: "person", min_frames: 3, within_seconds: 20 },
        [
          {
            type: "verify",
            question: "Is there a person inside the office in this frame?",
            min_confidence: 0.6,
            on_fail: "stop",
          },
          alertAction(
            ctx,
            "🌙 Someone on {camera_name} at {timestamp_local}, outside working hours",
            "After-hours presence detected",
            "warning",
          ),
        ],
        {
          ...(cameraConditions(ctx, picked, /office|floor|work|desk|lobby/i) ?? {}),
          time_after: "19:00",
          time_before: "06:00",
        },
        600,
        "alert",
      ),
  },
  {
    key: "reception-unattended",
    icon: "🔔",
    title: "A visitor is waiting and nobody is at the desk",
    blurb: "Unknown face at reception → chime the back office",
    category: "workplace",
    params: [{ name: "camera_id", label: "Which camera watches reception?", required: false }],
    build: (ctx, picked) =>
      synthRule(
        "Visitor waiting at reception",
        { type: "face_unknown" },
        [
          alertAction(
            ctx,
            "🔔 Visitor waiting at {camera_name} ({timestamp_local})",
            "A visitor is waiting at reception",
            "info",
          ),
        ],
        cameraConditions(ctx, picked, /reception|lobby|front\s*desk|entrance/i),
        180,
      ),
  },
  {
    key: "dock-dwell",
    icon: "🚚",
    title: "A truck has been on the dock too long",
    blurb: "Vehicle dwelling in the dock zone over 30 min → notify + post to your system",
    category: "workplace",
    needsGeometry: true,
    params: [{ name: "camera_id", label: "Which camera watches the dock?", required: false }],
    build: (ctx, picked) =>
      synthRule(
        "Dock dwell over 30 minutes",
        { type: "loitering", label: "truck", threshold_seconds: 1800 },
        [
          {
            type: "api_call",
            method: "POST",
            url: PLACEHOLDER_WMS,
            payload_template: {
              kind: "dock_dwell_exceeded",
              camera: "{{camera_name}}",
              occurred_at: "{{timestamp}}",
            },
          },
          alertAction(
            ctx,
            "🚚 Truck on {camera_name} for over 30 minutes ({timestamp_local})",
            "A truck has been on the dock over 30 minutes",
            "warning",
          ),
        ],
        cameraConditions(ctx, picked, /dock|bay|loading|yard/i),
        1800,
        "alert",
      ),
  },
  {
    key: "door-propped-open",
    icon: "🚧",
    title: "A door has been propped open",
    blurb: "Anything dwelling in the doorway zone over 2 min → alert once",
    category: "workplace",
    needsGeometry: true,
    params: [{ name: "camera_id", label: "Which camera watches the door?", required: false }],
    build: (ctx, picked) =>
      synthRule(
        "Door propped open",
        { type: "loitering", threshold_seconds: 120 },
        [
          alertAction(
            ctx,
            "🚧 Door held open on {camera_name} for over 2 minutes ({timestamp_local})",
            "A door has been propped open",
            "warning",
          ),
        ],
        cameraConditions(ctx, picked, /door|fire\s*exit|entrance|corridor/i),
        900,
        "alert",
      ),
  },

  // ---- On the floor ----------------------------------------------------
  {
    key: "mis-slotted-pallet",
    icon: "📦",
    title: "A pallet went into the wrong rack",
    blurb: "Put-away tripwire → ask the model → verify → flag it in your WMS",
    category: "industrial",
    needsGeometry: true,
    params: [{ name: "camera_id", label: "Which camera watches the aisle?", required: false }],
    build: (ctx, picked) =>
      synthRule(
        "Mis-slotted pallet",
        { type: "line_cross" },
        [
          {
            type: "locate",
            prompt: "a pallet resting in a racking bay",
            on_fail: "stop",
            require_corroboration: true,
            output: "pallet",
          },
          {
            type: "verify",
            question:
              "Is this pallet in the bay its label says it belongs to? Answer no if it is in the wrong bay.",
            min_confidence: 0.6,
            on_fail: "stop",
          },
          {
            type: "api_call",
            method: "POST",
            url: PLACEHOLDER_WMS,
            payload_template: {
              kind: "slot_mismatch",
              camera: "{{camera_name}}",
              occurred_at: "{{timestamp}}",
              event_id: "{{event_id}}",
            },
          },
          alertAction(
            ctx,
            "📦 Possible mis-slot on {camera_name} ({timestamp_local})",
            "Possible mis-slotted pallet",
            "warning",
          ),
        ],
        cameraConditions(ctx, picked, /aisle|rack|warehouse|storage/i),
        120,
        "alert",
      ),
  },
  {
    key: "ppe-check",
    icon: "🦺",
    title: "Someone entered the floor without PPE",
    blurb: "Person crosses the floor tripwire → VLM checks hard hat and hi-vis → alert",
    category: "industrial",
    needsGeometry: true,
    params: [{ name: "camera_id", label: "Which camera watches the floor entrance?", required: false }],
    build: (ctx, picked) =>
      synthRule(
        "PPE check at the floor entrance",
        { type: "line_cross", label: "person" },
        [
          {
            type: "verify",
            question:
              "Is this person missing a hard hat or a hi-vis vest? Answer yes only if PPE is clearly absent.",
            min_confidence: 0.65,
            on_fail: "stop",
          },
          alertAction(
            ctx,
            "🦺 PPE missing on {camera_name} ({timestamp_local})",
            "Someone entered the floor without PPE",
            "warning",
          ),
        ],
        cameraConditions(ctx, picked, /floor|entrance|shop|plant|line|gate/i),
        60,
        "alert",
      ),
  },
  {
    key: "hazard-zone-breach",
    icon: "⚠️",
    title: "Someone is standing in the hazard zone",
    blurb: "Person inside the exclusion polygon for 2s → critical alert",
    category: "industrial",
    needsGeometry: true,
    params: [{ name: "camera_id", label: "Which camera watches the cell?", required: false }],
    build: (ctx, picked) =>
      synthRule(
        "Hazard zone breach",
        { type: "loitering", label: "person", threshold_seconds: 2 },
        [
          {
            type: "notify",
            message: "⚠️ Person inside the hazard zone on {camera_name}",
            severity: "critical",
          },
          alertAction(
            ctx,
            "⚠️ Hazard zone breach on {camera_name} ({timestamp_local})",
            "Person inside the hazard zone",
            "warning",
          ),
        ],
        cameraConditions(ctx, picked, /cell|robot|press|machine|hazard|line/i),
        30,
        "alert",
      ),
  },
  {
    key: "line-stopped",
    icon: "⏱️",
    title: "The line has stopped moving",
    blurb: "Nothing crosses the conveyor zone for 5 min → open a maintenance ticket",
    category: "industrial",
    params: [{ name: "camera_id", label: "Which camera watches the conveyor?", required: false }],
    build: (ctx, picked) =>
      synthRule(
        "Line stopped",
        {
          type: "object_detected",
          // The absence alert: once something moves past, the next item must
          // appear within 5 minutes or on_timeout fires. See
          // docs/sequence-rules-design.md.
          sequence: {
            steps: [{ check: { type: "object_detected" }, within_seconds: 300 }],
            correlate_by: "camera",
            on_refire: "restart",
            on_timeout: [
              {
                type: "api_call",
                method: "POST",
                url: PLACEHOLDER_CMMS,
                payload_template: {
                  kind: "line_stoppage",
                  camera: "{{camera_name}}",
                  detected_at: "{{timestamp}}",
                },
              },
              {
                type: "notify",
                message: "⏱️ No movement on {camera_name} for 5 minutes. Line may be down.",
                severity: "critical",
              },
            ],
          },
        },
        [],
        cameraConditions(ctx, picked, /conveyor|line|station|assembly|belt/i),
        300,
        "alert",
      ),
  },
  {
    key: "forklift-pedestrian",
    icon: "🏗️",
    title: "A forklift and a person shared an aisle",
    blurb: "Person then vehicle in the same lane within 10s → critical near-miss alert",
    category: "industrial",
    params: [{ name: "camera_id", label: "Which camera watches the aisle?", required: false }],
    build: (ctx, picked) =>
      synthRule(
        "Forklift and pedestrian conflict",
        {
          type: "object_detected",
          label: "person",
          sequence: {
            steps: [{ check: { type: "object_detected", label: "truck" }, within_seconds: 10 }],
            correlate_by: "camera",
            on_refire: "ignore",
          },
        },
        [
          {
            type: "notify",
            message: "🏗️ Forklift and pedestrian in the same aisle on {camera_name}",
            severity: "critical",
          },
          alertAction(
            ctx,
            "🏗️ Near miss on {camera_name} ({timestamp_local}). Forklift and pedestrian in one aisle.",
            "Forklift and pedestrian in the same aisle",
            "warning",
          ),
        ],
        cameraConditions(ctx, picked, /aisle|warehouse|floor|dock|yard/i),
        60,
        "alert",
      ),
  },
];

export function findTemplate(key: string): RuleTemplate | undefined {
  return RULE_TEMPLATES.find((t) => t.key === key);
}
