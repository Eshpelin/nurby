"use client";

import { useCallback, useEffect, useRef, useState } from "react";

interface Turn {
  at: string | null;
  speaker: "visitor" | "camera";
  text: string;
  status?: string;
  suppressed_reason?: string | null;
}

interface Session {
  id: string;
  camera_id: string;
  started_at: string | null;
  ended_at: string | null;
  ended_reason: string | null;
  turns: number;
  handed_off: boolean;
  refusals: { reason: string; matched?: string | null }[];
  transcript?: Turn[];
}

export interface LiveConversationCardProps {
  cameraNames?: Record<string, string>;
  /** Poll interval. A doorstep exchange is seconds long, so this is
   *  fast on purpose; the card unmounts as soon as nothing is live. */
  pollMs?: number;
}

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Why a line was held back, in words a household would use.
const REASON_TEXT: Record<string, string> = {
  absence: "would have said nobody is home",
  schedule: "would have given away a schedule",
  access: "would have discussed keys or locks",
  identity: "would have named someone",
  impersonation: "would have implied a person was here",
  never_say: "matched a phrase you blocked",
  too_long: "was too long to say",
  empty: "was empty",
};

export function LiveConversationCard({
  cameraNames = {},
  pollMs = 3000,
}: LiveConversationCardProps) {
  const [session, setSession] = useState<Session | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const transcriptEnd = useRef<HTMLDivElement | null>(null);

  const headers = useCallback((): Record<string, string> => {
    const token =
      typeof window === "undefined" ? null : localStorage.getItem("token");
    return token ? { Authorization: `Bearer ${token}` } : {};
  }, []);

  const poll = useCallback(async () => {
    try {
      const resp = await fetch(`${API}/api/voice/sessions?active=true&limit=1`, {
        headers: headers(),
      });
      if (!resp.ok) return;
      const body = await resp.json();
      const live = (body.sessions ?? [])[0];
      if (!live) {
        setSession(null);
        return;
      }
      // Fetch the detail so the card shows the exchange, not just a row.
      const detail = await fetch(`${API}/api/voice/sessions/${live.id}`, {
        headers: headers(),
      });
      setSession(detail.ok ? await detail.json() : live);
    } catch {
      // A failed poll is not worth surfacing. The next one is 3s away,
      // and an error banner on a live doorbell would be noise.
    }
  }, [headers]);

  useEffect(() => {
    poll();
    const timer = setInterval(poll, pollMs);
    return () => clearInterval(timer);
  }, [poll, pollMs]);

  useEffect(() => {
    transcriptEnd.current?.scrollIntoView({ block: "nearest" });
  }, [session?.transcript?.length]);

  const takeOver = async () => {
    if (!session) return;
    setBusy(true);
    try {
      const resp = await fetch(
        `${API}/api/voice/sessions/${session.id}/handoff`,
        { method: "POST", headers: headers() },
      );
      const body = await resp.json();
      setNote(
        body.took_over
          ? "You have the conversation. The camera has stopped answering."
          : `Already ended: ${body.reason ?? "unknown"}.`,
      );
      await poll();
    } finally {
      setBusy(false);
    }
  };

  const say = async () => {
    if (!session || !draft.trim()) return;
    setBusy(true);
    try {
      const resp = await fetch(`${API}/api/voice/sessions/${session.id}/say`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...headers() },
        body: JSON.stringify({ text: draft.trim() }),
      });
      const body = await resp.json();
      setNote(
        body.spoken
          ? null
          : `Not played: ${body.reason ?? "unknown"}${body.detail ? ` (${body.detail})` : ""}`,
      );
      if (body.spoken) setDraft("");
      await poll();
    } finally {
      setBusy(false);
    }
  };

  // Nothing live means nothing to show. The card is not a placeholder.
  if (!session) return null;

  const cameraName = cameraNames[session.camera_id] ?? "a camera";

  return (
    <section className="rounded-lg border border-amber-600/40 bg-amber-500/5 p-4 mb-4">
      <div className="flex items-center justify-between gap-3 mb-3">
        <div className="flex items-center gap-2">
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-amber-400" />
          </span>
          <h2 className="text-sm font-medium text-amber-200">
            Someone is at {cameraName}
          </h2>
        </div>
        {!session.handed_off && (
          <button
            onClick={takeOver}
            disabled={busy}
            className="px-2.5 py-1 text-xs rounded-md border border-amber-500/50 bg-amber-500/15 text-amber-200 hover:bg-amber-500/25 disabled:opacity-50"
          >
            Take over
          </button>
        )}
      </div>

      <div className="max-h-52 overflow-y-auto rounded-md border border-border bg-background/60 p-2 mb-3">
        {(session.transcript ?? []).length === 0 ? (
          <p className="text-xs text-muted-foreground">Listening.</p>
        ) : (
          <ul className="space-y-1.5">
            {(session.transcript ?? []).map((turn, i) => (
              <li key={i} className="text-xs">
                <span
                  className={
                    turn.speaker === "visitor"
                      ? "text-zinc-300"
                      : "text-emerald-300/90"
                  }
                >
                  {turn.speaker === "visitor" ? "Visitor" : "Camera"}:
                </span>{" "}
                <span className="text-foreground">{turn.text}</span>
                {turn.status === "suppressed" && (
                  <span className="ml-1 text-[11px] text-amber-300/80">
                    (held back)
                  </span>
                )}
              </li>
            ))}
            <div ref={transcriptEnd} />
          </ul>
        )}
      </div>

      {/* Push to talk. What a household types is spoken as written: the
          disclosure filter exists to stop a model leaking their
          information, not to police their own words to their own
          visitor. */}
      <div className="flex items-center gap-2">
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") say();
          }}
          maxLength={240}
          placeholder="Say something to them."
          className="flex-1 px-3 py-1.5 rounded-md bg-background border border-border text-xs text-foreground"
        />
        <button
          onClick={say}
          disabled={busy || !draft.trim()}
          className="px-3 py-1.5 text-xs rounded-md bg-emerald-600/20 text-emerald-300 border border-emerald-600/40 hover:bg-emerald-600/30 disabled:opacity-50"
        >
          Speak
        </button>
      </div>

      {note && <p className="mt-2 text-xs text-amber-200/90">{note}</p>}

      {session.refusals.length > 0 && (
        <p className="mt-2 text-[11px] text-muted-foreground">
          Held back {session.refusals.length}{" "}
          {session.refusals.length === 1 ? "reply" : "replies"}:{" "}
          {session.refusals
            .map((r) => REASON_TEXT[r.reason] ?? r.reason)
            .join(", ")}
          .
        </p>
      )}
    </section>
  );
}
