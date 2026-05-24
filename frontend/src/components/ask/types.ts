// Shared types for the /ask surface. These mirror the Wave 2A REST +
// WS contracts in docs/agent-design.md sections 10 and 11. When the
// backend lands, contract mismatches surface as compile errors here.

export type RunStatus =
  | "running"
  | "completed"
  | "failed"
  | "cancelled"
  | "budget_exhausted";

export interface AgentRunSummary {
  id: string;
  question: string;
  status: RunStatus;
  cost_cents: number;
  started_at: string;
  ended_at: string | null;
  latency_ms: number | null;
  model: string | null;
  provider_name?: string | null;
  user_id?: string;
  user_display_name?: string | null;
}

export interface AgentToolCallRecord {
  id: string;
  turn_index: number;
  tool_name: string;
  arguments: Record<string, unknown>;
  result: Record<string, unknown> | null;
  error_message: string | null;
  latency_ms: number | null;
  cached?: boolean;
  created_at: string;
}

export interface AgentVlmCallRecord {
  id: string;
  observation_id: string | null;
  recording_id: string | null;
  question: string;
  response: Record<string, unknown> | null;
  confidence: number | null;
  cached: boolean;
  frame_count: number;
  cost_cents: number;
  created_at: string;
}

export interface AgentRunDetail extends AgentRunSummary {
  plan: string | null;
  final_answer: string | null;
  error_message: string | null;
  tool_calls: AgentToolCallRecord[];
  vlm_calls: AgentVlmCallRecord[];
  citations?: Citation[];
}

export interface Citation {
  kind: "observation" | "vlm_call" | "recording" | "journey";
  id: string;
  claim_idx?: number;
  label?: string;
}

export interface ProviderModel {
  id: string;             // model identifier
  name: string;           // display name
  kind: string;           // anthropic / openai / gemini / ollama
  provider_id: string;
  provider_name: string;
  recommended?: boolean;
  cost_per_1k_in?: number;
  cost_per_1k_out?: number;
}

export interface UsageToday {
  cost_cents: number;
  cost_cents_cap: number;
  tokens: number;
  tokens_cap: number;
  runs: number;
  per_run?: Array<{
    run_id: string;
    question: string;
    cost_cents: number;
    started_at: string;
  }>;
}
