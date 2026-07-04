"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import {
  cameraLookup,
  deviceLookup,
  personLookup,
  type Camera,
  type DeviceOption,
  type Person,
  type TelegramChannelOption,
} from "./types";

// Loads the reference data the rule builder needs (cameras, persons,
// telegram channels, devices) and keeps the id->name lookups populated.
// Shared by the /rules/new and /rules/[id]/edit pages.
export function useRuleRefData() {
  const { authFetch } = useAuth();
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [persons, setPersons] = useState<Person[]>([]);
  const [devices, setDevices] = useState<DeviceOption[]>([]);
  const [telegramChannels, setTelegramChannels] = useState<TelegramChannelOption[]>([]);
  const [telegramChannelsLoading, setTelegramChannelsLoading] = useState(true);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setTelegramChannelsLoading(true);
    try {
      const [camRes, perRes, tgRes, devRes] = await Promise.all([
        authFetch("/api/cameras"),
        authFetch("/api/persons"),
        authFetch("/api/telegram/channels"),
        authFetch("/api/devices/instances"),
      ]);
      if (camRes.ok) {
        const list: Camera[] = await camRes.json();
        setCameras(list);
        cameraLookup.clear();
        for (const c of list) cameraLookup.set(c.id, c.name);
      }
      if (perRes.ok) {
        const list: Person[] = await perRes.json();
        setPersons(list);
        personLookup.clear();
        for (const p of list) personLookup.set(p.id, p.display_name);
      }
      if (tgRes.ok) setTelegramChannels(await tgRes.json());
      if (devRes.ok) {
        const list: { id: string; name: string }[] = await devRes.json();
        const opts = list.map((d) => ({ id: d.id, name: d.name }));
        setDevices(opts);
        deviceLookup.clear();
        for (const d of opts) deviceLookup.set(d.id, d.name);
      }
    } catch {
      /* silent */
    } finally {
      setLoading(false);
      setTelegramChannelsLoading(false);
    }
  }, [authFetch]);

  useEffect(() => {
    load();
  }, [load]);

  return { cameras, persons, devices, telegramChannels, telegramChannelsLoading, loading };
}
