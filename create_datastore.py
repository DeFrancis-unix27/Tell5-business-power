"""Create Discovery Engine data store using Python SDK."""
import os, sys, time
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.path.abspath("json/tell5_key.json")

from google.cloud.discoveryengine import DataStoreServiceClient, CreateDataStoreRequest, DataStore
from google.cloud.discoveryengine import SolutionType

project = "project-d12aeb41-c158-4039-af8"
store_id = "tell5-knowledge-store"
parent = f"projects/{project}/locations/global"

client = DataStoreServiceClient()
request = CreateDataStoreRequest(
    parent=parent,
    data_store=DataStore(
        display_name="Tell5 Knowledge Base",
        industry_vertical="GENERIC",
        solution_types=[SolutionType.SOLUTION_TYPE_SEARCH],
    ),
    data_store_id=store_id,
)

for attempt in range(3):
    try:
        operation = client.create_data_store(request)
        result = operation.result(timeout=120)
        print(f"SUCCESS: Data store created. ID = {store_id}")
        print(f"\nSet in .env:\nAGENT_BUILDER_DATA_STORE={store_id}")
        sys.exit(0)
    except Exception as e:
        err = str(e)
        if "already exists" in err.lower():
            print(f"ALREADY EXISTS: {store_id}")
            sys.exit(0)
        if attempt < 2:
            print(f"Attempt {attempt+1} failed: {err[:100]}... retrying in 3s")
            time.sleep(3)
        else:
            print(f"FAILED after 3 attempts: {err}")
            sys.exit(1)
