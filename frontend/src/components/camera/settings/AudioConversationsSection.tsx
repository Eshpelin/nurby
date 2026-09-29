// Moved verbatim from src/app/cameras/[id]/page.tsx (issue #187).
// State stays in the page; this component renders and reports changes
// through the setters passed as props. Bodies are byte-identical to the
// originals, including their original indentation.

import type { Dispatch, SetStateAction } from "react";
import { Section, FieldRow, Toggle } from "./primitives";
import { formatInterval } from "./format";
import { translate, type Locale } from "@/lib/i18n";

interface AudioConversationsSectionProps {
  locale: Locale;
  conversationGapSeconds: number;
  conversationMinMessages: number;
  conversationSummaryEnabled: boolean;
  setConversationGapSeconds: Dispatch<SetStateAction<number>>;
  setConversationMinMessages: Dispatch<SetStateAction<number>>;
  setConversationSummaryEnabled: Dispatch<SetStateAction<boolean>>;
}

export function AudioConversationsSection({
  locale,
  conversationGapSeconds,
  conversationMinMessages,
  conversationSummaryEnabled,
  setConversationGapSeconds,
  setConversationMinMessages,
  setConversationSummaryEnabled,
}: AudioConversationsSectionProps) {
  const t = (key: string, values?: Record<string, string | number>) => translate(locale, key, values);
  return (
        <Section
          title={t("camera.audio_conversations.title")}
          description={t("camera.audio_conversations.description")}
        >
          <FieldRow label={t("camera.audio_conversations.gap")} hint={t("camera.audio_conversations.gap_hint")}>
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

          <FieldRow label={t("camera.audio_conversations.summary")} hint={t("camera.audio_conversations.summary_hint")}>
            <Toggle
              checked={conversationSummaryEnabled}
              onChange={setConversationSummaryEnabled}
              label={conversationSummaryEnabled ? t("common.enabled") : t("common.disabled")}
            />
          </FieldRow>

          {conversationSummaryEnabled && (
            <FieldRow label={t("camera.audio_conversations.minimum_messages")} hint={t("camera.audio_conversations.minimum_messages_hint")}>
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
                  {t("camera.audio_conversations.message_count", { count: conversationMinMessages })}
                </span>
              </div>
            </FieldRow>
          )}
        </Section>
  );
}
