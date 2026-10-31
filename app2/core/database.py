from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING
from app.core.config import settings

class Mongo:
    client: AsyncIOMotorClient | None = None
    db: AsyncIOMotorDatabase | None = None

mongo = Mongo()

async def connect_database() -> None:
    mongo.client = AsyncIOMotorClient(settings.MONGODB_URL, serverSelectionTimeoutMS=5000)
    await mongo.client.admin.command("ping")
    mongo.db = mongo.client[settings.DATABASE_NAME]
    await create_indexes()

async def create_indexes() -> None:
    db = get_database()
    await db.users.create_index([("email", ASCENDING)], unique=True)
    await db.users.create_index([("employee_id", ASCENDING)], unique=True, sparse=True)
    await db.faces.create_index([("user_id", ASCENDING)])
    await db.faces.create_index([("active", ASCENDING)])
    await db.attendance.create_index([("user_id", ASCENDING), ("date", ASCENDING)], unique=True)
    await db.attendance.create_index([("date", DESCENDING)])
    await db.recognition_events.create_index([("created_at", DESCENDING)])
    await db.recognition_events.create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])
    await db.departments.create_index([("code", ASCENDING)], unique=True)
    await db.departments.create_index([("name", ASCENDING)], unique=True)
    await db.designations.create_index([("department_id", ASCENDING), ("name", ASCENDING)], unique=True)
    await db.cameras.create_index([("name", ASCENDING)], unique=True)
    await db.policies.create_index([("name", ASCENDING)], unique=True)
    await db.password_reset_tokens.create_index([("token_hash", ASCENDING)], unique=True)
    await db.password_reset_tokens.create_index([("expires_at", ASCENDING)], expireAfterSeconds=0)
    await db.holidays.create_index([("date", ASCENDING)])
    await db.break_wallets.create_index([("user_id", ASCENDING), ("month", ASCENDING)], unique=True)
    await db.audit_logs.create_index([("created_at", DESCENDING)])

async def close_database() -> None:
    if mongo.client:
        mongo.client.close()
    mongo.client = None
    mongo.db = None

def get_database() -> AsyncIOMotorDatabase:
    if mongo.db is None:
        raise RuntimeError("Database is not initialized")
    return mongo.db

async def ping_database() -> bool:
    try:
        await mongo.client.admin.command("ping")
        return True
    except Exception:
        return False
