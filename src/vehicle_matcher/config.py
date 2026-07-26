from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MATCHER_", env_file=".env", extra="ignore")

    dsn: str = "postgresql://postgres:postgres@localhost:5433/vehicles"

    # Retrieval
    candidate_k: int = 20
    model_sim_threshold: float = 0.3  # pg_trgm.similarity_threshold for the model arm
    token_sim_threshold: float = 0.4  # pg_trgm.word_similarity_threshold for the token arm

    # Scoring / calibration
    min_match_score: float = 4.0

    # Optional LLM extraction tier
    llm_enabled: bool = False
    llm_model: str = "claude-haiku-4-5-20251001"
    llm_gate: int = 5  # escalate to the LLM only below this confidence
    llm_timeout_s: float = 3.0


def get_settings() -> Settings:
    return Settings()
