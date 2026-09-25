# Settings layers: household or Advanced

One decision per field, applied on both clients (docs/ia-rollout.md, phase 4).
The test is not "is this important" but "does a household member change
this, or does someone tuning the pipeline". Anything with a unit of tokens,
seconds, or a threshold is Advanced unless it has a household meaning.

## Camera page

| Section | Household layer | Advanced |
|---|---|---|
| Quick setup | personas | |
| Detection | object, face, plate toggles; classes to detect; models | merge strategy, consensus threshold |
| AI analysis | what to look for (prompt); AI model; when to look; trigger objects | minimum gap, description length, input budget |
| Second look | second-look model | keywords, trigger objects, lengths, budgets |
| Open vocabulary | things to watch for | |
| Camera recaps | write recaps; recap model; write periodic recaps; recap period; recap prompt | quiet before writing, ignore events shorter than, trigger objects, recap length |
| Voice | speak through this camera; policy; voice; test | volume, cooldown, daily cap |
| Audio | capture; transcribe; store raw; spoken language | transcript storage mode, retention days, transcription budget, decoding quality, carry context, silence threshold |
| Conversations | summarize conversations | gap, minimum lines |
| Incident tracking | group repeat sightings | close after |
| Blur areas | targets, per-area on/off/lock | blur strength |
| Recording | recording on/off; keep recordings (mode, days, size) | |
| Zones | all | |
| Misc | | timezone, exclude from review |

## Household settings

| Household layer | Advanced |
|---|---|
| privacy blur; objects to detect; morning recap on/off and hour; household timezone; listen for sounds | describe scenes while idle and its budget; end a journey after; the raw system-settings editor (every key) |

## Voice (household)

| Household layer | Advanced |
|---|---|
| let cameras speak; hold a conversation; quiet hours; what a camera may confirm; never say | maximum volume; end a conversation after (turns, seconds) |

## Save conventions

Household settings use immediate save with a brief inline `Saved` confirmation;
there is no hidden Save button. Advanced tuning follows the same immediate-save
convention because sliders and toggles are applied as soon as they change. The
Advanced fold is an information-architecture boundary, not a separate draft
or staging area.
