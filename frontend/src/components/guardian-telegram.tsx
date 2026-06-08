"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/lib/auth";

interface Channel {
  id: string;
  label: string;
  bot_username: string | null;
  chat_title: string | null;
  pairing_status: "pending" | "paired" | "blocked" | "disabled" | "error";
}
interface PairInit {
  nonce: string;
  deep_link: string;
  qr_payload: string;
  expires_in_seconds: number;
}

// Compact "Connect Telegram" for a guardian: add a bot, pair the chat, done.
// Reuses the operator telegram-channel endpoints (user-scoped).
export function GuardianTelegram() {
  const { authFetch } = useAuth();
  const [channels, setChannels] = useState<Channel[]>([]);
  const [adding, setAdding] = useState(false);
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [pairing, setPairing] = useState<{ channelId: string; init: PairInit } | null>(null);
  const poll = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await authFetch("/api/telegram/channels");
      if (res.ok) setChannels(await res.json());
    } catch {
      /* ignore */
    }
  }, [authFetch]);

  useEffect(() => {
    load();
    return () => {
      if (poll.current) clearInterval(poll.current);
    };
  }, [load]);

  const paired = channels.find((c) => c.pairing_status === "paired");

  const startPairing = useCallback(
    (channelId: string) => {
      if (poll.current) clearInterval(poll.current);
      poll.current = setInterval(async () => {
        const r = await authFetch(`/api/telegram/channels/${channelId}`);
        if (r.ok) {
          const c: Channel = await r.json();
          if (c.pairing_status === "paired") {
            if (poll.current) clearInterval(poll.current);
            setPairing(null);
            setAdding(false);
            setToken("");
            load();
          }
        }
      }, 2000);
    },
    [authFetch, load]
  );

  const connect = useCallback(async () => {
    setErr(null);
    setBusy(true);
    try {
      const res = await authFetch("/api/telegram/channels", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bot_token: token.trim(), label: "My Telegram" }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) {
        setErr(typeof data?.detail === "string" ? data.detail : "Could not add that bot.");
        return;
      }
      const initRes = await authFetch(`/api/telegram/channels/${data.id}/pair-init`, { method: "POST" });
      const init: PairInit = await initRes.json();
      setPairing({ channelId: data.id, init });
      startPairing(data.id);
    } catch {
      setErr("Something went wrong.");
    } finally {
      setBusy(false);
    }
  }, [authFetch, token, startPairing]);

  const disconnect = useCallback(
    async (id: string) => {
      await authFetch(`/api/telegram/channels/${id}`, { method: "DELETE" }).catch(() => {});
      load();
    },
    [authFetch, load]
  );

  return (
    <div className="rounded-lg border border-border bg-card p-5">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-medium">Telegram alerts</h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Get arrival and pickup alerts about your dependant on Telegram.
          </p>
        </div>
        {paired && (
          <span className="flex items-center gap-1.5 text-xs text-emerald-400">
            <span className="h-2 w-2 rounded-full bg-emerald-500" /> Connected
          </span>
        )}
      </div>

      {paired ? (
        <div className="mt-3 flex items-center justify-between rounded-md border border-border bg-background px-3 py-2 text-sm">
          <span>
            {paired.chat_title || "Your chat"}
            {paired.bot_username && <span className="text-muted-foreground"> · @{paired.bot_username}</span>}
          </span>
          <button onClick={() => disconnect(paired.id)} className="text-xs text-red-400 hover:text-red-300">
            Disconnect
          </button>
        </div>
      ) : pairing ? (
        <div className="mt-3 rounded-md border border-border bg-background p-4 text-center">
          <p className="text-sm">Open Telegram and press Start to finish.</p>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={`https://api.qrserver.com/v1/create-qr-code/?size=160x160&data=${encodeURIComponent(
              pairing.init.qr_payload
            )}`}
            alt="Telegram pairing QR"
            className="mx-auto my-3 h-40 w-40 rounded bg-white p-1"
          />
          <a
            href={pairing.init.deep_link}
            target="_blank"
            rel="noreferrer"
            className="inline-block rounded-md bg-emerald-500 px-3 py-1.5 text-sm font-medium text-black"
          >
            Open Telegram
          </a>
          <p className="mt-2 text-xs text-muted-foreground">Waiting for you to press Start...</p>
        </div>
      ) : adding ? (
        <div className="mt-3 space-y-2">
          <p className="text-xs text-muted-foreground">
            Create a bot with @BotFather in Telegram, then paste its token here.
          </p>
          <input
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="123456:ABC-bot-token"
            className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
          />
          {err && <p className="text-xs text-red-400">{err}</p>}
          <div className="flex gap-2">
            <button
              onClick={connect}
              disabled={busy || token.trim().length < 10}
              className="rounded-md bg-emerald-500 px-3 py-1.5 text-sm font-medium text-black disabled:opacity-40"
            >
              {busy ? "Connecting..." : "Connect"}
            </button>
            <button onClick={() => setAdding(false)} className="rounded-md border border-border px-3 py-1.5 text-sm">
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <button
          onClick={() => setAdding(true)}
          className="mt-3 rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted"
        >
          Connect Telegram
        </button>
      )}
    </div>
  );
}
