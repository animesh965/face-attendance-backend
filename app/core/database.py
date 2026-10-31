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
    await db.liveness_challenges.create_index([("expires_at", ASCENDING)], expireAfterSeconds=0)
    await create_leave_indexes(db)


async def create_leave_indexes(db) -> None:
    current = {"is_current": True}
    await db.employee_types.create_index([("name_key", ASCENDING)], unique=True)
    await db.users.create_index([("employee_type_id", ASCENDING)])
    await db.users.create_index([("reporting_manager_id", ASCENDING)])
    await db.leave_types.create_index([("code", ASCENDING)], unique=True)
    await db.leave_types.create_index([("name_key", ASCENDING)], unique=True)
    await db.leave_policies.create_index([("leave_type_id", ASCENDING), ("employee_type_id", ASCENDING)], unique=True,
                                         partialFilterExpression={"is_active": True}, name="uniq_active_policy")
    # One current mapping per pair; superseded rows are kept with is_current=False as history.
    await db.employee_type_leave_mappings.create_index([("employee_type_id", ASCENDING), ("leave_type_id", ASCENDING)], unique=True,
                                                       partialFilterExpression=current, name="uniq_current_type_mapping")
    await db.employee_leave_mappings.create_index([("employee_id", ASCENDING), ("leave_type_id", ASCENDING)], unique=True,
                                                  partialFilterExpression=current, name="uniq_current_employee_mapping")
    await db.leave_allocations.create_index([("year", ASCENDING), ("leave_type_id", ASCENDING), ("employee_type_id", ASCENDING), ("employee_id", ASCENDING)])
    await db.leave_balances.create_index([("employee_id", ASCENDING), ("leave_type_id", ASCENDING), ("year", ASCENDING)], unique=True)
    await db.leave_transactions.create_index([("idempotency_key", ASCENDING)], unique=True)
    await db.leave_transactions.create_index([("employee_id", ASCENDING), ("year", ASCENDING)])
    await db.leave_requests.create_index([("employee_id", ASCENDING), ("from_date", ASCENDING)])
    await db.leave_requests.create_index([("status", ASCENDING), ("applied_at", DESCENDING)])
    await db.leave_requests.create_index([("year", ASCENDING), ("status", ASCENDING)])
    await db.leave_requests.create_index([("request_no", ASCENDING)], unique=True, sparse=True)
    await db.leave_approvals.create_index([("request_id", ASCENDING), ("created_at", DESCENDING)])
    await db.leave_approvals.create_index([("created_at", DESCENDING)])
    await db.leave_adjustments.create_index([("year", ASCENDING), ("employee_id", ASCENDING)])
    await db.leave_saved_views.create_index([("user_id", ASCENDING), ("name", ASCENDING)], unique=True)
    await db.leave_locks.create_index([("expires_at", ASCENDING)], expireAfterSeconds=0)
    await db.notifications.create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])
    await db.employee_type_history.create_index([("employee_id", ASCENDING), ("changed_at", DESCENDING)])

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
