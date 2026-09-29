"use client";

// Invite Keys manager. Replaces the old cramped list+form modal with two
// clear modes:
//   • "keys"   — audit view: every key as a card with status, a usage bar,
//                and an expandable roster of who redeemed it and when.
//   • "invite" — a focused "invite a new user" form that, on success, shows
//                the fresh key + share link ready to copy.
// The parent owns the key list (the Settings card shows a count), so this
// component takes the list in and calls onChanged() after any mutation.

import { useState } from "react";
import { useAuth } from "@/lib/auth";
import { Locale, translate } from "@/lib/i18n";
import { formatDate, formatDateTime, timeAgo } from "@/lib/time";
import {
  Camera,
  InviteKey,
  InviteRedemption,
  inviteKeyStatus,
} from "./settings-helpers";

type Mode = "keys" | "invite";

const STATUS_STYLE: Record<string, { label: string; cls: string }> = {
  active: { label: "Active", cls: "text-green-400 bg-green-500/10 border-green-500/30" },
  expired: { label: "Expired", cls: "text-red-400 bg-red-500/10 border-red-500/30" },
  full: { label: "Fully used", cls: "text-amber-400 bg-amber-500/10 border-amber-500/30" },
};

function roleLabel(role: string): string {
  return role.charAt(0).toUpperCase() + role.slice(1);
}

function inviteLink(key: string): string {
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  return `${origin}/invite?key=${key}`;
}

export default function InviteKeysModal({
  inviteKeys,
  cameras,
  onClose,
  onChanged,
}: {
  inviteKeys: InviteKey[];
  cameras: Camera[];
  onClose: () => void;
  onChanged: () => void;
}) {
  const { authFetch, user } = useAuth();
  const locale = (user?.locale as Locale) || "en";
  const t = (key: string, values?: Record<string, string | number>) => translate(locale, key, values);
  const [mode, setMode] = useState<Mode>("keys");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="relative bg-card border border-border rounded-lg w-full max-w-lg shadow-xl max-h-[85vh] flex flex-col">
        {/* Header */}
        <div className="flex items-start justify-between px-6 pt-5 pb-4 border-b border-border">
          <div>
            <h2 className="text-lg font-semibold">{t("invite.keys")}</h2>
            <p className="text-xs text-muted-foreground mt-0.5">
              {t("invite.help")}
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label={t("invite.close")}
            className="text-muted-foreground hover:text-foreground text-xl leading-none -mt-1"
          >
            ×
          </button>
        </div>

        {/* Body */}
        <div className="overflow-y-auto px-6 py-4 flex-1">
          {mode === "keys" ? (
            <KeysView
              inviteKeys={inviteKeys}
              onInviteNew={() => setMode("invite")}
              onChanged={onChanged}
              locale={locale}
            />
          ) : (
            <InviteForm
              cameras={cameras}
              authFetch={authFetch}
              onDone={() => {
                onChanged();
                setMode("keys");
              }}
              onCancel={() => setMode("keys")}
              locale={locale}
            />
          )}
        </div>
      </div>
    </div>
  );
}

// ── Keys audit view ──────────────────────────────────────────────────

function KeysView({
  inviteKeys,
  onInviteNew,
  onChanged,
  locale,
}: {
  inviteKeys: InviteKey[];
  onInviteNew: () => void;
  onChanged: () => void;
  locale: Locale;
}) {
  const t = (key: string, values?: Record<string, string | number>) => translate(locale, key, values);
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">
          {inviteKeys.length === 0
            ? t("invite.no_keys")
            : t(inviteKeys.length === 1 ? "invite.key_count" : "invite.key_count_plural", { count: inviteKeys.length })}
        </span>
        <button
          onClick={onInviteNew}
          className="px-3 py-1.5 text-sm rounded-md bg-foreground text-background font-medium hover:opacity-90"
        >
          {t("invite.new_user")}
        </button>
      </div>

      {inviteKeys.length === 0 ? (
        <div className="rounded-md border border-dashed border-border bg-background/40 px-4 py-8 text-center">
          <p className="text-sm text-muted-foreground">
            {t("invite.none_yet")}
          </p>
          <button
            onClick={onInviteNew}
            className="mt-3 px-3 py-1.5 text-sm rounded-md border border-border hover:bg-muted transition-colors"
          >
            {t("invite.first")}
          </button>
        </div>
      ) : (
        <div className="space-y-2.5">
          {inviteKeys.map((ik) => (
            <KeyCard key={ik.id} ik={ik} onChanged={onChanged} locale={locale} />
          ))}
        </div>
      )}
    </div>
  );
}

function KeyCard({ ik, onChanged, locale }: { ik: InviteKey; onChanged: () => void; locale: Locale }) {
  const { authFetch } = useAuth();
  const t = (key: string, values?: Record<string, string | number>) => translate(locale, key, values);
  const [copied, setCopied] = useState(false);
  const [showKey, setShowKey] = useState(false);
  const [showUsers, setShowUsers] = useState(false);
  const [revoking, setRevoking] = useState(false);
  const [confirmRevoke, setConfirmRevoke] = useState(false);

  const status = inviteKeyStatus(ik);
  const pill = STATUS_STYLE[status];
  const statusLabel = status === "active" ? t("invite.active") : status === "expired" ? t("invite.expired") : t("invite.full");
  const pct = ik.max_uses > 0 ? Math.min(100, (ik.use_count / ik.max_uses) * 100) : 0;
  const remaining = Math.max(0, ik.max_uses - ik.use_count);

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(inviteLink(ik.key));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard unavailable (http / permissions); key stays selectable */
    }
  };

  const revoke = async () => {
    setRevoking(true);
    try {
      await authFetch(`/api/invites/${ik.id}`, { method: "DELETE" });
      onChanged();
    } catch {
      setRevoking(false);
      setConfirmRevoke(false);
    }
  };

  return (
    <div className="rounded-lg border border-border bg-background p-3.5 space-y-3">
      {/* Top: role + status + created context */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-medium">{roleLabel(ik.role)}</span>
          <span className={`text-[10px] uppercase tracking-wider border rounded px-1.5 py-0.5 ${pill.cls}`}>
            {statusLabel}
          </span>
        </div>
        <div className="text-[11px] text-muted-foreground text-right whitespace-nowrap">
          {t("invite.created", { date: formatDate(ik.created_at) })}
          {ik.created_by && (
            <div className="truncate max-w-[160px]">
              by {ik.created_by.display_name || ik.created_by.email}
            </div>
          )}
        </div>
      </div>

      {/* Key + copy link */}
      <div className="flex items-center gap-1.5">
        <code
          className="flex-1 min-w-0 text-xs font-mono bg-muted px-2 py-1.5 rounded select-all truncate"
          title={ik.key}
        >
          {showKey ? ik.key : `${ik.key.slice(0, 6)}${"•".repeat(10)}`}
        </code>
        <button
          onClick={() => setShowKey((v) => !v)}
          className="px-2 py-1.5 text-[11px] rounded border border-border hover:bg-muted transition-colors flex-shrink-0"
        >
          {showKey ? t("invite.hide") : t("invite.show")}
        </button>
        <button
          onClick={copyLink}
          className="px-2 py-1.5 text-[11px] rounded border border-border hover:bg-muted transition-colors flex-shrink-0"
        >
          {copied ? t("invite.copied") : t("invite.copy_link")}
        </button>
      </div>

      {/* Usage bar */}
      <div className="space-y-1">
        <div className="flex items-center justify-between text-[11px] text-muted-foreground">
          <span>
            {t("invite.used", { used: ik.use_count, max: ik.max_uses })}
            {status === "active" && remaining > 0 && t("invite.left", { count: remaining })}
          </span>
          <span>
            {ik.expires_at === null
              ? t("invite.never_expires")
              : status === "expired"
                ? t("invite.expired_on", { date: formatDate(ik.expires_at) })
                : t("invite.expires", { date: formatDate(ik.expires_at) })}
          </span>
        </div>
        <div className="h-1.5 rounded-full bg-muted overflow-hidden">
          <div
            className={`h-full rounded-full transition-all ${
              status === "full" ? "bg-amber-500" : status === "expired" ? "bg-red-500/60" : "bg-green-500"
            }`}
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      {/* Redemptions roster */}
      {ik.redemptions.length > 0 && (
        <div className="border-t border-border pt-2.5">
          <button
            onClick={() => setShowUsers((v) => !v)}
            className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            <span className={`transition-transform ${showUsers ? "rotate-90" : ""}`}>›</span>
            {t("invite.used_by", { count: ik.redemptions.length, kind: ik.redemptions.length === 1 ? t("invite.person") : t("invite.people") })}
          </button>
          {showUsers && (
            <ul className="mt-2 space-y-1.5">
              {ik.redemptions.map((r) => (
                <RedemptionRow key={r.user_id} r={r} locale={locale} />
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Revoke */}
      <div className="flex justify-end">
        {confirmRevoke ? (
          <div className="flex items-center gap-2 text-[11px]">
            <span className="text-muted-foreground">{t("invite.revoke_question")}</span>
            <button
              onClick={revoke}
              disabled={revoking}
              className="px-2 py-1 rounded border border-red-800 text-red-400 hover:bg-red-900/30 disabled:opacity-50"
            >
              {revoking ? t("invite.revoking") : t("invite.revoke")}
            </button>
            <button
              onClick={() => setConfirmRevoke(false)}
              className="px-2 py-1 rounded border border-border hover:bg-muted"
            >
              {t("invite.keep")}
            </button>
          </div>
        ) : (
          <button
            onClick={() => setConfirmRevoke(true)}
            className="text-[11px] text-red-400/80 hover:text-red-400 transition-colors"
          >
            {t("invite.revoke_key")}
          </button>
        )}
      </div>
    </div>
  );
}

function RedemptionRow({ r, locale }: { r: InviteRedemption; locale: Locale }) {
  const t = (key: string) => translate(locale, key);
  const name = r.display_name || r.email;
  return (
    <li className="flex items-center gap-2 text-xs">
      <span className="w-6 h-6 rounded-full bg-muted flex items-center justify-center text-[10px] font-medium uppercase flex-shrink-0">
        {name.charAt(0)}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="font-medium truncate">{name}</span>
          {!r.is_active && (
            <span className="text-[9px] uppercase tracking-wide text-muted-foreground border border-border rounded px-1">
              {t("invite.disabled")}
            </span>
          )}
        </div>
        {r.display_name && (
          <div className="text-[11px] text-muted-foreground truncate">{r.email}</div>
        )}
      </div>
      <span
        className="text-[11px] text-muted-foreground whitespace-nowrap flex-shrink-0"
        title={formatDateTime(r.redeemed_at)}
      >
        {timeAgo(r.redeemed_at)}
      </span>
    </li>
  );
}

// ── Invite new user form ─────────────────────────────────────────────

function InviteForm({
  cameras,
  authFetch,
  onDone,
  onCancel,
  locale,
}: {
  cameras: Camera[];
  authFetch: (input: string, init?: RequestInit) => Promise<Response>;
  onDone: () => void;
  onCancel: () => void;
  locale: Locale;
}) {
  const t = (key: string, values?: Record<string, string | number>) => translate(locale, key, values);
  const [role, setRole] = useState("viewer");
  const [maxUses, setMaxUses] = useState(1);
  const [expiryDays, setExpiryDays] = useState(7);
  const [cameraIds, setCameraIds] = useState<string[]>([]);
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState<InviteKey | null>(null);
  const [copied, setCopied] = useState(false);

  const create = async () => {
    setCreating(true);
    try {
      const body: Record<string, unknown> = { role, max_uses: maxUses };
      if (cameraIds.length > 0) body.camera_ids = cameraIds;
      if (expiryDays > 0) {
        body.expires_at = new Date(
          Date.now() + expiryDays * 24 * 60 * 60 * 1000
        ).toISOString();
      }
      const res = await authFetch("/api/invites", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.ok) setCreated(await res.json());
    } catch {
      /* silent; user can retry */
    } finally {
      setCreating(false);
    }
  };

  const copyLink = async () => {
    if (!created) return;
    try {
      await navigator.clipboard.writeText(inviteLink(created.key));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard unavailable */
    }
  };

  // Success state: surface the fresh key + link ready to hand off.
  if (created) {
    return (
      <div className="space-y-4">
        <div className="text-center">
          <div className="w-11 h-11 rounded-full bg-green-500/15 border border-green-500/30 flex items-center justify-center mx-auto mb-2 text-green-400 text-xl">
            ✓
          </div>
          <h3 className="text-sm font-semibold">{t("invite.ready")}</h3>
          <p className="text-xs text-muted-foreground mt-1">
            {t(created.max_uses > 1 ? "invite.ready_help_many" : "invite.ready_help_one", {
              role: roleLabel(created.role),
              count: created.max_uses,
            })}
          </p>
        </div>

        <div className="rounded-md border border-border bg-background p-3 space-y-2">
          <label className="text-[11px] font-medium text-muted-foreground">{t("invite.share_link")}</label>
          <div className="flex items-center gap-1.5">
            <code className="flex-1 min-w-0 text-xs font-mono bg-muted px-2 py-1.5 rounded select-all truncate">
              {inviteLink(created.key)}
            </code>
            <button
              onClick={copyLink}
              className="px-3 py-1.5 text-xs rounded border border-border hover:bg-muted transition-colors flex-shrink-0"
            >
              {copied ? t("invite.copied") : t("invite.copy")}
            </button>
          </div>
          <div className="text-[11px] text-muted-foreground">
            {t("invite.share_key")} {" "}
            <code className="font-mono select-all">{created.key}</code>
          </div>
        </div>

        <div className="flex justify-end gap-2">
          <button
            onClick={() => {
              setCreated(null);
              setRole("viewer");
              setMaxUses(1);
              setExpiryDays(7);
              setCameraIds([]);
            }}
            className="px-3 py-1.5 text-sm rounded-md border border-border hover:bg-muted transition-colors"
          >
            {t("invite.another")}
          </button>
          <button
            onClick={onDone}
            className="px-3 py-1.5 text-sm rounded-md bg-foreground text-background font-medium hover:opacity-90"
          >
            {t("invite.done")}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <button
        onClick={onCancel}
        className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
      >
        <span>‹</span> {t("invite.back")}
      </button>

      <div>
        <label className="text-xs font-medium text-muted-foreground block mb-1">{t("invite.role")}</label>
        <select
          value={role}
          onChange={(e) => setRole(e.target.value)}
          className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm focus:outline-none focus:border-accent"
        >
          <option value="viewer">{t("invite.viewer")}</option>
          <option value="admin">{t("invite.admin")}</option>
        </select>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs font-medium text-muted-foreground block mb-1">
            {t("invite.max_uses")}
          </label>
          <input
            type="number"
            min={1}
            max={100}
            value={maxUses}
            onChange={(e) => setMaxUses(Math.max(1, Number(e.target.value)))}
            className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm focus:outline-none focus:border-accent"
          />
          <p className="text-[10px] text-muted-foreground mt-1">
            {t("invite.max_uses_help")}
          </p>
        </div>
        <div>
          <label className="text-xs font-medium text-muted-foreground block mb-1">{t("invite.expires_label")}</label>
          <select
            value={expiryDays}
            onChange={(e) => setExpiryDays(Number(e.target.value))}
            className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm focus:outline-none focus:border-accent"
          >
            <option value={0}>{t("invite.never")}</option>
            <option value={1}>{t("invite.in_day")}</option>
            <option value={7}>{t("invite.in_days", { count: 7 })}</option>
            <option value={30}>{t("invite.in_days", { count: 30 })}</option>
          </select>
          <p className="text-[10px] text-muted-foreground mt-1">
            {t("invite.expires_help")}
          </p>
        </div>
      </div>

      {cameras.length > 0 && (
        <div>
          <label className="text-xs font-medium text-muted-foreground block mb-1">
            {t("invite.camera_access")}
          </label>
          <div className="space-y-1 max-h-32 overflow-y-auto rounded-md border border-border bg-background p-2">
            {cameras.map((cam) => (
              <label key={cam.id} className="flex items-center gap-2 cursor-pointer text-sm">
                <input
                  type="checkbox"
                  checked={cameraIds.includes(cam.id)}
                  onChange={(e) => {
                    if (e.target.checked) setCameraIds([...cameraIds, cam.id]);
                    else setCameraIds(cameraIds.filter((id) => id !== cam.id));
                  }}
                  className="accent-accent"
                />
                {cam.name}
              </label>
            ))}
          </div>
          <p className="text-[10px] text-muted-foreground mt-1">
            {t("invite.no_camera_access")}
          </p>
        </div>
      )}

      <div className="flex justify-end gap-2 pt-1">
        <button
          onClick={onCancel}
          className="px-3 py-1.5 text-sm rounded-md border border-border hover:bg-muted transition-colors"
        >
          {t("invite.cancel")}
        </button>
        <button
          onClick={create}
          disabled={creating}
          className="px-3 py-1.5 text-sm rounded-md bg-foreground text-background font-medium hover:opacity-90 disabled:opacity-50"
        >
          {creating ? t("invite.creating") : t("invite.create")}
        </button>
      </div>
    </div>
  );
}
