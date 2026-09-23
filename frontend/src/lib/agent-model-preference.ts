import type { ProviderModel } from "@/components/ask/types";

export const AGENT_MODEL_PREFERENCE_KEY = "nurby:agent-preferred-model";
const PREFERENCE_TTL_MS = 15 * 60 * 1000;

/** Remember a model deployed/configured by an explicit user action. */
export function rememberPreferredAgentModel(modelId: string): void {
  try {
    localStorage.setItem(
      AGENT_MODEL_PREFERENCE_KEY,
      JSON.stringify({ id: modelId, saved_at: Date.now() }),
    );
  } catch {
    // Storage can be unavailable in privacy mode; normal provider selection
    // remains the fallback.
  }
}

/**
 * Consume a recent deployment preference once the model is visible to Ask.
 * Never force-select an Ollama model that cannot drive the tool loop.
 */
export function consumePreferredAgentModel(
  providers: ProviderModel[],
): ProviderModel | null {
  try {
    const raw = localStorage.getItem(AGENT_MODEL_PREFERENCE_KEY);
    if (!raw) return null;
    const saved = JSON.parse(raw) as { id?: string; saved_at?: number };
    if (!saved.id || !saved.saved_at || Date.now() - saved.saved_at > PREFERENCE_TTL_MS) {
      localStorage.removeItem(AGENT_MODEL_PREFERENCE_KEY);
      return null;
    }
    const found = providers.find(
      (p) => p.kind === "ollama" && p.id === saved.id && p.supports_tools !== false,
    );
    if (!found) return null;
    localStorage.removeItem(AGENT_MODEL_PREFERENCE_KEY);
    return found;
  } catch {
    return null;
  }
}

/** Explicit user selection supersedes an automatic deployment preference. */
export function clearPreferredAgentModel(): void {
  try {
    localStorage.removeItem(AGENT_MODEL_PREFERENCE_KEY);
  } catch {
    // Best effort only.
  }
}
