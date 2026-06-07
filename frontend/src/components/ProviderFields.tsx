"use client";

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
        <label className={LABEL}>Display name</label>
        <input
          type="text"
          value={values.name}
          onChange={(e) => onChange("name", e.target.value)}
          className={ROW}
          placeholder="My OpenAI"
        />
      </div>

      <div>
        <label className={LABEL}>Base URL</label>
        <input
          type="url"
          value={values.baseUrl}
          onChange={(e) => onChange("baseUrl", e.target.value)}
          className={MONO}
          placeholder="https://api.openai.com"
        />
      </div>

      {!local && (
        <div>
          <label className={LABEL}>API key</label>
          <input
            type="password"
            value={values.apiKey}
            onChange={(e) => onChange("apiKey", e.target.value)}
            className={MONO}
            placeholder={editing ? "Leave blank to keep existing key" : "sk-..."}
          />
        </div>
      )}

      <div>
        <label className={LABEL}>Default model</label>
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
