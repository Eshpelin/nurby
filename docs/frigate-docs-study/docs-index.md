# Frigate Docs Index (source for this study)

Pulled from `blakeblackshear/frigate` `docs/docs/` @ `dev`, 2026-07-28.
`https://docs.frigate.video/<path>`. Owner = Nurby subsystem responsible for parity.

## configuration/
| Doc | Nurby owner |
|---|---|
| cameras, camera_specific, restream, go2rtc | ingestion / streaming |
| autotracking | perception/ptz_tracker |
| object_detectors, objects, object_filters, masks, motion_detection, stationary_objects, zones | perception |
| face_recognition, license_plate_recognition, audio_detectors, bird_classification, custom_classification/* | perception |
| semantic_search | search / perception |
| genai/config, genai/objects, genai/review_summaries | agent / vlm / digest |
| review, snapshots, record | events / ingestion |
| notifications | notify / push |
| authentication, tls | api / shared.auth |
| birdseye, live, pwa, profiles | streaming / frontend |
| metrics | api / admin_stats |
| config, config_overrides, advanced/system, advanced/reference, ffmpeg_presets | config layer (mostly N/A — DB-driven) |
| hardware_acceleration_video, hardware_acceleration_enrichments | N/A (CPU) |

## usage/
| Doc | Nurby owner |
|---|---|
| live | streaming / frontend |
| history | events / frontend |
| review | events |
| explore | search |
| exports | events / shares |

## integrations/
| Doc | Nurby owner |
|---|---|
| api | api |
| mqtt | MISSING |
| home-assistant | MISSING |
| homekit | N/A (go2rtc) |
| plus | N/A (Frigate+ marketplace) |
| third_party_extensions | N/A |

## frigate/ (concepts + install)
glossary, video_pipeline, hardware, installation, network_requirements, planning_setup,
camera_setup, updating, index — mostly conceptual/deploy; `video_pipeline` + `glossary` are the
useful mental-model refs.
