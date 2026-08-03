#!/bin/bash
# AIEC Application Backup Script
# Usage: ./backup_app.sh

BACKUP_DIR="/home/vsmwrurd/application_backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME="aiec_backup_${TIMESTAMP}"
APP_DIR="/home/vsmwrurd/ai_registration_engine"

mkdir -p "$BACKUP_DIR"

echo "🔐 Creating backup: $BACKUP_NAME..."

cd "$APP_DIR"

# Create main backup
tar -czf "$BACKUP_DIR/${BACKUP_NAME}.tar.gz" \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.git' \
    .

# Backup database
cp booking_storage.db "$BACKUP_DIR/${BACKUP_NAME}_database.db"

# Backup vouchers if exists
if [ -d "vouchers" ] && [ "$(ls -A vouchers)" ]; then
    tar -czf "$BACKUP_DIR/${BACKUP_NAME}_vouchers.tar.gz" vouchers/
fi

# Create latest symlinks
cd "$BACKUP_DIR"
ln -sf "${BACKUP_NAME}.tar.gz" latest_backup.tar.gz
ln -sf "${BACKUP_NAME}_database.db" latest_database.db

echo "✅ Backup completed: $BACKUP_DIR/${BACKUP_NAME}.tar.gz"
echo "📦 Size: $(du -h ${BACKUP_NAME}.tar.gz | cut -f1)"

# Cleanup old backups (keep last 10)
cd "$BACKUP_DIR"
ls -t aiec_backup_*.tar.gz | tail -n +11 | xargs -r rm
echo "🗑️  Old backups cleaned (keeping last 10)"
