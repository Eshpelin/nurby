"""
Face detection and recognition module.

Uses InsightFace (buffalo_l ArcFace) via ONNX runtime for detection and
512-dim embedding generation. No manual install step. The model pack
downloads on first use and is cached locally. Matches detected faces
against known embeddings stored in pgvector.
"""

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import select

from shared.database import async_session
from shared.models import FaceEmbedding, Person

logger = logging.getLogger("nurby.perception.faces")

# L2 distance thresholds for InsightFace normalized 512-dim embeddings.
# Rule of thumb. distance under ~1.1 is the same person (cosine > 0.4).
MATCH_THRESHOLD = 1.1

# Tighter cluster threshold so unknown-person clusters stay coherent.
CLUSTER_THRESHOLD = 1.0

# --- Quality gates -------------------------------------------------------
# A face below this detector confidence or pixel size produces an unreliable
# embedding. We refuse to match OR cluster it. Dropping a sighting is safer
# than inventing a wrong identity or spawning a junk cluster.
MIN_DET_SCORE = 0.50
MIN_FACE_PIXELS = 40
# Opening or extending a cluster is held to a stricter bar: a clean, frontal,
# reasonably large face. Off-angle / blurry / tiny crops are the main reason
# one real person fans out into several "Unknown" clusters.
CLUSTER_MIN_DET_SCORE = 0.65
CLUSTER_MIN_FACE_PIXELS = 60
CLUSTER_MAX_YAW_RATIO = 0.55

# How many recent samples per cluster to compare a new face against. Matching
# the nearest real sample (rather than one drifting centroid) keeps a cluster
# from rejecting the same person seen at a new angle.
MAX_CLUSTER_SAMPLES = 8


def _renorm(vec: np.ndarray) -> np.ndarray:
    """Project a vector back onto the unit sphere. ArcFace embeddings are
    L2-normalized; an average of several is not, and comparing a shrunken mean
    with raw L2 distance silently distorts every threshold."""
    norm = float(np.linalg.norm(vec))
    return vec / norm if norm > 0 else vec


def _yaw_ratio(kps) -> float | None:
    """Frontal-ness proxy from the 5 InsightFace keypoints
    [left_eye, right_eye, nose, left_mouth, right_mouth]. Returns the nose's
    horizontal offset from the eye midpoint as a fraction of inter-ocular
    distance: ~0 is dead frontal, large is profile. None when unusable."""
    try:
        le, re_, nose = kps[0], kps[1], kps[2]
        eye_cx = (float(le[0]) + float(re_[0])) / 2.0
        interocular = abs(float(re_[0]) - float(le[0]))
        if interocular < 1e-3:
            return None
        return abs(float(nose[0]) - eye_cx) / interocular
    except Exception:
        return None


def _viable_for_match(face: dict) -> bool:
    """Minimum bar to even attempt matching a face to a known person."""
    return (
        face.get("detect_score", 0.0) >= MIN_DET_SCORE
        and face.get("face_px", 0) >= MIN_FACE_PIXELS
    )


def _viable_for_cluster(face: dict) -> bool:
    """Stricter bar to open or extend an unknown-person cluster."""
    if face.get("detect_score", 0.0) < CLUSTER_MIN_DET_SCORE:
        return False
    if face.get("face_px", 0) < CLUSTER_MIN_FACE_PIXELS:
        return False
    yaw = face.get("yaw_ratio")
    if yaw is not None and yaw > CLUSTER_MAX_YAW_RATIO:
        return False
    return True


class FaceRecognizer:
    """Lazy-loaded InsightFace detector + ArcFace embedder."""

    def __init__(self):
        self._app = None

    def _load(self):
        if self._app is not None:
            return self._app
        try:
            from insightface.app import FaceAnalysis
        except ImportError:
            logger.warning(
                "insightface not installed. Face recognition disabled. "
                "Install with. pip install insightface onnxruntime"
            )
            return None
        try:
            # buffalo_l. full ArcFace pipeline (detection + recognition).
            # Model pack auto-downloads to ~/.insightface on first use.
            app = FaceAnalysis(
                name="buffalo_l",
                providers=["CPUExecutionProvider"],
                allowed_modules=["detection", "recognition"],
            )
            app.prepare(ctx_id=0, det_size=(640, 640))
            self._app = app
            logger.info("InsightFace 'buffalo_l' loaded (CPU, 640x640 detection)")
        except Exception:
            logger.exception("Failed to load InsightFace model")
            return None
        return self._app

    async def detect_and_embed(self, frame: np.ndarray) -> list[dict]:
        """Detect faces in frame, return list of {bbox, embedding}."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._detect_sync, frame)

    def _detect_sync(self, frame: np.ndarray) -> list[dict]:
        app = self._load()
        if app is None:
            return []
        try:
            # InsightFace expects BGR ndarray, which is what OpenCV gives.
            results = app.get(frame)
        except Exception:
            logger.exception("InsightFace inference failed")
            return []

        faces = []
        for face in results:
            box = getattr(face, "bbox", None)
            emb = getattr(face, "normed_embedding", None)
            if box is None or emb is None:
                continue
            x1, y1, x2, y2 = [int(round(v)) for v in box.tolist()]
            faces.append({
                "bbox": [x1, y1, x2, y2],
                "embedding": emb.tolist(),
                "detect_score": float(getattr(face, "det_score", 0.0) or 0.0),
                # Quality signals used to gate matching and clustering.
                "face_px": int(min(x2 - x1, y2 - y1)),
                "yaw_ratio": _yaw_ratio(getattr(face, "kps", None)),
            })
        logger.debug("InsightFace detected %d face(s)", len(faces))
        return faces

    async def match_faces(self, faces: list[dict]) -> list[dict]:
        """Match detected faces against known embeddings in DB.

        Returns faces with added person_id + display_name if matched.
        """
        if not faces:
            return faces

        # Load all known embeddings
        known = await self._load_known_embeddings()
        if not known:
            return faces

        for face in faces:
            # Garbage crops (tiny / low-confidence) yield embeddings that
            # land anywhere; matching them risks a confident wrong identity.
            if not _viable_for_match(face):
                face["person_id"] = None
                face["person_name"] = None
                face["match_distance"] = None
                continue

            # Use the per-track pooled embedding when the pipeline attached one
            # (stabler than a single noisy frame), else the raw frame embedding.
            face_emb = np.array(face.get("match_embedding") or face["embedding"])
            best_match = None
            best_distance = float("inf")

            for person_id, person_name, known_emb in known:
                distance = np.linalg.norm(face_emb - known_emb)
                if distance < best_distance:
                    best_distance = distance
                    best_match = (person_id, person_name)

            if best_match and best_distance < MATCH_THRESHOLD:
                face["person_id"] = str(best_match[0])
                face["person_name"] = best_match[1]
                face["match_distance"] = round(float(best_distance), 4)
                logger.info(
                    "Matched face to %s (distance=%.4f)",
                    best_match[1], best_distance,
                )
            else:
                face["person_id"] = None
                face["person_name"] = None
                face["match_distance"] = None

        return faces

    async def _load_known_embeddings(self) -> list[tuple]:
        """Load all face embeddings from DB. Returns [(person_id, name, np.array)]."""
        try:
            async with async_session() as db:
                result = await db.execute(
                    select(
                        FaceEmbedding.person_id,
                        Person.display_name,
                        FaceEmbedding.embedding,
                    ).join(Person, FaceEmbedding.person_id == Person.id)
                    .where(Person.consent_given.is_(True))
                )
                rows = result.all()
                return [
                    (row[0], row[1], np.array(row[2]))
                    for row in rows
                ]
        except Exception:
            logger.exception("Failed to load known embeddings")
            return []

    async def cluster_unknown_face(self, face: dict, camera_id: str, frame: np.ndarray | None = None) -> uuid.UUID | None:
        """Cluster an unmatched face. Either adds to existing cluster or creates new one.

        face dict must have 'embedding' and 'bbox' keys.
        Returns the cluster_id the face was assigned to, so callers can persist
        it on the observation for later grouping.
        """
        # Quality gate. Only clean, frontal, reasonably large faces may open or
        # extend a cluster. Low-grade crops are the main reason one real person
        # splits into several "Unknown" clusters, so we drop them here.
        if not _viable_for_cluster(face):
            return None

        # The raw frame embedding is stored as the cluster sample (diverse
        # gallery for nearest-sample matching). The pooled per-track embedding,
        # when present, drives the membership decision (stabler).
        sample_emb = np.array(face["embedding"])
        decide_emb = np.array(face.get("match_embedding") or face["embedding"])

        # Compare against the nearest stored sample of each pending cluster, not
        # a single averaged centroid that drifts as poses accumulate.
        cluster_samples = await self._load_pending_cluster_samples()

        best_cluster_id = None
        best_distance = float("inf")
        for cluster_id, embs in cluster_samples.items():
            distance = min(float(np.linalg.norm(decide_emb - e)) for e in embs)
            if distance < best_distance:
                best_distance = distance
                best_cluster_id = cluster_id

        # Save face crop thumbnail
        thumbnail_path = None
        if frame is not None:
            thumbnail_path = self._save_face_crop(face, frame, camera_id)

        if best_cluster_id and best_distance < CLUSTER_THRESHOLD:
            # Add to existing cluster
            await self._add_to_cluster(best_cluster_id, sample_emb, camera_id, thumbnail_path)
            logger.info("Added face to cluster %s (distance=%.4f)", best_cluster_id, best_distance)
            return best_cluster_id
        else:
            # Create new cluster
            new_id = await self._create_cluster(sample_emb, camera_id, thumbnail_path)
            logger.info("Created new face cluster %s", new_id)
            if new_id:
                # Fire-and-forget VLM appearance description on the initial crop
                asyncio.create_task(self._generate_appearance_description(new_id, thumbnail_path))
            return new_id

    def _save_face_crop(self, face: dict, frame: np.ndarray, camera_id: str) -> str | None:
        """Crop face from frame and save as thumbnail."""
        try:
            import os

            import cv2

            from shared.config import settings

            bbox = face["bbox"]  # [left, top, right, bottom]
            h, w = frame.shape[:2]

            # Add padding around face (20%)
            pad_x = int((bbox[2] - bbox[0]) * 0.2)
            pad_y = int((bbox[3] - bbox[1]) * 0.2)
            x1 = max(0, bbox[0] - pad_x)
            y1 = max(0, bbox[1] - pad_y)
            x2 = min(w, bbox[2] + pad_x)
            y2 = min(h, bbox[3] + pad_y)

            crop = frame[y1:y2, x1:x2]

            face_dir = os.path.join(settings.thumbnails_path, "faces")
            os.makedirs(face_dir, exist_ok=True)

            filename = f"{camera_id}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.jpg"
            path = os.path.join(face_dir, filename)
            cv2.imwrite(path, crop, [cv2.IMWRITE_JPEG_QUALITY, 90])
            return path
        except Exception:
            logger.exception("Failed to save face crop")
            return None

    async def _load_pending_clusters(self) -> list[tuple]:
        """Load pending face clusters. Returns [(cluster_id, np.array)]."""
        try:
            from shared.models import FaceCluster
            async with async_session() as db:
                result = await db.execute(
                    select(FaceCluster.id, FaceCluster.representative_embedding)
                    .where(FaceCluster.status == "pending")
                )
                return [
                    (row[0], np.array(row[1]))
                    for row in result.all()
                ]
        except Exception:
            logger.exception("Failed to load face clusters")
            return []

    async def _load_pending_cluster_samples(
        self, max_per_cluster: int = MAX_CLUSTER_SAMPLES,
    ) -> dict:
        """Return {cluster_id: [np.array, ...]} for pending clusters.

        Each cluster's representative is always included, plus up to
        `max_per_cluster` of its most recent real samples. Matching a new face
        against the nearest of these (not a single drifting mean) is what keeps
        a cluster from rejecting the same person at a new angle.
        """
        try:
            from shared.models import FaceCluster, FaceClusterSample
            async with async_session() as db:
                clusters = (await db.execute(
                    select(FaceCluster.id, FaceCluster.representative_embedding)
                    .where(FaceCluster.status == "pending")
                )).all()
                if not clusters:
                    return {}

                out: dict = {cid: [np.array(rep)] for cid, rep in clusters}

                samples = (await db.execute(
                    select(
                        FaceClusterSample.cluster_id,
                        FaceClusterSample.embedding,
                    )
                    .where(FaceClusterSample.cluster_id.in_(list(out.keys())))
                    .order_by(FaceClusterSample.captured_at.desc())
                )).all()

                counts: dict = {}
                for cid, emb in samples:
                    if counts.get(cid, 0) >= max_per_cluster:
                        continue
                    out[cid].append(np.array(emb))
                    counts[cid] = counts.get(cid, 0) + 1
                return out
        except Exception:
            logger.exception("Failed to load face cluster samples")
            return {}

    # Same-session window. Repeated detections of the same face inside this
    # window count as one visit. Prevents a person standing in frame from
    # inflating sighting_count by one per frame.
    SIGHTING_DEBOUNCE_SECONDS = 300  # 5 min

    async def _add_to_cluster(self, cluster_id: uuid.UUID, embedding: np.ndarray, camera_id: str, thumbnail_path: str | None):
        """Add a face sighting to an existing cluster.

        Debounced. Within SIGHTING_DEBOUNCE_SECONDS of last_seen_at we only
        bump last_seen_at (same visit). Past the window we count a new
        sighting and store a fresh sample.
        """
        try:
            from shared.models import FaceCluster, FaceClusterSample
            async with async_session() as db:
                cluster = await db.get(FaceCluster, cluster_id)
                if not cluster:
                    return

                now = datetime.now(timezone.utc)
                last_seen = cluster.last_seen_at
                if last_seen is not None and last_seen.tzinfo is None:
                    last_seen = last_seen.replace(tzinfo=timezone.utc)
                within_session = (
                    last_seen is not None
                    and (now - last_seen).total_seconds() < self.SIGHTING_DEBOUNCE_SECONDS
                )

                cluster.last_seen_at = now
                if within_session:
                    await db.commit()
                    return

                # New visit. Record sample, bump count, refine representative.
                sample = FaceClusterSample(
                    cluster_id=cluster_id,
                    camera_id=uuid.UUID(camera_id),
                    embedding=embedding.tolist(),
                    thumbnail_path=thumbnail_path,
                )
                db.add(sample)

                cluster.sighting_count += 1
                old_emb = np.array(cluster.representative_embedding)
                n = cluster.sighting_count
                # Running mean of unit vectors, renormalized back to the unit
                # sphere so L2 distance to it stays calibrated as samples grow.
                new_rep = _renorm(((old_emb * (n - 1)) + embedding) / n)
                cluster.representative_embedding = new_rep.tolist()

                if cluster.sighting_count <= 5 and thumbnail_path:
                    cluster.sample_thumbnail_path = thumbnail_path

                await db.commit()
        except Exception:
            logger.exception("Failed to add to cluster %s", cluster_id)

    async def _create_cluster(self, embedding: np.ndarray, camera_id: str, thumbnail_path: str | None) -> uuid.UUID | None:
        """Create a new face cluster from a single face detection."""
        try:
            from sqlalchemy import text

            from shared.models import FaceCluster, FaceClusterSample
            async with async_session() as db:
                # Allocate sequential label number. Sequence guarantees uniqueness
                # across concurrent inserts.
                label_row = await db.execute(text("SELECT nextval('face_cluster_label_seq')"))
                label_num = int(label_row.scalar() or 0)

                cluster = FaceCluster(
                    representative_embedding=embedding.tolist(),
                    sample_thumbnail_path=thumbnail_path,
                    first_camera_id=uuid.UUID(camera_id),
                    sighting_count=1,
                    auto_label_number=label_num,
                    appearance_description_status="pending",
                )
                db.add(cluster)
                await db.flush()

                sample = FaceClusterSample(
                    cluster_id=cluster.id,
                    camera_id=uuid.UUID(camera_id),
                    embedding=embedding.tolist(),
                    thumbnail_path=thumbnail_path,
                )
                db.add(sample)
                await db.commit()
                return cluster.id
        except Exception:
            logger.exception("Failed to create face cluster")
            return None

    async def _generate_appearance_description(self, cluster_id: uuid.UUID, thumbnail_path: str | None):
        """Run a VLM pass on the face crop to produce a short appearance label.

        Examples. "Caucasian male, 30s, blue jacket". Stored on the cluster so
        the UI can show a meaningful hint next to "Unknown 645".
        """
        if not thumbnail_path:
            return
        try:
            import os

            import cv2

            from services.perception.vlm import VLMClient, get_active_provider
            from shared.models import FaceCluster

            if not os.path.exists(thumbnail_path):
                return
            img = cv2.imread(thumbnail_path)
            if img is None:
                return

            provider = await get_active_provider()
            if not provider:
                async with async_session() as db:
                    cluster = await db.get(FaceCluster, cluster_id)
                    if cluster:
                        cluster.appearance_description_status = "failed"
                        await db.commit()
                return

            system_prompt = (
                "You describe the appearance of a person from a single face crop. "
                "Return 8 words or fewer. Cover apparent demographics (ethnicity, "
                "gender, age range) and any obvious clothing or accessories visible. "
                "No speculation beyond what the image shows. No sentences, just a "
                "short label. Example. 'Caucasian male, 30s, dark jacket'."
            )
            client = VLMClient()
            desc = await client.describe(
                frame=img,
                detections=[],
                provider=provider,
                system_prompt=system_prompt,
                max_tokens=40,
            )

            async with async_session() as db:
                cluster = await db.get(FaceCluster, cluster_id)
                if not cluster:
                    return
                if desc:
                    cluster.appearance_description = desc.strip().strip('"').strip(".")
                    cluster.appearance_description_status = "done"
                else:
                    cluster.appearance_description_status = "failed"
                await db.commit()
        except Exception:
            logger.exception("Failed to generate appearance description for cluster %s", cluster_id)

    @staticmethod
    def embed_from_image(image_bytes: bytes) -> list[float] | None:
        """Generate face embedding from image bytes (for upload flow)."""
        try:
            import face_recognition
            import numpy as np

            nparr = np.frombuffer(image_bytes, dtype=np.uint8)
            import cv2
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img is None:
                return None

            rgb = img[:, :, ::-1]
            encodings = face_recognition.face_encodings(rgb)
            if not encodings:
                return None
            return encodings[0].tolist()
        except Exception:
            logger.exception("Failed to generate embedding from image")
            return None


class FaceTrackPooler:
    """Per-camera running mean of face embeddings, keyed by tracker_id.

    A single keyframe's face embedding is noisy: angle, motion blur and
    lighting jitter push it around enough that the same person, frame to
    frame, can land in different clusters. Pooling the embeddings seen for one
    track and matching the pooled (averaged, renormalized) vector gives a far
    stabler identity decision for the life of that track.

    State is in-memory per camera and expires `ttl` seconds after a track was
    last updated, so a reused tracker_id never inherits a stale person. The
    influence of any one track is capped at `max_samples` so a long-standing
    track stays responsive to genuine change (e.g. someone new picking up the
    same tracker_id after an ID swap).
    """

    def __init__(self, ttl: float = 90.0, max_samples: int = 12) -> None:
        self.ttl = ttl
        self.max_samples = max_samples
        # tracker_id -> {"sum": np.ndarray, "n": int, "last": float}
        self._state: dict[int, dict] = {}

    def pool(self, tracker_id, embedding, *, now: float | None = None) -> list[float]:
        """Fold `embedding` into the track's running mean and return the
        current pooled unit embedding as a list."""
        now = time.monotonic() if now is None else now
        self._expire(now)
        tid = int(tracker_id)
        emb = np.asarray(embedding, dtype=float)

        st = self._state.get(tid)
        if st is None:
            st = {"sum": emb.copy(), "n": 1, "last": now}
            self._state[tid] = st
        else:
            # Cap influence: decay the running sum so it never represents more
            # than max_samples frames, keeping recent frames weighted.
            if st["n"] >= self.max_samples:
                scale = (self.max_samples - 1) / self.max_samples
                st["sum"] = st["sum"] * scale
                st["n"] = self.max_samples - 1
            st["sum"] = st["sum"] + emb
            st["n"] += 1
            st["last"] = now

        return _renorm(st["sum"] / st["n"]).tolist()

    def _expire(self, now: float) -> None:
        for tid in list(self._state):
            if now - self._state[tid]["last"] > self.ttl:
                del self._state[tid]

    def reset(self) -> None:
        self._state.clear()
