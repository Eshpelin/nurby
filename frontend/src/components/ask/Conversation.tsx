"use client";

// Center pane: a stack of turn cards. The active turn is the
// streaming one; past turns render as completed AgentResponseCards
// loaded from /api/agent/runs/{id}. A turn's FindAnything deep-scan
// result (if any) renders right under its card, so results stay in
// chat order instead of dangling at the bottom.

import type { AgentEvent } from "@/lib/agentWs";
import type { ScanStatus } from "@/lib/useDeepScan";
import { DeepScanResults } from "@/components/search/DeepScanResults";
import type { AgentRunDetail } from "./types";
import AgentResponseCard from "./AgentResponseCard";

interface ConversationProps {
  pastRuns: AgentRunDetail[];
  activeQuestion: string | null;
  activeEvents: AgentEvent[];
  isStreaming: boolean;
  scansByRun?: Record<string, { scan: ScanStatus | null; error: string | null }>;
}

export default function Conversation({
  pastRuns,
  activeQuestion,
  activeEvents,
  isStreaming,
  scansByRun = {},
}: ConversationProps) {
  return (
    <div className="space-y-4">
      {pastRuns.map((r) => {
        const s = scansByRun[r.id];
        return (
          <div key={r.id} className="space-y-2">
            <AgentResponseCard question={r.question} detail={r} />
            {s && (s.scan || s.error) && (
              <DeepScanResults scan={s.scan} error={s.error} />
            )}
          </div>
        );
      })}
      {activeQuestion && (
        <AgentResponseCard
          question={activeQuestion}
          events={activeEvents}
          isStreaming={isStreaming}
        />
      )}
    </div>
  );
}
