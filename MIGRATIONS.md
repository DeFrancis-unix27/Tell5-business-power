# Database Migrations Guide

This project uses Alembic for versioned database migrations. This is essential for production to safely manage schema changes.

## Initial Setup (One-time)

```bash
# Install Alembic (already in requirements.txt)
pip install -r requirements.txt

# Initialize Alembic in the project
alembic init alembic
```

This creates an `alembic/` directory with:
- `env.py` - Configuration for running migrations
- `script.py.mako` - Template for new migrations
- `versions/` - Directory for migration files

## Update alembic/env.py

After initialization, update `alembic/env.py` to use your models:

```python
from config import Config
from sqlalchemy import engine_from_config, pool
from alembic import context
from db import Base
import logging

# Use DATABASE_URL from Config
config.set_main_option("sqlalchemy.url", Config.DATABASE_URL)

# Use your models for auto-generation
target_metadata = Base.metadata
```

## Creating Migrations

### Automatic (Recommended)

```bash
# Auto-generate migration from model changes
alembic revision --autogenerate -m "Description of changes"

# Example: alembic revision --autogenerate -m "Add is_admin column to users"
```

### Manual

```bash
# Create an empty migration to write SQL manually
alembic revision -m "Description of changes"
```

## Running Migrations

```bash
# Upgrade to latest migration
alembic upgrade head

# Upgrade to specific revision
alembic upgrade <revision_id>

# Downgrade to previous revision
alembic downgrade -1

# Downgrade to specific revision
alembic downgrade <revision_id>

# View current revision
alembic current

# View history
alembic history
```

## Production Deployment

Before deploying:

1. **Test migrations locally:**
   ```bash
   alembic upgrade head
   ```

2. **Review migration files** in `alembic/versions/` to ensure they're safe

3. **Backup production database** before running migrations

4. **Run migrations in production:**
   ```bash
   alembic upgrade head
   ```

5. **For Docker/container deployments**, add to startup script:
   ```bash
   alembic upgrade head
   uvicorn api.index:app --host 0.0.0.0 --port 8000
   ```

## Best Practices

- **Always test migrations** in a staging environment first
- **Keep migrations small** and focused on one change
- **Write reversible migrations** (include downgrade logic)
- **Don't modify existing migrations** - create new ones instead
- **Review auto-generated migrations** before committing
- **Backup data** before production deployments

## Troubleshooting

**Issue: "Target database is not up to date"**
```bash
alembic upgrade head
```

**Issue: Need to downgrade after bad migration**
```bash
alembic downgrade -1
# Fix the migration file
# Then upgrade again
alembic upgrade head
```

**Issue: Lost track of revision history**
```bash
alembic history  # See all migrations
alembic current  # See current revision
```
