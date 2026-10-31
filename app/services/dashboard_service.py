from app.core.database import get_database
from app.core.time import local_date


class DashboardService:
    @staticmethod
    async def get_dashboard(user=None):
        db = get_database()
        date = local_date()
        is_employee = bool(user and user.get("role") == "user")
        if is_employee:
            employee_filter = {"user_id": {"$in": [user["_id"], str(user["_id"])]}}
            total = 1
            records = await db.attendance.find({**employee_filter, "date": date}).to_list(length=100)
            events = await db.recognition_events.find({"user_id": {"$in": [user["_id"], str(user["_id"])]}}).sort("created_at", -1).limit(10).to_list(length=10)
        else:
            total = await db.users.count_documents({"is_active": True, "employee_id": {"$exists": True}})
            records = await db.attendance.find({"date": date}).to_list(length=None)
            events = await db.recognition_events.find({}).sort("created_at", -1).limit(10).to_list(length=10)

        present = len(records)
        checked_in = sum(1 for r in records if r.get("current_state") == "IN")
        checked_out = sum(1 for r in records if r.get("current_state") == "OUT" and r.get("sessions"))
        recent = [{
            "id": str(e["_id"]),
            "trackId": 0,
            "name": e.get("name", "Unknown"),
            "camera": e.get("camera_name", "Main Camera"),
            "time": e.get("created_at"),
            "confidence": e.get("similarity", 0),
            "status": "recognized" if e.get("recognized") else "unknown",
        } for e in events]
        return {
            "success": True,
            "date": date,
            "summary": {
                "total_users": total,
                "present_today": present,
                "absent_today": max(0, total - present),
                "checked_in": checked_in,
                "checked_out": checked_out,
            },
            "attendance_trend": [],
            "recognitions_per_hour": [],
            "recent_activity": recent,
            "recent_recognitions": recent,
        }
