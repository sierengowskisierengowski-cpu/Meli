"""Database package — SQLAlchemy + SQLite."""
from meli.database.models import Base, get_engine, get_session


def init_db() -> None:
    """Create all tables if they don't exist."""
    engine = get_engine()
    Base.metadata.create_all(engine)


def get_db():
    """Context manager for database sessions."""
    return get_session()
