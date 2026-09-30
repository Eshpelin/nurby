"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { translate } from "@/lib/i18n";

// Shows why an offline camera is offline and a live countdown to the next
// reconnect attempt, fed by status_reason + next_retry_at from the API.
// The ingestion worker backs off (and enters a long lockout cooldown after
// repeated failures), so this tells the user when the next attempt lands
// instead of leaving a bare "offline".
export function RetryCountdown({
  nextRetryAt,
  reason,
  className = "",
}: {
  nextRetryAt?: number | null;
  reason?: string | null;
  className?: string;
}) {
  const { user } = useAuth();
  const t = (key: string, values?: Record<string, string | number>) => translate(user?.locale, key, values);
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (!nextRetryAt) return;
    const t = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(t);
  }, [nextRetryAt]);

  if (!reason && !nextRetryAt) return null;

  const remaining =
    nextRetryAt != null ? Math.max(0, Math.round(nextRetryAt - now)) : null;
  const mmss =
    remaining != null
      ? `${Math.floor(remaining / 60)}:${String(remaining % 60).padStart(2, "0")}`
      : null;

  return (
    <span className={className}>
      {reason ? <span className="text-danger">{reason}</span> : null}
      {mmss != null ? (
        <span className="ml-1 text-muted-foreground">
          {remaining && remaining > 0 ? t("camera.retrying_in", { time: mmss }) : t("camera.retrying_now")}
        </span>
      ) : null}
    </span>
  );
}
