"use client";

// Single citation chip. Clicking an observation citation opens a
// thumbnail lightbox; clicking a vlm_call citation opens the audit
// modal with the redacted frames the model actually saw.

import { useState } from "react";
import { useAuth } from "@/lib/auth";
import type { Citation } from "./types";

interface CitationChipProps {
  citation: Citation;
}

export default function CitationChip({ citation }: CitationChipProps) {
  const { token, authFetch } = useAuth();
  const [open, setOpen] = useState(false);
  const [vlmDetail, setVlmDetail] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);

  const label = citation.label ?? `${citation.kind}:${citation.id.slice(0, 6)}`;

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
        aria-label={`Open citation ${label}`}
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
                Citation · {citation.kind} · <span className="font-mono text-xs">{citation.id}</span>
              </div>
              <button onClick={() => setOpen(false)} aria-label="Close citation" className="text-muted-foreground hover:text-foreground">
                ✕
              </button>
            </div>

            {citation.kind === "observation" && (
              <div className="space-y-2">
                <img
                  src={`/api/observations/${citation.id}/thumbnail${token ? `?token=${token}` : ""}`}
                  alt="observation thumbnail"
                  className="w-full rounded border border-border bg-background"
                />
              </div>
            )}

            {citation.kind === "vlm_call" && (
              <div className="space-y-3">
                {loading && <div className="text-xs text-muted-foreground">Loading audit details.</div>}
                {vlmDetail ? (
                  <>
                    <div>
                      <div className="text-[10px] uppercase text-muted-foreground">Question asked</div>
                      <div className="text-sm">{(vlmDetail.question as string) ?? "—"}</div>
                    </div>
                    <div>
                      <div className="text-[10px] uppercase text-muted-foreground">Structured answer</div>
                      <pre className="text-[11px] font-mono bg-background border border-border rounded p-2 overflow-x-auto">
                        {JSON.stringify(vlmDetail.response ?? null, null, 2)}
                      </pre>
                    </div>
                    {Array.isArray(vlmDetail.frame_urls) && (vlmDetail.frame_urls as string[]).length > 0 && (
                      <div>
                        <div className="text-[10px] uppercase text-muted-foreground mb-1">Redacted frames the model saw</div>
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
                      Audit detail unavailable. The agent backend may not yet expose /api/agent/vlm_calls/&#123;id&#125;.
                    </div>
                  )
                )}
              </div>
            )}

            {citation.kind !== "observation" && citation.kind !== "vlm_call" && (
              <div className="text-xs text-muted-foreground">
                Citation kind <span className="font-mono">{citation.kind}</span> opens in its own surface (not wired yet).
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
