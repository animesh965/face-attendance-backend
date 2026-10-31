from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from pathlib import Path
from app.core.config import settings
from app.core.database import connect_database, close_database
from app.core.logger import logger
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

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s", settings.APP_NAME)
    await connect_database()
    yield
    await close_database()

limiter = Limiter(key_func=get_remote_address, default_limits=["300/minute"])

app=FastAPI(title=settings.APP_NAME,version=settings.APP_VERSION,debug=settings.DEBUG,lifespan=lifespan,docs_url="/docs" if settings.ENVIRONMENT!="production" else None,redoc_url=None)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
origins=settings.origins()
app.add_middleware(CORSMiddleware,allow_origins=origins,allow_credentials=True,allow_methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS"],allow_headers=["Authorization","Content-Type"],max_age=600)
Path(settings.UPLOAD_DIR).mkdir(parents=True,exist_ok=True)
app.mount("/uploads",StaticFiles(directory=settings.UPLOAD_DIR),name="uploads")
app.include_router(health_router); app.include_router(auth_router); app.include_router(dashboard_router); app.include_router(recognize_router); app.include_router(register_router); app.include_router(organization_router); app.include_router(attendance_router); app.include_router(cameras_router); app.include_router(employees_router); app.include_router(users_router); app.include_router(policies_router)
@app.get("/")
async def root(): return {"name":settings.APP_NAME,"version":settings.APP_VERSION,"status":"ok"}
