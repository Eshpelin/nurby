import { Section, FieldRow, Toggle } from "./primitives";
import { translate, type Locale } from "@/lib/i18n";

interface RelationshipPrivacySectionProps {
  locale: Locale;
  inferenceEnabled: boolean;
  notificationsEnabled: boolean;
  setInferenceEnabled: (value: boolean) => void;
  setNotificationsEnabled: (value: boolean) => void;
  vehicleInferenceEnabled: boolean;
  cooccurrenceInferenceEnabled: boolean;
  nameMentionInferenceEnabled: boolean;
  setVehicleInferenceEnabled: (value: boolean) => void;
  setCooccurrenceInferenceEnabled: (value: boolean) => void;
  setNameMentionInferenceEnabled: (value: boolean) => void;
}

export function RelationshipPrivacySection({
  locale,
  inferenceEnabled,
  notificationsEnabled,
  setInferenceEnabled,
  setNotificationsEnabled,
  vehicleInferenceEnabled,
  cooccurrenceInferenceEnabled,
  nameMentionInferenceEnabled,
  setVehicleInferenceEnabled,
  setCooccurrenceInferenceEnabled,
  setNameMentionInferenceEnabled,
}: RelationshipPrivacySectionProps) {
  const t = (key: string) => translate(locale, key);
  return (
    <Section
      title={t("camera.relationship_privacy.title")}
      description={t("camera.relationship_privacy.description")}
    >
      <FieldRow
        label={t("camera.relationship_privacy.inference_label")}
        hint={t("camera.relationship_privacy.inference_hint")}
      >
        <Toggle checked={inferenceEnabled} onChange={setInferenceEnabled} label={inferenceEnabled ? t("common.enabled") : t("common.disabled")} />
      </FieldRow>
      <FieldRow
        label={t("camera.relationship_privacy.notifications_label")}
        hint={t("camera.relationship_privacy.notifications_hint")}
      >
        <Toggle checked={notificationsEnabled} onChange={setNotificationsEnabled} label={notificationsEnabled ? t("common.enabled") : t("common.disabled")} />
      </FieldRow>
      <FieldRow
        label={t("camera.relationship_privacy.vehicle_label")}
        hint={t("camera.relationship_privacy.vehicle_hint")}
      >
        <Toggle checked={vehicleInferenceEnabled} onChange={setVehicleInferenceEnabled} label={vehicleInferenceEnabled ? t("common.enabled") : t("common.disabled")} />
      </FieldRow>
      <FieldRow
        label={t("camera.relationship_privacy.cooccurrence_label")}
        hint={t("camera.relationship_privacy.cooccurrence_hint")}
      >
        <Toggle checked={cooccurrenceInferenceEnabled} onChange={setCooccurrenceInferenceEnabled} label={cooccurrenceInferenceEnabled ? t("common.enabled") : t("common.disabled")} />
      </FieldRow>
      <FieldRow
        label={t("camera.relationship_privacy.name_label")}
        hint={t("camera.relationship_privacy.name_hint")}
      >
        <Toggle checked={nameMentionInferenceEnabled} onChange={setNameMentionInferenceEnabled} label={nameMentionInferenceEnabled ? t("common.enabled") : t("common.disabled")} />
      </FieldRow>
    </Section>
  );
}
