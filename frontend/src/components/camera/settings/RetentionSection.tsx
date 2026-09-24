// Moved verbatim from src/app/cameras/[id]/page.tsx (issue #187).
// State stays in the page; this component renders and reports changes
// through the setters passed as props. Bodies are byte-identical to the
// originals, including their original indentation.

import type { Dispatch, SetStateAction } from "react";
import { Section, FieldRow } from "./primitives";

interface RetentionSectionProps {
  retentionDays: number;
  retentionGb: number;
  retentionMode: string;
  setRetentionDays: Dispatch<SetStateAction<number>>;
  setRetentionGb: Dispatch<SetStateAction<number>>;
  setRetentionMode: Dispatch<SetStateAction<string>>;
}

export function RetentionSection({
  retentionDays,
  retentionGb,
  retentionMode,
  setRetentionDays,
  setRetentionGb,
  setRetentionMode,
}: RetentionSectionProps) {
  return (
        <Section
          title="Retention"
          description="How long recordings are kept before deletion"
        >
          <FieldRow label="Retention Policy">
            <div className="flex gap-1.5">
              {([
                { value: "none", label: "Keep Forever" },
                { value: "time", label: "By Age" },
                { value: "size", label: "By Size" },
              ] as const).map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setRetentionMode(opt.value)}
                  className={`px-3 py-1.5 text-xs rounded-md border transition-colors ${
                    retentionMode === opt.value
                      ? "border-accent bg-accent/10 text-accent-foreground"
                      : "border-border hover:border-muted-foreground text-muted-foreground"
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </FieldRow>

          {retentionMode === "time" && (
            <FieldRow label="Keep Recordings For" hint="Delete recordings older than this">
              <div className="flex items-center gap-3">
                <input
                  type="range"
                  min={1}
                  max={365}
                  step={1}
                  value={retentionDays}
                  onChange={(e) => setRetentionDays(Number(e.target.value))}
                  className="flex-1 accent-accent"
                />
                <span className="font-mono text-xs text-muted-foreground w-20 text-right">
                  {retentionDays < 30
                    ? `${retentionDays}d`
                    : retentionDays < 365
                      ? `${Math.floor(retentionDays / 30)}mo ${retentionDays % 30 ? `${retentionDays % 30}d` : ""}`.trim()
                      : `${Math.floor(retentionDays / 365)}y`}
                </span>
              </div>
              <div className="flex gap-2 mt-2">
                {[7, 14, 30, 90, 180, 365].map((d) => (
                  <button
                    key={d}
                    type="button"
                    onClick={() => setRetentionDays(d)}
                    className={`px-2 py-0.5 text-[11px] rounded border transition-colors ${
                      retentionDays === d
                        ? "border-accent text-accent-foreground"
                        : "border-border text-muted-foreground hover:border-muted-foreground"
                    }`}
                  >
                    {d < 30 ? `${d}d` : d < 365 ? `${d / 30}mo` : "1y"}
                  </button>
                ))}
              </div>
            </FieldRow>
          )}

          {retentionMode === "size" && (
            <FieldRow label="Max Storage" hint="Delete oldest recordings when limit is reached">
              <div className="flex items-center gap-3">
                <input
                  type="range"
                  min={1}
                  max={500}
                  step={1}
                  value={retentionGb}
                  onChange={(e) => setRetentionGb(Number(e.target.value))}
                  className="flex-1 accent-accent"
                />
                <span className="font-mono text-xs text-muted-foreground w-16 text-right">
                  {retentionGb < 1000 ? `${retentionGb} GB` : `${(retentionGb / 1000).toFixed(1)} TB`}
                </span>
              </div>
              <div className="flex gap-2 mt-2">
                {[5, 10, 25, 50, 100, 250, 500].map((g) => (
                  <button
                    key={g}
                    type="button"
                    onClick={() => setRetentionGb(g)}
                    className={`px-2 py-0.5 text-[11px] rounded border transition-colors ${
                      retentionGb === g
                        ? "border-accent text-accent-foreground"
                        : "border-border text-muted-foreground hover:border-muted-foreground"
                    }`}
                  >
                    {g} GB
                  </button>
                ))}
              </div>
            </FieldRow>
          )}

          {retentionMode !== "none" && (
            <div className="rounded-md bg-warning/5 border border-warning/20 px-3 py-2">
              <p className="text-xs text-warning">
                {retentionMode === "time"
                  ? `Recordings older than ${retentionDays} day${retentionDays !== 1 ? "s" : ""} will be automatically deleted from disk.`
                  : `When recordings exceed ${retentionGb} GB, oldest files will be deleted to make space.`}
              </p>
            </div>
          )}
        </Section>
  );
}
