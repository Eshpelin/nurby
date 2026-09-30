"use client";

import {
  ACTION_TYPES,
  describeActions,
  draftToDict,
  type ActionDraft,
  type ActionType,
  type WebhookDraft,
  type BroadcastDraft,
  type NotifyDraft,
  type EmailDraft,
  type TelegramDraft,
  type VlmCallDraft,
  type VerifyDraft,
  type LocateDraft,
  type DeviceDraft,
  type SpeakDraft,
  type DeviceOption,
  type ProviderOption,
  type TelegramChannelOption,
} from "../types";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { StyledSelect } from "../StyledSelect";
import { WebhookEditor } from "./WebhookEditor";
import { BroadcastEditor } from "./BroadcastEditor";
import { NotifyEditor } from "./NotifyEditor";
import { EmailEditor } from "./EmailEditor";
import { TelegramEditor } from "./TelegramEditor";
import { VlmCallEditor } from "./VlmCallEditor";
import { VerifyEditor } from "./VerifyEditor";
import { LocateEditor } from "./LocateEditor";
import { DeviceEditor } from "./DeviceEditor";
import { SpeakEditor } from "./SpeakEditor";
import { type VarSpec } from "./VarInserter";
import { useAuth } from "@/lib/auth";
import { translate } from "@/lib/i18n";

export interface ActionCardProps {
  sortableId: string;
  index: number;
  draft: ActionDraft;
  totalCount: number;
  onReplace: (next: ActionDraft) => void;
  onTypeChange: (type: ActionType) => void;
  onMove: (delta: -1 | 1) => void;
  onRemove: () => void;
  errorMessage?: string;
  availableVars: VarSpec[];
  telegramChannels: TelegramChannelOption[];
  telegramChannelsLoading: boolean;
  devices: DeviceOption[];
  cameras: { id: string; name: string }[];
  providers: ProviderOption[];
  isCollapsed: boolean;
  onToggleCollapsed: () => void;
}

export function ActionCard({
  sortableId,
  index,
  draft,
  totalCount,
  onReplace,
  onTypeChange,
  onMove,
  onRemove,
  errorMessage,
  availableVars,
  telegramChannels,
  telegramChannelsLoading,
  devices,
  cameras,
  providers,
  isCollapsed,
  onToggleCollapsed,
}: ActionCardProps) {
  const { user } = useAuth();
  const t = (key: string, values?: Record<string, string | number>) => translate(user?.locale, key, values);
  const typeLabel = t(`rules.action_type.${draft.type}`) || ACTION_TYPES.find((a) => a.value === draft.type)?.label || draft.type;

  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: sortableId });
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  // A gate that can abort the rest of the chain. Verify always can,
  // vlm_call only when its on-error is set to stop.
  const canStopChain =
    draft.type === "verify" ||
    (draft.type === "locate" && (draft as LocateDraft).onFail === "stop") ||
    (draft.type === "vlm_call" && (draft as VlmCallDraft).onError === "stop");

  // One-line summary shown when the card is collapsed.
  const collapsedSummary = describeActions(draftToDict(draft));

  return (
    <fieldset
      ref={setNodeRef}
      style={style}
      id={`rule-action-${index}`}
      className={`border rounded-md p-3 space-y-3 ${
        errorMessage ? "border-red-500/60" : "border-border"
      } ${isDragging ? "ring-1 ring-accent" : ""}`}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <button
            type="button"
            {...attributes}
            {...listeners}
            className="cursor-grab active:cursor-grabbing text-muted-foreground hover:text-foreground px-0.5 touch-none"
            title={t("rules.action.drag_to_reorder")}
            aria-label={t("rules.action.drag_to_reorder")}
          >
            ⠿
          </button>
          <span className="px-1.5 py-0.5 text-[10px] rounded bg-muted text-zinc-300 font-mono">
            {index + 1}
          </span>
          <span className="text-xs px-1.5 py-0.5 rounded border border-border text-muted-foreground">
            {typeLabel}
          </span>
          {canStopChain && (
            <span
              className="text-[10px] px-1.5 py-0.5 rounded border border-amber-500/40 bg-amber-500/10 text-amber-300"
              title={t("rules.action.may_stop_help")}
            >
              {t("rules.action.may_stop")}
            </span>
          )}
          <button
            type="button"
            onClick={onToggleCollapsed}
            className="text-[10px] px-1.5 py-0.5 rounded border border-border hover:bg-muted text-muted-foreground"
            title={isCollapsed ? t("rules.action.expand") : t("rules.action.collapse")}
          >
            {isCollapsed ? "▸" : "▾"}
          </button>
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            disabled={index === 0}
            onClick={() => onMove(-1)}
            className="text-[10px] px-1.5 py-0.5 rounded border border-border hover:bg-muted text-muted-foreground disabled:opacity-30"
            title={t("rules.action.move_up")}
          >
            ↑
          </button>
          <button
            type="button"
            disabled={index === totalCount - 1}
            onClick={() => onMove(1)}
            className="text-[10px] px-1.5 py-0.5 rounded border border-border hover:bg-muted text-muted-foreground disabled:opacity-30"
            title={t("rules.action.move_down")}
          >
            ↓
          </button>
          <button
            type="button"
            onClick={onRemove}
            className="text-[10px] px-1.5 py-0.5 rounded border border-red-800 text-red-400 hover:bg-red-900/30"
            title={t("rules.action.delete")}
          >
            ✕
          </button>
        </div>
      </div>
      {isCollapsed && (
        <div className="text-[11px] text-muted-foreground truncate pl-1">
          {collapsedSummary}
        </div>
      )}
      {!isCollapsed && (
        <>
          <StyledSelect
            value={draft.type}
            options={ACTION_TYPES.map((a) => ({ value: a.value, label: a.label }))}
            onChange={(v) => onTypeChange(v as ActionType)}
          />
          {(draft.type === "webhook" || draft.type === "api_call") && (
            <WebhookEditor
              draft={draft as WebhookDraft}
              onChange={(next) => onReplace(next)}
              availableVars={availableVars}
            />
          )}
          {draft.type === "broadcast" && (
            <BroadcastEditor
              draft={draft as BroadcastDraft}
              onChange={(next) => onReplace(next)}
              availableVars={availableVars}
            />
          )}
          {draft.type === "notify" && (
            <NotifyEditor
              draft={draft as NotifyDraft}
              onChange={(next) => onReplace(next)}
              availableVars={availableVars}
            />
          )}
          {draft.type === "email" && (
            <EmailEditor
              draft={draft as EmailDraft}
              onChange={(next) => onReplace(next)}
              availableVars={availableVars}
            />
          )}
          {draft.type === "telegram" && (
            <TelegramEditor
              draft={draft as TelegramDraft}
              onChange={(next) => onReplace(next)}
              availableVars={availableVars}
              telegramChannels={telegramChannels}
              telegramChannelsLoading={telegramChannelsLoading}
            />
          )}
          {draft.type === "vlm_call" && (
            <VlmCallEditor
              draft={draft as VlmCallDraft}
              onChange={(next) => onReplace(next)}
            />
          )}
          {draft.type === "verify" && (
            <VerifyEditor
              draft={draft as VerifyDraft}
              onChange={(next) => onReplace(next)}
              providers={providers}
            />
          )}
          {draft.type === "locate" && (
            <LocateEditor
              draft={draft as LocateDraft}
              onChange={(next) => onReplace(next)}
            />
          )}
          {draft.type === "speak" && (
            <SpeakEditor
              draft={draft as SpeakDraft}
              cameras={cameras}
              availableVars={availableVars}
              onChange={(next) => onReplace(next)}
            />
          )}
          {draft.type === "device" && (
            <DeviceEditor
              draft={draft as DeviceDraft}
              devices={devices}
              onChange={(patch) =>
                onReplace({ ...(draft as DeviceDraft), ...patch })
              }
            />
          )}
        </>
      )}
      {errorMessage && (
        <div className="text-[11px] text-red-400">{errorMessage}</div>
      )}
    </fieldset>
  );
}

export default ActionCard;
