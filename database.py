# database.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os
from dotenv import load_dotenv
import pymssql


load_dotenv()

# Import-time DDL must not hang when local .env has no Cloud SQL host.
_DB_CONFIGURED = bool((os.getenv("DB_SERVER") or "").strip())

SQLALCHEMY_DATABASE_URL = (
    f"mssql+pymssql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
    f"@{os.getenv('DB_SERVER')}/{os.getenv('DB_NAME')}"
)

# Cross-region (asia-south1 Cloud Run -> us-central1 SQL) needs longer login.
# USA defaults are 15/30; keep those unless overridden.
_DB_LOGIN_TIMEOUT = int(os.getenv("DB_LOGIN_TIMEOUT", "15"))
_DB_QUERY_TIMEOUT = int(os.getenv("DB_QUERY_TIMEOUT", "30"))

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_recycle=1800,    # recycle connections every 30 min; 60s was too short for idle dev sessions
    pool_size=5,
    max_overflow=10,
    connect_args={"timeout": _DB_QUERY_TIMEOUT, "login_timeout": _DB_LOGIN_TIMEOUT},
)

if not _DB_CONFIGURED:
    from contextlib import contextmanager

    class _NoDbConn:
        def execute(self, *a, **k):
            return None

        def commit(self):
            return None

        def close(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    @contextmanager
    def _no_db_begin(*_a, **_k):
        print("DB_SERVER unset; skipping import-time SQL")
        yield _NoDbConn()

    engine.begin = _no_db_begin
    engine.connect = _no_db_begin

# Declarative base
Base = declarative_base()

if not _DB_CONFIGURED:
    def _skip_create_all(*_a, **_k):
        return None

    Base.metadata.create_all = _skip_create_all

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def run_startup_ddl(label: str, fn):
    """Run import-time schema DDL; log and continue on failure.

    Incomplete BAK restores (or missing tables) must not prevent Cloud Run
    from binding PORT=8080.
    """
    if not _DB_CONFIGURED:
        return
    try:
        fn()
    except Exception as e:
        print(f"Startup DDL warning [{label}]: {e}")


# Dependency for FastAPI
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def blank_to_none(body):
    """Coerce empty / whitespace-only strings in a request body to None.

    Empty strings from form submissions break INSERT/UPDATEs into numeric, date, and
    time columns ("Error converting nvarchar to numeric" / a 1900-01-01 epoch fallback),
    surfacing as a 500 and a dead "Save"/"Create" button. Only blank strings are nulled
    (not 0 or other values), so required-field checks and real data are unaffected.
    """
    if not isinstance(body, dict):
        return body
    return {k: (None if isinstance(v, str) and v.strip() == "" else v) for k, v in body.items()}


def get_db_cursor():
    conn = pymssql.connect(
        server=os.getenv("DB_SERVER"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
        timeout=_DB_QUERY_TIMEOUT,
        login_timeout=_DB_LOGIN_TIMEOUT,
    )
    return conn.cursor(as_dict=True)


def get_raw_conn():
    conn = pymssql.connect(
        server=os.getenv("DB_SERVER"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
        timeout=_DB_QUERY_TIMEOUT,
        login_timeout=_DB_LOGIN_TIMEOUT,
    )
    try:
        yield conn
    finally:
        conn.close()