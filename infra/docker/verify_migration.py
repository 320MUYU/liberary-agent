"""Run in the API container with the source manifest on stdin, before acceptance writes."""

import json
import sys

sys.path.insert(0, "/app")

from app.database import engine
from app.services.vector_store import NativeChromaHttpClient
from app.config import settings
from migrate import table_counts


def main():
    manifest = json.load(sys.stdin)
    actual = table_counts(engine)
    if actual != manifest["tables"]:
        raise RuntimeError("MySQL table counts differ from the source snapshot")
    client = NativeChromaHttpClient(host=settings.CHROMA_HOST, port=settings.CHROMA_PORT)
    collections = client._request("GET", client.path)
    vectors = {item["name"]: client.get_collection(item["name"]).count() for item in collections}
    if vectors != manifest["chroma"]:
        raise RuntimeError("Chroma collection counts differ from the source snapshot")
    print(json.dumps({"passed": True, "tables": len(actual), "rows": sum(actual.values()),
        "collections": len(vectors), "vectors": sum(vectors.values()),
        "files_verified_during_restore": sum(len(value) for value in manifest["files"].values())}))


if __name__ == "__main__":
    main()
