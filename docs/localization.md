# Web localization

Nurby’s web catalog lives in `frontend/src/lib/i18n.ts`. English is the source
catalog, and every supported locale must contain the same keys and the same
`{named}` interpolation placeholders. `translate()` falls back to English and
then to the key itself, so a missing translation is visible to maintainers
instead of rendering an empty control.

Run the catalog contract and frontend suite with:

```sh
npm test --prefix frontend -- --run src/lib/__tests__/i18n.test.ts
```

To add a language, extend the `Locale` union, add its catalog entries and
`supportedLocales` label, then run the test. Keep labels and accessibility
copy in the catalog when a surface is migrated; do not translate camera IDs,
rule keys, API values, or security decisions.

The first proof currently covers the Settings language selector. The shell,
onboarding, alert/event pages, reports, camera settings, and mobile app still
contain inline English and are intentionally listed as follow-up migration
work rather than being represented as translated today.

The current migrated surfaces also include camera activity/package evidence,
camera voice settings, Settings tuning/digest copy, AI usage reporting, and
the identity review surfaces. The catalog test checks missing keys,
interpolation mismatches, and locale-only extra keys (`locale:key`), so a
contributor pack cannot silently drift from the English source catalog.

Locale is presentation-only. It does not change camera scope, permissions,
retention, rule semantics, timestamps’ source timezone, or model behavior.
