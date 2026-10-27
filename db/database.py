"""Database connection and session management with Cloud SQL & SQLite fallback."""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

logger = logging.getLogger("broker.db")
logging.basicConfig(level=logging.INFO)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
SQLITE_PATH = DATA_DIR / "broker.db"

DATABASE_URL = os.environ.get("DATABASE_URL")
CLOUD_SQL_INSTANCE = os.environ.get(
    "CLOUD_SQL_INSTANCE", "qwiklabs-gcp-03-c81d344a3430:us-central1:public-health-db"
)
DB_USER = os.environ.get("DB_USER", "postgres")
DB_PASS = os.environ.get("DB_PASS")
DB_NAME = os.environ.get("DB_NAME", "public_health_broker")

Base = declarative_base()


def _get_cloud_sql_password() -> str:
    """Fetch password from env or GCP Secret Manager."""
    global DB_PASS
    if DB_PASS:
        return DB_PASS
    try:
        token = subprocess.check_output(
            ["gcloud", "secrets", "versions", "access", "latest", "--secret=CloudSQLSecret"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        if token:
            DB_PASS = token
            return token
    except Exception as e:
        logger.debug(f"Could not retrieve CloudSQLSecret from Secret Manager: {e}")
    return ""


def _create_db_engine():
    """Create SQLAlchemy engine: Cloud SQL PostgreSQL first, then local SQLite fallback."""
    # 1. Direct DATABASE_URL
    if DATABASE_URL:
        url = DATABASE_URL
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        logger.info(f"Connecting to database via DATABASE_URL: {url.split('@')[-1]}")
        return create_engine(url, pool_pre_ping=True)

    # 2. Google Cloud SQL with Python Connector & Secret Manager password
    password = _get_cloud_sql_password()
    if CLOUD_SQL_INSTANCE and password:
        try:
            from google.cloud.sql.connector import Connector
            connector = Connector()

            def getconn():
                return connector.connect(
                    CLOUD_SQL_INSTANCE,
                    "pg8000",
                    user=DB_USER,
                    password=password,
                    db=DB_NAME,
                )

            logger.info(f"Connecting to Google Cloud SQL instance: {CLOUD_SQL_INSTANCE} (db: {DB_NAME})")
            engine = create_engine("postgresql+pg8000://", creator=getconn, pool_pre_ping=True)
            # Test immediate connectivity
            with engine.connect() as conn:
                logger.info("Cloud SQL PostgreSQL connection verified successfully!")
            return engine
        except Exception as e:
            logger.warning(f"Could not connect via Cloud SQL connector: {e}. Falling back to SQLite.")

    # 3. Graceful fallback: Local SQLite for offline tests
    sqlite_url = f"sqlite:///{SQLITE_PATH}"
    logger.info(f"Using local fallback database: {sqlite_url}")
    return create_engine(
        sqlite_url,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )


engine = _create_db_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Create all tables in the configured database."""
    Base.metadata.create_all(bind=engine)
    logger.info(f"Database tables initialized on {engine.url.drivername} backend.")


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency to yield database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
