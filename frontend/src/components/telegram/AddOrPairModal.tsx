"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAuth } from "@/lib/auth";
import { useToast, useConfirm } from "@/lib/feedback";
import {
  type TelegramChannel,
  type PairInit,
} from "./telegram-shared";

export function AddOrPairModal({
  existingChannelId,
  onClose,
  onChannelChange,
}: {
  existingChannelId: string | null;
  onClose: () => void;
  onChannelChange: () => void;
}) {
  const { authFetch } = useAuth();
  // Steps. 1 = enter token, 2 = pair, 3 = success
  const [step, setStep] = useState<1 | 2 | 3>(existingChannelId ? 2 : 1);
  const [label, setLabel] = useState("");
  const [token, setToken] = useState("");
  const [showToken, setShowToken] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [channelId, setChannelId] = useState<string | null>(existingChannelId);
  const [pair, setPair] = useState<PairInit | null>(null);
  const [pairTab, setPairTab] = useState<"dm" | "group">("dm");
  const [pairChannel, setPairChannel] = useState<TelegramChannel | null>(null);
  const [pairExpired, setPairExpired] = useState(false);
  const [secondsLeft, setSecondsLeft] = useState(0);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    if (tickRef.current) {
      clearInterval(tickRef.current);
      tickRef.current = null;
    }
  }, []);

  useEffect(() => {
    return stopPolling;
  }, [stopPolling]);

  const beginPair = useCallback(
    async (id: string) => {
      setError(null);
      try {
        const res = await authFetch(`/api/telegram/channels/${id}/pair-init`, {
          method: "POST",
        });
        if (!res.ok) {
          const body = await res.json().catch(() => null);
          setError(body?.detail || "Could not start pairing.");
          return;
        }
        const data: PairInit = await res.json();
        setPair(data);
        setPairExpired(false);
        setSecondsLeft(data.expires_in_seconds);
      } catch {
        setError("Network error starting pairing.");
      }
    },
    [authFetch]
  );

  // When we arrive at step 2 with a known channelId, kick off pairing.
  useEffect(() => {
    if (step !== 2 || !channelId) return;
    beginPair(channelId);
  }, [step, channelId, beginPair]);

  // Poll for pairing completion every 2s and count down the nonce TTL.
  useEffect(() => {
    if (step !== 2 || !channelId || !pair) return;
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const res = await authFetch(`/api/telegram/channels/${channelId}`);
        if (res.ok) {
          const data: TelegramChannel = await res.json();
          setPairChannel(data);
          if (data.pairing_status === "paired") {
            stopPolling();
            setStep(3);
            onChannelChange();
          }
        }
      } catch {
        /* silent */
      }
    }, 2000);

    tickRef.current = setInterval(() => {
      setSecondsLeft((s) => {
        if (s <= 1) {
          setPairExpired(true);
          if (pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
          }
          if (tickRef.current) {
            clearInterval(tickRef.current);
            tickRef.current = null;
          }
          return 0;
        }
        return s - 1;
      });
    }, 1000);

    return stopPolling;
  }, [step, channelId, pair, authFetch, stopPolling, onChannelChange]);

  const submitStep1 = async () => {
    setError(null);
    if (!label.trim()) {
      setError("Label is required.");
      return;
    }
    if (!token.trim()) {
      setError("Bot token is required.");
      return;
    }
    setSubmitting(true);
    try {
      const res = await authFetch("/api/telegram/channels", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ label: label.trim(), bot_token: token.trim() }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        setError(body?.detail || `Telegram rejected the token (${res.status}).`);
        return;
      }
      const ch: TelegramChannel = await res.json();
      setChannelId(ch.id);
      setStep(2);
      onChannelChange();
    } catch {
      setError("Network error. Try again.");
    } finally {
      setSubmitting(false);
    }
  };

  const restartPair = async () => {
    if (!channelId) return;
    await beginPair(channelId);
  };

  const sendTest = async () => {
    if (!channelId) return;
    try {
      await authFetch(`/api/telegram/channels/${channelId}/test`, { method: "POST" });
      onChannelChange();
    } catch {
      /* silent */
    }
  };

  const qrSrc = useMemo(() => {
    if (!pair) return null;
    // Fallback to api.qrserver.com — no local QR lib available. Phase 2
    // can swap this for a local renderer (e.g. qrcode.react).
    return `https://api.qrserver.com/v1/create-qr-code/?size=240x240&data=${encodeURIComponent(
      pair.qr_payload
    )}`;
  }, [pair]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="relative bg-card border border-border rounded-lg p-6 w-full max-w-lg shadow-xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-start justify-between mb-2">
          <h2 className="text-lg font-semibold">
            {step === 1 ? "Add Telegram channel" : step === 2 ? "Pair with Telegram" : "Paired"}
          </h2>
          <button
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground text-lg leading-none"
          >
            ×
          </button>
        </div>

        {step === 1 && (
          <>
            <p className="text-xs text-muted-foreground mb-3">
              Telegram alerts are sent by a bot you create. it is free and takes about a
              minute. You will make a bot, then choose where it sends. a private chat, a
              group, or a channel.
            </p>
            <div className="rounded-md border border-border bg-background/50 p-3 mb-4 space-y-2">
              <div className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                Step 1. Create your bot and get its token
              </div>
              <ol className="text-xs text-muted-foreground space-y-1.5 list-decimal pl-4">
                <li>
                  Open{" "}
                  <a
                    href="https://t.me/BotFather"
                    target="_blank"
                    rel="noreferrer"
                    className="text-accent hover:underline font-medium"
                  >
                    @BotFather
                  </a>{" "}
                  in Telegram (the official bot maker) and press <span className="font-medium">Start</span>.
                </li>
                <li>
                  Send <span className="font-mono text-foreground">/newbot</span>. It asks for a
                  name (e.g. <span className="text-foreground">Home Alerts</span>) and a username
                  ending in <span className="font-mono text-foreground">bot</span>.
                </li>
                <li>
                  BotFather replies with a <span className="font-medium text-foreground">token</span> that
                  looks like <span className="font-mono text-foreground">123456789:ABCdef...</span>. Copy it.
                </li>
                <li>Paste the token below. Nurby checks it instantly.</li>
              </ol>
            </div>
            <div className="space-y-3">
              <div>
                <label className="text-xs font-medium text-muted-foreground block mb-1">
                  Label
                </label>
                <input
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                  placeholder="Family alerts"
                  className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm"
                />
              </div>
              <div>
                <label className="text-xs font-medium text-muted-foreground block mb-1">
                  Bot token
                </label>
                <div className="flex gap-2">
                  <input
                    type={showToken ? "text" : "password"}
                    value={token}
                    onChange={(e) => setToken(e.target.value)}
                    placeholder="123456:ABC-DEF..."
                    className="flex-1 px-3 py-2 rounded-md bg-background border border-border text-sm font-mono"
                  />
                  <button
                    type="button"
                    onClick={() => setShowToken((s) => !s)}
                    className="px-3 py-2 text-xs rounded-md border border-border hover:bg-muted"
                  >
                    {showToken ? "Hide" : "Show"}
                  </button>
                </div>
              </div>
              {error && (
                <div className="text-xs text-red-400 bg-red-500/10 border border-red-500/30 rounded px-2 py-1.5">
                  {error}
                </div>
              )}
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={onClose}
                  className="px-3 py-1.5 text-xs rounded-md border border-border hover:bg-muted"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  disabled={submitting}
                  onClick={submitStep1}
                  className="px-3 py-1.5 text-xs rounded-md border border-green-500/40 bg-green-500/10 text-green-400 hover:bg-green-500/20 disabled:opacity-50"
                >
                  {submitting ? "Validating." : "Continue"}
                </button>
              </div>
            </div>
          </>
        )}

        {step === 2 && (
          <>
            <div className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-1.5">
              Step 2. Choose where this bot sends alerts
            </div>
            <p className="text-xs text-muted-foreground mb-3">
              A bot can only message places it has been added to, so pick a destination
              and connect it. Pairing tells Nurby the exact chat to send to. you can add
              more destinations later (e.g. Family, Security) and choose which one each
              rule alerts.
            </p>
            <div className="flex gap-1 mb-3">
              <button
                type="button"
                onClick={() => setPairTab("dm")}
                className={`flex-1 px-3 py-1.5 text-xs rounded border ${
                  pairTab === "dm"
                    ? "border-accent bg-accent/10 text-accent"
                    : "border-border hover:bg-muted"
                }`}
              >
                Direct message
              </button>
              <button
                type="button"
                onClick={() => setPairTab("group")}
                className={`flex-1 px-3 py-1.5 text-xs rounded border ${
                  pairTab === "group"
                    ? "border-accent bg-accent/10 text-accent"
                    : "border-border hover:bg-muted"
                }`}
              >
                Group / channel
              </button>
            </div>

            {pairTab === "dm" && pair && (
              <div className="space-y-3">
                <p className="text-xs text-muted-foreground">
                  Tap the link below or scan the QR. Telegram opens, hit Start.
                </p>
                <a
                  href={pair.deep_link}
                  target="_blank"
                  rel="noreferrer"
                  className="block text-center px-4 py-3 rounded-md border border-accent/40 bg-accent/10 text-accent text-sm font-medium hover:bg-accent/20"
                >
                  Open in Telegram
                </a>
                {qrSrc && (
                  <div className="flex justify-center">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={qrSrc}
                      alt="Telegram pairing QR"
                      width={240}
                      height={240}
                      className="rounded border border-border bg-white p-1"
                    />
                  </div>
                )}
              </div>
            )}

            {pairTab === "group" && pair && pairChannel && (
              <div className="text-xs text-muted-foreground space-y-2.5">
                <ol className="list-decimal pl-4 space-y-1.5">
                  <li>
                    Open the group or channel where you want alerts (or create a new one).
                  </li>
                  <li>
                    Add{" "}
                    <span className="font-mono text-foreground">@{pairChannel.bot_username || "your bot"}</span>{" "}
                    as a member. In a group, Add member. In a{" "}
                    <span className="text-foreground">channel</span>, add it as an{" "}
                    <span className="text-foreground font-medium">Administrator</span> with the
                    &ldquo;Post messages&rdquo; permission (channels only accept posts from admins).
                  </li>
                  <li>
                    Send this exact message in that group or channel so Nurby learns which chat it is.
                  </li>
                </ol>
                <div className="rounded-md bg-background border border-border px-3 py-2 font-mono text-xs select-all flex items-center justify-between gap-2">
                  <span>/pair {pair.nonce}</span>
                  <button
                    type="button"
                    onClick={() => navigator.clipboard?.writeText(`/pair ${pair.nonce}`)}
                    className="text-[10px] px-1.5 py-0.5 rounded border border-border hover:bg-muted text-muted-foreground"
                  >
                    Copy
                  </button>
                </div>
                <p className="text-[11px] text-muted-foreground/80">
                  As soon as the bot sees that message, this dialog flips to Paired. no need to refresh.
                </p>
              </div>
            )}

            {pairTab === "group" && pair && !pairChannel && (
              <div className="text-xs text-muted-foreground">
                Loading bot details.
              </div>
            )}

            <div className="mt-4 text-[11px] text-muted-foreground flex items-center justify-between">
              <span>
                {pairExpired
                  ? "Pairing link expired."
                  : `Waiting for Telegram. Expires in ${Math.max(0, secondsLeft)}s.`}
              </span>
              {pairExpired && (
                <button
                  type="button"
                  onClick={restartPair}
                  className="px-2 py-1 text-[11px] rounded border border-border hover:bg-muted"
                >
                  Try again
                </button>
              )}
            </div>
            {error && (
              <div className="mt-2 text-xs text-red-400 bg-red-500/10 border border-red-500/30 rounded px-2 py-1.5">
                {error}
              </div>
            )}
          </>
        )}

        {step === 3 && (
          <div className="space-y-3">
            <div className="rounded-md border border-green-500/30 bg-green-500/10 text-green-400 text-sm px-3 py-2">
              Paired ✓
              {pairChannel?.chat_title ? (
                <span className="ml-1 text-foreground/90">
                  with{" "}
                  <span className="font-medium">{pairChannel.chat_title}</span>
                </span>
              ) : null}
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={sendTest}
                className="px-3 py-1.5 text-xs rounded-md border border-border hover:bg-muted"
              >
                Send test
              </button>
              <button
                type="button"
                onClick={onClose}
                className="px-3 py-1.5 text-xs rounded-md border border-accent/40 bg-accent/10 text-accent hover:bg-accent/20"
              >
                Close
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
