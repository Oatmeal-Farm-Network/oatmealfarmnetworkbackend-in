# --- database.py --- (SQL Server connection for livestock data)
import re
from typing import List, Dict
from config import DB_CONFIG, ALLOWED_TABLES, RAG_AVAILABLE

if RAG_AVAILABLE:
    import pymssql


class Database:
    """Manages database connections and queries for livestock data."""

    def __init__(self):
        self._connection = None
        self._allowed_tables = [t.lower() for t in ALLOWED_TABLES]

    @property
    def connection(self):
        """Lazy connection to database."""
        if self._connection is None and RAG_AVAILABLE:
            try:
                if all([DB_CONFIG["host"], DB_CONFIG["user"], DB_CONFIG["database"]]):
                    self._connection = pymssql.connect(
                        server=DB_CONFIG["host"],
                        port=DB_CONFIG["port"],
                        user=DB_CONFIG["user"],
                        password=DB_CONFIG["password"],
                        database=DB_CONFIG["database"],
                        as_dict=True
                    )
                    print(f"[DB] Connected to {DB_CONFIG['database']}")
            except Exception as e:
                print(f"[DB] Connection failed: {e}")
        return self._connection

    def _validate_query(self, query: str) -> None:
        """Validate query only accesses allowed tables."""
        query_lower = query.lower()
        tables = re.findall(r'from\s+\[?(\w+)\]?', query_lower)
        tables += re.findall(r'join\s+\[?(\w+)\]?', query_lower)
        for table in tables:
            if table not in self._allowed_tables:
                raise PermissionError(f"Access denied to table: {table}")

    def fetch_all(self, table: str) -> List[Dict]:
        """Fetch all rows from an allowed table."""
        if table.lower() not in self._allowed_tables:
            raise PermissionError(f"Access denied to table: {table}")
        if not self.connection:
            return []
        try:
            cursor = self.connection.cursor()
            cursor.execute(f"SELECT * FROM [{table}]")
            return cursor.fetchall() or []
        except Exception as e:
            print(f"[DB] fetch_all({table}) error: {e}")
            return []

    def execute(self, query: str) -> List[Dict]:
        """Execute a SELECT query and return results."""
        if not self.connection:
            return []
        try:
            self._validate_query(query)
            cursor = self.connection.cursor()
            cursor.execute(query)
            results = cursor.fetchall()
            return results if results else []
        except Exception as e:
            print(f"[DB] Query error: {e}")
            return []


db = Database()
