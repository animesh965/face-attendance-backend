from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from app.core.config import settings

TZ = ZoneInfo(settings.TIMEZONE)

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def now_local() -> datetime:
    return datetime.now(TZ)

def local_date() -> str:
    return now_local().date().isoformat()

def local_datetime(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TZ)
