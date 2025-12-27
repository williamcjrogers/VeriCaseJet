"""
Index VeriCase codebase into Qdrant for semantic search.
Uses Fastembed for local embeddings (384 dimensions).
"""

import hashlib
import os
from pathlib import Path
from typing import Generator

from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct
from fastembed import TextEmbedding

# Configuration
QDRANT_URL = (
    "https://b5412748-1bf2-4a06-9a94-5ebf25ac2d5f.eu-west-2-0.aws.cloud.qdrant.io"
)
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
COLLECTION_NAME = "symbolic-bovid-aqua"
PROJECT_ROOT = Path(__file__).parent.parent

# File patterns to index
INCLUDE_PATTERNS = ["*.py", "*.js", "*.ts", "*.html", "*.css", "*.md"]
EXCLUDE_DIRS = {
    "node_modules",
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".next",
    "Deep Research",
    "assets/fontawesome",
}
EXCLUDE_FILES = {"*.min.js", "*.min.css", "*.map"}

# Chunking settings
CHUNK_SIZE = 1000  # characters
CHUNK_OVERLAP = 200


def should_index_file(path: Path) -> bool:
    """Check if file should be indexed."""
    # Check excluded directories
    for part in path.parts:
        if part in EXCLUDE_DIRS:
            return False

    # Check excluded file patterns
    name = path.name
    if name.endswith(".min.js") or name.endswith(".min.css"):
        return False

    # Check if matches include patterns
    for pattern in INCLUDE_PATTERNS:
        if path.match(pattern):
            return True
    return False


def chunk_text(
    text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP
) -> list[str]:
    """Split text into overlapping chunks."""
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]

        # Try to break at newline if possible
        if end < len(text):
            last_newline = chunk.rfind("\n")
            if last_newline > chunk_size // 2:
                chunk = chunk[:last_newline]
                end = start + last_newline

        chunks.append(chunk)
        start = end - overlap

    return chunks


def get_files_to_index() -> Generator[Path, None, None]:
    """Get all files that should be indexed."""
    vericase_dir = PROJECT_ROOT / "vericase"

    for pattern in INCLUDE_PATTERNS:
        for file_path in vericase_dir.rglob(pattern):
            if should_index_file(file_path):
                yield file_path


def generate_point_id(file_path: str, chunk_index: int) -> int:
    """Generate a deterministic point ID from file path and chunk index."""
    content = f"{file_path}:{chunk_index}"
    hash_bytes = hashlib.md5(content.encode()).digest()
    # Use first 8 bytes as unsigned int
    return int.from_bytes(hash_bytes[:8], byteorder="big") & 0x7FFFFFFFFFFFFFFF


def main():
    print("=" * 60)
    print("VeriCase Codebase Indexer")
    print("=" * 60)

    # Initialize Qdrant client
    print("\nConnecting to Qdrant...")
    client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)

    # Verify collection exists
    try:
        info = client.get_collection(COLLECTION_NAME)
        print(f"Collection '{COLLECTION_NAME}' found (vectors: {info.points_count})")
    except Exception as e:
        print(f"Error: Collection not found - {e}")
        return

    # Initialize embedding model
    print("\nLoading embedding model (first run downloads ~90MB)...")
    embedding_model = TextEmbedding(model_name="sentence-transformers/all-MiniLM-L6-v2")

    # Collect files
    print("\nScanning for files...")
    files = list(get_files_to_index())
    print(f"Found {len(files)} files to index")

    # Process files
    points = []
    total_chunks = 0

    for i, file_path in enumerate(files):
        try:
            relative_path = file_path.relative_to(PROJECT_ROOT)
            content = file_path.read_text(encoding="utf-8", errors="ignore")

            if not content.strip():
                continue

            chunks = chunk_text(content)

            for chunk_idx, chunk in enumerate(chunks):
                # Generate embedding
                embedding = list(embedding_model.embed([chunk]))[0]

                # Create point
                point_id = generate_point_id(str(relative_path), chunk_idx)
                points.append(
                    PointStruct(
                        id=point_id,
                        vector=embedding.tolist(),
                        payload={
                            "file_path": str(relative_path),
                            "chunk_index": chunk_idx,
                            "total_chunks": len(chunks),
                            "content": chunk[:500],  # Store preview
                            "file_type": file_path.suffix,
                        },
                    )
                )
                total_chunks += 1

            if (i + 1) % 10 == 0:
                print(f"  Processed {i + 1}/{len(files)} files ({total_chunks} chunks)")

        except Exception as e:
            print(f"  Error processing {file_path}: {e}")

    # Upload to Qdrant in batches
    print(f"\nUploading {len(points)} vectors to Qdrant...")
    batch_size = 100
    for i in range(0, len(points), batch_size):
        batch = points[i : i + batch_size]
        client.upsert(collection_name=COLLECTION_NAME, points=batch)
        print(f"  Uploaded {min(i + batch_size, len(points))}/{len(points)}")

    # Final stats
    info = client.get_collection(COLLECTION_NAME)
    print("\n" + "=" * 60)
    print("Indexing complete!")
    print(f"  Files indexed: {len(files)}")
    print(f"  Total vectors: {info.points_count}")
    print("=" * 60)


if __name__ == "__main__":
    main()
