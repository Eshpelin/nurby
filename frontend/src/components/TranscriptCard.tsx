"use client";

import { useState } from "react";
import { useAuth } from "@/lib/auth";
import { formatWith } from "@/lib/time";

// Inline SVG. The frontend does not bundle lucide-react.
const Mic = ({ className }: { className?: string }) => (
  <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
    <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
    <line x1="12" y1="19" x2="12" y2="23" />
    <line x1="8" y1="23" x2="16" y2="23" />
  </svg>
);

const PlayIcon = ({ className }: { className?: string }) => (
  <svg className={className} viewBox="0 0 24 24" fill="currentColor" stroke="none">
    <polygon points="6 4 20 12 6 20 6 4" />
  </svg>
);

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
}

/**
 * Timeline card for a transcript event. Italic text, mic icon, optional
 * inline audio player when raw audio is on disk. Stays visually distinct
 * from observation cards so the feed stays scannable.
 */
export function TranscriptCard(props: TranscriptCardProps) {
  const { startedAt, text, audioCaptureId, provider, language } = props;
  const { token } = useAuth();
  const [showPlayer, setShowPlayer] = useState(false);
  const t = new Date(startedAt);

  const audioUrl = audioCaptureId && token
    ? `/api/audio/${audioCaptureId}?token=${encodeURIComponent(token)}`
    : null;

  return (
    <div
      role="article"
      className="rounded-lg border border-zinc-800 bg-zinc-900 p-3 hover:border-zinc-700 transition"
    >
      <div className="flex items-center gap-2 text-xs text-zinc-400 mb-1.5">
        <Mic className="w-3.5 h-3.5 text-emerald-400" />
        <span>{formatWith(t, { hour: "numeric", minute: "2-digit", second: "2-digit" })}</span>
        {provider ? <span className="text-zinc-500">· {provider}</span> : null}
        {language ? <span className="text-zinc-500">· {language}</span> : null}
      </div>
      <p className="text-sm italic text-zinc-100 leading-relaxed">{text}</p>
      {audioUrl ? (
        <div className="mt-2">
          {showPlayer ? (
            <audio
              controls
              autoPlay
              src={audioUrl}
              className="w-full h-8"
              preload="none"
            />
          ) : (
            <button
              type="button"
              onClick={() => setShowPlayer(true)}
              className="inline-flex items-center gap-1 text-xs text-emerald-400 hover:text-emerald-300"
            >
              <PlayIcon className="w-3 h-3" />
              Play audio
            </button>
          )}
        </div>
      ) : null}
    </div>
  );
}
