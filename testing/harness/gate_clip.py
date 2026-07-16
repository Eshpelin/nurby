#!/usr/bin/env python3
"""Quality gate for UX-army feed clips.

Usage: gate_clip.py <video> <required-classes>
  required-classes: comma-separated COCO names, any one of which counts
  (e.g. "person" or "dog,cat"). Pass "none" to skip content checking.

Samples frames spread across the clip and passes the clip only if a
required class is detected in at least 20% of them. Keeps bulk-fetched
footage honest: a "parking" variant must actually contain cars.
Exit 0 = pass, 1 = fail, 2 = unreadable.
"""
import sys

import cv2
from ultralytics import YOLO

SAMPLES = 10
CONF = 0.30
MIN_HIT_RATIO = 0.20

path, required = sys.argv[1], sys.argv[2]
if required == "none":
    sys.exit(0)
wanted = set(required.split(","))

cap = cv2.VideoCapture(path)
total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
if total < SAMPLES:
    print(f"unreadable or too short: {path}")
    sys.exit(2)

model = YOLO("yolov8n.pt")
names = model.names
hits = 0
for i in range(SAMPLES):
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(total * (i + 0.5) / SAMPLES))
    ok, frame = cap.read()
    if not ok:
        continue
    res = model.predict(frame, conf=CONF, verbose=False)[0]
    if any(names[int(b.cls)] in wanted for b in res.boxes):
        hits += 1
cap.release()

ratio = hits / SAMPLES
print(f"{path}: {wanted} in {hits}/{SAMPLES} sampled frames")
sys.exit(0 if ratio >= MIN_HIT_RATIO else 1)
