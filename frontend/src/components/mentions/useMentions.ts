"use client";

// Shared @-mention machinery for plain <input> and <textarea> composers.
// No contentEditable, no token pills: '@' opens a filtered dropdown,
// selecting splices the plain name into the text and records the
// resolved {kind, id, name}. At submit time callers take
// activeMentions(text): only mentions whose name still appears in the
// text survive, so edits/deletions degrade to name matching, never to
// a wrong UUID (the backend independently drops unknown ids).

import { RefObject, useCallback, useMemo, useState } from "react";
import {
  useMentionables,
  type MentionRef,
  type Mentionable,
} from "@/lib/useMentionables";

const MAX_ITEMS = 8;
// An active token is "@partial-word" immediately before the caret,
// preceded by start-of-text or whitespace.
const TOKEN_RE = /(^|\s)@([\w-]*)$/;

type Field = HTMLInputElement | HTMLTextAreaElement;

export interface UseMentionsResult {
  open: boolean;
  items: Mentionable[];
  highlight: number;
  // Chain BEFORE any Enter-submits handler; returns true when the event
  // was consumed by the dropdown (caller must then skip its own logic).
  onKeyDown: (e: React.KeyboardEvent<Field>) => boolean;
  // Re-evaluate the active token. Call from the field's onChange (and
  // onClick/onKeyUp if caret-only moves should update the menu).
  refresh: () => void;
  select: (item: Mentionable) => void;
  close: () => void;
  activeMentions: (text: string) => MentionRef[];
}

export function useMentions(
  fieldRef: RefObject<Field | null>,
  value: string,
  onChangeValue: (v: string) => void,
): UseMentionsResult {
  const { mentionables } = useMentionables();
  const [tokenStart, setTokenStart] = useState(-1); // index of '@', -1 = closed
  const [query, setQuery] = useState("");
  const [highlight, setHighlight] = useState(0);
  const [mentions, setMentions] = useState<MentionRef[]>([]);

  const refresh = useCallback(() => {
    const el = fieldRef.current;
    if (!el || el.selectionStart == null) {
      setTokenStart(-1);
      return;
    }
    const upToCaret = el.value.slice(0, el.selectionStart);
    const m = TOKEN_RE.exec(upToCaret);
    if (m) {
      setTokenStart(upToCaret.length - m[2].length - 1);
      setQuery(m[2]);
      setHighlight(0);
    } else {
      setTokenStart(-1);
    }
  }, [fieldRef]);

  const items = useMemo(() => {
    if (tokenStart < 0) return [];
    const q = query.toLowerCase();
    return mentionables
      .filter(
        (it) =>
          !q ||
          it.name.toLowerCase().includes(q) ||
          (it.hint || "").toLowerCase().includes(q),
      )
      .slice(0, MAX_ITEMS);
  }, [mentionables, tokenStart, query]);

  const open = tokenStart >= 0 && items.length > 0;

  const close = useCallback(() => setTokenStart(-1), []);

  const select = useCallback(
    (item: Mentionable) => {
      const el = fieldRef.current;
      if (!el || tokenStart < 0) return;
      const caret = el.selectionStart ?? value.length;
      const before = value.slice(0, tokenStart);
      const after = value.slice(caret);
      const inserted = `@${item.name} `;
      onChangeValue(before + inserted + after);
      setMentions((prev) =>
        prev.some((m) => m.kind === item.kind && m.id === item.id)
          ? prev
          : [...prev, { kind: item.kind, id: item.id, name: item.name }],
      );
      setTokenStart(-1);
      // Restore the caret after React re-renders the controlled value.
      const pos = before.length + inserted.length;
      requestAnimationFrame(() => {
        el.focus();
        try {
          el.setSelectionRange(pos, pos);
        } catch {
          /* number inputs etc. don't support it; not our fields */
        }
      });
    },
    [fieldRef, tokenStart, value, onChangeValue],
  );

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent<Field>): boolean => {
      if (!open) return false;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setHighlight((h) => (h + 1) % items.length);
        return true;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setHighlight((h) => (h - 1 + items.length) % items.length);
        return true;
      }
      if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        select(items[Math.min(highlight, items.length - 1)]);
        return true;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        close();
        return true;
      }
      return false;
    },
    [open, items, highlight, select, close],
  );

  const activeMentions = useCallback(
    (text: string): MentionRef[] => {
      const lower = text.toLowerCase();
      return mentions.filter((m) => lower.includes(m.name.toLowerCase()));
    },
    [mentions],
  );

  return { open, items, highlight, onKeyDown, refresh, select, close, activeMentions };
}
