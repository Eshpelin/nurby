// Single source of truth for VLM/LLM provider presets. Both the Settings
// provider form and the first-run onboarding wizard read from here so a
// model name or base URL can never drift between the two screens.

export interface ProviderPreset {
  name: string;
  kind: string;
  url: string;
  model: string;
  description: string;
  needsKey: boolean;
}

// Provider "kinds" the backend adapter understands. Display labels for the
// kind selector in Settings.
export const PROVIDER_KINDS = [
  { value: "openai", label: "OpenAI-compatible" },
  { value: "anthropic", label: "Anthropic" },
  { value: "google", label: "Google Gemini" },
  { value: "ollama", label: "Ollama" },
] as const;

// Full catalog shown in Settings. Order matters. the first three are the
// headline cloud providers, then OpenAI-compatible gateways, then local.
export const ALL_PROVIDERS: ProviderPreset[] = [
  { name: "OpenAI", kind: "openai", url: "https://api.openai.com", model: "gpt-4o-mini", description: "GPT-4o, GPT-4o-mini, o1", needsKey: true },
  { name: "Anthropic", kind: "anthropic", url: "https://api.anthropic.com", model: "claude-sonnet-4-20250514", description: "Claude Sonnet, Opus, Haiku", needsKey: true },
  { name: "Google Gemini", kind: "google", url: "https://generativelanguage.googleapis.com", model: "gemini-2.0-flash", description: "Gemini 2.0 Flash, Pro, Ultra", needsKey: true },
  { name: "Together AI", kind: "openai", url: "https://api.together.xyz", model: "meta-llama/Llama-3-70b-chat-hf", description: "Llama, Mixtral, Qwen, SDXL", needsKey: true },
  { name: "Groq", kind: "openai", url: "https://api.groq.com/openai", model: "llama-3.1-70b-versatile", description: "Ultra-fast Llama, Mixtral inference", needsKey: true },
  { name: "Fireworks AI", kind: "openai", url: "https://api.fireworks.ai/inference", model: "accounts/fireworks/models/llama-v3p1-70b-instruct", description: "Llama, Mixtral, FireFunction", needsKey: true },
  { name: "Mistral AI", kind: "openai", url: "https://api.mistral.ai", model: "mistral-large-latest", description: "Mistral Large, Medium, Small", needsKey: true },
  { name: "DeepSeek", kind: "openai", url: "https://api.deepseek.com", model: "deepseek-chat", description: "DeepSeek V3, R1", needsKey: true },
  { name: "OpenRouter", kind: "openai", url: "https://openrouter.ai/api", model: "openai/gpt-4o-mini", description: "Unified gateway to 200+ models", needsKey: true },
  { name: "Perplexity", kind: "openai", url: "https://api.perplexity.ai", model: "llama-3.1-sonar-large-128k-online", description: "Online search-grounded models", needsKey: true },
  { name: "Ollama", kind: "ollama", url: "http://localhost:11434", model: "gemma4:12b", description: "Local models (Gemma 4, gemma3, llava, etc.)", needsKey: false },
  { name: "LMStudio", kind: "openai", url: "http://localhost:1234", model: "local-model", description: "Local OpenAI-compatible server", needsKey: false },
  { name: "vLLM", kind: "openai", url: "http://localhost:8000", model: "local-model", description: "High-throughput local serving", needsKey: false },
];

// Shape the onboarding wizard's provider step consumes. A curated subset
// of ALL_PROVIDERS, derived so the two screens never disagree on URLs or
// default models.
export interface OnboardingPreset {
  kind: string;
  name: string;
  base_url: string;
  default_model: string;
  keyRequired: boolean;
  hint: string;
}

function onboardingPreset(catalogName: string, displayName: string, hint: string): OnboardingPreset {
  const p = ALL_PROVIDERS.find((x) => x.name === catalogName)!;
  return {
    kind: p.kind,
    name: displayName,
    base_url: p.url,
    default_model: p.model,
    keyRequired: p.needsKey,
    hint,
  };
}

export const ONBOARDING_PRESETS: OnboardingPreset[] = [
  onboardingPreset("Ollama", "Local (Ollama)", "Runs locally. No API key. No data leaves your network."),
  onboardingPreset("OpenAI", "OpenAI", "Cloud. Best image understanding. Pay-per-call."),
  onboardingPreset("Anthropic", "Anthropic Claude", "Cloud. Strong at language and reasoning."),
  onboardingPreset("Google Gemini", "Google Gemini", "Cloud. Generous free tier."),
];
