from pydantic_settings import BaseSettings,SettingsConfigDict
from pathlib import Path

# APP_DIR 指向 backend/app（代码所在），BASE_DIR 指向 backend/（项目根）。
# 配置与运行时产物（.env、uploads/）都放在 backend/ 根，不跟着代码走，
# 这样它们既不会混进 app 包里，也和 .gitignore 的忽略规则对得上。
APP_DIR = Path(__file__).resolve().parent
BASE_DIR = APP_DIR.parent

class Settings(BaseSettings):
    DATABASE_URL: str
    JWT_SECRET_KEY: str
    JWT_EXPIRE_HOURS: int
    JWT_ALGORITHM: str


    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
    )


settings = Settings()

UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100M

ALLOWED_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".zip",
}
