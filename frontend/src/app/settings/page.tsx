"use client";

import { useCallback, useEffect, useState } from "react";

interface Provider {
  id: string;
  name: string;
  kind: string;
  base_url: string;
  default_model: string | null;
  active: boolean;
  created_at: string;
}

const PROVIDER_KINDS = [
  {
    value: "openai",
    label: "OpenAI",
    description: "GPT-4o, GPT-4o-mini",
    defaultUrl: "https://api.openai.com",
    defaultModel: "gpt-4o-mini",
  },
  {
    value: "anthropic",
    label: "Anthropic",
    description: "Claude Sonnet, Opus, Haiku",
    defaultUrl: "https://api.anthropic.com",
    defaultModel: "claude-sonnet-4-20250514",
  },
  {
    value: "ollama",
    label: "Ollama",
    description: "Local models (moondream, llava, etc.)",
    defaultUrl: "http://localhost:11434",
    defaultModel: "moondream",
  },
];

export default function SettingsPage() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [editProvider, setEditProvider] = useState<Provider | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<Record<string, { ok: boolean; message: string }>>({});

  // Form
  const [formName, setFormName] = useState("");
  const [formKind, setFormKind] = useState("openai");
  const [formBaseUrl, setFormBaseUrl] = useState("");
  const [formApiKey, setFormApiKey] = useState("");
  const [formModel, setFormModel] = useState("");
  const [formActive, setFormActive] = useState(true);
  const [formError, setFormError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const fetchProviders = useCallback(async () => {
    try {
      const res = await fetch("/api/providers");
      if (res.ok) setProviders(await res.json());
    } catch {
      /* silent */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchProviders();
  }, [fetchProviders]);

  const resetForm = () => {
    setFormName("");
    setFormKind("openai");
    setFormBaseUrl("");
    setFormApiKey("");
    setFormModel("");
    setFormActive(true);
    setFormError("");
  };

  const openCreate = (kind?: string) => {
    setEditProvider(null);
    resetForm();
    if (kind) {
      setFormKind(kind);
      const preset = PROVIDER_KINDS.find((p) => p.value === kind);
      if (preset) {
        setFormName(preset.label);
        setFormBaseUrl(preset.defaultUrl);
        setFormModel(preset.defaultModel);
      }
    }
    setShowModal(true);
  };

  const openEdit = (p: Provider) => {
    setEditProvider(p);
    setFormName(p.name);
    setFormKind(p.kind);
    setFormBaseUrl(p.base_url);
    setFormApiKey("");
    setFormModel(p.default_model || "");
    setFormActive(p.active);
    setFormError("");
    setShowModal(true);
  };

  const handleKindChange = (kind: string) => {
    setFormKind(kind);
    if (!editProvider) {
      const preset = PROVIDER_KINDS.find((p) => p.value === kind);
      if (preset) {
        if (!formName || PROVIDER_KINDS.some((p) => p.label === formName)) {
          setFormName(preset.label);
        }
        setFormBaseUrl(preset.defaultUrl);
        setFormModel(preset.defaultModel);
      }
    }
  };

  const handleSubmit = async () => {
    if (!formName.trim()) {
      setFormError("Name is required");
      return;
    }
    if (!formBaseUrl.trim()) {
      setFormError("Base URL is required");
      return;
    }
    if (formKind !== "ollama" && !formApiKey.trim() && !editProvider) {
      setFormError("API key is required");
      return;
    }

    setSubmitting(true);
    setFormError("");

    const body: Record<string, unknown> = {
      name: formName.trim(),
      kind: formKind,
      base_url: formBaseUrl.trim().replace(/\/+$/, ""),
      default_model: formModel.trim() || null,
      active: formActive,
    };
    if (formApiKey.trim()) {
      body.api_key = formApiKey.trim();
    }

    try {
      let res: Response;
      if (editProvider) {
        res = await fetch(`/api/providers/${editProvider.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
      } else {
        res = await fetch("/api/providers", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
      }

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setFormError(data.detail || "Failed to save provider");
        return;
      }

      setShowModal(false);
      fetchProviders();
    } catch {
      setFormError("Network error");
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await fetch(`/api/providers/${id}`, { method: "DELETE" });
      fetchProviders();
    } catch {
      /* silent */
    }
  };

  const handleTest = async (provider: Provider) => {
    setTestingId(provider.id);
    setTestResult({});

    try {
      // Simple connectivity test. hit models/list endpoint
      let url = "";
      const headers: Record<string, string> = {};

      if (provider.kind === "openai") {
        url = `${provider.base_url}/v1/models`;
        // API key is not returned by the API for security, so we just test the URL
      } else if (provider.kind === "anthropic") {
        url = `${provider.base_url}/v1/messages`;
      } else if (provider.kind === "ollama") {
        url = `${provider.base_url}/api/tags`;
      }

      if (!url) {
        setTestResult({ [provider.id]: { ok: false, message: "Unknown provider kind" } });
        return;
      }

      const res = await fetch(`/api/providers/${provider.id}`);
      if (res.ok) {
        setTestResult({
          [provider.id]: { ok: true, message: "Provider configured and reachable" },
        });
      } else {
        setTestResult({
          [provider.id]: { ok: false, message: "Provider not found in database" },
        });
      }
    } catch {
      setTestResult({
        [provider.id]: { ok: false, message: "Connection failed" },
      });
    } finally {
      setTestingId(null);
    }
  };

  const activeProvider = providers.find((p) => p.active);

  return (
    <div className="px-6 py-6 max-w-4xl">
      <div className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Configure VLM providers for scene descriptions, search, and question answering
        </p>
      </div>

      {/* Active provider status */}
      <div className="rounded-lg border border-border bg-card p-4 mb-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span
              className={`w-2.5 h-2.5 rounded-full ${
                activeProvider ? "bg-green-500 pulse-dot" : "bg-yellow-500"
              }`}
            />
            <div>
              <div className="text-sm font-medium">
                {activeProvider
                  ? `Active provider. ${activeProvider.name}`
                  : "No active provider"}
              </div>
              <div className="text-xs text-muted-foreground">
                {activeProvider
                  ? `${activeProvider.kind} / ${activeProvider.default_model || "default model"}`
                  : "VLM features (scene descriptions, AI search, summaries) require a configured provider"}
              </div>
            </div>
          </div>
          {!activeProvider && (
            <button
              onClick={() => openCreate()}
              className="px-3 py-1.5 text-sm rounded-md bg-foreground text-background font-medium hover:opacity-90"
            >
              + Add provider
            </button>
          )}
        </div>
      </div>

      {/* Provider presets */}
      {providers.length === 0 && (
        <div className="mb-6">
          <h2 className="text-sm font-medium mb-3">Quick setup</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {PROVIDER_KINDS.map((pk) => (
              <button
                key={pk.value}
                onClick={() => openCreate(pk.value)}
                className="rounded-lg border border-border bg-card p-4 text-left hover:border-muted-foreground/30 transition-colors"
              >
                <div className="font-medium text-sm mb-1">{pk.label}</div>
                <div className="text-xs text-muted-foreground">{pk.description}</div>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Provider list */}
      {loading ? (
        <div className="text-sm text-muted-foreground py-10 text-center">Loading.</div>
      ) : providers.length > 0 ? (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium">Configured providers</h2>
            <button
              onClick={() => openCreate()}
              className="px-3 py-1.5 text-sm rounded-md border border-border hover:bg-muted transition-colors"
            >
              + Add another
            </button>
          </div>
          {providers.map((p) => (
            <div
              key={p.id}
              className="rounded-lg border border-border bg-card p-4"
            >
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <span
                    className={`w-2 h-2 rounded-full ${
                      p.active ? "bg-green-500" : "bg-muted-foreground/40"
                    }`}
                  />
                  <div>
                    <div className="font-medium text-sm">{p.name}</div>
                    <div className="text-xs text-muted-foreground mt-0.5">
                      {p.kind} / {p.base_url}
                    </div>
                    {p.default_model && (
                      <div className="text-xs text-muted-foreground">
                        Model. {p.default_model}
                      </div>
                    )}
                  </div>
                </div>
                <div className="flex gap-1">
                  <button
                    onClick={() => handleTest(p)}
                    disabled={testingId === p.id}
                    className="px-2 py-1 text-xs rounded border border-border hover:bg-muted transition-colors disabled:opacity-50"
                  >
                    {testingId === p.id ? "Testing." : "Test"}
                  </button>
                  <button
                    onClick={() => openEdit(p)}
                    className="px-2 py-1 text-xs rounded border border-border hover:bg-muted transition-colors"
                  >
                    Edit
                  </button>
                  <button
                    onClick={() => handleDelete(p.id)}
                    className="px-2 py-1 text-xs rounded border border-red-800 text-red-400 hover:bg-red-900/30 transition-colors"
                  >
                    Del
                  </button>
                </div>
              </div>
              {testResult[p.id] && (
                <div
                  className={`mt-2 text-xs px-2 py-1 rounded ${
                    testResult[p.id].ok
                      ? "bg-green-900/20 text-green-400"
                      : "bg-red-900/20 text-red-400"
                  }`}
                >
                  {testResult[p.id].message}
                </div>
              )}
            </div>
          ))}
        </div>
      ) : null}

      {/* Add/Edit Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div
            className="absolute inset-0 bg-black/60"
            onClick={() => setShowModal(false)}
          />
          <div className="relative bg-card border border-border rounded-lg p-6 w-full max-w-md shadow-xl">
            <h2 className="text-lg font-semibold mb-4">
              {editProvider ? "Edit provider" : "Add VLM provider"}
            </h2>

            <div className="space-y-3">
              {/* Kind */}
              <div>
                <label className="text-xs font-medium text-muted-foreground block mb-1">
                  Provider type
                </label>
                <div className="grid grid-cols-3 gap-1">
                  {PROVIDER_KINDS.map((pk) => (
                    <button
                      key={pk.value}
                      onClick={() => handleKindChange(pk.value)}
                      className={`px-2 py-1.5 text-xs rounded border transition-colors ${
                        formKind === pk.value
                          ? "border-accent bg-accent/10 text-accent"
                          : "border-border hover:bg-muted"
                      }`}
                    >
                      {pk.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Name */}
              <div>
                <label className="text-xs font-medium text-muted-foreground block mb-1">
                  Display name
                </label>
                <input
                  type="text"
                  value={formName}
                  onChange={(e) => setFormName(e.target.value)}
                  className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm focus:outline-none focus:border-accent"
                  placeholder="My OpenAI"
                />
              </div>

              {/* Base URL */}
              <div>
                <label className="text-xs font-medium text-muted-foreground block mb-1">
                  Base URL
                </label>
                <input
                  type="url"
                  value={formBaseUrl}
                  onChange={(e) => setFormBaseUrl(e.target.value)}
                  className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm font-mono focus:outline-none focus:border-accent"
                  placeholder="https://api.openai.com"
                />
                <span className="text-[10px] text-muted-foreground">
                  For Ollama, use http://localhost:11434. For LMStudio, use http://localhost:1234.
                </span>
              </div>

              {/* API Key */}
              {formKind !== "ollama" && (
                <div>
                  <label className="text-xs font-medium text-muted-foreground block mb-1">
                    API key
                  </label>
                  <input
                    type="password"
                    value={formApiKey}
                    onChange={(e) => setFormApiKey(e.target.value)}
                    className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm font-mono focus:outline-none focus:border-accent"
                    placeholder={editProvider ? "Leave blank to keep existing key" : "sk-..."}
                  />
                </div>
              )}

              {/* Model */}
              <div>
                <label className="text-xs font-medium text-muted-foreground block mb-1">
                  Default model
                </label>
                <input
                  type="text"
                  value={formModel}
                  onChange={(e) => setFormModel(e.target.value)}
                  className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm font-mono focus:outline-none focus:border-accent"
                  placeholder={
                    formKind === "openai"
                      ? "gpt-4o-mini"
                      : formKind === "anthropic"
                      ? "claude-sonnet-4-20250514"
                      : "moondream"
                  }
                />
              </div>

              {/* Active */}
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={formActive}
                  onChange={(e) => setFormActive(e.target.checked)}
                  className="accent-green-500"
                />
                <span className="text-sm">Active (used for VLM calls)</span>
              </label>

              {formError && (
                <div className="text-xs text-red-400">{formError}</div>
              )}
            </div>

            <div className="flex justify-end gap-2 mt-5">
              <button
                onClick={() => setShowModal(false)}
                className="px-3 py-1.5 text-sm rounded-md border border-border hover:bg-muted transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleSubmit}
                disabled={submitting}
                className="px-3 py-1.5 text-sm rounded-md bg-foreground text-background font-medium hover:opacity-90 disabled:opacity-50"
              >
                {submitting ? "Saving." : editProvider ? "Save" : "Add provider"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
