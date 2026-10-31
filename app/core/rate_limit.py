from slowapi import Limiter
from slowapi.util import get_remote_address

# Shared limiter: the default applies to every route through SlowAPIMiddleware,
# and auth routes add stricter per-route limits with @limiter.limit(...).
limiter = Limiter(key_func=get_remote_address, default_limits=["300/minute"])
