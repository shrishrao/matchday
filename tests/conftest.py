"""Shared fixtures. API and seed tests use a separate database, so real seed data is untouched."""

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from scripts.seed import seed_database

TEST_DATABASE = "matchday_test"
TEST_REACTIONS = 2_000


# ===== Database fixtures =====
@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """Create a fresh, seeded test database and return settings that point at it."""
    main_settings = Settings()
    with psycopg.connect(main_settings.conninfo(), autocommit=True) as admin:
        admin.execute(f"DROP DATABASE IF EXISTS {TEST_DATABASE} WITH (FORCE)")
        admin.execute(f"CREATE DATABASE {TEST_DATABASE}")

    settings = Settings(postgres_db=TEST_DATABASE)
    with psycopg.connect(settings.conninfo()) as connection:
        seed_database(connection, reactions=TEST_REACTIONS)
    return settings


@pytest.fixture
def connection(test_settings):
    """Open a direct connection to the test database."""
    with psycopg.connect(test_settings.conninfo()) as open_connection:
        yield open_connection


# ===== API fixture =====
@pytest.fixture(scope="session")
def client(test_settings):
    """Run the API against the test database."""
    with TestClient(create_app(test_settings)) as test_client:
        yield test_client
