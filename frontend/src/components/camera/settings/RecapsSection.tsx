// Moved verbatim from src/app/cameras/[id]/page.tsx (issue #187).
// State stays in the page; this component renders and reports changes
// through the setters passed as props. Bodies are byte-identical to the
// originals, including their original indentation.

import type { Dispatch, SetStateAction } from "react";
import { Section, FieldRow, Toggle, inputClass } from "./primitives";
import type { Provider } from "./types";
import { translate, type Locale } from "@/lib/i18n";

interface RecapsSectionProps {
  locale: Locale;
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
  locale,
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
  const t = (key: string) => translate(locale, key);
  return (
        <Section
          title={t("camera.recaps.title")}
          description={t("camera.recaps.description")}
        >
          <FieldRow label={t("camera.recaps.label")}>
            <Toggle
              checked={digestEnabled}
              onChange={setDigestEnabled}
              label={digestEnabled ? t("common.enabled") : t("common.disabled")}
            />
          </FieldRow>

          {digestEnabled && (
            <>
              <FieldRow label={t("camera.recaps.period")} hint={t("camera.recaps.period_hint")}>
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
                      {t(`camera.recaps.period.${p}`)}
                    </button>
                  ))}
                </div>
              </FieldRow>

              <FieldRow label={t("camera.recaps.model")} hint={t("camera.recaps.model_hint")}>
                <select
                  value={digestProviderId || ""}
                  onChange={(e) => setDigestProviderId(e.target.value || null)}
                  className={inputClass}
                >
                  <option value="">
                    {t("camera.recaps.system_default")}{activeProvider ? ` (${activeProvider.name})` : ""}
                  </option>
                  {providers.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                      {p.default_model ? ` · ${p.default_model}` : ""}
                    </option>
                  ))}
                </select>
              </FieldRow>

              <FieldRow label={t("camera.recaps.prompt")} hint={t("camera.recaps.prompt_hint")}>
                <textarea
                  value={digestPrompt}
                  onChange={(e) => setDigestPrompt(e.target.value)}
                  placeholder={t("camera.recaps.prompt_placeholder")}
                  rows={3}
                  className={`${inputClass} resize-y`}
                />
                {digestPrompt.trim() && (
                  <button
                    type="button"
                    onClick={() => setDigestPrompt("")}
                    className="text-[11px] text-muted-foreground hover:text-danger mt-1 transition-colors"
                  >
                    {t("camera.recaps.reset")}
                  </button>
                )}
              </FieldRow>
            </>
          )}
        </Section>
  );
}
