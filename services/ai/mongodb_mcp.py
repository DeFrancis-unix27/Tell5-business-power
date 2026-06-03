import logging
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


class MongoDBProvider:
    """MongoDB data provider using the Motor async driver.

    Mirrors the MongoDB MCP server tool interface so the pipeline
    can interact with MongoDB as a partner data source. This is the
    production-level integration point for MongoDB as an MCP-compatible
    tool provider within the Tell5 agent architecture.

    Tool catalog (mirrors mongodb-mcp-server):
      - mongodb_find           Find documents in a collection
      - mongodb_insert_one     Insert a single document
      - mongodb_update_one     Update a single document
      - mongodb_delete_one     Delete a single document
      - mongodb_aggregate      Run an aggregation pipeline
      - mongodb_list_collections  List collections in a database
      - mongodb_run_command    Run a raw database command
    """

    def __init__(self, connection_string: str, db_name: str = "tell5", read_only: bool = False):
        self._connection_string = connection_string
        self._db_name = db_name
        self._read_only = read_only
        self._client: Optional[Any] = None
        self._ready = False

    async def start(self):
        from motor.motor_asyncio import AsyncIOMotorClient

        logger.info("Connecting to MongoDB: %s", self._connection_string[:30] + "...")
        self._client = AsyncIOMotorClient(
            self._connection_string,
            serverSelectionTimeoutMS=10000,
            connectTimeoutMS=10000,
        )
        # Verify connectivity
        await self._client.admin.command("ping")
        self._ready = True
        logger.info("MongoDB connected (db=%s, read_only=%s)", self._db_name, self._read_only)

    @property
    def is_ready(self) -> bool:
        return self._ready and self._client is not None

    @property
    def db(self):
        return self._client[self._db_name] if self._client else None

    # ------------------------------------------------------------------
    # Tool implementations (mirror mongodb-mcp-server tool interface)
    # ------------------------------------------------------------------

    async def find_documents(
        self,
        collection: str,
        filter: Optional[dict] = None,
        limit: int = 10,
        sort: Optional[list] = None,
        projection: Optional[dict] = None,
        database: Optional[str] = None,
    ) -> list[dict]:
        db = self._client[database] if database else self.db
        cursor = db[collection].find(filter or {}, projection=projection)
        if sort:
            cursor = cursor.sort(sort)
        cursor = cursor.limit(limit)
        return await cursor.to_list(length=limit)

    async def insert_one(self, collection: str, document: dict, database: Optional[str] = None) -> str:
        self._check_read_only()
        db = self._client[database] if database else self.db
        doc = dict(document)
        if "created_at" not in doc:
            doc["created_at"] = datetime.now(timezone.utc).isoformat()
        result = await db[collection].insert_one(doc)
        return str(result.inserted_id)

    async def update_one(
        self, collection: str, filter: dict, update: dict,
        database: Optional[str] = None,
    ) -> int:
        self._check_read_only()
        db = self._client[database] if database else self.db
        upd = dict(update)
        if "$set" in upd:
            upd["$set"] = {**upd["$set"], "updated_at": datetime.now(timezone.utc).isoformat()}
        elif "$set" not in upd and not any(k.startswith("$") for k in upd):
            upd = {"$set": {**upd, "updated_at": datetime.now(timezone.utc).isoformat()}}
        result = await db[collection].update_one(filter, upd)
        return result.modified_count

    async def delete_one(self, collection: str, filter: dict, database: Optional[str] = None) -> int:
        self._check_read_only()
        db = self._client[database] if database else self.db
        result = await db[collection].delete_one(filter)
        return result.deleted_count

    async def aggregate(self, collection: str, pipeline: list[dict], database: Optional[str] = None) -> list[dict]:
        db = self._client[database] if database else self.db
        cursor = db[collection].aggregate(pipeline)
        return await cursor.to_list(length=None)

    async def list_collections(self, database: Optional[str] = None) -> list[str]:
        db = self._client[database] if database else self.db
        return await db.list_collection_names()

    async def run_command(self, command: dict, database: str = "admin") -> dict:
        return await self._client[database].command(command)

    def _check_read_only(self):
        if self._read_only:
            raise PermissionError("MongoDB provider is in read-only mode")

    async def close(self):
        self._ready = False
        if self._client:
            self._client.close()
            logger.info("MongoDB connection closed")
