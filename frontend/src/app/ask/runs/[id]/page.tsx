"use client";

// Audit drill-in for a single completed AgentRun. Reuses
// AgentResponseCard so the replay view is byte-for-byte the same
// shape as the live chat answer. Sharable URL.

import { use, useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import AgentResponseCard from "@/components/ask/AgentResponseCard";
import type { AgentRunDetail } from "@/components/ask/types";
import { translate } from "@/lib/i18n";

interface Props {
  params: Promise<{ id: string }>;
}

export default function AskRunPage({ params }: Props) {
  const { id } = use(params);
  const { authFetch, user } = useAuth();
  const locale = user?.locale;
  const t = (key: string) => translate(locale, key);
  const [detail, setDetail] = useState<AgentRunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const res = await authFetch(`/api/agent/runs/${id}`);
        if (res.status === 404) {
          if (!cancelled) setError(translate(locale, "ask.run_not_found"));
          return;
        }
        if (res.status === 403) {
          if (!cancelled) setError(translate(locale, "ask.run_forbidden"));
          return;
        }
        if (res.ok) {
          if (!cancelled) setDetail(await res.json());
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : translate(locale, "common.network_error"));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [authFetch, id, locale]);

  return (
    <div className="max-w-3xl mx-auto px-4 py-6 space-y-4">
      <div className="flex items-center justify-between">
        <Link href="/ask" className="text-xs text-muted-foreground hover:text-foreground">
          {t("ask.back_to_chat")}
        </Link>
        <a
          href={typeof window !== "undefined" ? window.location.href : "#"}
          className="text-xs text-muted-foreground hover:text-foreground"
          aria-label={t("ask.share_run")}
          onClick={(e) => {
            e.preventDefault();
            navigator.clipboard?.writeText(window.location.href);
          }}
        >
          {t("ask.copy_share_link")}
        </a>
      </div>
      {loading && <div className="text-sm text-muted-foreground">{t("ask.loading_run")}</div>}
      {error && <div className="text-sm text-red-300 bg-red-500/10 border border-red-500/30 rounded p-3">{error}</div>}
      {detail && (
        <AgentResponseCard question={detail.question} detail={detail} />
      )}
    </div>
  );
}
