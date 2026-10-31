from bson import ObjectId
from app.core.config import settings
from app.core.database import get_database
from app.core.time import now_utc
from app.services.face_service import FaceService
from app.services.attendance_service import AttendanceService

class Recognizer:
    @staticmethod
    async def recognize(
        data: bytes,
        camera_id: str | None = None,
        camera_name: str = "Main Camera",
        allowed_user_id: str | None = None,
    ):
        _, face_obj, _ = await FaceService.extract(data, require_quality=False)
        return await Recognizer.recognize_face(face_obj, camera_id, camera_name, allowed_user_id)

    @staticmethod
    async def recognize_face(
        face_obj,
        camera_id: str | None = None,
        camera_name: str = "Main Camera",
        allowed_user_id: str | None = None,
    ):
        """Match an already-detected face (e.g. the frontal frame of a passed liveness check)."""
        db = get_database(); now = now_utc()
        embedding = face_obj.embedding.astype(float).tolist()
        # Current implementation uses MongoDB cosine search. Replace only this search layer with FAISS later.
        face_query = {"active": True}
        if allowed_user_id:
            face_query["user_id"] = ObjectId(allowed_user_id)
        docs = await db.faces.find(face_query, {"embedding": 1, "user_id": 1}).to_list(length=None)
        best = None; best_score = -1.0
        import numpy as np
        q = np.asarray(embedding, dtype=np.float32); qn = np.linalg.norm(q)
        for doc in docs:
            v = np.asarray(doc.get("embedding", []), dtype=np.float32)
            if v.size != q.size: continue
            vn = np.linalg.norm(v)
            if qn == 0 or vn == 0: continue
            score = float(np.dot(q, v) / (qn * vn))
            if score > best_score:
                best_score, best = score, doc
        if best is None or best_score < settings.FACE_MATCH_THRESHOLD:
            event = {"user_id": None, "name": "Unknown Face", "recognized": False, "similarity": round(max(best_score,0),4), "camera_id": camera_id, "camera_name": camera_name, "created_at": now}
            result = await db.recognition_events.insert_one(event)
            return {"success": True, "recognized": False, "similarity": round(max(best_score,0),4), "message": "Unknown person.", "recognition_event_id": str(result.inserted_id), "detections": [{"trackId": 0, "name":"Unknown", "confidence": round(max(best_score,0),4), "status":"unknown", "box": {"x":int(face_obj.bbox[0]),"y":int(face_obj.bbox[1]),"w":int(face_obj.bbox[2]-face_obj.bbox[0]),"h":int(face_obj.bbox[3]-face_obj.bbox[1])}}]}
        user = await db.users.find_one({"_id": ObjectId(str(best["user_id"]))})
        if not user or not user.get("is_active", True):
            return {"success": True, "recognized": False, "message": "Matched identity is inactive"}
        attendance = await AttendanceService.process_attendance(str(user["_id"]), user, best_score)
        event = {"user_id": str(user["_id"]), "name": user.get("name"), "recognized": True, "similarity": round(best_score,4), "camera_id": camera_id, "camera_name": camera_name, "created_at": now, "attendance_action": attendance.get("action")}
        result = await db.recognition_events.insert_one(event)
        return {"success": True, "recognized": True, "similarity": round(best_score,4), "user": {"id":str(user["_id"]),"name":user.get("name"),"email":user.get("email"),"employee_id":user.get("employee_id")}, "recognition_event_id": str(result.inserted_id), "attendance": attendance, "detections": [{"trackId": 0, "name":user.get("name","Unknown"), "confidence":round(best_score,4), "status":"recognized", "box": {"x":int(face_obj.bbox[0]),"y":int(face_obj.bbox[1]),"w":int(face_obj.bbox[2]-face_obj.bbox[0]),"h":int(face_obj.bbox[3]-face_obj.bbox[1])}}]}
