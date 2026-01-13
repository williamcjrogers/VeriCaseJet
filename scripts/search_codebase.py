"""Quick semantic search test for the indexed codebase."""

import os
from qdrant_client import QdrantClient
from fastembed import TextEmbedding

QDRANT_URL = os.getenv(
    "QDRANT_URL",
    "https://b5412748-1bf2-4a06-9a94-5ebf25ac2d5f.eu-west-2-0.aws.cloud.qdrant.io",
)
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")

client = QdrantClient(
    url=QDRANT_URL,
    api_key=QDRANT_API_KEY,
)

# Debug logging
print(f"DEBUG: Qdrant URL: {QDRANT_URL}")
print(f"DEBUG: Qdrant API Key present: {bool(QDRANT_API_KEY)}")
if QDRANT_API_KEY:
    print(f"DEBUG: Qdrant API Key length: {len(QDRANT_API_KEY)}")
else:
    print("DEBUG: Qdrant API Key is MISSING")

model = TextEmbedding(model_name="sentence-transformers/all-MiniLM-L6-v2")
query = "email authentication and user login"
embedding = list(model.embed([query]))[0]

results = client.query_points(
    collection_name="symbolic-bovid-aqua", query=embedding.tolist(), limit=5
).points

print(f"Query: {query}")
print("=" * 50)
for r in results:
    if r.payload:
        path = r.payload.get("file_path", "Unknown")
        print(f"{r.score:.3f} - {path}")
    else:
        print(f"{r.score:.3f} - [No Payload]")
