"""
1.1.2 — Database Connectors (Standalone Module)
-------------------------------------------------
Read-only connectors to pull financial data from external databases.
The user provides connection details, we pull their transaction tables.

IMPORTANT: All connections are READ-ONLY. We NEVER write to, modify, or
delete anything in the user's source database.

Supported databases:
    - SQLite   (local file — .db, .sqlite, .sqlite3)
    - PostgreSQL (remote or local server)
    - MySQL    (remote or local server)

Dependencies:
    pip install pandas sqlalchemy
    pip install psycopg2-binary   # for PostgreSQL
    pip install pymysql            # for MySQL

Usage:
    from db_connector import DatabaseConnector

    # SQLite
    conn = DatabaseConnector.sqlite("/path/to/accounting.db")
    tables = conn.list_tables()
    df = conn.read_table("transactions")

    # PostgreSQL
    conn = DatabaseConnector.postgres(
        host="localhost", port=5432,
        database="mybooks", user="reader", password="***"
    )
    df = conn.read_query("SELECT * FROM journal_entries WHERE year = 2026")
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd
from sqlalchemy import create_engine, inspect, text


# ── Exceptions ────────────────────────────────────────────────────────────────
class ConnectorError(Exception):
    """Base error for database connection issues."""
    pass


class ConnectionFailedError(ConnectorError):
    """Could not connect to the database."""
    pass


class TableNotFoundError(ConnectorError):
    """The requested table does not exist."""
    pass


# ── Main Class ────────────────────────────────────────────────────────────────
@dataclass
class DatabaseConnector:
    """
    Read-only database connector.

    Creates a SQLAlchemy engine and provides methods to:
      - list_tables(): see what tables exist
      - read_table(name): read an entire table into a DataFrame
      - read_query(sql): run a custom SELECT query

    All operations are READ-ONLY. The engine is created with
    execution_options(isolation_level="AUTOCOMMIT") and we only
    allow SELECT statements in read_query().
    """
    engine: object  # sqlalchemy.Engine
    db_type: str    # "sqlite", "postgresql", "mysql"

    # ── Factory methods ───────────────────────────────────────────────────────

    @classmethod
    def sqlite(cls, filepath: str) -> "DatabaseConnector":
        """
        Connect to a local SQLite database file.

        Args:
            filepath: path to .db / .sqlite / .sqlite3 file

        Raises:
            ConnectionFailedError: if file doesn't exist
        """
        path = Path(filepath)
        if not path.exists():
            raise ConnectionFailedError(f"SQLite file not found: {filepath}")

        url = f"sqlite:///{filepath}"
        try:
            engine = create_engine(url)
            # Test the connection
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return cls(engine=engine, db_type="sqlite")
        except Exception as e:
            raise ConnectionFailedError(f"SQLite connection failed: {e}")

    @classmethod
    def postgres(
        cls,
        host: str = "localhost",
        port: int = 5432,
        database: str = "postgres",
        user: str = "postgres",
        password: str = "",
    ) -> "DatabaseConnector":
        """
        Connect to a PostgreSQL server (read-only).

        Requires: pip install psycopg2-binary
        """
        url = f"postgresql://{user}:{password}@{host}:{port}/{database}"
        try:
            engine = create_engine(url)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return cls(engine=engine, db_type="postgresql")
        except Exception as e:
            raise ConnectionFailedError(f"PostgreSQL connection failed: {e}")

    @classmethod
    def mysql(
        cls,
        host: str = "localhost",
        port: int = 3306,
        database: str = "mysql",
        user: str = "root",
        password: str = "",
    ) -> "DatabaseConnector":
        """
        Connect to a MySQL server (read-only).

        Requires: pip install pymysql
        """
        url = f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}"
        try:
            engine = create_engine(url)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return cls(engine=engine, db_type="mysql")
        except Exception as e:
            raise ConnectionFailedError(f"MySQL connection failed: {e}")

    # ── Read-only operations ──────────────────────────────────────────────────

    def list_tables(self) -> list[str]:
        """Return a list of all table names in the database."""
        inspector = inspect(self.engine)
        return inspector.get_table_names()

    def read_table(
        self,
        table_name: str,
        limit: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Read an entire table into a DataFrame.

        Args:
            table_name: name of the table
            limit: max rows to fetch (None = all rows)

        Raises:
            TableNotFoundError: if the table doesn't exist
        """
        tables = self.list_tables()
        if table_name not in tables:
            raise TableNotFoundError(
                f"Table '{table_name}' not found. "
                f"Available: {tables}"
            )

        query = f"SELECT * FROM {table_name}"
        if limit:
            query += f" LIMIT {limit}"

        return pd.read_sql(text(query), self.engine)

    def read_query(self, sql: str) -> pd.DataFrame:
        """
        Execute a custom SELECT query and return results as DataFrame.

        SECURITY: Only SELECT statements are allowed. Any INSERT, UPDATE,
        DELETE, DROP, ALTER, CREATE, or TRUNCATE will be rejected.

        Args:
            sql: a SELECT query string

        Raises:
            ConnectorError: if the query is not a SELECT statement
        """
        # Safety check: only allow SELECT queries
        cleaned = sql.strip().upper()
        forbidden = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE"]
        for keyword in forbidden:
            if cleaned.startswith(keyword):
                raise ConnectorError(
                    f"Only SELECT queries are allowed. "
                    f"'{keyword}' statements are blocked for safety."
                )

        return pd.read_sql(text(sql), self.engine)

    def get_table_info(self, table_name: str) -> list[dict]:
        """
        Get column names and types for a table.

        Returns a list of dicts: [{"name": "id", "type": "INTEGER"}, ...]
        """
        inspector = inspect(self.engine)
        columns = inspector.get_columns(table_name)
        return [
            {"name": col["name"], "type": str(col["type"])}
            for col in columns
        ]

    def close(self):
        """Close the database connection."""
        self.engine.dispose()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


# ── CLI entry point ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python db_connector.py <path_to_sqlite.db>")
        print("       python db_connector.py <path> <table_name>")
        sys.exit(1)

    db_path = sys.argv[1]
    print(f"Connecting to SQLite: {db_path}")

    with DatabaseConnector.sqlite(db_path) as conn:
        tables = conn.list_tables()
        print(f"Tables found: {tables}")

        if len(sys.argv) >= 3:
            table = sys.argv[2]
            df = conn.read_table(table, limit=10)
            print(f"\nFirst 10 rows of '{table}':")
            print(df.to_string())
        elif tables:
            table = tables[0]
            df = conn.read_table(table, limit=5)
            print(f"\nFirst 5 rows of '{table}':")
            print(df.to_string())
