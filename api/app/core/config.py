from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration comes from environment variables or api/.env. Nothing here is sent to the frontend."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "AEROCAST NCR API"
    app_version: str = "0.1.0"
    environment: Literal["development", "production", "test"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # PostgreSQL/PostGIS: local or on another machine (see docs/postgis-integration.md).
    database_url: SecretStr = SecretStr("postgresql+psycopg://aerocast:change-me@localhost:5432/aerocast")
    database_connect_timeout_s: int = 2

    # Ollama runs on a separate machine.
    ollama_base_url: str = "http://localhost:11434"
    # Initial model. If the hardware struggles, set OLLAMA_MODEL to a smaller tool-capable model (e.g. qwen3:4b).
    ollama_model: str = "qwen3:8b-q4_K_M"
    ollama_embed_model: str = "nomic-embed-text"
    ollama_timeout_s: float = 3.0  # status probes only

    # Assistant generation. Only one chat model is ever used, and it is kept loaded between questions.
    llm_temperature: float = 0.2
    llm_top_p: float = 0.9
    llm_num_ctx: int = 8192
    llm_max_tokens: int = 800  # hard cap on generated tokens per model call
    llm_think: bool = False  # Qwen3 "thinking" is slower; leave off unless answer quality needs it
    llm_keep_alive: str = "10m"
    llm_connect_timeout_s: float = 5.0
    llm_timeout_s: float = 180.0  # longest silent wait for the model (covers first-load time)
    llm_max_tool_rounds: int = 3
    llm_max_tool_calls: int = 4
    llm_max_history_messages: int = 12
    llm_max_message_chars: int = 2000
    llm_tool_result_chars: int = 4000

    # Knowledge base (documents -> chunks -> embeddings -> Chroma). Files and the index live under kb_dir.
    kb_dir: str = "./data/kb"
    kb_max_upload_mb: int = 10
    kb_max_pdf_pages: int = 400
    kb_max_text_chars: int = 2_000_000
    kb_extract_timeout_s: float = 60.0
    kb_chunk_chars: int = 1000
    kb_chunk_overlap: int = 150
    kb_max_chunks_per_doc: int = 3000
    kb_csv_max_rows: int = 20_000
    kb_csv_max_columns: int = 100
    # Time zone assumed for CSV timestamps that carry no offset. Stored as UTC; the assumption is shown in every profile and query.
    kb_dataset_timezone: str = "Asia/Kolkata"
    # A passage found by exact words (not by meaning) is admitted if its similarity is within this of kb_min_score.
    kb_lexical_relax: float = 0.20
    kb_embed_batch: int = 16
    kb_top_k_default: int = 4
    kb_top_k_max: int = 10
    # Minimum cosine similarity for a passage to count as relevant. Measured with nomic-embed-text on a small
    # all-air-quality corpus: questions the documents answer scored 0.68-0.80, off-topic questions up to 0.58.
    # Near-misses (on topic, but the passage does not answer) still score 0.65-0.72, which no threshold can
    # separate, so the assistant is also told to cite only passages that actually answer. Re-tune on the real corpus.
    kb_min_score: float = 0.62
    # When the user names a document, the search is already narrowed to it, so the threshold is lowered by this much.
    # (LLM-written keyword queries often score ~0.6 against a passage that contains the exact answer.)
    kb_named_document_relax: float = 0.10

    # Embeddings are behind an interface; Ollama is the only provider implemented so far.
    embedding_provider: Literal["ollama"] = "ollama"
    embedding_doc_prefix: str = "search_document: "  # nomic-embed-text expects task prefixes
    embedding_query_prefix: str = "search_query: "
    embedding_timeout_s: float = 60.0

    # Optional external ML forecasting service (see docs/ml-forecast-interface.md). AEROCAST contains no forecasting
    # model: with no URL set, pollution forecasts are simply unavailable.
    ml_forecast_url: str = ""
    ml_forecast_api_key: SecretStr = SecretStr("")
    ml_forecast_timeout_s: float = 30.0
    # Optional LOCAL model (trained offline by `python -m app.ml train`; see docs/ml-model-comparison.md). Used only when no external
    # ML_FORECAST_URL is set. Empty = off.
    ml_local_model_dir: str = ""
    ml_history_db: str = ""  # default: DATA_DIR/history.sqlite
    ml_max_station_km: float = 15.0
    ml_max_input_age_hours: int = 6  # newest observation allowed to be this old at the request time; otherwise "unavailable"

    # Local application data (alert rules). Knowledge-base files use kb_dir.
    data_dir: str = "./data"

    # Weather: Open-Meteo (free, non-commercial tier; no key). Commercial use requires their subscription.
    open_meteo_base_url: str = "https://api.open-meteo.com/v1/forecast"
    # Historical (reanalysis-based) archive used only by the offline data pipeline (app.history), never by live pages.
    open_meteo_archive_url: str = "https://archive-api.open-meteo.com/v1/archive"
    open_meteo_air_quality_url: str = "https://air-quality-api.open-meteo.com/v1/air-quality"
    # Multi-coordinate batch chunk size: Open-Meteo recommends up to 100 coordinates per request to avoid HTTP 414 URL limits.
    open_meteo_batch_chunk_size: int = 100
    open_meteo_api_key: SecretStr = SecretStr("")
    weather_timeout_s: float = 10.0
    weather_max_attempts: int = 3
    weather_retry_backoff_s: float = 0.5
    weather_cache_ttl_s: int = 900
    # Data whose newest source timestamp is older than this is flagged stale.
    weather_stale_after_s: int = 10800

    # Air quality: OpenAQ v3 (documented API; requires a free key, sent as the X-API-Key header).
    aq_api_base_url: str = "https://api.openaq.org/v3"
    aq_api_key: SecretStr = SecretStr("")
    aq_timeout_s: float = 15.0
    aq_max_attempts: int = 3
    aq_retry_backoff_s: float = 1.0
    aq_cache_ttl_s: int = 900
    # Free tier allows 60 requests/minute; stay below it.
    aq_rate_per_minute: int = 50
    # Only reference-grade (regulatory) monitors by default; set false to include other sensors.
    aq_reference_only: bool = True
    # Comma-separated OpenAQ provider IDs to restrict to (e.g. a government provider). Empty = all.
    aq_provider_ids: str = ""
    # A station whose newest reading is older than this is flagged stale.
    aq_stale_after_s: int = 10800
    # Stations with no data newer than this many days are treated as inactive and left out.
    aq_active_days: int = 7
    aq_max_stations: int = 80

    # Optional TypeSafe "Jev" decision-support service (docs/jev-integration.md). OFF by default; "shadow" records its decisions next to
    # the deterministic ones without influencing any answer. The key is read from the environment only.
    india_aqi_api_key: SecretStr = SecretStr("")  # XKDR India air-quality archive (CPCB history); training data only
    jev_mode: str = "off"  # off (kill switch) | shadow
    jev_backend: str = "laya"  # laya (local, open-source package) | typesafe (remote HTTP API)
    laya_model: str = "convaiinnovations/laya"
    jev_base_url: str = "https://api.typesafe.ai"
    typesafe_api_key: SecretStr = SecretStr("")
    jev_model: str = ""  # empty = use the first name returned by GET /v1/models; never guessed
    jev_timeout_s: float = 8.0
    jev_max_attempts: int = 2
    jev_send_excerpts: bool = False  # default: only questions and passage titles/scores leave the machine, never document text

    # Comma-separated list of allowed browser origins.
    cors_origins: str = "http://localhost:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
