"use client";

import { useAuth } from "@/lib/auth";
import { extractApiError } from "@/lib/api-error";

import { useCallback, useEffect, useRef, useState } from "react";
import { PersonaPicker } from "@/components/PersonaPicker";
import { RetryCountdown } from "@/components/RetryCountdown";
import { CameraPlayer } from "@/components/CameraPlayer";
import type { PersonaPatch } from "@/lib/camera-personas";
import { PrivacyZonesSection } from "@/components/PrivacyZonesSection";
import { ActivityStrip } from "@/components/ActivityStrip";
import type { MotionZone } from "@/components/camera/types";
import { ZoneEditorCanvas } from "@/components/camera/ZoneEditorCanvas";
import { PTZControlPanel } from "@/components/camera/PTZControlPanel";
import { CameraActivityTab } from "@/components/camera/CameraActivityTab";
import { Section, StatusDot } from "@/components/camera/settings/primitives";
import { STREAM_TYPES } from "@/components/camera/settings/constants";
import type { Camera, Provider } from "@/components/camera/settings/types";
import { GeneralSection } from "@/components/camera/settings/GeneralSection";
import { FeedSection } from "@/components/camera/settings/FeedSection";
import { AuthSection } from "@/components/camera/settings/AuthSection";
import { AiAnalysisSection } from "@/components/camera/settings/AiAnalysisSection";
import { RefinerSection } from "@/components/camera/settings/RefinerSection";
import { DetectionSection } from "@/components/camera/settings/DetectionSection";
import { RecapsSection } from "@/components/camera/settings/RecapsSection";
import { SummarizationSection } from "@/components/camera/settings/SummarizationSection";
import { AudioConversationsSection } from "@/components/camera/settings/AudioConversationsSection";
import { IncidentTrackingSection } from "@/components/camera/settings/IncidentTrackingSection";
import { SmartTrackSection } from "@/components/camera/settings/SmartTrackSection";
import { YoloWorldPromptsSection } from "@/components/camera/settings/YoloWorldPromptsSection";
import { TimezoneSection } from "@/components/camera/settings/TimezoneSection";
import { RetentionSection } from "@/components/camera/settings/RetentionSection";
import { StorageSection } from "@/components/camera/settings/StorageSection";
import { DangerZoneSection } from "@/components/camera/settings/DangerZoneSection";
import { SaveBar } from "@/components/camera/settings/SaveBar";

import { useParams, useRouter } from "next/navigation";
import Link from "next/link";




export default function CameraConfigPage() {
  const { authFetch, loading: authLoading } = useAuth();
  const params = useParams();
  const router = useRouter();
  const cameraId = params.id as string;

  const [camera, setCamera] = useState<Camera | null>(null);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState(false);

  // Form state
  const [name, setName] = useState("");
  const [streamUrl, setStreamUrl] = useState("");
  const [streamType, setStreamType] = useState("rtsp");
  const [locationLabel, setLocationLabel] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [authToken, setAuthToken] = useState("");
  const [snapshotInterval, setSnapshotInterval] = useState(2);
  const [motionSensitivity, setMotionSensitivity] = useState(0.5);
  const [recordingEnabled, setRecordingEnabled] = useState(true);
  const [recordingMode, setRecordingMode] = useState("always");
  const [recordingTriggerObjects, setRecordingTriggerObjects] = useState<string[]>([]);
  const [recordingClipPre, setRecordingClipPre] = useState(5);
  const [recordingClipPost, setRecordingClipPost] = useState(10);
  const [vlmProviderId, setVlmProviderId] = useState<string | null>(null);
  const [vlmPrompt, setVlmPrompt] = useState("");
  const [showDefaultVlmPrompt, setShowDefaultVlmPrompt] = useState(false);
  // Live view starts open; a camera the user collapsed stays collapsed.
  const [liveViewOpen, setLiveViewOpen] = useState(() => {
    if (typeof window !== "undefined") {
      try { return localStorage.getItem(`nurby-cam-live-${window.location.pathname.split("/")[2]}`) !== "0"; }
      catch { /* ignore */ }
    }
    return true;
  });
  const [vlmInterval, setVlmInterval] = useState(0);
  const [vlmMaxTokens, setVlmMaxTokens] = useState(200);
  const [vlmMaxInputTokens, setVlmMaxInputTokens] = useState<string>("");
  const [vlmRefinerProviderId, setVlmRefinerProviderId] = useState<string | null>(null);
  const [vlmRefinerTriggerObjects, setVlmRefinerTriggerObjects] = useState<string[]>(["person"]);
  const [vlmRefinerKeywords, setVlmRefinerKeywords] = useState<string[]>(["package", "delivery", "stranger", "weapon"]);
  const [vlmRefinerMaxTokens, setVlmRefinerMaxTokens] = useState<string>("");
  const [vlmRefinerMaxInputTokens, setVlmRefinerMaxInputTokens] = useState<string>("");
  const [vlmTrigger, setVlmTrigger] = useState("always");
  const [vlmTriggerObjects, setVlmTriggerObjects] = useState<string[]>([]);
  const [detectObjects, setDetectObjects] = useState(true);
  const [detectFaces, setDetectFaces] = useState(true);
  const [detectPlates, setDetectPlates] = useState(true);
  const [detectClasses, setDetectClasses] = useState<string[] | null>(null);
  const [sceneMode, setSceneMode] = useState("indoor");
  const [platelessReid, setPlatelessReid] = useState<boolean | null>(null);
  const [objectConfidence, setObjectConfidence] = useState(0.35);
  const [detectionModels, setDetectionModels] = useState<{model: string; confidence: number; enabled: boolean; label_filter: string[]}[]>([]);
  const [detectionMerge, setDetectionMerge] = useState("any");
  const [modelClasses, setModelClasses] = useState<string[]>([]);
  const [modelClassesLoading, setModelClassesLoading] = useState(false);
  const [detectionConsensusMin, setDetectionConsensusMin] = useState(2);
  const [digestEnabled, setDigestEnabled] = useState(true);
  const [digestPeriod, setDigestPeriod] = useState("24h");
  const [digestProviderId, setDigestProviderId] = useState<string | null>(null);
  const [digestPrompt, setDigestPrompt] = useState("");
  const [retentionMode, setRetentionMode] = useState("none");
  const [storageProfileId, setStorageProfileId] = useState<string | null>(null);
  const [retentionDays, setRetentionDays] = useState(30);
  const [retentionGb, setRetentionGb] = useState(50);
  const [summaryProviderId, setSummaryProviderId] = useState<string | null>(null);
  const [summaryMode, setSummaryMode] = useState("off");
  const [summaryPeriodSeconds, setSummaryPeriodSeconds] = useState(1800);
  const [summaryEventQuietSeconds, setSummaryEventQuietSeconds] = useState(60);
  const [summaryEventTriggerObjects, setSummaryEventTriggerObjects] = useState<string[]>(["person"]);
  const [summaryEventMinDurationSeconds, setSummaryEventMinDurationSeconds] = useState(5);
  const [summaryMaxTokens, setSummaryMaxTokens] = useState(400);
  const [conversationGapSeconds, setConversationGapSeconds] = useState(30);
  const [conversationSummaryEnabled, setConversationSummaryEnabled] = useState(true);
  const [conversationMinMessages, setConversationMinMessages] = useState(2);
  const [incidentTrackingEnabled, setIncidentTrackingEnabled] = useState(true);
  const [incidentIdleSeconds, setIncidentIdleSeconds] = useState(600);
  const [privacyZoneTargets, setPrivacyZoneTargets] = useState<string[]>([]);
  const [privacyZoneBlurStrength, setPrivacyZoneBlurStrength] = useState(55);
  const [yoloWorldPrompts, setYoloWorldPrompts] = useState<string[]>([]);
  const [cameraTimezone, setCameraTimezone] = useState<string>("");
  // Smart Track state
  const [smartTrackEnabled, setSmartTrackEnabled] = useState(false);
  const [smartTrackTargets, setSmartTrackTargets] = useState<string[]>([]);
  const [smartTrackIgnore, setSmartTrackIgnore] = useState<string[]>([]);
  const [smartTrackPriority, setSmartTrackPriority] = useState<string[]>([]);
  const [smartTrackLostSeconds, setSmartTrackLostSeconds] = useState(3);
  const [smartTrackHomePreset, setSmartTrackHomePreset] = useState<string>("");
  const [smartTrackZoom, setSmartTrackZoom] = useState(false);
  const [smartTrackDeadzone, setSmartTrackDeadzone] = useState(0.15);
  const [smartTrackMaxSpeed, setSmartTrackMaxSpeed] = useState(0.5);
  const [smartTrackGain, setSmartTrackGain] = useState(1.5);
  const [smartTrackMinConfidence, setSmartTrackMinConfidence] = useState(0.45);
  const [smartTrackMoveBudget, setSmartTrackMoveBudget] = useState(30);
  const [ptzProfileToken, setPtzProfileToken] = useState("Profile_1");
  const [smartTrackPresets, setSmartTrackPresets] = useState<{token: string; name: string}[]>([]);
  const [activeTab, setActiveTab] = useState<"settings" | "activity">("settings");
  const [motionZones, setMotionZones] = useState<MotionZone[]>([]);

  const fetchData = useCallback(async () => {
    try {
      const [camRes, provRes] = await Promise.all([
        authFetch(`/api/cameras/${cameraId}`),
        authFetch(`/api/providers`),
      ]);
      if (!camRes.ok) {
        setError("Camera not found");
        setLoading(false);
        return;
      }
      const cam: Camera = await camRes.json();
      const provs: Provider[] = provRes.ok ? await provRes.json() : [];

      setCamera(cam);
      setProviders(provs);

      // Populate form
      setName(cam.name);
      setStreamUrl(cam.stream_url);
      setStreamType(cam.stream_type);
      setLocationLabel(cam.location_label || "");
      setUsername(cam.username || "");
      setPassword("");
      setAuthToken(cam.auth_token || "");
      setSnapshotInterval(cam.snapshot_interval ?? 2);
      setMotionSensitivity(cam.motion_sensitivity ?? 0.5);
      setRecordingEnabled(cam.recording_enabled ?? true);
      setRecordingMode(cam.recording_mode ?? "always");
      setRecordingTriggerObjects(cam.recording_trigger_objects ?? []);
      setRecordingClipPre(cam.recording_clip_pre ?? 5);
      setRecordingClipPost(cam.recording_clip_post ?? 10);
      setVlmProviderId(cam.vlm_provider_id ?? null);
      setVlmPrompt(cam.vlm_prompt || "");
      setVlmInterval(cam.vlm_interval ?? 0);
      setVlmMaxTokens(cam.vlm_max_tokens ?? 200);
      setVlmMaxInputTokens(cam.vlm_max_input_tokens != null ? String(cam.vlm_max_input_tokens) : "");
      setVlmRefinerProviderId(cam.vlm_refiner_provider_id ?? null);
      setVlmRefinerTriggerObjects(cam.vlm_refiner_trigger_objects ?? ["person"]);
      setVlmRefinerKeywords(cam.vlm_refiner_keywords ?? ["package", "delivery", "stranger", "weapon"]);
      setVlmRefinerMaxTokens(cam.vlm_refiner_max_tokens != null ? String(cam.vlm_refiner_max_tokens) : "");
      setVlmRefinerMaxInputTokens(cam.vlm_refiner_max_input_tokens != null ? String(cam.vlm_refiner_max_input_tokens) : "");
      setVlmTrigger(cam.vlm_trigger ?? "always");
      setVlmTriggerObjects(cam.vlm_trigger_objects ?? []);
      setDetectObjects(cam.detect_objects ?? true);
      setDetectFaces(cam.detect_faces ?? true);
      setDetectPlates(cam.detect_plates ?? true);
      setDetectClasses(cam.detect_classes ?? null);
      setSceneMode(cam.scene_mode ?? "indoor");
      setPlatelessReid(cam.plateless_reid_enabled ?? null);
      setObjectConfidence(cam.object_confidence ?? 0.35);
      setDetectionModels(cam.detection_models ?? []);
      setDetectionMerge(cam.detection_merge ?? "any");
      setDetectionConsensusMin(cam.detection_consensus_min ?? 2);
      setDigestEnabled(cam.digest_enabled ?? true);
      setDigestPeriod(cam.digest_period ?? "24h");
      setDigestProviderId(cam.digest_provider_id ?? null);
      setDigestPrompt(cam.digest_prompt || "");
      setRetentionMode(cam.retention_mode ?? "none");
      setStorageProfileId(cam.storage_profile_id ?? null);
      setRetentionDays(cam.retention_days ?? 30);
      setRetentionGb(cam.retention_gb ?? 50);
      setSummaryProviderId(cam.summary_provider_id ?? null);
      setSummaryMode(cam.summary_mode ?? "off");
      setSummaryPeriodSeconds(cam.summary_period_seconds ?? 1800);
      setSummaryEventQuietSeconds(cam.summary_event_quiet_seconds ?? 60);
      setSummaryEventTriggerObjects(cam.summary_event_trigger_objects ?? ["person"]);
      setSummaryEventMinDurationSeconds(cam.summary_event_min_duration_seconds ?? 5);
      setSummaryMaxTokens(cam.summary_max_tokens ?? 400);
      setConversationGapSeconds(cam.conversation_gap_seconds ?? 30);
      setConversationSummaryEnabled(cam.conversation_summary_enabled ?? true);
      setConversationMinMessages(cam.conversation_min_messages_for_summary ?? 2);
      setIncidentTrackingEnabled(cam.incident_tracking_enabled ?? true);
      setIncidentIdleSeconds(cam.incident_idle_seconds ?? 600);
      setPrivacyZoneTargets(cam.privacy_zone_targets ?? []);
      setPrivacyZoneBlurStrength(cam.privacy_zone_blur_strength ?? 55);
      setYoloWorldPrompts((cam as Camera & { yolo_world_prompts?: string[] | null }).yolo_world_prompts ?? []);
      setCameraTimezone(cam.timezone ?? "");
      setMotionZones(cam.motion_zones ?? []);
      setSmartTrackEnabled(cam.ptz_smart_track_enabled ?? false);
      setSmartTrackTargets(cam.ptz_smart_track_targets ?? []);
      setSmartTrackIgnore(cam.ptz_smart_track_ignore ?? []);
      setSmartTrackPriority(cam.ptz_smart_track_priority ?? []);
      setSmartTrackLostSeconds(cam.ptz_smart_track_lost_seconds ?? 3);
      setSmartTrackHomePreset(cam.ptz_smart_track_home_preset ?? "");
      setSmartTrackZoom(cam.ptz_smart_track_zoom ?? false);
      setSmartTrackDeadzone(cam.ptz_smart_track_deadzone ?? 0.15);
      setSmartTrackMaxSpeed(cam.ptz_smart_track_max_speed ?? 0.5);
      setSmartTrackGain(cam.ptz_smart_track_gain ?? 1.5);
      setSmartTrackMinConfidence(cam.ptz_smart_track_min_confidence ?? 0.45);
      setSmartTrackMoveBudget(cam.ptz_smart_track_move_budget_per_minute ?? 30);
      setPtzProfileToken(cam.ptz_profile_token ?? "Profile_1");
    } catch {
      setError("Failed to load camera");
    } finally {
      setLoading(false);
      // Mark autosave as armed only after the hydrate burst settles.
      // setTimeout pushes past the React commit so the next render
      // tick is the first one autosave watches.
      setTimeout(() => {
        firstLoadDone.current = true;
      }, 0);
    }
  }, [cameraId]);

  useEffect(() => {
    // Wait for auth to hydrate the token from localStorage before fetching.
    // On a hard load / direct URL the token loads via effects one tick after
    // mount; firing fetchData first sends an unauthenticated request that
    // 401s and renders a false "Camera not found".
    if (authLoading) return;
    fetchData();
  }, [fetchData, authLoading]);

  // Archive destination (issue #270): retention then moves old footage there
  // instead of deleting it, and the Retention copy says so. Admin-only
  // endpoint; anyone else keeps the plain wording.
  const [archiveName, setArchiveName] = useState<string | null>(null);
  useEffect(() => {
    if (authLoading) return;
    let cancelled = false;
    (async () => {
      try {
        const r = await authFetch("/api/storage/archive");
        if (!r.ok) return;
        const d = await r.json();
        if (!cancelled) setArchiveName(d.active ? d.profile_name : null);
      } catch {/* ignore */}
    })();
    return () => { cancelled = true; };
  }, [authFetch, authLoading]);

  // Fetch class names from the selected detection models. Falls back to
  // yolov8n.pt when the list is empty (matches backend fallback).
  useEffect(() => {
    const models = detectionModels.length > 0
      ? detectionModels.map((m) => m.model).filter(Boolean)
      : ["yolov8n.pt"];
    const params = models.map((m) => `model=${encodeURIComponent(m)}`).join("&");
    let cancelled = false;
    setModelClassesLoading(true);
    (async () => {
      try {
        const res = await authFetch(`/api/detection-models/classes?${params}`);
        if (!res.ok) throw new Error("fetch failed");
        const data = await res.json();
        if (!cancelled) setModelClasses(Array.isArray(data.classes) ? data.classes : []);
      } catch {
        if (!cancelled) setModelClasses([]);
      } finally {
        if (!cancelled) setModelClassesLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [detectionModels, authFetch]);

  // Apply a persona preset by mapping each patch field onto its
  // corresponding setState. Only fields the persona defines are
  // touched. The user still has to click Save to persist.
  function applyPersona(patch: PersonaPatch) {
    if (patch.detect_objects !== undefined) setDetectObjects(patch.detect_objects);
    if (patch.detect_faces !== undefined) setDetectFaces(patch.detect_faces);
    if (patch.scene_mode !== undefined) setSceneMode(patch.scene_mode);
    if (patch.object_confidence !== undefined) setObjectConfidence(patch.object_confidence);
    if (patch.detection_models !== undefined) setDetectionModels(patch.detection_models);
    if (patch.vlm_trigger !== undefined) setVlmTrigger(patch.vlm_trigger);
    if (patch.vlm_trigger_objects !== undefined) setVlmTriggerObjects(patch.vlm_trigger_objects);
    if (patch.vlm_max_tokens !== undefined) setVlmMaxTokens(patch.vlm_max_tokens);
    if (patch.recording_mode !== undefined) setRecordingMode(patch.recording_mode);
    if (patch.recording_trigger_objects !== undefined) setRecordingTriggerObjects(patch.recording_trigger_objects);
    if (patch.recording_clip_pre !== undefined) setRecordingClipPre(patch.recording_clip_pre);
    if (patch.recording_clip_post !== undefined) setRecordingClipPost(patch.recording_clip_post);
    if (patch.retention_mode !== undefined) setRetentionMode(patch.retention_mode);
    if (patch.retention_days !== undefined) setRetentionDays(patch.retention_days);
    if (patch.retention_gb !== undefined) setRetentionGb(patch.retention_gb);
    if (patch.summary_mode !== undefined) setSummaryMode(patch.summary_mode);
    if (patch.summary_period_seconds !== undefined) setSummaryPeriodSeconds(patch.summary_period_seconds);
    if (patch.summary_event_quiet_seconds !== undefined) setSummaryEventQuietSeconds(patch.summary_event_quiet_seconds);
    if (patch.summary_event_trigger_objects !== undefined) setSummaryEventTriggerObjects(patch.summary_event_trigger_objects);
    if (patch.summary_event_min_duration_seconds !== undefined) setSummaryEventMinDurationSeconds(patch.summary_event_min_duration_seconds);
    if (patch.conversation_gap_seconds !== undefined) setConversationGapSeconds(patch.conversation_gap_seconds);
    if (patch.conversation_summary_enabled !== undefined) setConversationSummaryEnabled(patch.conversation_summary_enabled);
    if (patch.yolo_world_prompts !== undefined) setYoloWorldPrompts(patch.yolo_world_prompts);
    if (patch.privacy_zone_targets !== undefined) setPrivacyZoneTargets(patch.privacy_zone_targets);
  }

  // Autosave plumbing. FirstLoadDone flips true after fetchData
  // hydrates the form so the initial setState burst does not trigger
  // a save loop. AutosaveTimer holds the pending debounce so a flurry
  // of slider drags collapses into a single PATCH.
  const firstLoadDone = useRef(false);
  const autosaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  async function handleSave() {
    setSaving(true);
    setError(null);
    setSaved(false);

    try {
      const payload: Record<string, unknown> = {
        name: name.trim(),
        stream_url: streamUrl.trim(),
        stream_type: streamType,
        location_label: locationLabel.trim() || null,
        snapshot_interval: snapshotInterval,
        motion_sensitivity: motionSensitivity,
        recording_enabled: recordingEnabled,
        recording_mode: recordingMode,
        recording_trigger_objects: recordingTriggerObjects.length > 0 ? recordingTriggerObjects : null,
        recording_clip_pre: recordingClipPre,
        recording_clip_post: recordingClipPost,
        vlm_provider_id: vlmProviderId,
        vlm_prompt: vlmPrompt.trim() || null,
        vlm_interval: vlmInterval,
        vlm_max_tokens: vlmMaxTokens,
        vlm_max_input_tokens: vlmMaxInputTokens.trim() ? Number(vlmMaxInputTokens) : null,
        vlm_refiner_provider_id: vlmRefinerProviderId,
        vlm_refiner_trigger_objects: vlmRefinerProviderId && vlmRefinerTriggerObjects.length > 0 ? vlmRefinerTriggerObjects : null,
        vlm_refiner_keywords: vlmRefinerProviderId && vlmRefinerKeywords.length > 0 ? vlmRefinerKeywords : null,
        vlm_refiner_max_tokens: vlmRefinerMaxTokens.trim() ? Number(vlmRefinerMaxTokens) : null,
        vlm_refiner_max_input_tokens: vlmRefinerMaxInputTokens.trim() ? Number(vlmRefinerMaxInputTokens) : null,
        vlm_trigger: vlmTrigger,
        vlm_trigger_objects: vlmTriggerObjects.length > 0 ? vlmTriggerObjects : null,
        detect_objects: detectObjects,
        detect_faces: detectFaces,
        detect_plates: detectPlates,
        detect_classes: detectClasses,
        scene_mode: sceneMode,
        plateless_reid_enabled: platelessReid,
        object_confidence: objectConfidence,
        detection_models: detectionModels.length > 0 ? detectionModels : null,
        detection_merge: detectionMerge,
        detection_consensus_min: detectionConsensusMin,
        digest_enabled: digestEnabled,
        digest_period: digestPeriod,
        digest_provider_id: digestProviderId,
        digest_prompt: digestPrompt.trim() || null,
        retention_mode: retentionMode,
        retention_days: retentionDays,
        retention_gb: retentionGb,
        storage_profile_id: storageProfileId,
        summary_provider_id: summaryProviderId,
        summary_mode: summaryMode,
        summary_period_seconds: summaryPeriodSeconds,
        summary_event_quiet_seconds: summaryEventQuietSeconds,
        summary_event_trigger_objects: summaryEventTriggerObjects.length > 0 ? summaryEventTriggerObjects : null,
        summary_event_min_duration_seconds: summaryEventMinDurationSeconds,
        summary_max_tokens: summaryMaxTokens,
        conversation_gap_seconds: conversationGapSeconds,
        conversation_summary_enabled: conversationSummaryEnabled,
        conversation_min_messages_for_summary: conversationMinMessages,
        incident_tracking_enabled: incidentTrackingEnabled,
        incident_idle_seconds: incidentIdleSeconds,
        privacy_zone_targets: privacyZoneTargets.length > 0 ? privacyZoneTargets : null,
        privacy_zone_blur_strength: privacyZoneBlurStrength,
        yolo_world_prompts: yoloWorldPrompts.length > 0 ? yoloWorldPrompts : null,
        timezone: cameraTimezone.trim() || null,
        motion_zones: motionZones.length > 0 ? motionZones : null,
        ptz_smart_track_enabled: smartTrackEnabled,
        ptz_smart_track_targets: smartTrackTargets.length > 0 ? smartTrackTargets : null,
        ptz_smart_track_ignore: smartTrackIgnore.length > 0 ? smartTrackIgnore : null,
        ptz_smart_track_priority: smartTrackPriority.length > 0 ? smartTrackPriority : null,
        ptz_smart_track_lost_seconds: smartTrackLostSeconds,
        ptz_smart_track_home_preset: smartTrackHomePreset.trim() || null,
        ptz_smart_track_zoom: smartTrackZoom,
        ptz_smart_track_deadzone: smartTrackDeadzone,
        ptz_smart_track_max_speed: smartTrackMaxSpeed,
        ptz_smart_track_gain: smartTrackGain,
        ptz_smart_track_min_confidence: smartTrackMinConfidence,
        ptz_smart_track_move_budget_per_minute: smartTrackMoveBudget,
        ptz_profile_token: ptzProfileToken.trim() || "Profile_1",
      };

      if (username.trim()) payload.username = username.trim();
      if (password) payload.password = password;
      if (authToken.trim()) payload.auth_token = authToken.trim();

      const res = await authFetch(`/api/cameras/${cameraId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(extractApiError(body, `Save failed with status ${res.status}`));
      }

      const updated = await res.json();
      setCamera(updated);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  // Autosave. Watches every editable field and PATCHes the camera
  // 800ms after the last change. Skips the first hydrate burst via
  // the firstLoadDone ref so we never POST an immediate save on
  // mount.
  useEffect(() => {
    if (!firstLoadDone.current) return;
    if (autosaveTimer.current) clearTimeout(autosaveTimer.current);
    autosaveTimer.current = setTimeout(() => {
      handleSave();
    }, 800);
    return () => {
      if (autosaveTimer.current) clearTimeout(autosaveTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    name, streamUrl, streamType, locationLabel, username, password, authToken,
    snapshotInterval, motionSensitivity, recordingEnabled, recordingMode,
    recordingTriggerObjects, recordingClipPre, recordingClipPost,
    vlmProviderId, vlmPrompt, vlmInterval, vlmMaxTokens, vlmMaxInputTokens,
    vlmTrigger, vlmTriggerObjects,
    vlmRefinerProviderId, vlmRefinerTriggerObjects, vlmRefinerKeywords,
    vlmRefinerMaxTokens, vlmRefinerMaxInputTokens,
    detectObjects, detectFaces, detectPlates, detectClasses, sceneMode, platelessReid, objectConfidence,
    detectionModels, detectionMerge, detectionConsensusMin,
    digestEnabled, digestPeriod, digestProviderId, digestPrompt,
    retentionMode, retentionDays, retentionGb,
    summaryProviderId, summaryMode, summaryPeriodSeconds,
    summaryEventQuietSeconds, summaryEventTriggerObjects,
    summaryEventMinDurationSeconds, summaryMaxTokens,
    conversationGapSeconds, conversationSummaryEnabled, conversationMinMessages,
    incidentTrackingEnabled, incidentIdleSeconds,
    privacyZoneTargets, privacyZoneBlurStrength, yoloWorldPrompts, cameraTimezone,
    motionZones,
    smartTrackEnabled, smartTrackTargets, smartTrackIgnore, smartTrackPriority,
    smartTrackLostSeconds, smartTrackHomePreset, smartTrackZoom,
    smartTrackDeadzone, smartTrackMaxSpeed, smartTrackGain,
    smartTrackMinConfidence, smartTrackMoveBudget, ptzProfileToken,
  ]);

  // Fetch ONVIF presets when Smart Track section visible. Used to
  // populate the home preset dropdown so the user doesn't type tokens.
  useEffect(() => {
    if (camera?.stream_type !== "rtsp") return;
    if (!smartTrackEnabled) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await authFetch(`/api/cameras/${cameraId}/ptz/presets`);
        if (!res.ok) return;
        const data = await res.json();
        if (!cancelled && Array.isArray(data)) setSmartTrackPresets(data);
      } catch {
        if (!cancelled) setSmartTrackPresets([]);
      }
    })();
    return () => { cancelled = true; };
  }, [cameraId, camera?.stream_type, smartTrackEnabled, authFetch]);

  async function handleDelete() {
    try {
      const res = await authFetch(`/api/cameras/${cameraId}`, { method: "DELETE" });
      if (res.ok) {
        router.push("/");
      }
    } catch {
      setError("Failed to delete camera");
    }
  }

  if (loading) {
    return (
      <div className="px-6 py-6">
        <div className="text-sm text-muted-foreground">Loading camera config...</div>
      </div>
    );
  }

  if (error && !camera) {
    return (
      <div className="px-6 py-6">
        <div className="text-sm text-danger">{error}</div>
        <Link href="/" className="text-sm text-accent hover:underline mt-2 inline-block">
          Back to cameras
        </Link>
      </div>
    );
  }

  if (!camera) return null;

  const supportsAuth = ["rtsp", "http_mjpeg", "http_snapshot", "hls"].includes(streamType);
  const activeProvider = providers.find((p) => p.active);
  const selectedProvider = vlmProviderId
    ? providers.find((p) => p.id === vlmProviderId)
    : null;

  return (
    <div className="px-6 py-6 max-w-3xl">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <Link
          href="/"
          className="text-muted-foreground hover:text-foreground transition-colors text-sm"
        >
          ← Cameras
        </Link>
        <span className="text-muted-foreground">/</span>
        <h1 className="text-lg font-semibold">{camera.name}</h1>
        <StatusDot status={camera.status} />
        {camera.status === "offline" && camera.stream_type === "file" ? (
          <span
            className="text-xs text-muted-foreground"
            title="The clip plays in your browser below, but Nurby's decoder is not running, so nothing is being detected or recorded right now."
          >
            file · player only
          </span>
        ) : (
          <span className="text-xs text-muted-foreground capitalize">{camera.status}</span>
        )}
        {camera.status === "offline" && (
          <RetryCountdown
            className="text-xs"
            nextRetryAt={camera.next_retry_at}
            reason={camera.status_reason}
          />
        )}
        <Link
          href={`/cameras/${cameraId}/voice`}
          className="ml-auto inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:text-foreground hover:border-foreground/30"
          title="What this camera is allowed to say out loud, and when"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
            <path d="M15.54 8.46a5 5 0 0 1 0 7.07" />
            <path d="M19.07 4.93a10 10 0 0 1 0 14.14" />
          </svg>
          Voice
        </Link>
        <Link
          href={`/cameras/${cameraId}/audio`}
          className="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:text-foreground hover:border-foreground/30"
          title="Audio capture, transcription, and recent transcripts"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
            <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
            <line x1="12" y1="19" x2="12" y2="23" />
            <line x1="8" y1="23" x2="16" y2="23" />
          </svg>
          Audio
        </Link>
        <Link
          href={`/memory?entity_kind=camera&entity_key=${cameraId}&label=${encodeURIComponent(camera.name)}`}
          className="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:text-foreground hover:border-foreground/30"
          title="Household notes about this camera"
        >
          Notes
        </Link>
      </div>

      {/* Live view (#319). The workspace used to show everything about the
          camera except the camera. Collapsible; the choice is remembered
          per camera. Uses the exact feed component the dashboard wall
          uses, so every stream type plays with the same fallbacks. */}
      <div className="mb-6">
        <button
          type="button"
          onClick={() => {
            const next = !liveViewOpen;
            setLiveViewOpen(next);
            try { localStorage.setItem(`nurby-cam-live-${cameraId}`, next ? "1" : "0"); } catch { /* ignore */ }
          }}
          aria-expanded={liveViewOpen}
          className="flex items-center gap-2 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors mb-2"
        >
          <span className={`inline-block transition-transform ${liveViewOpen ? "rotate-90" : ""}`}>▸</span>
          Live view
        </button>
        {liveViewOpen && (
          <div className="relative w-full aspect-video bg-black rounded-lg border border-border overflow-hidden">
            <CameraPlayer camera={camera} objectFit="contain" />
          </div>
        )}
      </div>

      {/* Presence + movement strip: when activity happened and who was there,
          clickable straight into the covering recording. Sits above the HAR
          timeline, which stays empty until action recognition is enabled. */}
      <div className="mb-4">
        <ActivityStrip cameraId={cameraId} cameraName={camera.name} />
      </div>

      {/* Resolution + FPS info bar */}
      {(camera.width || camera.fps) && (
        <div className="flex gap-4 mb-6 text-xs text-muted-foreground font-mono">
          {camera.width && camera.height && (
            <span>{camera.width}x{camera.height}</span>
          )}
          {camera.fps && <span>{camera.fps} fps</span>}
          <span className="uppercase">{STREAM_TYPES[camera.stream_type] || camera.stream_type}</span>
        </div>
      )}

      {/* Tabs */}
      <div className="flex items-center gap-1 mb-5 border-b border-border">
        {([
          { v: "settings", l: "Settings" },
          { v: "activity", l: "Activity" },
        ] as const).map((t) => (
          <button
            key={t.v}
            type="button"
            onClick={() => setActiveTab(t.v)}
            className={`px-3 py-2 text-sm font-medium transition-colors border-b-2 -mb-px ${
              activeTab === t.v
                ? "border-accent text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {t.l}
          </button>
        ))}
      </div>

      {activeTab === "activity" && (
        <CameraActivityTab cameraId={cameraId} cameraName={camera.name} />
      )}

      {activeTab === "settings" && (
      <div className="space-y-5">
        {/* ── Quick personas ── */}
        <Section
          title="Quick setup"
          description="Apply a preset bundle to fill detection, recording, and summary settings in one click. Override anything afterward."
        >
          <PersonaPicker variant="compact" cameraName={name} onApply={(patch) => applyPersona(patch)} />
        </Section>

        {/* ── General ── */}
        <GeneralSection
          locationLabel={locationLabel}
          name={name}
          setLocationLabel={setLocationLabel}
          setName={setName}
        />

        {/* ── Feed ── */}
        <FeedSection
          detectionModels={detectionModels}
          modelClasses={modelClasses}
          modelClassesLoading={modelClassesLoading}
          motionSensitivity={motionSensitivity}
          recordingClipPost={recordingClipPost}
          recordingClipPre={recordingClipPre}
          recordingMode={recordingMode}
          recordingTriggerObjects={recordingTriggerObjects}
          setDetectionModels={setDetectionModels}
          setMotionSensitivity={setMotionSensitivity}
          setRecordingClipPost={setRecordingClipPost}
          setRecordingClipPre={setRecordingClipPre}
          setRecordingEnabled={setRecordingEnabled}
          setRecordingMode={setRecordingMode}
          setRecordingTriggerObjects={setRecordingTriggerObjects}
          setSnapshotInterval={setSnapshotInterval}
          setStreamType={setStreamType}
          setStreamUrl={setStreamUrl}
          snapshotInterval={snapshotInterval}
          streamType={streamType}
          streamUrl={streamUrl}
        />

        {/* ── Authentication ── */}
        {supportsAuth && (
          <AuthSection
            authToken={authToken}
            password={password}
            setAuthToken={setAuthToken}
            setPassword={setPassword}
            setUsername={setUsername}
            username={username}
          />
        )}

        {/* ── VLM / AI Analysis ── */}
        <AiAnalysisSection
          activeProvider={activeProvider}
          detectionModels={detectionModels}
          modelClasses={modelClasses}
          modelClassesLoading={modelClassesLoading}
          providers={providers}
          selectedProvider={selectedProvider}
          setDetectionModels={setDetectionModels}
          setShowDefaultVlmPrompt={setShowDefaultVlmPrompt}
          setVlmInterval={setVlmInterval}
          setVlmMaxInputTokens={setVlmMaxInputTokens}
          setVlmMaxTokens={setVlmMaxTokens}
          setVlmPrompt={setVlmPrompt}
          setVlmProviderId={setVlmProviderId}
          setVlmTrigger={setVlmTrigger}
          setVlmTriggerObjects={setVlmTriggerObjects}
          showDefaultVlmPrompt={showDefaultVlmPrompt}
          vlmInterval={vlmInterval}
          vlmMaxInputTokens={vlmMaxInputTokens}
          vlmMaxTokens={vlmMaxTokens}
          vlmPrompt={vlmPrompt}
          vlmProviderId={vlmProviderId}
          vlmTrigger={vlmTrigger}
          vlmTriggerObjects={vlmTriggerObjects}
        />

        {/* Cascade refiner */}
        <RefinerSection
          detectionModels={detectionModels}
          modelClasses={modelClasses}
          modelClassesLoading={modelClassesLoading}
          providers={providers}
          setDetectionModels={setDetectionModels}
          setVlmRefinerKeywords={setVlmRefinerKeywords}
          setVlmRefinerMaxInputTokens={setVlmRefinerMaxInputTokens}
          setVlmRefinerMaxTokens={setVlmRefinerMaxTokens}
          setVlmRefinerProviderId={setVlmRefinerProviderId}
          setVlmRefinerTriggerObjects={setVlmRefinerTriggerObjects}
          vlmProviderId={vlmProviderId}
          vlmRefinerKeywords={vlmRefinerKeywords}
          vlmRefinerMaxInputTokens={vlmRefinerMaxInputTokens}
          vlmRefinerMaxTokens={vlmRefinerMaxTokens}
          vlmRefinerProviderId={vlmRefinerProviderId}
          vlmRefinerTriggerObjects={vlmRefinerTriggerObjects}
        />

        {/* Detection */}
        <DetectionSection
          detectClasses={detectClasses}
          detectFaces={detectFaces}
          detectObjects={detectObjects}
          detectPlates={detectPlates}
          detectionConsensusMin={detectionConsensusMin}
          detectionMerge={detectionMerge}
          detectionModels={detectionModels}
          modelClasses={modelClasses}
          modelClassesLoading={modelClassesLoading}
          objectConfidence={objectConfidence}
          platelessReid={platelessReid}
          sceneMode={sceneMode}
          setDetectClasses={setDetectClasses}
          setDetectFaces={setDetectFaces}
          setDetectObjects={setDetectObjects}
          setDetectPlates={setDetectPlates}
          setDetectionConsensusMin={setDetectionConsensusMin}
          setDetectionMerge={setDetectionMerge}
          setDetectionModels={setDetectionModels}
          setObjectConfidence={setObjectConfidence}
          setPlatelessReid={setPlatelessReid}
          setSceneMode={setSceneMode}
        />

        {/* ── Activity Digest ── */}
        <RecapsSection
          activeProvider={activeProvider}
          digestEnabled={digestEnabled}
          digestPeriod={digestPeriod}
          digestPrompt={digestPrompt}
          digestProviderId={digestProviderId}
          providers={providers}
          setDigestEnabled={setDigestEnabled}
          setDigestPeriod={setDigestPeriod}
          setDigestPrompt={setDigestPrompt}
          setDigestProviderId={setDigestProviderId}
        />

        {/* ── Summarization ── */}
        <SummarizationSection
          activeProvider={activeProvider}
          detectionModels={detectionModels}
          modelClasses={modelClasses}
          modelClassesLoading={modelClassesLoading}
          providers={providers}
          setDetectionModels={setDetectionModels}
          setSummaryEventMinDurationSeconds={setSummaryEventMinDurationSeconds}
          setSummaryEventQuietSeconds={setSummaryEventQuietSeconds}
          setSummaryEventTriggerObjects={setSummaryEventTriggerObjects}
          setSummaryMaxTokens={setSummaryMaxTokens}
          setSummaryMode={setSummaryMode}
          setSummaryPeriodSeconds={setSummaryPeriodSeconds}
          setSummaryProviderId={setSummaryProviderId}
          summaryEventMinDurationSeconds={summaryEventMinDurationSeconds}
          summaryEventQuietSeconds={summaryEventQuietSeconds}
          summaryEventTriggerObjects={summaryEventTriggerObjects}
          summaryMaxTokens={summaryMaxTokens}
          summaryMode={summaryMode}
          summaryPeriodSeconds={summaryPeriodSeconds}
          summaryProviderId={summaryProviderId}
          vlmProviderId={vlmProviderId}
        />

        {/* ── Audio Conversations ── */}
        {(camera.audio_capture_enabled || camera.audio_transcribe_enabled) && (
          <AudioConversationsSection
            conversationGapSeconds={conversationGapSeconds}
            conversationMinMessages={conversationMinMessages}
            conversationSummaryEnabled={conversationSummaryEnabled}
            setConversationGapSeconds={setConversationGapSeconds}
            setConversationMinMessages={setConversationMinMessages}
            setConversationSummaryEnabled={setConversationSummaryEnabled}
          />
        )}

        {/* ── Incident tracking ── */}
        <IncidentTrackingSection
          incidentIdleSeconds={incidentIdleSeconds}
          incidentTrackingEnabled={incidentTrackingEnabled}
          setIncidentIdleSeconds={setIncidentIdleSeconds}
          setIncidentTrackingEnabled={setIncidentTrackingEnabled}
        />

        {/* ── Smart Track (PTZ auto-follow) ── */}
        {camera?.stream_type === "rtsp" && (
          <SmartTrackSection
            ptzProfileToken={ptzProfileToken}
            setPtzProfileToken={setPtzProfileToken}
            setSmartTrackDeadzone={setSmartTrackDeadzone}
            setSmartTrackEnabled={setSmartTrackEnabled}
            setSmartTrackGain={setSmartTrackGain}
            setSmartTrackHomePreset={setSmartTrackHomePreset}
            setSmartTrackIgnore={setSmartTrackIgnore}
            setSmartTrackLostSeconds={setSmartTrackLostSeconds}
            setSmartTrackMaxSpeed={setSmartTrackMaxSpeed}
            setSmartTrackMinConfidence={setSmartTrackMinConfidence}
            setSmartTrackMoveBudget={setSmartTrackMoveBudget}
            setSmartTrackPriority={setSmartTrackPriority}
            setSmartTrackTargets={setSmartTrackTargets}
            setSmartTrackZoom={setSmartTrackZoom}
            smartTrackDeadzone={smartTrackDeadzone}
            smartTrackEnabled={smartTrackEnabled}
            smartTrackGain={smartTrackGain}
            smartTrackHomePreset={smartTrackHomePreset}
            smartTrackIgnore={smartTrackIgnore}
            smartTrackLostSeconds={smartTrackLostSeconds}
            smartTrackMaxSpeed={smartTrackMaxSpeed}
            smartTrackMinConfidence={smartTrackMinConfidence}
            smartTrackMoveBudget={smartTrackMoveBudget}
            smartTrackPresets={smartTrackPresets}
            smartTrackPriority={smartTrackPriority}
            smartTrackTargets={smartTrackTargets}
            smartTrackZoom={smartTrackZoom}
          />
        )}

        {/* ── YOLO-World prompts ── */}
        {detectionModels.some((m) => m.model.includes("world")) && (
          <YoloWorldPromptsSection setYoloWorldPrompts={setYoloWorldPrompts} yoloWorldPrompts={yoloWorldPrompts} />
        )}

        {/* ── Privacy zones ── */}
        <Section
          title="Blur areas"
          description="AI detects beds, bathrooms, monitors, windows on every keyframe and blurs them before the frame is stored, sent to the VLM, or used for thumbnails."
        >
          <PrivacyZonesSection
            cameraId={cameraId as string}
            targets={privacyZoneTargets}
            setTargets={setPrivacyZoneTargets}
            blurStrength={privacyZoneBlurStrength}
            setBlurStrength={setPrivacyZoneBlurStrength}
          />
        </Section>

        {/* ── Timezone ── */}
        <TimezoneSection cameraTimezone={cameraTimezone} setCameraTimezone={setCameraTimezone} />

        {/* ── Retention ── */}
        <RetentionSection
          retentionDays={retentionDays}
          retentionGb={retentionGb}
          retentionMode={retentionMode}
          setRetentionDays={setRetentionDays}
          setRetentionGb={setRetentionGb}
          setRetentionMode={setRetentionMode}
          archiveName={archiveName}
        />

        {/* ── Recordings location ── */}
        <StorageSection
          storageProfileId={storageProfileId}
          setStorageProfileId={setStorageProfileId}
        />

        {/* ── PTZ Control ── */}
        {streamType === "rtsp" && (
          <Section
            title="PTZ Control"
            description="Pan, tilt, and zoom controls for ONVIF-compatible cameras"
          >
            <PTZControlPanel cameraId={cameraId} />
          </Section>
        )}

        {/* ── Motion Zones ── */}
        <Section
          title="Zones and Tripwires"
          description="Draw areas on the live frame and give them jobs. Named areas let rules target places (person in Driveway) without hiding anything; loiter areas and tripwires power their matching rule types; masks hide pixels from the AI entirely; a veto area pauses all alerts while something is inside it."
        >
          <ZoneEditorCanvas
            zones={motionZones}
            onChange={setMotionZones}
            width={camera.width || 1920}
            height={camera.height || 1080}
            cameraId={cameraId}
          />
        </Section>

        {/* ── Danger Zone ── */}
        <DangerZoneSection deleteConfirm={deleteConfirm} handleDelete={handleDelete} setDeleteConfirm={setDeleteConfirm} />
      </div>
      )}

      {/* Sticky save bar. Only on settings tab. */}
      {activeTab === "settings" && (
      <SaveBar error={error} saved={saved} saving={saving} />
      )}
    </div>
  );
}
