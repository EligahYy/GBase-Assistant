"""应用配置，通过环境变量和 .env 文件加载。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).parent.parent  # backend/


class Settings(BaseSettings):
    # 数据库
    database_url: str = f"sqlite+aiosqlite:///{BASE_DIR}/data/app.db"

    # LLM API Keys
    deepseek_api_key: str = ""
    dashscope_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""

    # 默认模型
    default_model: str = "deepseek/deepseek-chat"

    # 向量数据库
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""

    # 应用
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    debug: bool = False
    secret_key: str = ""  # GBase 连接密码 AES-GCM 加密密钥
    use_v3_arch: bool = False  # Enable v3 ReAct Agent architecture

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors(cls, v: str | list) -> list[str]:
        if isinstance(v, str):
            import json

            return json.loads(v)
        return v

    @property
    def models_config(self) -> dict:
        """从 config/models.yaml 加载模型配置"""
        config_path = BASE_DIR / "config" / "models.yaml"
        if config_path.exists():
            with open(config_path, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}

    @property
    def knowledge_dir(self) -> Path:
        """知识库目录（项目根下的 knowledge/）"""
        return BASE_DIR.parent / "knowledge"


@lru_cache
def get_settings() -> Settings:
    return Settings()
