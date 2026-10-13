from functools import lru_cache

from sqlalchemy import Engine, create_engine

from app.core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    """Engines are lazy: no connection is made until first use, so the API starts even if Postgres is down."""
    s = get_settings()
    return create_engine(
        s.database_url.get_secret_value(),
        pool_pre_ping=True,
        connect_args={"connect_timeout": s.database_connect_timeout_s},
    )
