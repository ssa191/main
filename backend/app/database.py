"""Database engine, session factory, and declarative base.

We use SQLAlchemy 2.0 style. A single Base is shared by every model so that
`Base.metadata.create_all()` can build the whole schema in one call.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

# check_same_thread is a SQLite-only flag needed because FastAPI serves
# requests from a threadpool. It is ignored by other databases.
connect_args = (
    {"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {}
)

engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency that yields a request-scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
