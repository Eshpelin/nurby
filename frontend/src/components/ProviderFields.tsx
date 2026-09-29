"use client";

import { useAuth } from "@/lib/auth";
import { translate, type Locale } from "@/lib/i18n";

// Shared provider form fields. used by both the Settings → AI Providers
// modal and the onboarding wizard so the two never drift. Controlled. the
// parent owns the state and submit; this just renders the common rows
// (name, base URL, API key, default model) with the same local-detection
// rule for hiding the API key on a local Ollama endpoint.

export interface ProviderFieldValues {
  name: string;
  kind: string;
  baseUrl: string;
  model: string;
  apiKey: string;
}

export type ProviderField = keyof ProviderFieldValues;

export function isLocalProvider(kind: string, baseUrl: string): boolean {
  return (
    kind === "ollama" ||
    baseUrl.includes("localhost") ||
    baseUrl.includes("127.0.0.1") ||
    baseUrl.includes("host.docker.internal")
  );
}

const ROW = "w-full px-3 py-2 rounded-md bg-background border border-border text-sm focus:outline-none focus:border-accent";
const MONO = ROW + " font-mono";
const LABEL = "text-xs font-medium text-muted-foreground block mb-1";

export function ProviderFields({
  values,
  onChange,
  editing = false,
  modelPlaceholder,
}: {
  values: ProviderFieldValues;
  onChange: (field: ProviderField, value: string) => void;
  editing?: boolean;
  modelPlaceholder?: string;
}) {
  const { user } = useAuth();
  const locale = (user?.locale as Locale) || "en";
  const t = (key: string) => translate(locale, key);
  const local = isLocalProvider(values.kind, values.baseUrl);
  const modelHint =
    modelPlaceholder ??
    (values.kind === "openai"
      ? "gpt-4o-mini"
      : values.kind === "anthropic"
        ? "claude-sonnet-4-20250514"
        : values.kind === "google"
          ? "gemini-2.0-flash"
          : "moondream");

  return (
    <>
      <div>
        <label className={LABEL}>{t("provider_fields.display_name")}</label>
        <input
          type="text"
          value={values.name}
          onChange={(e) => onChange("name", e.target.value)}
          className={ROW}
          placeholder={t("provider_fields.name_placeholder")}
        />
      </div>

      <div>
        <label className={LABEL}>{t("provider_fields.base_url")}</label>
        <input
          type="url"
          value={values.baseUrl}
          onChange={(e) => onChange("baseUrl", e.target.value)}
          className={MONO}
          placeholder={t("provider_fields.base_url_placeholder")}
        />
      </div>

      {!local && (
        <div>
        <label className={LABEL}>{t("provider_fields.api_key")}</label>
          <input
            type="password"
            value={values.apiKey}
            onChange={(e) => onChange("apiKey", e.target.value)}
            className={MONO}
            placeholder={editing ? t("provider_fields.api_key_keep") : t("provider_fields.api_key_placeholder")}
          />
        </div>
      )}

      <div>
        <label className={LABEL}>{t("provider_fields.default_model")}</label>
        <input
          type="text"
          value={values.model}
          onChange={(e) => onChange("model", e.target.value)}
          className={MONO}
          placeholder={modelHint}
        />
      </div>
    </>
  );
}
