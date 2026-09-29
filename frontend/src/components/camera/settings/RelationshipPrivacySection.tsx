import { Section, FieldRow, Toggle } from "./primitives";

interface RelationshipPrivacySectionProps {
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
      <FieldRow
        label="Vehicle evidence"
        hint="Allow person-to-vehicle patterns from this camera. Disable this to keep vehicle sightings while preventing relationship hypotheses."
      >
        <Toggle checked={vehicleInferenceEnabled} onChange={setVehicleInferenceEnabled} label={vehicleInferenceEnabled ? "Enabled" : "Disabled"} />
      </FieldRow>
      <FieldRow
        label="Co-occurrence evidence"
        hint="Allow recurring person/appearance co-occurrence hypotheses from this camera."
      >
        <Toggle checked={cooccurrenceInferenceEnabled} onChange={setCooccurrenceInferenceEnabled} label={cooccurrenceInferenceEnabled ? "Enabled" : "Disabled"} />
      </FieldRow>
      <FieldRow
        label="Spoken-name evidence"
        hint="Allow transcript name mentions to create reviewable identity hypotheses from this camera."
      >
        <Toggle checked={nameMentionInferenceEnabled} onChange={setNameMentionInferenceEnabled} label={nameMentionInferenceEnabled ? "Enabled" : "Disabled"} />
      </FieldRow>
    </Section>
  );
}
