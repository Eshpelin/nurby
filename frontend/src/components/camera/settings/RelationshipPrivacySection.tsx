import { Section, FieldRow, Toggle } from "./primitives";

interface RelationshipPrivacySectionProps {
  inferenceEnabled: boolean;
  notificationsEnabled: boolean;
  setInferenceEnabled: (value: boolean) => void;
  setNotificationsEnabled: (value: boolean) => void;
}

export function RelationshipPrivacySection({
  inferenceEnabled,
  notificationsEnabled,
  setInferenceEnabled,
  setNotificationsEnabled,
}: RelationshipPrivacySectionProps) {
  return (
    <Section
      title="Identity and relationship privacy"
      description="Control whether this camera may contribute to inferred identity or relationship suggestions. Source detector settings remain separate."
    >
      <FieldRow
        label="Allow relationship inference"
        hint="When disabled, this camera can still record and detect normally, but its evidence will not create person, vehicle, co-occurrence, or spoken-name hypotheses."
      >
        <Toggle checked={inferenceEnabled} onChange={setInferenceEnabled} label={inferenceEnabled ? "Enabled" : "Disabled"} />
      </FieldRow>
      <FieldRow
        label="Notify about relationship patterns"
        hint="When disabled, recurring unknown-subject notifications from this camera are suppressed. Existing review history is preserved."
      >
        <Toggle checked={notificationsEnabled} onChange={setNotificationsEnabled} label={notificationsEnabled ? "Enabled" : "Disabled"} />
      </FieldRow>
    </Section>
  );
}
