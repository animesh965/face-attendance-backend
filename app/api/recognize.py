import asyncio
from typing import List
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from app.core.config import settings
from app.core.database import get_database
from app.core.logger import logger
from app.core.time import now_utc
from app.dependencies.permissions import require_permission
from app.services.liveness_service import LivenessError, LivenessService
from app.services.recognizer import Recognizer

router = APIRouter(prefix="/recognize", tags=["Recognition"])


@router.post("/liveness/challenge")
async def liveness_challenge(user=Depends(require_permission("recognition.read"))):
    """Issue a single-use, random head-turn challenge that the next /recognize call must satisfy."""
    return await LivenessService.create_challenge(user)


@router.post("/")
async def recognize(
    image: UploadFile | None = File(None),
    frames: List[UploadFile] | None = File(None),
    challenge_id: str | None = Form(None),
    camera_id: str | None = Form(None),
    camera_name: str = Form("Main Camera"),
    user=Depends(require_permission("recognition.read")),
    db=Depends(get_database),
):
    # Employee recognition is constrained to that employee's own enrolled face.
    own_id = str(user["_id"]) if user.get("role") == "user" else None

    if frames or settings.LIVENESS_REQUIRED:
        if not frames or not challenge_id:
            raise HTTPException(400, "Liveness check required. Request a challenge and send the captured frames.")
        for idx, frame in enumerate(frames, 1):
            if frame.content_type and not frame.content_type.startswith("image/"):
                raise HTTPException(400, f"Frame {idx} is not an image")
        try:
            steps = await LivenessService.consume_challenge(challenge_id, user)
            data = [await f.read() for f in frames]
            # Face analysis is CPU-bound; keep the event loop free while it runs.
            _, face, report = await asyncio.to_thread(LivenessService.verify_frames, data, steps)
        except LivenessError as exc:
            await db.recognition_events.insert_one({
                "user_id": None, "name": "Liveness failed", "recognized": False, "spoof_suspected": True,
                "reason": str(exc), "requested_by": str(user["_id"]),
                "camera_id": camera_id, "camera_name": camera_name, "created_at": now_utc(),
            })
            logger.warning("Liveness failed for user %s: %s", user["_id"], exc)
            raise HTTPException(400, str(exc))
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        result = await Recognizer.recognize_face(face, camera_id, camera_name, allowed_user_id=own_id)
        result["liveness"] = report
        return result

    if image is None:
        raise HTTPException(400, "Image file required")
    if image.content_type and not image.content_type.startswith("image/"):
        raise HTTPException(400, "Image file required")
    data = await image.read()
    try:
        return await Recognizer.recognize(data, camera_id, camera_name, allowed_user_id=own_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
