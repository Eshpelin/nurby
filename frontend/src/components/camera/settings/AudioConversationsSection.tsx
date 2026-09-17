// Moved verbatim from src/app/cameras/[id]/page.tsx (issue #187).
// State stays in the page; this component renders and reports changes
// through the setters passed as props. Bodies are byte-identical to the
// originals, including their original indentation.

import type { Dispatch, SetStateAction } from "react";
import { Section, FieldRow, Toggle } from "./primitives";
import { formatInterval } from "./format";

interface AudioConversationsSectionProps {
  conversationGapSeconds: number;
  conversationMinMessages: number;
  conversationSummaryEnabled: boolean;
  setConversationGapSeconds: Dispatch<SetStateAction<number>>;
  setConversationMinMessages: Dispatch<SetStateAction<number>>;
  setConversationSummaryEnabled: Dispatch<SetStateAction<boolean>>;
}

export function AudioConversationsSection({
  conversationGapSeconds,
  conversationMinMessages,
  conversationSummaryEnabled,
  setConversationGapSeconds,
  setConversationMinMessages,
  setConversationSummaryEnabled,
}: AudioConversationsSectionProps) {
  return (
        <Section
          title="Audio Conversations"
          description="Group consecutive transcripts into a single rolling card and summarize the conversation when it goes quiet."
        >
          <FieldRow label="Conversation Gap" hint="Maximum silence between transcripts that still counts as the same conversation. Beyond this, a new conversation opens.">
            <div className="flex items-center gap-3">
              <input
                type="range"
                min={5}
                max={300}
                step={5}
                value={conversationGapSeconds}
                onChange={(e) => setConversationGapSeconds(Number(e.target.value))}
                className="flex-1 accent-accent"
              />
              <span className="font-mono text-xs text-muted-foreground w-20 text-right">
                {formatInterval(conversationGapSeconds)}
              </span>
            </div>
          </FieldRow>

          <FieldRow label="Generate Summary" hint="When the conversation closes, send the full transcript to the summary VLM and replace the live caption with a one-line recap.">
            <Toggle
              checked={conversationSummaryEnabled}
              onChange={setConversationSummaryEnabled}
              label={conversationSummaryEnabled ? "Enabled" : "Disabled"}
            />
          </FieldRow>

          {conversationSummaryEnabled && (
            <FieldRow label="Minimum Messages" hint="Skip the summary call for short conversations (one-liners) to save tokens.">
              <div className="flex items-center gap-3">
                <input
                  type="range"
                  min={1}
                  max={10}
                  step={1}
                  value={conversationMinMessages}
                  onChange={(e) => setConversationMinMessages(Number(e.target.value))}
                  className="flex-1 accent-accent"
                />
                <span className="font-mono text-xs text-muted-foreground w-20 text-right">
                  {conversationMinMessages} msg
                </span>
              </div>
            </FieldRow>
          )}
        </Section>
  );
}
