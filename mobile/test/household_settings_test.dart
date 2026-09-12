import 'package:flutter_test/flutter_test.dart';
import 'package:nurby_mobile/features/settings/household_settings.dart';

void main() {
  test('every curated key is a real system setting the server accepts', () {
    // Mirrors SystemSettingsUpdate. If a key here is not in that schema
    // the generic editor would hide it and the household section would
    // 400 on write, so it would vanish from mobile entirely.
    const accepted = {
      'system_timezone', 'journey_idle_seconds', 'daily_digest_enabled',
      'daily_digest_hour', 'nudity_blur', 'detect_classes', 'audio_events',
      'body_reid_tentative_decay_days', 'cluster_naming_min_sightings',
      'public_base_url', 'rules_cooldown_backend', 'onboarding_dismissed',
      'setup_checklist_dismissed', 'vlm_enrichment_enabled',
      'vlm_enrichment_budget_minutes_per_hour',
      'vehicle_appearance_match_min_similarity', 'guardian_enabled',
    };
    for (final k in kCuratedSettingKeys) {
      expect(accepted, contains(k), reason: k);
    }
  });
}
