# Testing Guide

Comprehensive testing for Tell5 application with unit tests, integration tests, webhook tests, and security tests.

## Setup

### Install Test Dependencies

```bash
pip install -r requirements.txt
```

This includes:
- `pytest>=7.0.0` - Testing framework
- `pytest-asyncio>=0.21.0` - Async test support
- `pytest-cov>=4.0.0` - Coverage reporting
- `httpx>=0.24.0` - Async HTTP client

### Configuration

Tests use `pytest.ini` for configuration and `tests/conftest.py` for fixtures.

## Running Tests

### Run All Tests

```bash
pytest
```

### Run Tests with Coverage

```bash
pytest --cov=. --cov-report=html
```

This generates an HTML coverage report in `htmlcov/index.html`

### Run Specific Test Categories

```bash
# Unit tests only
pytest -m unit

# Integration tests only
pytest -m integration

# Webhook tests only
pytest -m webhook

# Auth tests only
pytest -m auth

# Security tests only
pytest -m security
```

### Run Specific Test Files

```bash
pytest tests/test_auth.py
pytest tests/test_api.py
pytest tests/test_webhook.py
pytest tests/test_csrf.py
pytest tests/test_crud.py
pytest tests/test_config.py
```

### Run with Verbose Output

```bash
pytest -v
```

### Run Single Test

```bash
pytest tests/test_auth.py::TestPasswordHashing::test_hash_password_creates_hash -v
```

### Run Tests Matching Pattern

```bash
pytest -k "csrf" -v
```

## Test Structure

### tests/conftest.py
Global fixtures and test setup:
- `test_env_setup` - Sets environment variables for tests
- `test_db` - In-memory SQLite database
- `client` - FastAPI test client
- `sample_user_data` - Sample user for tests
- `sample_conversation_data` - Sample conversation
- `sample_order_data` - Sample order

### tests/test_auth.py
**Unit tests for authentication**
- Password hashing and verification
- Session token creation and verification
- Token expiration
- Token tampering detection

### tests/test_config.py
**Unit tests for configuration**
- Environment variable loading
- Configuration validation
- Required fields validation
- Production-specific rules

### tests/test_crud.py
**Unit tests for database operations**
- User CRUD operations
- Conversation CRUD operations
- Order CRUD operations
- Notification CRUD operations

### tests/test_api.py
**Integration tests for API endpoints**
- Health check endpoint
- Authentication endpoints (signup, login, logout)
- Conversation endpoints
- Stats endpoints
- Dashboard endpoint
- Rate limiting tests

### tests/test_webhook.py
**Integration tests for Twilio webhook**
- Webhook signature validation
- Message categorization
- Order parsing
- Different message types (order, inquiry, complaint, feedback)
- TwiML response format

### tests/test_csrf.py
**Security tests for CSRF protection**
- CSRF token generation
- Token verification
- Token extraction from forms and headers
- Token expiration
- CSRF endpoints

## Test Markers

Tests are marked with markers for organization:

- `@pytest.mark.unit` - Unit tests
- `@pytest.mark.integration` - Integration tests
- `@pytest.mark.webhook` - Webhook tests
- `@pytest.mark.auth` - Authentication tests
- `@pytest.mark.security` - Security tests

## Coverage Goals

| Module | Target | Current |
|--------|--------|---------|
| auth.py | 95% | - |
| config.py | 90% | - |
| crud.py | 85% | - |
| api/index.py | 80% | - |
| csrf.py | 90% | - |

Run coverage report to check current coverage:

```bash
pytest --cov=. --cov-report=term-missing
```

## Writing New Tests

### Basic Unit Test

```python
import pytest

@pytest.mark.unit
def test_example():
    """Test description"""
    result = some_function()
    assert result == expected_value
```

### Async Test

```python
import pytest

@pytest.mark.integration
@pytest.mark.asyncio
async def test_async_endpoint(client):
    """Test async endpoint"""
    response = await client.get("/api/endpoint")
    assert response.status_code == 200
```

### Using Fixtures

```python
@pytest.mark.unit
@pytest.mark.asyncio
async def test_with_fixtures(test_db, sample_user_data):
    """Test using fixtures"""
    async with test_db() as session:
        user = await crud.create_user(session, **sample_user_data)
        assert user.id is not None
```

## Debugging Tests

### Run Single Test with Print Output

```bash
pytest tests/test_auth.py::TestPasswordHashing::test_hash_password_creates_hash -v -s
```

The `-s` flag shows print statements.

### Run with PDB (Python Debugger)

```bash
pytest tests/test_auth.py -v --pdb
```

Stops at first failure and enters debugger.

### Run with Timeout

```bash
pip install pytest-timeout
pytest --timeout=300  # 5 minute timeout
```

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: pytest --cov=. --cov-report=xml
      - uses: codecov/codecov-action@v2
```

## Performance Testing

### Run Slow Tests Last

```bash
pytest --durations=10
```

Shows 10 slowest tests.

### Parallel Testing

```bash
pip install pytest-xdist
pytest -n auto
```

Runs tests in parallel using all available CPUs.

## Database Testing

Tests use in-memory SQLite database for speed. For integration testing with PostgreSQL:

```python
# In tests/conftest.py, change engine URL to:
# "postgresql+asyncpg://user:pass@localhost:5432/test_db"
```

## Common Issues

### "ModuleNotFoundError" in tests
- Solution: Run from project root directory: `cd /path/to/Tell5 && pytest`

### Tests fail with "database is locked"
- Solution: Use `--tb=short` for cleaner output, or check for leftover database connections

### Async test hanging
- Solution: Increase timeout or check for missing `await` keywords

### Import errors in conftest
- Solution: Ensure all imports use absolute paths from project root

## Best Practices

1. **Test one thing per test** - Keep tests focused and isolated
2. **Use descriptive names** - Test names should describe what they test
3. **Use fixtures** - Don't repeat setup code
4. **Mock external services** - Don't call real APIs in tests
5. **Test edge cases** - Test with empty, null, invalid inputs
6. **Keep tests fast** - Use mocks and in-memory databases
7. **Write tests first** - Practice TDD when possible

## Continuous Testing

Watch for file changes and re-run tests:

```bash
pip install pytest-watch
ptw
```

## Test Reports

### HTML Report

```bash
pytest --html=report.html --self-contained-html
```

Opens in browser for detailed view of all tests.

### JUnit XML (for CI/CD)

```bash
pytest --junit-xml=junit.xml
```

For integration with Jenkins, GitLab CI, etc.

### Coverage HTML Report

```bash
pytest --cov=. --cov-report=html
open htmlcov/index.html
```

## FAQ

**Q: How do I test without Twilio credentials?**
A: Tests use test credentials from conftest.py, which mock real values.

**Q: Can I run tests in production?**
A: No, tests modify database. Always use separate test environment.

**Q: How do I skip a test temporarily?**
A: Use `@pytest.mark.skip` decorator or `pytest -k "not test_name"`

**Q: How do I make a test expected to fail?**
A: Use `@pytest.mark.xfail` decorator.

---

For more information, see [pytest documentation](https://docs.pytest.org/)
