"""Quick semantic search test for the indexed codebase."""

import os
from qdrant_client import QdrantClient
from fastembed import TextEmbedding

client = QdrantClient(
    url="https://b5412748-1bf2-4a06-9a94-5ebf25ac2d5f.eu-west-2-0.aws.cloud.qdrant.io",
    api_key=os.getenv("QDRANT_API_KEY", ""),
)

model = TextEmbedding(model_name="sentence-transformers/all-MiniLM-L6-v2")
query = "email authentication and user login"
embedding = list(model.embed([query]))[0]

results = client.query_points(
    collection_name="symbolic-bovid-aqua", query=embedding.tolist(), limit=5
).points

print(f"Query: {query}")
print("=" * 50)
for r in results:
    path = r.payload["file_path"]
    print(f"{r.score:.3f} - {path}")
