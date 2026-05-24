"use client";

// Center pane: a stack of turn cards. The active turn is the
// streaming one; past turns render as completed AgentResponseCards
// loaded from /api/agent/runs/{id}.

import type { AgentEvent } from "@/lib/agentWs";
import type { AgentRunDetail } from "./types";
import AgentResponseCard from "./AgentResponseCard";

interface ConversationProps {
  pastRuns: AgentRunDetail[];
  activeQuestion: string | null;
  activeEvents: AgentEvent[];
  isStreaming: boolean;
}

export default function Conversation({
  pastRuns,
  activeQuestion,
  activeEvents,
  isStreaming,
}: ConversationProps) {
  return (
    <div className="space-y-4">
      {pastRuns.map((r) => (
        <AgentResponseCard key={r.id} question={r.question} detail={r} />
      ))}
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
