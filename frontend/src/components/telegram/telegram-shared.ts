// Shared Telegram types + status helper. Extracted from
// TelegramSection.tsx (no behavior change).

export interface TelegramChannel {
  id: string;
  label: string;
  bot_username: string | null;
  chat_id: string | null;
  chat_title: string | null;
  chat_type: string | null;
  default_silent: boolean;
  enabled: boolean;
  paired_at: string | null;
  last_test_at: string | null;
  last_test_ok: boolean | null;
  last_error: string | null;
  pairing_status: "pending" | "paired" | "blocked" | "disabled" | "error";
  // Phase 3 fields. Webhook_secret is intentionally never sent over the wire.
  delivery_mode: "long_poll" | "webhook";
  webhook_url: string | null;
  media_quality: "off" | "low" | "high";
  rate_limit_per_chat_qps: number;
  rate_limit_per_chat_burst: number;
  dedupe_window_seconds: number;
  // Phase 4 household sharing.
  shared_with_household: boolean;
  share_permissions: "use" | "use_and_test";
  owned_by_me: boolean;
  owner_display_name: string | null;
  created_at: string;
}

export interface WebhookInfo {
  url: string | null;
  has_custom_certificate: boolean;
  pending_update_count: number;
  last_error_date: number | null;
  last_error_message: string | null;
  ip_address: string | null;
  max_connections: number | null;
  backend_reachable: boolean | null;
  backend_probe_error: string | null;
}

export interface PairInit {
  nonce: string;
  deep_link: string;
  qr_payload: string;
  expires_in_seconds: number;
}

export interface TestResult {
  ok: boolean;
  message_id?: number | null;
  error?: string | null;
}

export function statusPill(c: TelegramChannel): { label: string; cls: string } {
  switch (c.pairing_status) {
    case "paired":
      return { label: "Paired", cls: "bg-green-500/15 text-green-400 border-green-500/30" };
    case "pending":
      return { label: "Pending pairing", cls: "bg-amber-500/15 text-amber-400 border-amber-500/30" };
    case "blocked":
      return { label: "Blocked", cls: "bg-red-500/15 text-red-400 border-red-500/30" };
    case "disabled":
      return { label: "Disabled", cls: "bg-muted text-muted-foreground border-border" };
    case "error":
    default:
      return { label: "Error", cls: "bg-red-500/15 text-red-400 border-red-500/30" };
  }
}
