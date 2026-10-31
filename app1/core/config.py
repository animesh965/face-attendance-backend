from functools import lru_cache
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    APP_NAME: str = "VertexFace AI Attendance API"
    APP_VERSION: str = "2.0.0"
    ENVIRONMENT: str = "production"
    DEBUG: bool = False
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    MONGODB_URL: str = Field(...)
    DATABASE_NAME: str = Field(...)

    SECRET_KEY: str = Field(..., min_length=32)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    FRONTEND_ORIGINS: str = ""
    TIMEZONE: str = "Asia/Kolkata"

    UPLOAD_DIR: str = "data/uploads"
    MAX_UPLOAD_MB: int = 8
    MIN_FACE_IMAGES: int = 3
    MAX_FACE_IMAGES: int = 5
    FACE_MATCH_THRESHOLD: float = 0.55
    DETECTION_CONFIDENCE: float = 0.70
    MIN_FACE_WIDTH: int = 100
    MIN_FACE_HEIGHT: int = 100
    BLUR_THRESHOLD: float = 40.0
    MIN_BRIGHTNESS: float = 35.0
    MAX_BRIGHTNESS: float = 225.0
    RECOGNITION_COOLDOWN_SECONDS: int = 3
    UNKNOWN_COOLDOWN_SECONDS: int = 5
    ATTENDANCE_TOGGLE_COOLDOWN_SECONDS: int = 30
    STABLE_RECOGNITIONS_REQUIRED: int = 2

    SEED_ADMIN_EMAIL: str = ""
    SEED_ADMIN_PASSWORD: str = ""
    SEED_ADMIN_NAME: str = "System Administrator"

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")

    @field_validator("FRONTEND_ORIGINS")
    @classmethod
    def clean_origins(cls, value: str) -> str:
        return value.strip()

    def origins(self) -> list[str]:
        return [x.strip() for x in self.FRONTEND_ORIGINS.split(",") if x.strip()]

@lru_cache
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
