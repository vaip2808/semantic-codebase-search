import os
from datetime import datetime, UTC
from sqlalchemy import (
    create_engine,
    ForeignKey,
    Integer,
    String,
    Text,
    DateTime,
    event,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker, Mapped, mapped_column
from dotenv import load_dotenv
from pgvector.sqlalchemy import Vector

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL:
    DATABASE_URL = DATABASE_URL.strip()

IS_POSTGRES = bool(DATABASE_URL and (DATABASE_URL.startswith("postgresql://") or DATABASE_URL.startswith("postgres://")))

def _get_engine():
    global _engine_instance, IS_POSTGRES
    if _engine_instance is not None:
        return _engine_instance
        
    if IS_POSTGRES:
        try:
            temp_engine = create_engine(
                DATABASE_URL,
                connect_args={"connect_timeout": 5},
                pool_pre_ping=True,
                pool_recycle=300,
            )
            # Test connection lazily on first access
            with temp_engine.connect() as conn:
                pass
            _engine_instance = temp_engine
            return _engine_instance
        except Exception as e:
            print(f"[WARNING] PostgreSQL unavailable ({e}). Falling back lazily to SQLite database at sementic_cb_search.db")
            IS_POSTGRES = False

    sqlite_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "sementic_cb_search.db"))
    _engine_instance = create_engine(f"sqlite:///{sqlite_path}", connect_args={"check_same_thread": False})
    return _engine_instance

_engine_instance = None
# Deferred engine reference for ORM definitions
engine = create_engine(
    DATABASE_URL if IS_POSTGRES else f"sqlite:///{os.path.abspath(os.path.join(os.path.dirname(__file__), 'sementic_cb_search.db'))}",
    connect_args={"connect_timeout": 5} if IS_POSTGRES else {"check_same_thread": False}
)

Base = declarative_base()

class Repo(Base):
    __tablename__ = "repos"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    failed_stage: Mapped[str | None] = mapped_column(String(50), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_progress_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    clone_path: Mapped[str | None] = mapped_column(Text, nullable=True) # Cache clone path
    ingested_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

class Function(Base):
    __tablename__ = "functions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id", ondelete="CASCADE"), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    class_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(50), nullable=False)

class CallEdge(Base):
    __tablename__ = "call_edges"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    caller_function_id: Mapped[int] = mapped_column(ForeignKey("functions.id", ondelete="CASCADE"), nullable=False)
    callee_function_id: Mapped[int] = mapped_column(ForeignKey("functions.id", ondelete="CASCADE"), nullable=False)
    call_line: Mapped[int] = mapped_column(Integer, nullable=False)

class UnresolvedCall(Base):
    __tablename__ = "unresolved_calls"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    caller_function_id: Mapped[int] = mapped_column(ForeignKey("functions.id", ondelete="CASCADE"), nullable=False)
    called_name: Mapped[str] = mapped_column(String(255), nullable=False)
    call_line: Mapped[int] = mapped_column(Integer, nullable=False)

from sqlalchemy.types import TypeDecorator

class VectorOrText(TypeDecorator):
    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(Vector(768))
        return dialect.type_descriptor(Text())

class FunctionEmbedding(Base):
    __tablename__ = "function_embeddings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    function_id: Mapped[int] = mapped_column(ForeignKey("functions.id", ondelete="CASCADE"), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(VectorOrText, nullable=False)

def init_db():
    eng = _get_engine()
    if IS_POSTGRES:
        try:
            with eng.connect() as conn:
                from sqlalchemy import text
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                conn.commit()
        except Exception as e:
            raise RuntimeError(f"Database initialization failed: Could not connect to PostgreSQL. {e}")
    Base.metadata.create_all(bind=eng)
    
    # Auto-migration for missing columns on existing SQLite/Postgres repos table
    with eng.connect() as conn:
        from sqlalchemy import text, inspect
        inspector = inspect(eng)
        columns = [c['name'] for c in inspector.get_columns('repos')]
        if 'failed_stage' not in columns:
            try:
                conn.execute(text("ALTER TABLE repos ADD COLUMN failed_stage VARCHAR(50)"))
                conn.commit()
            except Exception:
                pass
        if 'failed_at' not in columns:
            try:
                conn.execute(text("ALTER TABLE repos ADD COLUMN failed_at DATETIME"))
                conn.commit()
            except Exception:
                pass
        if 'last_progress_at' not in columns:
            try:
                conn.execute(text("ALTER TABLE repos ADD COLUMN last_progress_at DATETIME"))
                conn.commit()
            except Exception:
                pass

def get_session():
    eng = _get_engine()
    session_factory = sessionmaker(bind=eng, autoflush=False, autocommit=False)
    return session_factory()
