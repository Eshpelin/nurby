"use client";

import { Mic } from "lucide-react";

interface TranscriptCardProps {
  id: string;
  cameraId: string;
  cameraName?: string;
  startedAt: string;
  endedAt: string;
  text: string;
  audioCaptureId?: string | null;
  language?: string | null;
  provider?: string;
  onPlay?: (captureId: string) => void;
}

/**
 * Timeline card for a transcript event. Italic text, mic icon, optional
 * play button when raw audio is on disk. Stays visually distinct from
 * observation cards so the feed stays scannable.
 */
export function TranscriptCard(props: TranscriptCardProps) {
  const { startedAt, text, audioCaptureId, provider, language, onPlay } = props;
  const t = new Date(startedAt);

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-3 hover:border-zinc-700 transition">
      <div className="flex items-center gap-2 text-xs text-zinc-400 mb-1.5">
        <Mic className="w-3.5 h-3.5 text-emerald-400" />
        <span>{t.toLocaleTimeString()}</span>
        {provider ? <span className="text-zinc-500">· {provider}</span> : null}
        {language ? <span className="text-zinc-500">· {language}</span> : null}
      </div>
      <p className="text-sm italic text-zinc-100 leading-relaxed">{text}</p>
      {audioCaptureId ? (
        <button
          type="button"
          onClick={() => onPlay?.(audioCaptureId)}
          className="mt-2 text-xs text-emerald-400 hover:text-emerald-300"
        >
          Play audio
        </button>
      ) : null}
    </div>
  );
}
