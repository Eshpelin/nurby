"use client";

// Single citation chip. Clicking an observation citation opens a
// thumbnail lightbox; clicking a vlm_call citation opens the audit
// modal with the redacted frames the model actually saw.

import { useState } from "react";
import { useAuth } from "@/lib/auth";
import { translate } from "@/lib/i18n";
import type { Citation } from "./types";

interface CitationChipProps {
  citation: Citation;
}

export default function CitationChip({ citation }: CitationChipProps) {
  const { token, authFetch, user } = useAuth();
  const [open, setOpen] = useState(false);
  const [vlmDetail, setVlmDetail] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);

  const label = citation.label ?? `${citation.kind}:${citation.id.slice(0, 6)}`;
  const t = (key: string, values?: Record<string, string | number>) => translate(user?.locale, key, values);

  const onClick = async () => {
    setOpen(true);
    if (citation.kind === "vlm_call" && !vlmDetail) {
      setLoading(true);
      try {
        const res = await authFetch(`/api/agent/vlm_calls/${citation.id}`);
        if (res.ok) setVlmDetail(await res.json());
      } catch {/* ignore */}
      finally { setLoading(false); }
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={onClick}
        aria-label={t("ask.citation_open", { label })}
        className="inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] rounded border border-accent/40 text-accent bg-accent/10 hover:bg-accent/20 font-mono"
      >
        {citation.kind === "vlm_call" ? "vlm" : citation.kind.slice(0, 3)}·{citation.id.slice(0, 6)}
      </button>

      {open && (
        <div
          className="fixed inset-0 z-[100] bg-black/70 flex items-center justify-center p-6"
          onClick={() => setOpen(false)}
        >
          <div
            className="bg-card border border-border rounded-lg max-w-3xl w-full max-h-[85vh] overflow-auto p-4 space-y-3"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between">
              <div className="text-sm font-semibold">
                {t("ask.citation_title")} · {citation.kind} · <span className="font-mono text-xs">{citation.id}</span>
              </div>
              <button onClick={() => setOpen(false)} aria-label={t("ask.citation_close")} className="text-muted-foreground hover:text-foreground">
                ✕
              </button>
            </div>

            {citation.kind === "observation" && (
              <div className="space-y-2">
                <img
                  src={`/api/observations/${citation.id}/thumbnail${token ? `?token=${token}` : ""}`}
                  alt={t("ask.citation_observation_alt")}
                  className="w-full rounded border border-border bg-background"
                />
              </div>
            )}

            {citation.kind === "vlm_call" && (
              <div className="space-y-3">
                {loading && <div className="text-xs text-muted-foreground">{t("ask.citation_loading_audit")}</div>}
                {vlmDetail ? (
                  <>
                    <div>
                      <div className="text-[10px] uppercase text-muted-foreground">{t("ask.citation_question")}</div>
                      <div className="text-sm">{(vlmDetail.question as string) ?? "—"}</div>
                    </div>
                    <div>
                      <div className="text-[10px] uppercase text-muted-foreground">{t("ask.citation_structured_answer")}</div>
                      <pre className="text-[11px] font-mono bg-background border border-border rounded p-2 overflow-x-auto">
                        {JSON.stringify(vlmDetail.response ?? null, null, 2)}
                      </pre>
                    </div>
                    {Array.isArray(vlmDetail.frame_urls) && (vlmDetail.frame_urls as string[]).length > 0 && (
                      <div>
                        <div className="text-[10px] uppercase text-muted-foreground mb-1">{t("ask.citation_redacted_frames")}</div>
                        <div className="grid grid-cols-2 gap-2">
                          {(vlmDetail.frame_urls as string[]).map((u, i) => (
                            <img
                              key={i}
                              src={`${u}${u.includes("?") ? "&" : "?"}token=${token ?? ""}`}
                              alt={`frame ${i}`}
                              className="w-full rounded border border-border"
                            />
                          ))}
                        </div>
                      </div>
                    )}
                  </>
                ) : (
                  !loading && (
                    <div className="text-xs text-muted-foreground">
                      {t("ask.citation_unavailable")}
                    </div>
                  )
                )}
              </div>
            )}

            {citation.kind !== "observation" && citation.kind !== "vlm_call" && (
              <div className="text-xs text-muted-foreground">
                {t("ask.citation_kind_unwired", { kind: citation.kind })}
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
