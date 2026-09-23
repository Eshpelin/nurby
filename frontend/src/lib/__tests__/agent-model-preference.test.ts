import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ProviderModel } from "@/components/ask/types";
import {
  AGENT_MODEL_PREFERENCE_KEY,
  clearPreferredAgentModel,
  consumePreferredAgentModel,
  rememberPreferredAgentModel,
} from "../agent-model-preference";

const provider = (overrides: Partial<ProviderModel> = {}): ProviderModel => ({
  id: "qwen2.5:3b",
  name: "qwen2.5:3b",
  kind: "ollama",
  provider_id: "ollama-1",
  provider_name: "Ollama",
  supports_tools: true,
  ...overrides,
});

describe("agent model deployment preference", () => {
  beforeEach(() => {
    const values = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
      removeItem: (key: string) => values.delete(key),
    });
  });

  it("selects and consumes the newly deployed tool-capable model", () => {
    rememberPreferredAgentModel("qwen2.5:3b");
    expect(consumePreferredAgentModel([provider()])?.id).toBe("qwen2.5:3b");
    expect(localStorage.getItem(AGENT_MODEL_PREFERENCE_KEY)).toBeNull();
  });

  it("waits until the model is listed and ignores incompatible models", () => {
    rememberPreferredAgentModel("qwen2.5:3b");
    expect(consumePreferredAgentModel([])).toBeNull();
    expect(consumePreferredAgentModel([provider({ supports_tools: false })])).toBeNull();
    expect(localStorage.getItem(AGENT_MODEL_PREFERENCE_KEY)).not.toBeNull();
    expect(consumePreferredAgentModel([provider()])?.id).toBe("qwen2.5:3b");
  });

  it("clears a preference when the user explicitly picks another model", () => {
    rememberPreferredAgentModel("qwen2.5:3b");
    clearPreferredAgentModel();
    expect(localStorage.getItem(AGENT_MODEL_PREFERENCE_KEY)).toBeNull();
  });

  it("drops stale preferences", () => {
    vi.spyOn(Date, "now").mockReturnValue(2_000_000);
    localStorage.setItem(
      AGENT_MODEL_PREFERENCE_KEY,
      JSON.stringify({ id: "qwen2.5:3b", saved_at: 1_000_000 }),
    );
    expect(consumePreferredAgentModel([provider()])).toBeNull();
    expect(localStorage.getItem(AGENT_MODEL_PREFERENCE_KEY)).toBeNull();
    vi.restoreAllMocks();
  });
});
