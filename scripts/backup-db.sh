#!/usr/bin/env bash
# Database backup script for Tell5
# Usage: ./scripts/backup-db.sh
# Recommended: run via cron daily
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DB_URL="${DATABASE_URL:-}"

if [ -z "$DB_URL" ]; then
  echo "ERROR: DATABASE_URL not set"
  exit 1
fi

mkdir -p "$BACKUP_DIR"

# Dump and compress
pg_dump "$DB_URL" --no-owner --no-acl | gzip > "$BACKUP_DIR/tell5_$TIMESTAMP.sql.gz"

# Keep only last 30 backups
ls -t "$BACKUP_DIR"/tell5_*.sql.gz | tail -n +31 | xargs rm -f 2>/dev/null || true

echo "Backup saved: $BACKUP_DIR/tell5_$TIMESTAMP.sql.gz ($(du -h "$BACKUP_DIR/tell5_$TIMESTAMP.sql.gz" | cut -f1))"
