import pytest
import pytest_asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool
from db import Base, get_db
from api.index import app
from httpx import AsyncClient


@pytest.fixture
def test_env_setup():
    """Set test environment variables"""
    test_vars = {
        "TWILIO_ACCOUNT_SID": "test_sid",
        "TWILIO_AUTH_TOKEN": "test_token",
        "TWILIO_PHONE_NUMBER": "whatsapp:+1234567890",
        "SESSION_SECRET": "test-session-secret-at-least-32-characters-long!!!",
        "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
        "DEBUG": "True",
        "ENVIRONMENT": "test",
        "COOKIE_SECURE": "False",
    }
    original_vars = {}
    for key, value in test_vars.items():
        original_vars[key] = os.environ.get(key)
        os.environ[key] = value

    yield test_vars

    for key, original_value in original_vars.items():
        if original_value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = original_value


@pytest_asyncio.fixture
async def test_db():
    """Create in-memory test database"""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with async_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    yield async_session

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest_asyncio.fixture
async def client(test_env_setup, test_db):
    """Create test client"""
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def sample_user_data():
    """Sample user data for testing"""
    return {
        "first_name": "John",
        "last_name": "Doe",
        "email": "john@example.com",
        "phone": "+1234567890",
        "password": "TestPassword123!",
    }


@pytest.fixture
def sample_conversation_data():
    """Sample conversation data for testing"""
    return {
        "phone": "+1234567890",
        "message": "I would like to order 2 pizzas",
        "category": "order",
    }


@pytest.fixture
def sample_order_data():
    """Sample order data for testing"""
    return {
        "phone": "+1234567890",
        "customer_name": "John Doe",
        "item": "Pizza",
        "quantity": 2,
        "status": "pending",
    }
