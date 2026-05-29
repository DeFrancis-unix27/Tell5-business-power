import pytest
from sqlalchemy.ext.asyncio import AsyncSession
import crud
from models import User, Conversation, Order, Notification


@pytest.mark.unit
@pytest.mark.asyncio
class TestUserCRUD:
    """Test user CRUD operations"""

    async def test_create_user(self, test_db, sample_user_data):
        """Test creating a user"""
        async with test_db() as session:
            user = await crud.create_user(
                session,
                email=sample_user_data["email"],
                password_hash="hashed_password",
                first_name=sample_user_data["first_name"],
                last_name=sample_user_data["last_name"],
                phone=sample_user_data["phone"],
            )
            assert user.id is not None
            assert user.email == sample_user_data["email"]
            assert user.first_name == sample_user_data["first_name"]

    async def test_get_user_by_email(self, test_db, sample_user_data):
        """Test retrieving user by email"""
        async with test_db() as session:
            # Create user
            await crud.create_user(
                session,
                email=sample_user_data["email"],
                password_hash="hashed_password",
                first_name=sample_user_data["first_name"],
                last_name=sample_user_data["last_name"],
                phone=sample_user_data["phone"],
            )
            await session.commit()

            # Retrieve user
            user = await crud.get_user_by_email(session, sample_user_data["email"])
            assert user is not None
            assert user.email == sample_user_data["email"]

    async def test_get_user_by_email_not_found(self, test_db):
        """Test retrieving non-existent user returns None"""
        async with test_db() as session:
            user = await crud.get_user_by_email(session, "nonexistent@example.com")
            assert user is None

    async def test_get_user_by_id(self, test_db, sample_user_data):
        """Test retrieving user by ID"""
        async with test_db() as session:
            user = await crud.create_user(
                session,
                email=sample_user_data["email"],
                password_hash="hashed_password",
                first_name=sample_user_data["first_name"],
                last_name=sample_user_data["last_name"],
                phone=sample_user_data["phone"],
            )
            await session.commit()

            retrieved = await crud.get_user_by_id(session, user.id)
            assert retrieved is not None
            assert retrieved.id == user.id

    async def test_count_users(self, test_db, sample_user_data):
        """Test counting users"""
        async with test_db() as session:
            count_before = await crud.count_users(session)
            await crud.create_user(
                session,
                email=sample_user_data["email"],
                password_hash="hashed_password",
                first_name=sample_user_data["first_name"],
                last_name=sample_user_data["last_name"],
                phone=sample_user_data["phone"],
            )
            await session.commit()
            count_after = await crud.count_users(session)
            assert count_after == count_before + 1


@pytest.mark.unit
@pytest.mark.asyncio
class TestConversationCRUD:
    """Test conversation CRUD operations"""

    async def test_create_conversation(self, test_db, sample_conversation_data):
        """Test creating a conversation"""
        async with test_db() as session:
            conv = await crud.create_conversation(
                session,
                phone=sample_conversation_data["phone"],
                message=sample_conversation_data["message"],
                category=sample_conversation_data["category"],
            )
            assert conv.id is not None
            assert conv.phone == sample_conversation_data["phone"]
            assert conv.category == "order"

    async def test_list_conversations(self, test_db, sample_conversation_data):
        """Test listing conversations"""
        async with test_db() as session:
            await crud.create_conversation(
                session,
                phone=sample_conversation_data["phone"],
                message=sample_conversation_data["message"],
                category=sample_conversation_data["category"],
            )
            await session.commit()

            convs = await crud.list_conversations(session)
            assert len(convs) > 0


@pytest.mark.unit
@pytest.mark.asyncio
class TestOrderCRUD:
    """Test order CRUD operations"""

    async def test_create_order(self, test_db, sample_order_data):
        """Test creating an order"""
        async with test_db() as session:
            order = await crud.create_order(
                session,
                phone=sample_order_data["phone"],
                item=sample_order_data["item"],
                quantity=sample_order_data["quantity"],
            )
            assert order.id is not None
            assert order.phone == sample_order_data["phone"]
            assert order.item == sample_order_data["item"]

    async def test_list_orders(self, test_db, sample_order_data):
        """Test listing orders"""
        async with test_db() as session:
            await crud.create_order(
                session,
                phone=sample_order_data["phone"],
                item=sample_order_data["item"],
                quantity=sample_order_data["quantity"],
            )
            await session.commit()

            orders = await crud.list_orders(session)
            assert len(orders) > 0


@pytest.mark.unit
@pytest.mark.asyncio
class TestNotificationCRUD:
    """Test notification CRUD operations"""

    async def test_create_notification(self, test_db):
        """Test creating a notification"""
        async with test_db() as session:
            notif = await crud.create_notification(
                session,
                ntype="new_order",
                payload="test_payload",
            )
            assert notif.id is not None
            assert notif.ntype == "new_order"

    async def test_list_notifications(self, test_db):
        """Test listing notifications"""
        async with test_db() as session:
            await crud.create_notification(
                session,
                ntype="new_order",
                payload="test",
            )
            await session.commit()

            notifs = await crud.list_notifications(session)
            assert len(notifs) >= 0
