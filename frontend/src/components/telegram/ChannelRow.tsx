"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAuth } from "@/lib/auth";
import { useToast, useConfirm } from "@/lib/feedback";
import {
  type TelegramChannel,
  type WebhookInfo,
  type TestResult,
  statusPill,
} from "./telegram-shared";
import { extractApiError } from "@/lib/api-error";

export function ChannelRow({
  channel,
  onChange,
  onResumePair,
}: {
  channel: TelegramChannel;
  onChange: () => void;
  onResumePair: () => void;
}) {
  const { authFetch } = useAuth();
  const toast = useToast();
  const confirm = useConfirm();
  const pill = statusPill(channel);
  const [savingField, setSavingField] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestResult | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [showDelete, setShowDelete] = useState(false);
  const [ruleCount, setRuleCount] = useState<number | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [webhookInfo, setWebhookInfo] = useState<WebhookInfo | null>(null);
  const [webhookBusy, setWebhookBusy] = useState(false);
  const [webhookError, setWebhookError] = useState<string | null>(null);
  // Local sliders. So the user can drag without firing a PATCH per tick.
  // Committed onMouseUp / onBlur.
  const [qpsLocal, setQpsLocal] = useState<number>(channel.rate_limit_per_chat_qps);
  const [burstLocal, setBurstLocal] = useState<number>(channel.rate_limit_per_chat_burst);
  const [dedupeLocal, setDedupeLocal] = useState<number>(channel.dedupe_window_seconds);
  useEffect(() => {
    setQpsLocal(channel.rate_limit_per_chat_qps);
    setBurstLocal(channel.rate_limit_per_chat_burst);
    setDedupeLocal(channel.dedupe_window_seconds);
  }, [channel.rate_limit_per_chat_qps, channel.rate_limit_per_chat_burst, channel.dedupe_window_seconds]);

  const fetchWebhookInfo = useCallback(async () => {
    try {
      const res = await authFetch(`/api/telegram/channels/${channel.id}/webhook-info`);
      if (res.ok) {
        setWebhookInfo(await res.json());
      } else {
        const body = await res.json().catch(() => null);
        setWebhookError(extractApiError(body, "Could not fetch webhook info"));
      }
    } catch {
      setWebhookError("Network error fetching webhook info");
    }
  }, [authFetch, channel.id]);

  useEffect(() => {
    if (!showAdvanced) return;
    void fetchWebhookInfo();
  }, [showAdvanced, fetchWebhookInfo]);

  const switchDelivery = async (mode: "long_poll" | "webhook", dropPending = false) => {
    setWebhookBusy(true);
    setWebhookError(null);
    try {
      const res = await authFetch(`/api/telegram/channels/${channel.id}/delivery`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode, drop_pending_updates: dropPending }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        setWebhookError(extractApiError(body, `Switch failed (${res.status}).`));
      } else {
        onChange();
        await fetchWebhookInfo();
      }
    } catch {
      setWebhookError("Network error.");
    } finally {
      setWebhookBusy(false);
    }
  };

  const requestSwitchToLongPoll = async () => {
    // Phase 3 UX note. If Telegram has pending updates queued, ask
    // before discarding them so the user doesn't lose acks/pairs in
    // flight.
    const pending = webhookInfo?.pending_update_count ?? 0;
    let drop = false;
    if (pending > 0) {
      drop = await confirm({
        title: `Discard ${pending} queued Telegram update${pending === 1 ? "" : "s"}?`,
        body: "Discard them and switch to long-poll, or keep them (Cancel) and they replay on the next poll.",
        confirmLabel: "Discard and switch",
        cancelLabel: "Keep and switch",
      });
    }
    await switchDelivery("long_poll", drop);
  };

  const patch = async (patchBody: Partial<TelegramChannel>) => {
    setSavingField(Object.keys(patchBody)[0] || null);
    try {
      const res = await authFetch(`/api/telegram/channels/${channel.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patchBody),
      });
      if (res.ok) onChange();
    } catch {
      /* silent */
    } finally {
      setSavingField(null);
    }
  };

  const runTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const res = await authFetch(`/api/telegram/channels/${channel.id}/test`, {
        method: "POST",
      });
      const data = await res.json();
      setTestResult(data);
      if (res.ok || res.status === 200) onChange();
    } catch {
      setTestResult({ ok: false, error: "Network error" });
    } finally {
      setTesting(false);
    }
  };

  const askDelete = async () => {
    setShowDelete(true);
    try {
      const res = await authFetch(`/api/telegram/channels/${channel.id}/rule-usage`);
      if (res.ok) {
        const data = await res.json();
        setRuleCount(typeof data.rule_count === "number" ? data.rule_count : 0);
      }
    } catch {
      setRuleCount(0);
    }
  };

  const confirmDelete = async () => {
    setDeleting(true);
    try {
      const res = await authFetch(`/api/telegram/channels/${channel.id}`, {
        method: "DELETE",
      });
      if (res.ok || res.status === 204) {
        onChange();
        setShowDelete(false);
      }
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="rounded-md border border-border bg-background/40 px-3 py-2.5">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <div className="text-sm font-medium truncate">{channel.label}</div>
            <span className={`text-[10px] px-1.5 py-0.5 rounded border ${pill.cls}`}>
              {pill.label}
            </span>
            <span
              className={`text-[10px] px-1.5 py-0.5 rounded border ${
                channel.delivery_mode === "webhook"
                  ? "bg-blue-500/15 text-blue-400 border-blue-500/30"
                  : "bg-muted text-muted-foreground border-border"
              }`}
              title={channel.delivery_mode === "webhook" ? "Updates arrive via webhook POST" : "Long-polling getUpdates"}
            >
              {channel.delivery_mode === "webhook" ? "Webhook" : "Long poll"}
            </span>
            {/* Phase 4. Owner badge + shared-by chip. */}
            <span
              className={`text-[10px] px-1.5 py-0.5 rounded border ${
                channel.owned_by_me
                  ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/30"
                  : "bg-purple-500/15 text-purple-400 border-purple-500/30"
              }`}
              title={
                channel.owned_by_me
                  ? "You own this channel"
                  : `Shared by ${channel.owner_display_name || "another user"}. You can use it in your rules.`
              }
            >
              {channel.owned_by_me
                ? "You"
                : `Shared by ${channel.owner_display_name || "other"}`}
            </span>
            {channel.shared_with_household && channel.owned_by_me && (
              <span className="text-[10px] px-1.5 py-0.5 rounded border bg-purple-500/15 text-purple-400 border-purple-500/30">
                Household
              </span>
            )}
          </div>
          <div className="text-[11px] text-muted-foreground mt-0.5 truncate">
            {channel.bot_username ? <span>@{channel.bot_username}</span> : <span>(no bot)</span>}
            {channel.chat_title ? <span> · {channel.chat_title}</span> : null}
            {channel.chat_type ? <span> · {channel.chat_type}</span> : null}
          </div>
          {channel.last_error && channel.pairing_status !== "paired" && (
            <div className="text-[11px] text-red-400 mt-0.5 truncate">{channel.last_error}</div>
          )}
        </div>

        <div className="flex items-center gap-2 flex-shrink-0">
          {channel.pairing_status === "pending" && (
            <button
              type="button"
              onClick={onResumePair}
              className="px-2 py-1 text-[11px] rounded border border-amber-500/40 text-amber-400 hover:bg-amber-500/10"
            >
              Resume pairing
            </button>
          )}

          {channel.pairing_status === "blocked" && (
            <button
              type="button"
              onClick={async () => {
                await patch({ enabled: true });
                await runTest();
              }}
              className="px-2 py-1 text-[11px] rounded border border-red-500/40 text-red-400 hover:bg-red-500/10"
            >
              Re-enable
            </button>
          )}

          <label
            className={`flex items-center gap-1 text-[11px] text-muted-foreground select-none ${
              channel.owned_by_me ? "cursor-pointer" : "cursor-not-allowed opacity-50"
            }`}
            title={channel.owned_by_me ? "" : "Owner-only setting"}
          >
            <input
              type="checkbox"
              checked={channel.default_silent}
              disabled={savingField !== null || !channel.owned_by_me}
              onChange={(e) => patch({ default_silent: e.target.checked })}
              className="accent-green-500"
            />
            silent
          </label>
          <label
            className={`flex items-center gap-1 text-[11px] text-muted-foreground select-none ${
              channel.owned_by_me ? "cursor-pointer" : "cursor-not-allowed opacity-50"
            }`}
            title={channel.owned_by_me ? "" : "Owner-only setting"}
          >
            <input
              type="checkbox"
              checked={channel.enabled}
              disabled={savingField !== null || !channel.owned_by_me}
              onChange={(e) => patch({ enabled: e.target.checked })}
              className="accent-green-500"
            />
            enabled
          </label>

          {channel.pairing_status === "paired" && (channel.owned_by_me || channel.share_permissions === "use_and_test") && (
            <button
              type="button"
              disabled={testing}
              onClick={runTest}
              className="px-2 py-1 text-[11px] rounded border border-border hover:bg-muted disabled:opacity-50"
            >
              {testing ? "Sending." : "Send test"}
            </button>
          )}

          <button
            type="button"
            onClick={() => setShowAdvanced((s) => !s)}
            className="px-2 py-1 text-[11px] rounded border border-border hover:bg-muted text-muted-foreground"
          >
            {showAdvanced ? "Hide advanced" : "Advanced"}
          </button>

          <button
            type="button"
            onClick={askDelete}
            disabled={!channel.owned_by_me}
            title={channel.owned_by_me ? "" : "Only the owner can delete a shared channel"}
            className="px-2 py-1 text-[11px] rounded border border-border hover:bg-muted text-muted-foreground disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent"
          >
            Delete
          </button>
        </div>
      </div>

      {showAdvanced && (
        <div className="mt-3 border-t border-border pt-3 space-y-4">
          {/* Phase 4. Household sharing. Visible to everyone; owner
              can toggle, non-owners see a tooltip explainer. */}
          <div>
            <div className="text-xs font-medium mb-1.5">Household sharing</div>
            {channel.owned_by_me ? (
              <>
                <label className="flex items-center gap-2 text-[11px] cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={channel.shared_with_household}
                    disabled={savingField !== null}
                    onChange={(e) =>
                      patch({ shared_with_household: e.target.checked } as Partial<TelegramChannel>)
                    }
                    className="accent-purple-500"
                  />
                  Share with household. Everyone can use this channel in their rules.
                </label>
                {channel.shared_with_household && (
                  <div className="mt-2">
                    <div className="text-[11px] text-muted-foreground mb-1">
                      Share permissions
                    </div>
                    <div className="flex gap-2">
                      {(["use", "use_and_test"] as const).map((p) => (
                        <label key={p} className="flex items-center gap-1.5 text-[11px] cursor-pointer">
                          <input
                            type="radio"
                            name={`share-${channel.id}`}
                            checked={channel.share_permissions === p}
                            disabled={savingField !== null}
                            onChange={() =>
                              patch({ share_permissions: p } as Partial<TelegramChannel>)
                            }
                            className="accent-purple-500"
                          />
                          {p === "use" ? "Use only" : "Use and test"}
                        </label>
                      ))}
                    </div>
                    <div className="text-[11px] text-muted-foreground mt-1">
                      Token + chat binding stay yours. Others can pick this channel for their
                      rules. &quot;Use and test&quot; also lets them fire the Send test button.
                    </div>
                  </div>
                )}
              </>
            ) : (
              <div className="text-[11px] text-muted-foreground bg-muted/30 border border-border rounded px-2 py-1.5">
                Shared by <span className="text-foreground/90 font-medium">{channel.owner_display_name || "another user"}</span>.
                You can pick this channel in your rules. Delete + token replacement are owner-only.
              </div>
            )}
          </div>

          {/* Owner-only knobs below. Non-owners see a short note. */}
          {!channel.owned_by_me && (
            <div className="text-[11px] text-muted-foreground">
              Delivery, media quality, rate limit, and dedupe are owner-only.
            </div>
          )}
          {channel.owned_by_me && (
          <>
          {/* Delivery mode */}
          <div>
            <div className="text-xs font-medium mb-1.5">Delivery mode</div>
            <div className="flex gap-2">
              <label className="flex items-center gap-1.5 text-[11px] cursor-pointer">
                <input
                  type="radio"
                  name={`delivery-${channel.id}`}
                  checked={channel.delivery_mode === "long_poll"}
                  disabled={webhookBusy}
                  onChange={() => void requestSwitchToLongPoll()}
                  className="accent-green-500"
                />
                Long poll (default)
              </label>
              <label className="flex items-center gap-1.5 text-[11px] cursor-pointer">
                <input
                  type="radio"
                  name={`delivery-${channel.id}`}
                  checked={channel.delivery_mode === "webhook"}
                  disabled={webhookBusy}
                  onChange={() => void switchDelivery("webhook")}
                  className="accent-blue-500"
                />
                Webhook (requires public URL)
              </label>
            </div>
            {webhookError && (
              <div className="mt-1.5 text-[11px] text-red-400 bg-red-500/10 border border-red-500/30 rounded px-2 py-1">
                {webhookError}
                {/not set/i.test(webhookError) && (
                  <>
                    {" "}
                    <a href="/settings#system" className="underline">
                      Open System settings
                    </a>
                  </>
                )}
              </div>
            )}
            {channel.delivery_mode === "webhook" && webhookInfo && (
              <div className="mt-2 text-[11px] text-muted-foreground space-y-1">
                <div>
                  URL.{" "}
                  <span className="font-mono text-foreground/90 break-all">
                    {webhookInfo.url || "(not registered)"}
                  </span>
                </div>
                <div>
                  Pending updates.{" "}
                  <span
                    className={
                      webhookInfo.pending_update_count > 0
                        ? "text-amber-400 font-medium"
                        : "text-foreground/80"
                    }
                  >
                    {webhookInfo.pending_update_count}
                  </span>
                </div>
                {webhookInfo.pending_update_count > 0 && (
                  <div className="text-amber-400">
                    Telegram has {webhookInfo.pending_update_count} unprocessed updates.
                    Check your public URL is reachable.
                  </div>
                )}
                {webhookInfo.last_error_message && (
                  <div className="text-red-400">
                    Last error. {webhookInfo.last_error_message}
                  </div>
                )}
                {webhookInfo.backend_reachable === false && (
                  <div className="text-red-400">
                    Backend not reachable at the public URL.{" "}
                    {webhookInfo.backend_probe_error || "Webhook delivery will silently fail."}
                  </div>
                )}
                <div className="flex gap-2 pt-1">
                  <button
                    type="button"
                    onClick={() => void fetchWebhookInfo()}
                    className="px-2 py-0.5 text-[10px] rounded border border-border hover:bg-muted"
                  >
                    Refresh
                  </button>
                  <button
                    type="button"
                    disabled={webhookBusy}
                    onClick={async () => {
                      setWebhookBusy(true);
                      try {
                        await authFetch(
                          `/api/telegram/channels/${channel.id}/refresh-webhook`,
                          { method: "POST" },
                        );
                        await fetchWebhookInfo();
                        onChange();
                      } finally {
                        setWebhookBusy(false);
                      }
                    }}
                    className="px-2 py-0.5 text-[10px] rounded border border-border hover:bg-muted disabled:opacity-50"
                  >
                    Refresh URL with Telegram
                  </button>
                  <button
                    type="button"
                    onClick={async () => {
                      const res = await authFetch(
                        `/api/telegram/channels/${channel.id}/test-webhook-delivery`,
                        { method: "POST" },
                      );
                      const data = await res.json().catch(() => null);
                      if (data?.ok) {
                        toast.success(`Backend reachable at ${data?.probed_url || "public URL"}.`);
                      } else {
                        toast.error(`Backend not reachable. ${data?.error || "unknown error"}`);
                      }
                    }}
                    className="px-2 py-0.5 text-[10px] rounded border border-border hover:bg-muted"
                  >
                    Test webhook delivery
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* Media quality */}
          <div>
            <div className="text-xs font-medium mb-1.5">Media quality</div>
            <div className="flex gap-2">
              {(["off", "low", "high"] as const).map((q) => (
                <label key={q} className="flex items-center gap-1.5 text-[11px] cursor-pointer">
                  <input
                    type="radio"
                    name={`media-${channel.id}`}
                    checked={channel.media_quality === q}
                    disabled={savingField !== null}
                    onChange={() => void patch({ media_quality: q } as Partial<TelegramChannel>)}
                    className="accent-green-500"
                  />
                  {q === "off" ? "Off" : q === "low" ? "Low (720p, q70)" : "High (original)"}
                </label>
              ))}
            </div>
            <div className="text-[11px] text-muted-foreground mt-1">
              Low reduces bandwidth for outdoor cameras. Off sends text alerts only.
            </div>
          </div>

          {/* Per-chat rate limit */}
          <div>
            <div className="text-xs font-medium mb-1.5">Per-chat rate limit</div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <div className="text-[11px] text-muted-foreground mb-0.5">
                  QPS. <span className="text-foreground/90">{qpsLocal.toFixed(2)}</span>
                </div>
                <input
                  type="range"
                  min={0.2}
                  max={5.0}
                  step={0.1}
                  value={qpsLocal}
                  onChange={(e) => setQpsLocal(parseFloat(e.target.value))}
                  onMouseUp={() => void patch({ rate_limit_per_chat_qps: qpsLocal } as Partial<TelegramChannel>)}
                  onTouchEnd={() => void patch({ rate_limit_per_chat_qps: qpsLocal } as Partial<TelegramChannel>)}
                  className="w-full accent-green-500"
                />
              </div>
              <div>
                <div className="text-[11px] text-muted-foreground mb-0.5">
                  Burst. <span className="text-foreground/90">{burstLocal}</span>
                </div>
                <input
                  type="range"
                  min={1}
                  max={10}
                  step={1}
                  value={burstLocal}
                  onChange={(e) => setBurstLocal(parseInt(e.target.value, 10))}
                  onMouseUp={() => void patch({ rate_limit_per_chat_burst: burstLocal } as Partial<TelegramChannel>)}
                  onTouchEnd={() => void patch({ rate_limit_per_chat_burst: burstLocal } as Partial<TelegramChannel>)}
                  className="w-full accent-green-500"
                />
              </div>
            </div>
            <div className="text-[11px] text-muted-foreground mt-1">
              Telegram limits group chats to 20 messages/minute. Tighten if you hit blockages.
            </div>
          </div>

          {/* Dedupe window */}
          <div>
            <div className="text-xs font-medium mb-1.5">
              Dedupe window.{" "}
              <span className="text-muted-foreground font-normal">{dedupeLocal}s</span>
            </div>
            <input
              type="range"
              min={0}
              max={300}
              step={5}
              value={dedupeLocal}
              onChange={(e) => setDedupeLocal(parseInt(e.target.value, 10))}
              onMouseUp={() => void patch({ dedupe_window_seconds: dedupeLocal } as Partial<TelegramChannel>)}
              onTouchEnd={() => void patch({ dedupe_window_seconds: dedupeLocal } as Partial<TelegramChannel>)}
              className="w-full accent-green-500"
            />
            <div className="text-[11px] text-muted-foreground mt-1">
              Suppresses identical messages within this window so a chatty rule doesn&apos;t spam.
            </div>
          </div>
          </>
          )}
        </div>
      )}

      {testResult && (
        <div
          className={`mt-2 text-[11px] rounded px-2 py-1 ${
            testResult.ok
              ? "bg-green-500/10 text-green-400 border border-green-500/30"
              : "bg-red-500/10 text-red-400 border border-red-500/30"
          }`}
        >
          {testResult.ok
            ? `Sent ✓ (message id ${testResult.message_id ?? "?"})`
            : `Failed. ${testResult.error || "Telegram rejected the send."}`}
        </div>
      )}

      {showDelete && (
        <div className="mt-3 border-t border-border pt-3">
          <div className="text-xs text-foreground/90 mb-2">
            This will stop alerts to{" "}
            <span className="font-medium">{channel.chat_title || channel.label}</span>. Existing
            rules using this channel will silently no-op until you point them at another channel.
          </div>
          <div className="text-[11px] text-muted-foreground mb-3">
            {ruleCount === null
              ? "Checking rule usage."
              : ruleCount === 0
              ? "No rules reference this channel."
              : `${ruleCount} rule${ruleCount === 1 ? "" : "s"} currently reference this channel.`}
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={deleting}
              onClick={confirmDelete}
              className="px-3 py-1.5 text-xs rounded border border-red-500/40 text-red-400 hover:bg-red-500/10 disabled:opacity-50"
            >
              {deleting ? "Deleting." : "Delete channel"}
            </button>
            <button
              type="button"
              onClick={() => setShowDelete(false)}
              className="px-3 py-1.5 text-xs rounded border border-border hover:bg-muted"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
