"""
Azure SQL Database provisioner — creates per-org databases on demand.

When AZURE_SQL_SERVER is set, each new org gets its own Azure SQL Database
with a contained user. When absent, the system falls back to SQLite.
"""

from __future__ import annotations

import logging
import os
import re
import secrets
import time

import pymssql

import metadata as db
from datetime import datetime, timezone

logger = logging.getLogger("autopdf2sqlizer.provisioner")


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

def is_azure_sql_configured() -> bool:
    """Check whether Azure SQL admin credentials are present."""
    return bool(os.getenv("AZURE_SQL_SERVER"))


def get_admin_connection(database: str = "master"):
    """Connect to Azure SQL Server with admin credentials."""
    server = os.getenv("AZURE_SQL_SERVER")
    user = os.getenv("AZURE_SQL_ADMIN_USER")
    password = os.getenv("AZURE_SQL_ADMIN_PASSWORD")
    port = int(os.getenv("AZURE_SQL_PORT", "1433"))

    if not all([server, user, password]):
        raise EnvironmentError("Azure SQL admin credentials not configured")

    return pymssql.connect(
        server=server, user=user, password=password,
        port=port, database=database,
    )


def generate_password() -> str:
    """Generate a password meeting Azure SQL complexity policy."""
    base = secrets.token_urlsafe(32)
    return base + "!A1"  # Ensure uppercase, lowercase, digit, symbol


# ---------------------------------------------------------------------------
# Provisioning
# ---------------------------------------------------------------------------

def provision_database(org_id: str) -> dict:
    """
    Create a new Azure SQL Database for an org.

    Steps:
      1. CREATE DATABASE on master
      2. Wait for ONLINE status
      3. Create contained user with appropriate roles
      4. Store credentials in metadata DB
    """
    server = os.getenv("AZURE_SQL_SERVER")
    port = int(os.getenv("AZURE_SQL_PORT", "1433"))

    safe_prefix = re.sub(r"[^\w]", "", org_id[:8])
    db_name = f"org_{safe_prefix}"
    username = f"org_{safe_prefix}_user"
    password = generate_password()

    try:
        _create_database(db_name)
        _wait_or_raise(db_name)
        _create_contained_user(db_name, username, password)
        _store_credentials(org_id, db_name, server, username, password, port)
    except Exception as exc:
        logger.error("Provisioning failed for org %s: %s", org_id, exc)
        db.update_org_database_status(
            org_id=org_id,
            status="failed",
            error=str(exc),
        )
        raise

    return {"database_name": db_name, "username": username, "status": "ready"}


def _create_database(db_name: str) -> None:
    """Issue CREATE DATABASE on the master connection."""
    admin_conn = get_admin_connection("master")
    admin_conn.autocommit(True)
    cursor = admin_conn.cursor()
    cursor.execute(f"CREATE DATABASE [{db_name}]")
    admin_conn.close()


def _wait_or_raise(db_name: str, timeout: int = 120) -> None:
    """Wait for database to come ONLINE or raise TimeoutError."""
    if not wait_for_database_online(db_name, timeout=timeout):
        raise TimeoutError(
            f"Database {db_name} did not come online within {timeout}s"
        )


def _create_contained_user(
    db_name: str, username: str, password: str,
) -> None:
    """Create a contained user with reader/writer/ddladmin roles."""
    org_conn = get_admin_connection(db_name)
    org_conn.autocommit(True)
    cursor = org_conn.cursor()
    cursor.execute(
        f"CREATE USER [{username}] WITH PASSWORD = %s", (password,)
    )
    cursor.execute(f"ALTER ROLE db_datareader ADD MEMBER [{username}]")
    cursor.execute(f"ALTER ROLE db_datawriter ADD MEMBER [{username}]")
    cursor.execute(f"ALTER ROLE db_ddladmin ADD MEMBER [{username}]")
    org_conn.close()


def _store_credentials(
    org_id: str,
    db_name: str,
    server: str,
    username: str,
    password: str,
    port: int,
) -> None:
    """Update the placeholder record with real credentials and mark ready."""
    db.update_org_database_credentials(
        org_id=org_id,
        database_name=db_name,
        server=server,
        username=username,
        password=password,
        port=port,
    )
    db.update_org_database_status(
        org_id=org_id,
        status="ready",
        ready_at=datetime.now(timezone.utc).isoformat(),
    )


# ---------------------------------------------------------------------------
# Polling
# ---------------------------------------------------------------------------

def wait_for_database_online(db_name: str, timeout: int = 120) -> bool:
    """Poll sys.databases until state is ONLINE."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            conn = get_admin_connection("master")
            cursor = conn.cursor()
            cursor.execute(
                "SELECT state_desc FROM sys.databases WHERE name = %s",
                (db_name,),
            )
            row = cursor.fetchone()
            conn.close()
            if row and row[0] == "ONLINE":
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


# ---------------------------------------------------------------------------
# Connection testing
# ---------------------------------------------------------------------------

def test_org_connection(org_id: str) -> bool:
    """Test the per-org database connection."""
    org_db = db.get_org_database(org_id)
    if not org_db:
        return False
    try:
        conn = pymssql.connect(
            server=org_db.server,
            user=org_db.username,
            password=org_db.password_encrypted,
            port=org_db.port,
            database=org_db.database_name,
        )
        conn.close()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Deprovisioning (cleanup / testing)
# ---------------------------------------------------------------------------

def deprovision_database(org_id: str) -> None:
    """Drop an org's database. Used for cleanup and testing."""
    org_db = db.get_org_database(org_id)
    if not org_db:
        return
    try:
        conn = get_admin_connection("master")
        conn.autocommit(True)
        cursor = conn.cursor()
        cursor.execute(
            f"DROP DATABASE IF EXISTS [{org_db.database_name}]"
        )
        conn.close()
    except Exception as exc:
        logger.warning(
            "Failed to drop database for org %s: %s", org_id, exc,
        )
