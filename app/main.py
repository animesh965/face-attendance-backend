from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from pathlib import Path
from app.core.config import settings
from app.core.database import connect_database, close_database
from app.core.logger import logger
from app.core.rate_limit import limiter
from app.api.auth import router as auth_router
from app.api.dashboard import router as dashboard_router
from app.api.recognize import router as recognize_router
from app.api.register import router as register_router
from app.api.organization import router as organization_router
from app.api.attendance import router as attendance_router
from app.api.cameras import router as cameras_router
from app.api.employees import router as employees_router
from app.api.users import router as users_router
from app.api.health import router as health_router
from app.api.policies import router as policies_router
from app.api.designations import router as designations_router
from app.api.holidays import router as holidays_router
from app.api.uploads import router as uploads_router
from app.api.leave import router as leave_router
from app.api.leave_admin import router as leave_admin_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s", settings.APP_NAME)
    await connect_database()
    yield
    await close_database()

app=FastAPI(title=settings.APP_NAME,version=settings.APP_VERSION,debug=settings.DEBUG,lifespan=lifespan,docs_url="/docs" if settings.ENVIRONMENT!="production" else None,redoc_url=None)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
origins=settings.origins()
app.add_middleware(CORSMiddleware,allow_origins=origins,allow_credentials=True,allow_methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS"],allow_headers=["Authorization","Content-Type"],max_age=600)
Path(settings.UPLOAD_DIR).mkdir(parents=True,exist_ok=True)
app.include_router(health_router); app.include_router(auth_router); app.include_router(dashboard_router); app.include_router(recognize_router); app.include_router(register_router); app.include_router(organization_router); app.include_router(attendance_router); app.include_router(cameras_router); app.include_router(employees_router); app.include_router(users_router); app.include_router(policies_router); app.include_router(designations_router); app.include_router(holidays_router); app.include_router(uploads_router); app.include_router(leave_router); app.include_router(leave_admin_router)
@app.get("/")
async def root(): return {"name":settings.APP_NAME,"version":settings.APP_VERSION,"status":"ok"}
