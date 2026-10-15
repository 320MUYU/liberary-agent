from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

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
    DEEPSEEK_API_KEY: SecretStr | None = None
    DEEPSEEK_MODEL: str = "deepseek-chat"
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_TIMEOUT_SECONDS: float = 60.0
    RAG_ENABLED: bool = False
    EMBEDDING_PROVIDER: Literal["dashscope", "openai-compatible"] = "dashscope"
    EMBEDDING_BASE_URL: str = ""
    EMBEDDING_API_KEY: SecretStr | None = None
    EMBEDDING_BATCH_SIZE: int = Field(default=32, ge=1, le=128)
    DASHSCOPE_API_KEY: SecretStr | None = None
    # Copy the native synchronous endpoint from the console for your workspace/region.
    DASHSCOPE_EMBEDDING_URL: str = ""
    EMBEDDING_MODEL: str = "text-embedding-v4"
    EMBEDDING_DIMENSIONS: int = Field(default=1024, gt=0, le=65536,
        validation_alias=AliasChoices("EMBEDDING_DIMENSIONS", "EMBEDDING_DIMENSION"))
    EMBEDDING_TIMEOUT_SECONDS: float = Field(default=15.0, gt=0, le=60)
    EMBEDDING_MAX_RETRIES: int = Field(default=2, ge=0, le=5)
    CHROMA_HOST: str = "127.0.0.1"
    CHROMA_PORT: int = Field(default=8001, ge=1, le=65535)
    CHROMA_TIMEOUT_SECONDS: float = Field(default=10.0, gt=0, le=60)
    KNOWLEDGE_DIR: Path = BASE_DIR / "data" / "knowledge"
    KNOWLEDGE_MAX_BYTES: int = Field(default=10 * 1024 * 1024, gt=0)
    KNOWLEDGE_MAX_CHARS: int = Field(default=500_000, gt=0)
    KNOWLEDGE_MAX_PAGES: int = Field(default=200, gt=0)
    RAG_CHUNK_SIZE: int = Field(default=800, ge=100, le=2000)
    RAG_CHUNK_OVERLAP: int = Field(default=100, ge=0)
    RAG_CANDIDATES: int = Field(default=8, ge=1, le=100)
    RAG_TOP_K: int = Field(default=4, ge=1, le=10)
    RAG_MAX_DISTANCE: float = Field(default=0.6, ge=0, le=2)
    RAG_CONTEXT_CHARS: int = Field(default=6000, ge=800, le=12000)
    RAG_HISTORY_CHARS: int = Field(default=6000, ge=1000, le=12000)
    RAG_QUERY_CHARS: int = Field(default=1000, ge=100, le=2000)
    RAG_REQUEST_TIMEOUT_SECONDS: float = Field(default=60.0, gt=0, le=180)
    KNOWLEDGE_JOB_MAX_ATTEMPTS: int = Field(default=3, ge=1, le=10)
    KNOWLEDGE_JOB_LEASE_SECONDS: int = Field(default=600, ge=30)

    @model_validator(mode="after")
    def validate_rag(self):
        if self.EMBEDDING_PROVIDER == "dashscope" and self.EMBEDDING_DIMENSIONS not in {64, 128, 256, 512, 768, 1024, 1536, 2048}:
            raise ValueError("不支持的 text-embedding-v4 维度")
        if self.EMBEDDING_MODEL.lower() == "baai/bge-m3" and self.EMBEDDING_DIMENSIONS != 1024:
            raise ValueError("BGE-M3 必须使用 1024 维向量")
        if self.RAG_CHUNK_OVERLAP >= self.RAG_CHUNK_SIZE:
            raise ValueError("切片重叠必须小于切片长度")
        if self.RAG_TOP_K > self.RAG_CANDIDATES:
            raise ValueError("最终切片数不能超过候选数")
        return self

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
