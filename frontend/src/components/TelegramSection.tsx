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
import { translate } from "@/lib/i18n";
import { useToast, useConfirm } from "@/lib/feedback";

import { ChannelRow } from "./telegram/ChannelRow";
import { AddOrPairModal } from "./telegram/AddOrPairModal";
import { type TelegramChannel } from "./telegram/telegram-shared";

export default function TelegramSection() {
  const { authFetch, user } = useAuth();
  const t = (key: string, values?: Record<string, string | number>) => translate(user?.locale, key, values);
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
      <div id="telegram-alerts" className="rounded-lg border border-border bg-card px-4 py-3.5 scroll-mt-20">
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
              <div className="text-sm font-medium">{t("telegram.title")}</div>
              <div className="text-xs text-muted-foreground mt-0.5">
                {loading
                  ? t("telegram.loading")
                  : channels.length === 0
                  ? t("telegram.empty")
                  : `${t(enabledPairedCount === 1 ? "telegram.paired_one" : "telegram.paired_other", { count: enabledPairedCount })}${pendingCount > 0 ? `, ${t(pendingCount === 1 ? "telegram.pending_one" : "telegram.pending_other", { count: pendingCount })}` : ""}.`}
              </div>
            </div>
          </div>
          <button
            type="button"
            onClick={openAdd}
            className="px-3 py-1.5 text-xs rounded-md border border-border hover:bg-muted transition-colors"
          >
            {t("telegram.add")}
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
