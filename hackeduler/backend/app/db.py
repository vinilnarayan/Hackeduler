from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings

_s = get_settings()
engine = create_engine(_s.effective_database_url, pool_pre_ping=True, future=True, pool_size=_s.db_pool_size,
                       max_overflow=_s.db_max_overflow, pool_recycle=_s.db_pool_recycle_seconds)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
