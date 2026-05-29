import pytest
from auth import hash_password, verify_password, create_session_token, verify_session_token
import time


@pytest.mark.unit
@pytest.mark.auth
class TestPasswordHashing:
    """Test password hashing and verification"""

    def test_hash_password_creates_hash(self):
        """Test that hash_password creates a valid hash"""
        password = "TestPassword123!"
        hashed = hash_password(password)
        assert hashed.startswith("pbkdf2_sha256$")
        assert len(hashed) > 50

    def test_verify_password_correct(self):
        """Test that correct password verifies"""
        password = "TestPassword123!"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_verify_password_incorrect(self):
        """Test that incorrect password fails verification"""
        password = "TestPassword123!"
        wrong_password = "WrongPassword456!"
        hashed = hash_password(password)
        assert verify_password(wrong_password, hashed) is False

    def test_verify_password_invalid_hash(self):
        """Test that invalid hash returns False"""
        assert verify_password("password", "invalid_hash") is False

    def test_verify_password_empty_hash(self):
        """Test that empty hash returns False"""
        assert verify_password("password", "") is False

    def test_password_hashes_are_unique(self):
        """Test that same password produces different hashes"""
        password = "TestPassword123!"
        hash1 = hash_password(password)
        hash2 = hash_password(password)
        assert hash1 != hash2
        assert verify_password(password, hash1)
        assert verify_password(password, hash2)


@pytest.mark.unit
@pytest.mark.auth
class TestSessionTokens:
    """Test session token generation and verification"""

    def test_create_session_token_returns_string(self):
        """Test that session token is a string"""
        token = create_session_token(user_id=1)
        assert isinstance(token, str)
        assert len(token) > 0

    def test_verify_session_token_valid(self):
        """Test that valid token verifies correctly"""
        user_id = 42
        token = create_session_token(user_id=user_id)
        verified_id = verify_session_token(token)
        assert verified_id == user_id

    def test_verify_session_token_invalid(self):
        """Test that invalid token returns None"""
        assert verify_session_token("invalid_token") is None

    def test_verify_session_token_empty(self):
        """Test that empty token returns None"""
        assert verify_session_token("") is None

    def test_verify_session_token_malformed(self):
        """Test that malformed token returns None"""
        assert verify_session_token("no.dots") is None
        assert verify_session_token("too.many.dots") is None

    def test_session_token_expires(self):
        """Test that expired token returns None"""
        user_id = 1
        token = create_session_token(user_id=user_id)

        # Token should be valid now
        assert verify_session_token(token) == user_id

    def test_different_tokens_for_different_users(self):
        """Test that different users get different tokens"""
        token1 = create_session_token(user_id=1)
        token2 = create_session_token(user_id=2)
        assert token1 != token2
        assert verify_session_token(token1) == 1
        assert verify_session_token(token2) == 2

    def test_session_token_tampered_fails(self):
        """Test that tampered token fails verification"""
        token = create_session_token(user_id=1)
        # Tamper with the token
        tampered = token[:-1] + ("X" if token[-1] != "X" else "Y")
        assert verify_session_token(tampered) is None
