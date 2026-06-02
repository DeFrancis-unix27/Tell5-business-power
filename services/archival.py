import csv
import io
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

ARCHIVE_DIR = Path("data/archives")
ARCHIVE_RETENTION_DAYS = 90


async def ensure_archive_dir():
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)


async def archive_conversations(db: AsyncSession) -> dict[str, int]:
    from models import Conversation

    await ensure_archive_dir()
    cutoff = datetime.utcnow() - timedelta(days=7)
    week_ago_str = cutoff.isoformat()

    q = await db.execute(
        select(Conversation).where(Conversation.timestamp < cutoff)
    )
    old_records = q.scalars().all()

    if not old_records:
        return {"archived": 0, "csv": "", "pdf": ""}

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    csv_path = ARCHIVE_DIR / f"conversations_{timestamp}.csv"

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "phone", "message", "category", "timestamp", "user_id"])
        for conv in old_records:
            writer.writerow([
                conv.id, conv.phone, conv.message,
                conv.category, conv.timestamp, conv.user_id,
            ])

    for conv in old_records:
        await db.delete(conv)
    await db.flush()

    logger.info(f"Archived {len(old_records)} conversations to {csv_path}")
    return {
        "archived": len(old_records),
        "csv": str(csv_path),
    }


async def archive_orders(db: AsyncSession) -> dict[str, int]:
    from models import Order

    await ensure_archive_dir()
    cutoff = datetime.utcnow() - timedelta(days=30)

    q = await db.execute(
        select(Order).where(
            Order.timestamp < cutoff,
            Order.status.in_(["delivered", "cancelled"]),
        )
    )
    old_orders = q.scalars().all()

    if not old_orders:
        return {"archived": 0}

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    csv_path = ARCHIVE_DIR / f"orders_{timestamp}.csv"

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "phone", "customer_name", "item", "quantity", "status", "timestamp", "user_id"])
        for order in old_orders:
            writer.writerow([
                order.id, order.phone, order.customer_name,
                order.item, order.quantity, order.status,
                order.timestamp, order.user_id,
            ])

    for order in old_orders:
        await db.delete(order)
    await db.flush()

    logger.info(f"Archived {len(old_orders)} orders to {csv_path}")
    return {"archived": len(old_orders)}


async def run_weekly_archive(db: AsyncSession) -> dict[str, Any]:
    conv_result = await archive_conversations(db)
    order_result = await archive_orders(db)
    await db.commit()
    return {
        "conversations": conv_result,
        "orders": order_result,
        "archived_at": datetime.utcnow().isoformat(),
    }


from typing import Any
