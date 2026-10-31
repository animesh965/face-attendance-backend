"""Anti-spoofing for face attendance.

A still photo (printed or on a screen) is flat, so however it is tilted or moved in front
of the camera, the nose keeps the same position relative to the eyes and mouth in the
face's own affine frame. A real head turning left/right changes that position. The client
captures a short frame sequence while the person follows a random server-issued turn order,
and this module verifies, on the server:

1. the challenge is valid, unexpired, single-use and belongs to this user;
2. every frame comes from the same camera (same resolution) and shows one face;
3. all frames show the same person;
4. the yaw index follows the challenge order (center -> first turn -> second turn) and
   swings far enough in both directions;
5. the background stays consistent across frames (frames were captured in one session,
   not assembled from separate photos);
6. optionally, a passive anti-spoof model (MiniFASNet ONNX) scores every face as real.
"""
import random
import secrets
from datetime import timedelta

import cv2
import numpy as np

from app.core.config import settings
from app.core.database import get_database
from app.core.time import now_utc
from app.utils.image import validate_image_bytes

TURNS = ("left", "right")


class LivenessError(ValueError):
    """Raised when a frame sequence fails an anti-spoofing check."""


def yaw_index(kps) -> float | None:
    """Nose offset along the eye axis, in the affine frame spanned by the eyes and mouth.

    Positive means the person turned to their own left in an unmirrored camera frame.
    The value is invariant to any affine motion of a flat picture, so photos stay near 0.
    """
    pts = np.asarray(kps, dtype=np.float64)[:5]
    eyes = sorted([pts[0], pts[1]], key=lambda p: p[0])
    left_eye, right_eye = eyes  # image-left, image-right
    nose, mouth_mid = pts[2], (pts[3] + pts[4]) / 2
    eye_mid = (left_eye + right_eye) / 2
    basis = np.column_stack([right_eye - left_eye, mouth_mid - eye_mid])
    if abs(np.linalg.det(basis)) < 1e-6:
        return None
    a, _ = np.linalg.solve(basis, nose - eye_mid)
    return float(-a if settings.LIVENESS_FLIP_YAW else a)


def _matches(step: str, yaw: float) -> bool:
    if step == "center":
        return abs(yaw) <= settings.LIVENESS_CENTER_MAX
    if step == "left":
        return yaw >= settings.LIVENESS_TURN_MIN
    return yaw <= -settings.LIVENESS_TURN_MIN


def _unit(v):
    v = np.asarray(v, dtype=np.float32)
    return v / max(float(np.linalg.norm(v)), 1e-8)


def _background_diff(images, faces) -> float | None:
    """Mean absolute grey-level difference of the region away from the face/body, vs the first frame."""
    h, w = images[0].shape[:2]
    small = (64, 48)
    mask = np.ones((small[1], small[0]), dtype=bool)
    sx, sy = small[0] / w, small[1] / h
    for f in faces:
        x1, y1, x2, y2 = [float(v) for v in f.bbox]
        fw, fh = x2 - x1, y2 - y1
        # Exclude the head generously and everything below it (shoulders/body move with the head).
        bx1, bx2 = max(0, int((x1 - fw) * sx)), min(small[0], int((x2 + fw) * sx) + 1)
        by1 = max(0, int((y1 - 0.6 * fh) * sy))
        mask[by1:, bx1:bx2] = False
    if mask.mean() < 0.15:
        return None  # face fills the frame: not enough background to compare
    grays = [cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), small).astype(np.float32) for img in images]
    return float(max(np.abs(g - grays[0])[mask].mean() for g in grays[1:]))


class PassiveAntiSpoof:
    """Optional MiniFASNetV2 (80x80, scale 2.7) ONNX model; disabled unless ANTISPOOF_MODEL_PATH is set."""

    _session = None

    @classmethod
    def session(cls):
        if not settings.ANTISPOOF_MODEL_PATH:
            return None
        if cls._session is None:
            import onnxruntime as ort
            cls._session = ort.InferenceSession(settings.ANTISPOOF_MODEL_PATH, providers=["CPUExecutionProvider"])
        return cls._session

    @staticmethod
    def _crop(image, bbox, scale=2.7, out=80):
        src_h, src_w = image.shape[:2]
        x1, y1, x2, y2 = [float(v) for v in bbox]
        bw, bh = x2 - x1, y2 - y1
        scale = min((src_h - 1) / bh, (src_w - 1) / bw, scale)
        nw, nh = bw * scale, bh * scale
        cx, cy = x1 + bw / 2, y1 + bh / 2
        left, top = max(0, cx - nw / 2), max(0, cy - nh / 2)
        right, bottom = min(src_w - 1, left + nw), min(src_h - 1, top + nh)
        left, top = max(0, right - nw), max(0, bottom - nh)
        crop = image[int(top):int(bottom) + 1, int(left):int(right) + 1]
        return cv2.resize(crop, (out, out))

    @classmethod
    def real_score(cls, image, bbox) -> float | None:
        sess = cls.session()
        if sess is None:
            return None
        x = cls._crop(image, bbox).astype(np.float32).transpose(2, 0, 1)[None]
        logits = sess.run(None, {sess.get_inputs()[0].name: x})[0][0]
        p = np.exp(logits - logits.max())
        p /= p.sum()
        return float(p[1])  # class 1 = real face


class LivenessService:
    @staticmethod
    async def create_challenge(user) -> dict:
        db = get_database()
        now = now_utc()
        first = random.choice(TURNS)
        turns = [first, "right" if first == "left" else "left"]
        challenge_id = secrets.token_urlsafe(24)
        await db.liveness_challenges.insert_one({
            "_id": challenge_id,
            "user_id": user["_id"],
            "steps": turns,
            "created_at": now,
            "expires_at": now + timedelta(seconds=settings.LIVENESS_CHALLENGE_SECONDS),
            "used_at": None,
        })
        return {
            "challenge_id": challenge_id,
            "steps": ["center", *turns],
            "expires_in": settings.LIVENESS_CHALLENGE_SECONDS,
            "center_max": settings.LIVENESS_CENTER_MAX,
            "turn_min": settings.LIVENESS_TURN_MIN,
            "max_frames": settings.LIVENESS_MAX_FRAMES,
        }

    @staticmethod
    async def consume_challenge(challenge_id: str, user) -> list[str]:
        """Atomically mark the challenge used, so each challenge verifies at most one attempt."""
        db = get_database()
        now = now_utc()
        record = await db.liveness_challenges.find_one_and_update(
            {"_id": challenge_id, "user_id": user["_id"], "used_at": None, "expires_at": {"$gt": now}},
            {"$set": {"used_at": now}},
        )
        if not record:
            raise LivenessError("Liveness challenge is invalid or expired. Please try again.")
        return ["center", *record["steps"]]

    @staticmethod
    def verify_frames(frames: list[bytes], steps: list[str], analyzer=None):
        """Run every check on the frame sequence. Returns (image, face, report) for the most frontal frame."""
        if analyzer is None:
            from app.core.face_analyzer import face_analyzer as analyzer
        if not settings.LIVENESS_MIN_FRAMES <= len(frames) <= settings.LIVENESS_MAX_FRAMES:
            raise LivenessError(
                f"Send between {settings.LIVENESS_MIN_FRAMES} and {settings.LIVENESS_MAX_FRAMES} liveness frames"
            )

        samples = []  # (image, face, yaw)
        shape = None
        for data in frames:
            image = validate_image_bytes(data, settings.MAX_UPLOAD_MB * 1024 * 1024)
            if shape is not None and image.shape != shape:
                raise LivenessError("All liveness frames must come from the same camera")
            shape = image.shape
            faces = analyzer.get(image)
            if len(faces) > 1:
                raise LivenessError("Multiple faces detected. Only one person may be in front of the camera")
            if not faces or float(faces[0].det_score) < 0.5:
                continue  # a turned face can occasionally be missed; the step check below decides
            yaw = yaw_index(faces[0].kps)
            if yaw is not None:
                samples.append((image, faces[0], yaw))

        if len(samples) < len(steps):
            raise LivenessError("Keep your face inside the frame while turning your head")

        # Same person in every frame (blocks swapping in different pictures per step).
        ref_image, ref_face, ref_yaw = min(samples, key=lambda s: abs(s[2]))
        ref = _unit(ref_face.embedding)
        for _, face, _ in samples:
            if float(np.dot(ref, _unit(face.embedding))) < settings.LIVENESS_SAME_PERSON_MIN:
                raise LivenessError("Different faces were detected during the liveness check")

        # Head movement must follow the challenge order.
        yaws = [s[2] for s in samples]
        idx = 0
        for yaw in yaws:
            if idx < len(steps) and _matches(steps[idx], yaw):
                idx += 1
        if idx < len(steps):
            missing = steps[idx]
            hint = "look straight at the camera" if missing == "center" else f"turn your head to your {missing}"
            raise LivenessError(f"Liveness check failed: please {hint} when asked")
        yaw_range = max(yaws) - min(yaws)
        if yaw_range < settings.LIVENESS_MIN_YAW_RANGE:
            raise LivenessError("Liveness check failed: turn your head further to each side")

        # Frames captured in one session share a background.
        bg_diff = _background_diff([s[0] for s in samples], [s[1] for s in samples])
        if bg_diff is not None and bg_diff > settings.LIVENESS_MAX_BACKGROUND_DIFF:
            raise LivenessError("Liveness check failed: frames do not come from one continuous capture")

        passive = None
        if PassiveAntiSpoof.session() is not None:
            scores = [PassiveAntiSpoof.real_score(img, face.bbox) for img, face, _ in samples]
            passive = float(np.mean(scores))
            if passive < settings.ANTISPOOF_REAL_THRESHOLD:
                raise LivenessError("Spoof suspected: a photo or screen was detected")

        report = {
            "passed": True,
            "frames": len(frames),
            "faces": len(samples),
            "yaw_range": round(yaw_range, 3),
            "background_diff": None if bg_diff is None else round(bg_diff, 2),
            "passive_score": None if passive is None else round(passive, 3),
        }
        return ref_image, ref_face, report
