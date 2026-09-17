// Moved verbatim from src/app/cameras/[id]/page.tsx (issue #187).
// State stays in the page; this component renders and reports changes
// through the setters passed as props. Bodies are byte-identical to the
// originals, including their original indentation.

import type { Dispatch, SetStateAction } from "react";
import { Section, FieldRow, Toggle, inputClass } from "./primitives";
import type { Provider } from "./types";

interface RecapsSectionProps {
  activeProvider: Provider | undefined;
  digestEnabled: boolean;
  digestPeriod: string;
  digestPrompt: string;
  digestProviderId: string | null;
  providers: Provider[];
  setDigestEnabled: Dispatch<SetStateAction<boolean>>;
  setDigestPeriod: Dispatch<SetStateAction<string>>;
  setDigestPrompt: Dispatch<SetStateAction<string>>;
  setDigestProviderId: Dispatch<SetStateAction<string | null>>;
}

export function RecapsSection({
  activeProvider,
  digestEnabled,
  digestPeriod,
  digestPrompt,
  digestProviderId,
  providers,
  setDigestEnabled,
  setDigestPeriod,
  setDigestPrompt,
  setDigestProviderId,
}: RecapsSectionProps) {
  return (
        <Section
          title="Periodic recaps"
          description="Configure the automatic activity summary shown on the cameras page"
        >
          <FieldRow label="Recaps">
            <Toggle
              checked={digestEnabled}
              onChange={setDigestEnabled}
              label={digestEnabled ? "Enabled" : "Disabled"}
            />
          </FieldRow>

          {digestEnabled && (
            <>
              <FieldRow label="Time Period" hint="How far back to look for activity">
                <div className="flex gap-1.5 flex-wrap">
                  {(["1h", "6h", "12h", "24h", "48h", "7d"] as const).map((p) => (
                    <button
                      key={p}
                      type="button"
                      onClick={() => setDigestPeriod(p)}
                      className={`px-2.5 py-1.5 text-xs rounded-md border transition-colors ${
                        digestPeriod === p
                          ? "border-accent bg-accent/10 text-accent-foreground"
                          : "border-border hover:border-muted-foreground text-muted-foreground"
                      }`}
                    >
                      {p === "1h" ? "1 hour"
                        : p === "6h" ? "6 hours"
                        : p === "12h" ? "12 hours"
                        : p === "24h" ? "24 hours"
                        : p === "48h" ? "2 days"
                        : "7 days"}
                    </button>
                  ))}
                </div>
              </FieldRow>

              <FieldRow label="Recap model" hint="Which model generates the summary">
                <select
                  value={digestProviderId || ""}
                  onChange={(e) => setDigestProviderId(e.target.value || null)}
                  className={inputClass}
                >
                  <option value="">
                    System Default{activeProvider ? ` (${activeProvider.name})` : ""}
                  </option>
                  {providers.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                      {p.default_model ? ` · ${p.default_model}` : ""}
                    </option>
                  ))}
                </select>
              </FieldRow>

              <FieldRow label="Recap prompt" hint="Custom instructions for generating the summary">
                <textarea
                  value={digestPrompt}
                  onChange={(e) => setDigestPrompt(e.target.value)}
                  placeholder="You are Nurby, an AI camera monitoring assistant. Summarize the following camera observations into a brief digest. Be concise (2-4 sentences). Mention key activity, people, and patterns."
                  rows={3}
                  className={`${inputClass} resize-y`}
                />
                {digestPrompt.trim() && (
                  <button
                    type="button"
                    onClick={() => setDigestPrompt("")}
                    className="text-[11px] text-muted-foreground hover:text-danger mt-1 transition-colors"
                  >
                    Reset to default
                  </button>
                )}
              </FieldRow>
            </>
          )}
        </Section>
  );
}
