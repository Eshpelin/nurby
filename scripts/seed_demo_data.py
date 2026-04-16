"""Seed the database with realistic demo data for UI testing.

Usage:
    python -m scripts.seed_demo_data          # add all demo data
    python -m scripts.seed_demo_data --clean   # wipe existing data first, then seed

Creates:
    - 5 cameras (front door, backyard, garage, kitchen, driveway)
    - 4 named persons with sighting history
    - 2 unknown face clusters (pending suggestions)
    - ~200 observations spread across the last 48 hours
    - Camera status logs
    - A sample digest entry
    - 2 rules with recent events
"""

import asyncio
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, text

from shared.database import async_session
from shared.models import (
    Camera,
    CameraStatusLog,
    DigestEntry,
    Event,
    FaceCluster,
    FaceClusterSample,
    Observation,
    Person,
    Rule,
)

UTC = timezone.utc
NOW = datetime.now(UTC)

# ── Camera definitions ──

CAMERAS = [
    {
        "name": "Front Door",
        "stream_url": "rtsp://192.168.1.100:554/stream1",
        "stream_type": "rtsp",
        "location_label": "Main entrance",
        "status": "live",
        "width": 1920,
        "height": 1080,
        "fps": 15.0,
        "recording_mode": "on_motion",
        "digest_enabled": True,
        "digest_period": "24h",
    },
    {
        "name": "Backyard",
        "stream_url": "rtsp://192.168.1.101:554/stream1",
        "stream_type": "rtsp",
        "location_label": "Garden area",
        "status": "live",
        "width": 2560,
        "height": 1440,
        "fps": 20.0,
        "recording_mode": "always",
        "digest_enabled": True,
        "digest_period": "12h",
    },
    {
        "name": "Garage",
        "stream_url": "rtsp://192.168.1.102:554/stream1",
        "stream_type": "rtsp",
        "location_label": "Garage interior",
        "status": "live",
        "width": 1920,
        "height": 1080,
        "fps": 10.0,
        "recording_mode": "on_object",
        "recording_trigger_objects": ["person", "car"],
        "digest_enabled": True,
        "digest_period": "24h",
    },
    {
        "name": "Kitchen",
        "stream_url": "rtsp://192.168.1.103:554/stream1",
        "stream_type": "rtsp",
        "location_label": "Indoor kitchen",
        "status": "offline",
        "width": 1280,
        "height": 720,
        "fps": 15.0,
        "recording_mode": "on_motion",
        "digest_enabled": False,
    },
    {
        "name": "Driveway",
        "stream_url": "rtsp://192.168.1.104:554/stream1",
        "stream_type": "rtsp",
        "location_label": "Front driveway",
        "status": "live",
        "width": 1920,
        "height": 1080,
        "fps": 15.0,
        "recording_mode": "clip",
        "recording_clip_pre": 5,
        "recording_clip_post": 15,
        "digest_enabled": True,
        "digest_period": "6h",
    },
]

# ── Person definitions ──

PERSONS = [
    {"display_name": "Sarah Chen", "relationship": "Family", "consent_given": True},
    {"display_name": "Mike Rodriguez", "relationship": "Neighbor", "consent_given": True},
    {"display_name": "Emma Wilson", "relationship": "Family", "consent_given": True},
    {"display_name": "James Park", "relationship": "Delivery", "consent_given": False},
]

# ── VLM descriptions pool ──

DESCRIPTIONS_BY_CAMERA = {
    "Front Door": [
        "A person is walking up to the front door carrying a small package. They appear to be a delivery driver wearing a blue uniform.",
        "Two people are standing at the front door having a conversation. One is holding car keys.",
        "A person is unlocking the front door with a key. A backpack is visible on their shoulder.",
        "The front porch is empty. A small package has been left near the doormat.",
        "A person is leaving through the front door, locking it behind them. Morning sunlight visible.",
        "A cat is sitting on the front porch railing. No people visible in frame.",
        "Someone is ringing the doorbell. They are holding a clipboard and wearing a vest.",
        "A person is sweeping the front porch. Garden tools are visible to the left.",
        "Two children are playing near the front steps. An adult is watching from the doorway.",
        "A person is checking the mailbox near the front door. Letters visible in hand.",
    ],
    "Backyard": [
        "A person is watering plants in the garden. The sprinkler system is also running in the background.",
        "A dog is running across the backyard lawn. No people currently visible.",
        "Two people are sitting at the patio table having a meal. Evening lighting detected.",
        "A person is mowing the lawn with a push mower. Moving from left to right across frame.",
        "The backyard is empty. Wind is causing movement in the tree branches.",
        "A bird has landed on the bird feeder. Squirrel also visible near the fence.",
        "A person is grilling on the barbecue. Smoke visible rising from the grill.",
        "Children are playing on the swing set. An adult is pushing one child on the swing.",
        "A person is reading a book on the patio lounge chair. Glass of water on the side table.",
        "A raccoon has been detected near the trash bins at the back of the yard.",
    ],
    "Garage": [
        "A car is pulling into the garage. The garage door is fully open.",
        "A person is organizing tools on the workbench. Several boxes are stacked nearby.",
        "The garage is empty. Both parking spots are vacant. Door is closed.",
        "A person is loading items into the trunk of a sedan. Moving boxes visible.",
        "A bicycle has fallen over near the wall. No people in frame.",
        "Two people are working on a car engine. Hood is propped open. Tools scattered.",
        "A person is entering the garage from the house door carrying laundry.",
        "A car is backing out of the garage. Brake lights illuminated.",
    ],
    "Kitchen": [
        "A person is cooking at the stove. Steam rising from a pot.",
        "Two people are sitting at the kitchen counter eating breakfast. Coffee mugs visible.",
        "The kitchen is empty. Overhead lights are on. Dishes visible in the sink.",
        "A person is unloading groceries from bags onto the counter.",
        "A child is reaching into the refrigerator. Kitchen light is on.",
        "A person is washing dishes at the sink. Radio appears to be on.",
    ],
    "Driveway": [
        "A delivery van is parked in the driveway. Driver is walking to the front with a package.",
        "A car is pulling into the driveway. Headlights are on, suggesting evening arrival.",
        "Two cars are parked in the driveway. No movement detected.",
        "A person is washing a car in the driveway with a hose. Soapy water visible.",
        "A person is walking down the driveway towards the street. They are jogging.",
        "A FedEx truck has stopped at the end of the driveway. Driver is scanning a package.",
        "Kids are riding bicycles in the driveway. Chalk drawings visible on the pavement.",
        "A person is shoveling the driveway. Light snow visible on the ground.",
    ],
}

# ── Object detection templates ──

OBJECT_POOLS = {
    "Front Door": [
        [{"label": "person", "confidence": 0.92, "bbox": [100, 50, 300, 400]}],
        [
            {"label": "person", "confidence": 0.88, "bbox": [80, 60, 280, 380]},
            {"label": "person", "confidence": 0.76, "bbox": [320, 80, 480, 390]},
        ],
        [{"label": "cat", "confidence": 0.71, "bbox": [200, 300, 280, 380]}],
        [{"label": "backpack", "confidence": 0.65, "bbox": [150, 200, 220, 320]}],
        [],
    ],
    "Backyard": [
        [{"label": "person", "confidence": 0.89, "bbox": [50, 100, 250, 450]}],
        [{"label": "dog", "confidence": 0.94, "bbox": [300, 250, 450, 400]}],
        [
            {"label": "person", "confidence": 0.85, "bbox": [100, 80, 300, 430]},
            {"label": "person", "confidence": 0.81, "bbox": [400, 100, 560, 440]},
        ],
        [{"label": "bird", "confidence": 0.67, "bbox": [500, 50, 560, 100]}],
        [],
    ],
    "Garage": [
        [
            {"label": "car", "confidence": 0.96, "bbox": [50, 100, 600, 400]},
            {"label": "license_plate", "confidence": 0.88, "bbox": [200, 340, 380, 390], "plate_text": "7ABC 123"},
        ],
        [{"label": "person", "confidence": 0.87, "bbox": [200, 80, 350, 400]}],
        [
            {"label": "person", "confidence": 0.83, "bbox": [100, 80, 260, 400]},
            {"label": "car", "confidence": 0.91, "bbox": [300, 120, 620, 380]},
            {"label": "license_plate", "confidence": 0.82, "bbox": [400, 330, 540, 370], "plate_text": "CA 8X2 B49"},
        ],
        [{"label": "bicycle", "confidence": 0.78, "bbox": [450, 200, 550, 380]}],
        [],
    ],
    "Kitchen": [
        [{"label": "person", "confidence": 0.90, "bbox": [150, 60, 350, 420]}],
        [
            {"label": "person", "confidence": 0.86, "bbox": [80, 70, 240, 400]},
            {"label": "person", "confidence": 0.79, "bbox": [300, 80, 460, 410]},
        ],
        [{"label": "cup", "confidence": 0.62, "bbox": [400, 200, 440, 260]}],
        [],
    ],
    "Driveway": [
        [
            {"label": "car", "confidence": 0.95, "bbox": [100, 150, 550, 400]},
            {"label": "license_plate", "confidence": 0.91, "bbox": [250, 350, 400, 390], "plate_text": "KZN 4521"},
            {"label": "person", "confidence": 0.84, "bbox": [580, 100, 700, 420]},
        ],
        [
            {"label": "car", "confidence": 0.93, "bbox": [80, 140, 520, 390]},
            {"label": "license_plate", "confidence": 0.85, "bbox": [200, 340, 370, 380], "plate_text": "7ABC 123"},
        ],
        [{"label": "person", "confidence": 0.88, "bbox": [300, 80, 460, 430]}],
        [
            {"label": "truck", "confidence": 0.91, "bbox": [50, 100, 640, 420]},
            {"label": "license_plate", "confidence": 0.79, "bbox": [250, 370, 430, 410], "plate_text": "FDX 90182"},
        ],
        [{"label": "bicycle", "confidence": 0.82, "bbox": [200, 200, 350, 400]}],
        [],
    ],
}


def rand_time(hours_ago_max: float = 48.0, hours_ago_min: float = 0.0) -> datetime:
    """Random timestamp between hours_ago_min and hours_ago_max before now."""
    delta = random.uniform(hours_ago_min, hours_ago_max)
    return NOW - timedelta(hours=delta)


def make_person_detections(person_id: str | None, person_name: str | None) -> dict | None:
    """Build a person_detections JSON blob."""
    if person_id is None:
        # Random chance of unknown face
        if random.random() < 0.3:
            return {
                "faces": [
                    {
                        "bbox": [random.randint(50, 200), random.randint(30, 100), random.randint(250, 400), random.randint(200, 350)],
                        "person_id": None,
                        "person_name": None,
                        "match_distance": None,
                    }
                ],
                "count": 1,
            }
        return None
    return {
        "faces": [
            {
                "bbox": [random.randint(50, 200), random.randint(30, 100), random.randint(250, 400), random.randint(200, 350)],
                "person_id": person_id,
                "person_name": person_name,
                "match_distance": round(random.uniform(0.15, 0.45), 3),
            }
        ],
        "count": 1,
    }


async def seed():
    """Populate database with demo data."""
    clean = "--clean" in sys.argv

    async with async_session() as db:
        if clean:
            print("Cleaning existing data.")
            for table in [
                Event, DigestEntry, Observation, CameraStatusLog,
                FaceClusterSample, FaceCluster, Person, Rule, Camera,
            ]:
                await db.execute(delete(table))
            await db.commit()
            print("Done cleaning.")

        # ── 1. Cameras ──
        print("Creating cameras.")
        camera_ids: dict[str, uuid.UUID] = {}
        for cam_def in CAMERAS:
            cam = Camera(**cam_def)
            db.add(cam)
            await db.flush()
            camera_ids[cam_def["name"]] = cam.id
        await db.commit()
        print(f"  Created {len(camera_ids)} cameras.")

        # ── 2. Persons ──
        print("Creating persons.")
        person_ids: dict[str, uuid.UUID] = {}
        for p_def in PERSONS:
            p = Person(**p_def)
            db.add(p)
            await db.flush()
            person_ids[p_def["display_name"]] = p.id
        await db.commit()
        print(f"  Created {len(person_ids)} persons.")

        # ── 3. Face clusters (unknown people suggestions) ──
        print("Creating face cluster suggestions.")
        fake_embedding_128 = [random.uniform(-0.1, 0.1) for _ in range(128)]
        clusters_created = 0
        for i, (cam_name, cam_id) in enumerate(list(camera_ids.items())[:2]):
            cluster = FaceCluster(
                representative_embedding=fake_embedding_128,
                sighting_count=random.randint(3, 12),
                first_seen_at=rand_time(72, 24),
                last_seen_at=rand_time(6, 0),
                first_camera_id=cam_id,
                status="pending",
            )
            db.add(cluster)
            await db.flush()
            clusters_created += 1

            # Add sample entries
            for _ in range(3):
                sample = FaceClusterSample(
                    cluster_id=cluster.id,
                    camera_id=cam_id,
                    embedding=fake_embedding_128,
                    captured_at=rand_time(48, 0),
                )
                db.add(sample)

        await db.commit()
        print(f"  Created {clusters_created} unknown face clusters.")

        # ── 4. Observations ──
        print("Creating observations.")
        person_list = list(person_ids.items())
        obs_count = 0

        for cam_name, cam_id in camera_ids.items():
            descs = DESCRIPTIONS_BY_CAMERA.get(cam_name, [])
            objects = OBJECT_POOLS.get(cam_name, [[]])

            # Generate 30-50 observations per camera
            num_obs = random.randint(30, 50)
            for _ in range(num_obs):
                started = rand_time(48, 0)
                ended = started + timedelta(seconds=random.randint(2, 30))

                # Pick random objects
                obj_set = random.choice(objects)
                obj_det = {"objects": obj_set, "count": len(obj_set)} if obj_set else None

                # Sometimes attach a known person
                person_det = None
                has_person_obj = any(o["label"] == "person" for o in obj_set)
                if has_person_obj and random.random() < 0.5:
                    pname, pid = random.choice(person_list)
                    person_det = make_person_detections(str(pid), pname)
                elif has_person_obj:
                    person_det = make_person_detections(None, None)

                obs = Observation(
                    camera_id=cam_id,
                    started_at=started,
                    ended_at=ended,
                    object_detections=obj_det,
                    person_detections=person_det,
                    vlm_description=random.choice(descs) if descs and random.random() < 0.8 else None,
                    vlm_provider="demo-vlm",
                    confidence=round(random.uniform(0.5, 0.99), 2),
                )
                db.add(obs)
                obs_count += 1

        await db.commit()
        print(f"  Created {obs_count} observations.")

        # ── 5. Camera status logs ──
        print("Creating status logs.")
        log_count = 0
        for cam_name, cam_id in camera_ids.items():
            statuses = ["offline", "live", "live", "live", "recording"]
            for i in range(random.randint(3, 8)):
                t = rand_time(48, 0)
                prev_status = random.choice(statuses)
                new_status = random.choice([s for s in statuses if s != prev_status])
                log = CameraStatusLog(
                    camera_id=cam_id,
                    status=new_status,
                    previous_status=prev_status,
                    reason="Stream reconnected" if new_status == "live" else "Connection timeout",
                    timestamp=t,
                )
                db.add(log)
                log_count += 1
        await db.commit()
        print(f"  Created {log_count} status logs.")

        # ── 6. Rules + Events ──
        print("Creating rules and events.")
        rule1 = Rule(
            name="Person at front door",
            enabled=True,
            trigger_pattern={"type": "object_detected", "labels": ["person"]},
            conditions={"camera_ids": [str(camera_ids["Front Door"])]},
            actions={"type": "notification", "message": "Person detected at front door"},
            cooldown_seconds=120,
        )
        rule2 = Rule(
            name="Car in driveway",
            enabled=True,
            trigger_pattern={"type": "object_detected", "labels": ["car", "truck"]},
            conditions={"camera_ids": [str(camera_ids["Driveway"])]},
            actions={"type": "webhook", "url": "https://example.com/hook"},
            cooldown_seconds=300,
        )
        db.add(rule1)
        db.add(rule2)
        await db.flush()

        event_count = 0
        for rule in [rule1, rule2]:
            for _ in range(random.randint(5, 15)):
                ev = Event(
                    rule_id=rule.id,
                    fired_at=rand_time(48, 0),
                    payload={"rule_name": rule.name, "trigger": "demo"},
                )
                db.add(ev)
                event_count += 1
        await db.commit()
        print(f"  Created 2 rules and {event_count} events.")

        # ── 7. Digest entry ──
        print("Creating digest entries.")
        for cam_name in ["Front Door", "Backyard", "Driveway"]:
            cam_id = camera_ids[cam_name]
            digest = DigestEntry(
                camera_id=cam_id,
                period="24h",
                summary=f"Over the last 24 hours, the {cam_name.lower()} camera captured moderate activity. "
                f"Multiple person detections were logged during daytime hours, with peak activity "
                f"between 8 AM and 6 PM. A few vehicle movements were also recorded. "
                f"No unusual patterns or security concerns were identified.",
                highlights=[
                    f"12 person detections at {cam_name.lower()}",
                    "Peak activity between 8 AM and 6 PM",
                    "3 vehicle movements recorded",
                    "No security alerts triggered",
                ],
                stats={
                    "total_observations": random.randint(25, 45),
                    "person_detections": random.randint(8, 20),
                    "vehicle_detections": random.randint(2, 8),
                    "avg_confidence": round(random.uniform(0.7, 0.9), 2),
                },
                total_observations=random.randint(25, 45),
                generated_at=NOW - timedelta(hours=1),
            )
            db.add(digest)
        await db.commit()
        print("  Created 3 digest entries.")

        print("\nSeed complete. Demo data ready.")
        print(f"  Cameras   {len(camera_ids)}")
        print(f"  Persons   {len(person_ids)}")
        print(f"  Clusters  {clusters_created}")
        print(f"  Events    {obs_count} observations, {event_count} rule events")


if __name__ == "__main__":
    asyncio.run(seed())
