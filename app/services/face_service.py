from pathlib import Path
from uuid import uuid4
import cv2
from app.core.config import settings
from app.core.face_analyzer import face_analyzer
from app.utils.image import validate_image_bytes, quality

class FaceService:
    @staticmethod
    async def extract(data: bytes, require_quality: bool = True):
        image = validate_image_bytes(data, settings.MAX_UPLOAD_MB * 1024 * 1024)
        faces = face_analyzer.get(image)
        if len(faces) == 0:
            raise ValueError("No face detected")
        if len(faces) > 1:
            raise ValueError("Multiple faces detected. Only one face is allowed")
        face = faces[0]
        if float(face.det_score) < settings.DETECTION_CONFIDENCE:
            raise ValueError("Face detection confidence is too low")
        metrics = quality(image, face, settings.MIN_FACE_WIDTH, settings.MIN_FACE_HEIGHT, settings.BLUR_THRESHOLD, settings.MIN_BRIGHTNESS, settings.MAX_BRIGHTNESS) if require_quality else {}
        return image, face, metrics

    @staticmethod
    async def extract_and_store(data: bytes, require_quality=True):
        image, face, metrics = await FaceService.extract(data, require_quality)
        return FaceService.store(image, face, metrics)

    @staticmethod
    def store(image, face, metrics):
        """Write the full image and face crop to UPLOAD_DIR and return the face document fields."""
        root = Path(settings.UPLOAD_DIR); crop_dir = root / "crops"
        root.mkdir(parents=True, exist_ok=True); crop_dir.mkdir(parents=True, exist_ok=True)
        image_name = f"{uuid4()}.jpg"; crop_name = f"{uuid4()}.jpg"
        image_path = root / image_name
        crop_path = crop_dir / crop_name
        cv2.imwrite(str(image_path), image)
        x1,y1,x2,y2 = [int(v) for v in face.bbox]
        pad = 30
        x1=max(0,x1-pad); y1=max(0,y1-pad); x2=min(image.shape[1],x2+pad); y2=min(image.shape[0],y2+pad)
        cv2.imwrite(str(crop_path), image[y1:y2,x1:x2])
        return {
            "embedding": face.embedding.astype(float).tolist(),
            "bbox": face.bbox.astype(int).tolist(),
            "landmarks": face.kps.astype(int).tolist(),
            "confidence": float(face.det_score),
            "image_path": str(image_path).replace("\\", "/"),
            "crop_path": str(crop_path).replace("\\", "/"),
            **metrics,
        }
