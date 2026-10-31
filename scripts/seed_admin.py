import asyncio
from datetime import datetime, timezone
from app.core.database import connect_database, close_database, get_database
from app.core.config import settings
from app.core.security import hash_password
from app.core.permissions import permissions_for_role

async def main():
    if not settings.SEED_ADMIN_EMAIL or not settings.SEED_ADMIN_PASSWORD:
        raise SystemExit("Set SEED_ADMIN_EMAIL and SEED_ADMIN_PASSWORD")
    await connect_database(); db=get_database(); now=datetime.now(timezone.utc)
    await db.users.update_one({"email":settings.SEED_ADMIN_EMAIL.lower()},{"$setOnInsert":{"name":settings.SEED_ADMIN_NAME,"email":settings.SEED_ADMIN_EMAIL.lower(),"password_hash":hash_password(settings.SEED_ADMIN_PASSWORD),"role":"admin","permissions":permissions_for_role("admin"),"is_active":True,"face_registered":False,"created_at":now,"updated_at":now}},upsert=True)
    await db.policies.update_one({"name":"Standard"},{"$setOnInsert":{"name":"Standard","start_time":"09:45","required_work_minutes":585,"daily_break_minutes":45,"carry_forward":True,"monthly_expiry":True,"created_at":now}},upsert=True)
    print("Admin seed complete")
    await close_database()

asyncio.run(main())
