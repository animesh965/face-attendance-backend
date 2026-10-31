from datetime import timedelta
from app.core.database import get_database
from app.core.time import local_date, now_utc

class DashboardService:
    @staticmethod
    async def get_dashboard():
        db=get_database(); date=local_date()
        total=await db.users.count_documents({"is_active":True})
        records=await db.attendance.find({"date":date}).to_list(length=None)
        present=len(records); checked_in=sum(1 for r in records if r.get("current_state")=="IN"); checked_out=sum(1 for r in records if r.get("current_state")=="OUT" and r.get("sessions"));
        events=await db.recognition_events.find({}).sort("created_at",-1).limit(10).to_list(length=10)
        recent=[]
        for e in events:
            recent.append({"id":str(e["_id"]),"trackId":0,"name":e.get("name","Unknown"),"camera":e.get("camera_name","Main Camera"),"time":e.get("created_at"),"confidence":e.get("similarity",0),"status":"recognized" if e.get("recognized") else "unknown"})
        return {"success":True,"date":date,"summary":{"total_users":total,"present_today":present,"absent_today":max(0,total-present),"checked_in":checked_in,"checked_out":checked_out},"attendance_trend":[],"recognitions_per_hour":[],"recent_activity":recent,"recent_recognitions":recent}
