import asyncio
import logging
import os
from typing import Any, Optional

from config import Config

logger = logging.getLogger(__name__)


class DiscoveryEngineClient:
    def __init__(self):
        self._client_search = None
        self._client_doc = None
        self._client_datastore = None
        self._ready = False

    async def start(self) -> bool:
        if not Config.AGENT_BUILDER_DATA_STORE:
            logger.info("AGENT_BUILDER_DATA_STORE not set, skipping Discovery Engine")
            return False

        creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
        if not creds_path or not os.path.isfile(creds_path):
            logger.warning("GOOGLE_APPLICATION_CREDENTIALS not found: %s", creds_path)
            return False

        try:
            from google.cloud.discoveryengine import SearchServiceClient
            from google.cloud.discoveryengine import DocumentServiceClient
            from google.cloud.discoveryengine import DataStoreServiceClient

            self._client_search = SearchServiceClient()
            self._client_doc = DocumentServiceClient()
            self._client_datastore = DataStoreServiceClient()
            self._ready = True
            logger.info(
                "Discovery Engine client ready (project=%s, location=%s, store=%s)",
                Config.GOOGLE_CLOUD_PROJECT,
                Config.AGENT_BUILDER_LOCATION,
                Config.AGENT_BUILDER_DATA_STORE,
            )
            return True
        except ImportError:
            logger.warning("google-cloud-discoveryengine not installed, skipping")
        except Exception as e:
            logger.warning("Failed to initialize Discovery Engine: %s", e)
        return False

    async def close(self):
        self._client_search = None
        self._client_doc = None
        self._client_datastore = None
        self._ready = False
        logger.info("Discovery Engine client stopped")

    @property
    def configured(self) -> bool:
        return self._ready

    def _base_path(self) -> str:
        return (
            f"projects/{Config.GOOGLE_CLOUD_PROJECT}"
            f"/locations/{Config.AGENT_BUILDER_LOCATION}"
            f"/collections/default_collection"
        )

    @property
    def serving_config(self) -> Optional[str]:
        if not self._ready:
            return None
        return (
            f"{self._base_path()}"
            f"/dataStores/{Config.AGENT_BUILDER_DATA_STORE}"
            f"/servingConfigs/default_search"
        )

    async def search(self, query: str, page_size: int = 5) -> list[dict[str, Any]]:
        if not self._ready:
            return []
        try:
            from google.cloud.discoveryengine import SearchRequest

            request = SearchRequest(
                serving_config=self.serving_config,
                query=query,
                page_size=page_size,
                query_expansion_spec=SearchRequest.QueryExpansionSpec(
                    condition=SearchRequest.QueryExpansionSpec.Condition.AUTO,
                ),
                spell_correction_spec=SearchRequest.SpellCorrectionSpec(
                    mode=SearchRequest.SpellCorrectionSpec.Mode.AUTO,
                ),
            )
            response = await asyncio.to_thread(self._client_search.search, request)
            results = []
            for r in response.results:
                doc = r.document
                data = {"id": doc.id, "title": doc.name}
                if doc.json_data:
                    data["data"] = {
                        k: v for k, v in doc.json_data.items() if not k.startswith("_")
                    }
                elif doc.struct_data:
                    data["data"] = dict(doc.struct_data)
                snippet = ""
                if r.model_snippet_info and r.model_snippet_info.answers:
                    snippet = r.model_snippet_info.answers[0].answer
                data["snippet"] = snippet
                results.append(data)
            return results
        except Exception as e:
            logger.warning("Discovery Engine search failed: %s", e)
            return []

    async def ensure_data_store(self, data_store_id: str, display_name: str = "Tell5 Knowledge Base") -> bool:
        if not self._client_datastore:
            return False
        try:
            from google.cloud.discoveryengine import CreateDataStoreRequest, DataStore
            from google.cloud.discoveryengine import SolutionType

            request = CreateDataStoreRequest(
                parent=self._base_path(),
                data_store=DataStore(
                    display_name=display_name,
                    industry_vertical="GENERIC",
                    solution_types=[SolutionType.SOLUTION_TYPE_SEARCH],
                ),
                data_store_id=data_store_id,
            )
            operation = await asyncio.to_thread(self._client_datastore.create_data_store, request)
            await asyncio.to_thread(operation.result, timeout=120)
            logger.info("Created Discovery Engine data store: %s", data_store_id)
            return True
        except Exception as e:
            if "already exists" in str(e).lower():
                logger.info("Data store already exists: %s", data_store_id)
                return True
            logger.warning("Failed to create data store: %s", e)
            return False

    async def index_document(self, doc_id: str, json_data: dict[str, Any]) -> bool:
        if not self._client_doc:
            return False
        try:
            from google.cloud.discoveryengine import Document

            parent = (
                f"{self._base_path()}"
                f"/dataStores/{Config.AGENT_BUILDER_DATA_STORE}"
                f"/branches/0"
            )
            document = Document(
                id=doc_id,
                json_data=json_data,
            )
            await asyncio.to_thread(
                self._client_doc.create_document,
                parent=parent,
                document=document,
                document_id=doc_id,
            )
            logger.info("Indexed document %s in Discovery Engine", doc_id)
            return True
        except Exception as e:
            logger.warning("Failed to index document %s: %s", doc_id, e)
            return False

    async def delete_document(self, doc_id: str) -> bool:
        if not self._client_doc:
            return False
        try:
            name = (
                f"{self._base_path()}"
                f"/dataStores/{Config.AGENT_BUILDER_DATA_STORE}"
                f"/branches/0/documents/{doc_id}"
            )
            await asyncio.to_thread(self._client_doc.delete_document, name=name)
            logger.info("Deleted document %s from Discovery Engine", doc_id)
            return True
        except Exception as e:
            logger.warning("Failed to delete document %s: %s", doc_id, e)
            return False


_client: Optional[DiscoveryEngineClient] = None


def get_client() -> Optional[DiscoveryEngineClient]:
    return _client


def set_client(client: DiscoveryEngineClient) -> None:
    global _client
    _client = client


async def search_knowledge(query: str, page_size: int = 5) -> list[dict[str, Any]]:
    if not _client:
        return []
    return await _client.search(query, page_size=page_size)


async def sync_business_profile_to_discovery(
    profile_id: int,
    business_name: str,
    description: str | None = None,
    category: str | None = None,
    address: str | None = None,
    products: list[dict[str, Any]] | None = None,
) -> bool:
    if not _client or not _client.configured:
        return False
    doc_id = f"business-{profile_id}"
    data = {
        "_type": "business_profile",
        "business_name": business_name,
        "description": description or "",
        "category": category or "",
        "address": address or "",
        "products": products or [],
    }
    return await _client.index_document(doc_id, data)


async def sync_product_to_discovery(
    product_id: int,
    business_id: int,
    name: str,
    description: str | None = None,
    price: float | None = None,
    currency: str = "NGN",
) -> bool:
    if not _client or not _client.configured:
        return False
    doc_id = f"product-{product_id}"
    data = {
        "_type": "product",
        "business_id": business_id,
        "name": name,
        "description": description or "",
        "price": price or 0,
        "currency": currency,
    }
    return await _client.index_document(doc_id, data)
