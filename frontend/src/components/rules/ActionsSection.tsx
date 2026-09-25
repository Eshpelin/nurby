"use client";

import {
  defaultDraftForType,
  availableVarsBefore,
  MAX_ACTIONS_PER_RULE,
  type ActionType,
  type ActionDraft,
  type DeviceOption,
  type ProviderOption,
  type TelegramChannelOption,
} from "./types";
import { ActionCard } from "./actions/ActionCard";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import {
  DndContext,
  PointerSensor,
  KeyboardSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";

export interface ActionsSectionProps {
  telegramChannels: TelegramChannelOption[];
  telegramChannelsLoading: boolean;
  devices: DeviceOption[];
  providers: ProviderOption[];
  cameras: { id: string; name: string }[];

  formActions: ActionDraft[];
  setFormActions: (updater: ActionDraft[] | ((prev: ActionDraft[]) => ActionDraft[])) => void;

  // Per-card error message keyed by card index (var-ref validation).
  cardErrors: Record<number, string>;
}

export function ActionsSection(props: ActionsSectionProps) {
  const { telegramChannels, telegramChannelsLoading, devices, providers, cameras, formActions, setFormActions, cardErrors } =
    props;
  const [collapsed, setCollapsed] = useState<Record<number, boolean>>({});
  const { authFetch } = useAuth();
  const [pairedPhones, setPairedPhones] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await authFetch("/api/push/devices");
        if (!res.ok) return;
        const devices: unknown = await res.json();
        if (!cancelled && Array.isArray(devices)) setPairedPhones(devices.length);
      } catch {
        // Delivery status is advisory; rule editing must remain available.
      }
    })();
    return () => { cancelled = true; };
  }, [authFetch]);

  // Stable per-card ids for drag. Kept in lockstep with formActions so a
  // reorder animates correctly. Length changes (add/delete/hydrate) are
  // reconciled here; in-place edits keep the same ids.
  const counter = useRef(0);
  const newId = () => `act-${counter.current++}`;
  const [ids, setIds] = useState<string[]>(() => formActions.map(newId));
  useEffect(() => {
    setIds((prev) => {
      if (prev.length === formActions.length) return prev;
      if (prev.length < formActions.length) {
        return [...prev, ...Array(formActions.length - prev.length).fill(0).map(newId)];
      }
      return prev.slice(0, formActions.length);
    });
  }, [formActions.length]);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const replaceAt = (i: number, next: ActionDraft) => {
    setFormActions((prev) => prev.map((d, idx) => (idx === i ? next : d)));
  };
  const moveAt = (i: number, delta: -1 | 1) => {
    const j = i + delta;
    if (j < 0 || j >= formActions.length) return;
    setFormActions((prev) => arrayMove(prev, i, j));
    setIds((prev) => arrayMove(prev, i, j));
  };
  const deleteAt = (i: number) => {
    if (formActions.length <= 1) return;
    setFormActions((prev) => prev.filter((_, idx) => idx !== i));
    setIds((prev) => prev.filter((_, idx) => idx !== i));
  };
  const changeTypeAt = (i: number, t: ActionType) => {
    setFormActions((prev) =>
      prev.map((d, idx) => (idx === i ? defaultDraftForType(t) : d)),
    );
  };
  const addAction = () => {
    if (formActions.length >= MAX_ACTIONS_PER_RULE) return;
    setFormActions((prev) => [...prev, defaultDraftForType("notify")]);
    setIds((prev) => [...prev, newId()]);
  };

  const onDragEnd = (e: DragEndEvent) => {
    const { active, over } = e;
    if (!over || active.id === over.id) return;
    const from = ids.indexOf(String(active.id));
    const to = ids.indexOf(String(over.id));
    if (from < 0 || to < 0) return;
    setFormActions((prev) => arrayMove(prev, from, to));
    setIds((prev) => arrayMove(prev, from, to));
  };

  const pairedTelegram = telegramChannels.filter(
    (channel) => channel.enabled && channel.pairing_status === "paired",
  ).length;
  const hasTelegramAction = formActions.some((action) => action.type === "telegram");
  const destinations = [
    "In-app bell",
    ...(pairedPhones > 0 ? [`${pairedPhones} paired phone${pairedPhones === 1 ? "" : "s"}`] : []),
    ...(hasTelegramAction && pairedTelegram > 0 ? [`${pairedTelegram} Telegram channel${pairedTelegram === 1 ? "" : "s"}`] : []),
  ];

  return (
    <fieldset className="border border-border rounded-md p-3 space-y-2">
      <legend className="text-xs font-medium text-muted-foreground px-1">
        Action chain ({formActions.length})
      </legend>
      <p className="text-[11px] text-muted-foreground px-1 -mt-1 mb-1">
        Actions run top to bottom. Drag the handle to reorder.
      </p>
      <div className={`rounded-md border px-3 py-2 text-xs ${destinations.length === 1 ? "border-yellow-500/35 bg-yellow-500/5" : "border-border bg-muted/20"}`}>
        <div className="flex items-center justify-between gap-2">
          <span className="text-muted-foreground">This alert reaches: <span className="text-foreground">{destinations.join(", ")}</span></span>
          {destinations.length === 1 && <Link href="/settings#mobile-pairing" className="shrink-0 text-accent hover:underline">Add a phone</Link>}
        </div>
        {destinations.length === 1 && <p className="mt-1 text-[11px] text-muted-foreground">In-app alerts work while Nurby is open. Add a phone or Telegram channel to receive alerts when you are away.</p>}
      </div>
      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
        <SortableContext items={ids} strategy={verticalListSortingStrategy}>
          {formActions.map((draft, i) => (
            <div key={ids[i] ?? i}>
              <ActionCard
                sortableId={ids[i] ?? `act-${i}`}
                index={i}
                draft={draft}
                totalCount={formActions.length}
                onReplace={(next) => replaceAt(i, next)}
                onTypeChange={(t) => changeTypeAt(i, t)}
                onMove={(delta) => moveAt(i, delta)}
                onRemove={() => deleteAt(i)}
                errorMessage={cardErrors[i]}
                availableVars={availableVarsBefore(formActions, i)}
                telegramChannels={telegramChannels}
                telegramChannelsLoading={telegramChannelsLoading}
                devices={devices}
                providers={providers}
                cameras={cameras}
                isCollapsed={!!collapsed[i]}
                onToggleCollapsed={() =>
                  setCollapsed((m) => ({ ...m, [i]: !m[i] }))
                }
              />
              {i < formActions.length - 1 && (
                <div className="flex justify-center py-0.5" aria-hidden>
                  <span className="text-muted-foreground text-xs leading-none">↓</span>
                </div>
              )}
            </div>
          ))}
        </SortableContext>
      </DndContext>
      <div className="flex items-center gap-2 pt-1">
        <button
          type="button"
          onClick={addAction}
          disabled={formActions.length >= MAX_ACTIONS_PER_RULE}
          className="px-2 py-1 text-xs rounded border border-dashed border-border hover:bg-muted text-muted-foreground disabled:opacity-50"
        >
          + Add action
        </button>
        {formActions.length >= MAX_ACTIONS_PER_RULE && (
          <span className="text-[10px] text-muted-foreground">
            Limit of {MAX_ACTIONS_PER_RULE} actions reached.
          </span>
        )}
      </div>
    </fieldset>
  );
}
