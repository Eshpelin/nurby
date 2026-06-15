"use client";

/**
 * Telegram notifications settings section.
 *
 * Renders the card row in the Settings page plus the multi-step modal
 * for adding a channel and guiding the user through pairing.
 *
 * Phase 1 design notes:
 *  - QR rendering uses `api.qrserver.com` since the project has no
 *    local QR library. The URL is short and stable; the user can also
 *    tap the deep link directly. If the asset host is unreachable,
 *    pairing still works via the link or the manual /pair command.
 *  - The pairing modal polls GET /channels/{id} every 2 seconds while
 *    on step 2; we stop polling on success, modal close, or after the
 *    nonce TTL elapses.
 */

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { useToast, useConfirm } from "@/lib/feedback";

import { ChannelRow } from "./telegram/ChannelRow";
import { AddOrPairModal } from "./telegram/AddOrPairModal";
import { type TelegramChannel } from "./telegram/telegram-shared";

export default function TelegramSection() {
  const { authFetch } = useAuth();
  const [channels, setChannels] = useState<TelegramChannel[]>([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [pairingChannelId, setPairingChannelId] = useState<string | null>(null);

  const fetchChannels = useCallback(async () => {
    try {
      const res = await authFetch("/api/telegram/channels");
      if (res.ok) setChannels(await res.json());
    } catch {
      /* silent */
    } finally {
      setLoading(false);
    }
  }, [authFetch]);

  useEffect(() => {
    fetchChannels();
  }, [fetchChannels]);

  const openAdd = () => {
    setPairingChannelId(null);
    setShowModal(true);
  };

  const resumePairing = (channelId: string) => {
    setPairingChannelId(channelId);
    setShowModal(true);
  };

  const enabledPairedCount = channels.filter((c) => c.pairing_status === "paired").length;
  const pendingCount = channels.filter((c) => c.pairing_status === "pending").length;

  return (
    <>
      {/* Section card. Mirrors the Email card style */}
      <div className="rounded-lg border border-border bg-card px-4 py-3.5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span
              className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${
                channels.length === 0
                  ? "bg-muted-foreground/40"
                  : enabledPairedCount > 0
                  ? "bg-green-500"
                  : "bg-amber-500"
              }`}
            />
            <div>
              <div className="text-sm font-medium">Telegram alerts</div>
              <div className="text-xs text-muted-foreground mt-0.5">
                {loading
                  ? "Loading."
                  : channels.length === 0
                  ? "No channels yet. Add a Telegram bot to receive alerts."
                  : `${enabledPairedCount} paired${pendingCount > 0 ? `, ${pendingCount} pending` : ""}.`}
              </div>
            </div>
          </div>
          <button
            type="button"
            onClick={openAdd}
            className="px-3 py-1.5 text-xs rounded-md border border-border hover:bg-muted transition-colors"
          >
            Add Telegram channel
          </button>
        </div>

        {channels.length > 0 && (
          <div className="mt-4 space-y-2">
            {channels.map((c) => (
              <ChannelRow
                key={c.id}
                channel={c}
                onChange={fetchChannels}
                onResumePair={() => resumePairing(c.id)}
              />
            ))}
          </div>
        )}
      </div>

      {showModal && (
        <AddOrPairModal
          existingChannelId={pairingChannelId}
          onClose={() => {
            setShowModal(false);
            setPairingChannelId(null);
            fetchChannels();
          }}
          onChannelChange={fetchChannels}
        />
      )}
    </>
  );
}

