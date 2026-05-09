from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings


load_dotenv()


class Settings(BaseSettings):
    groq_api_key: str = ""
    groq_api_keys: str = ""
    groq_model: str = "llama-3.1-70b-versatile"
    groq_models: str = "llama-3.1-8b-instant,llama-3.3-70b-versatile,openai/gpt-oss-20b,openai/gpt-oss-120b,qwen/qwen3-32b"
    gemini_api_key: str = ""
    gemini_api_keys: str = ""
    gemini_models: str = "gemini-2.5-flash,gemini-2.0-flash,gemini-2.5-flash-lite-preview-09-2025"
    llm_provider_order: str = "groq,gemini"
    llm_max_attempts: int = 8
    app_secret_key: str = "change-me-for-production"
    persistent_dir: str = ""
    database_path: str = ""
    evidence_dir: str = ""
    catalog_path: str = "shl_product_catalog.json"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    enable_sentence_transformer: bool = False

    @property
    def root_dir(self) -> Path:
        return Path(__file__).resolve().parent.parent

    def resolve(self, value: str) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        return self.root_dir / path

    @property
    def storage_root(self) -> Path:
        if self.persistent_dir:
            return self.resolve(self.persistent_dir)
        hf_data = Path("/data")
        if hf_data.exists():
            return hf_data / "shl-recommender"
        return self.root_dir / "storage"

    @property
    def resolved_database_path(self) -> Path:
        if self.database_path:
            return self.resolve(self.database_path)
        return self.storage_root / "shl_recommender.sqlite3"

    @property
    def resolved_evidence_dir(self) -> Path:
        if self.evidence_dir:
            return self.resolve(self.evidence_dir)
        return self.storage_root / "evidence"

    @staticmethod
    def csv(value: str) -> list[str]:
        return [part.strip() for part in value.split(",") if part.strip()]

    @property
    def groq_key_list(self) -> list[str]:
        return self.csv(",".join([self.groq_api_key, self.groq_api_keys]))

    @property
    def groq_model_list(self) -> list[str]:
        models = self.csv(self.groq_models)
        if self.groq_model and self.groq_model not in models:
            models.insert(0, self.groq_model)
        return models

    @property
    def gemini_key_list(self) -> list[str]:
        return self.csv(",".join([self.gemini_api_key, self.gemini_api_keys]))

    @property
    def gemini_model_list(self) -> list[str]:
        return self.csv(self.gemini_models)

    @property
    def provider_order_list(self) -> list[str]:
        providers = self.csv(self.llm_provider_order)
        return providers or ["groq", "gemini"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
