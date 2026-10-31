from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from app.core.config import settings
from app.dependencies.permissions import require_permission

router = APIRouter(prefix="/uploads", tags=["Uploads"])


@router.get("/{file_path:path}")
async def get_upload(file_path: str, user=Depends(require_permission("face.manage"))):
    # Face images are biometric data: serve them only to admins, and only from inside UPLOAD_DIR.
    root = Path(settings.UPLOAD_DIR).resolve()
    target = (root / file_path).resolve()
    if root not in target.parents or not target.is_file():
        raise HTTPException(404, "File not found")
    return FileResponse(target, headers={"Cache-Control": "private, no-store"})
