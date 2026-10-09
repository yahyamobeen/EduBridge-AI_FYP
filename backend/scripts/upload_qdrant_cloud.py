"""Upload ColQwen2 Visual Page Embeddings to Qdrant Cloud.

Creates collection 'physics9_visual_pages' with MultiVector MaxSim comparator
and indexes all 200 Class 9 Physics textbook pages with metadata.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import torch
from qdrant_client import QdrantClient
from qdrant_client.http import models

# Windows UTF-8 console output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Configuration
QDRANT_URL = os.environ.get(
    "QDRANT_URL",
    "https://e6653eb2-fef0-4864-a1ae-1a6d43f27039.eu-west-2-0.aws.cloud.qdrant.io",
)
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY", "")
COLLECTION_NAME = os.environ.get("QDRANT_COLLECTION", "physics9_visual_pages")
VECTOR_DIM = 128

EMBEDDINGS_PATH = Path(
    os.environ.get(
        "PHYSICS_EMBEDDINGS_PATH",
        r"C:\Users\Mujtaba\Desktop\FYP_Folder\edubridge-chatbot-SEND-THIS\colqwen2\pages.colqwen2.pt",
    )
)

# Chapter mappings from official PCTB Class 9 Physics contents
CHAPTERS: dict[int, tuple[int, int]] = {
    1: (5, 27),
    2: (28, 51),
    3: (52, 79),
    4: (80, 104),
    5: (105, 126),
    6: (127, 147),
    7: (148, 160),
    8: (161, 180),
    9: (181, 193),
}


def get_chapter(page_num: int) -> int | None:
    for ch, (lo, hi) in CHAPTERS.items():
        if lo <= page_num <= hi:
            return ch
    return None


def main() -> None:
    t0 = time.time()
    print("==================================================")
    print(" EduBridge AI: Upload Visual Embeddings to Qdrant ")
    print("==================================================")

    if not EMBEDDINGS_PATH.exists():
        print(f"ERROR: Embeddings file not found at: {EMBEDDINGS_PATH}")
        sys.exit(1)

    print(f"Connecting to Qdrant Cloud at:\n  {QDRANT_URL}")
    client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, timeout=60.0)

    print(f"\nLoading PyTorch embeddings from:\n  {EMBEDDINGS_PATH}")
    store = torch.load(EMBEDDINGS_PATH, map_location="cpu", weights_only=False)

    pages = store.get("pages", [])
    embeddings = store.get("embeddings", [])
    checkpoint = store.get("checkpoint", "vidore/colqwen2-v1.0")
    dim = store.get("dim", VECTOR_DIM)

    print(f"  Pages loaded:    {len(pages)} (Page {min(pages)} to {max(pages)})")
    print(f"  Vector dim:      {dim}")
    print(f"  Model checkpoint: {checkpoint}")

    if len(pages) != len(embeddings):
        print(f"ERROR: Page count ({len(pages)}) does not match embeddings ({len(embeddings)})")
        sys.exit(1)

    print(f"\nConfiguring Collection '{COLLECTION_NAME}' with Multi-Vector MaxSim...")
    # Recreate collection to guarantee clean state
    client.recreate_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=models.VectorParams(
            size=VECTOR_DIM,
            distance=models.Distance.COSINE,
            multivector_config=models.MultiVectorConfig(
                comparator=models.MultiVectorComparator.MAX_SIM
            ),
        ),
    )
    print("Collection created successfully.")

    # Batch upload
    BATCH_SIZE = 10
    total_pages = len(pages)
    points_buffer: list[models.PointStruct] = []

    print(f"\nUploading {total_pages} pages in batches of {BATCH_SIZE}...")
    for idx, (page_num, tensor) in enumerate(zip(pages, embeddings, strict=True), start=1):
        # Convert tensor to float32 list of lists (shape: [num_patches, 128])
        vector_matrix = tensor.to(torch.float32).cpu().tolist()

        point = models.PointStruct(
            id=int(page_num),
            vector=vector_matrix,
            payload={
                "page": int(page_num),
                "chapter": get_chapter(page_num),
                "checkpoint": checkpoint,
                "filename": f"p{page_num:03d}.jpeg",
                "num_patches": len(vector_matrix),
            },
        )
        points_buffer.append(point)

        if len(points_buffer) >= BATCH_SIZE:
            client.upsert(collection_name=COLLECTION_NAME, points=points_buffer)
            print(f"  [✓] Indexed {idx}/{total_pages} pages (latest: Page {page_num})")
            points_buffer = []

    # Upload remaining
    if points_buffer:
        client.upsert(collection_name=COLLECTION_NAME, points=points_buffer)
        print(f"  [✓] Indexed {total_pages}/{total_pages} pages")

    print("\n--------------------------------------------------")
    print("Verifying collection in Qdrant Cloud...")
    info = client.get_collection(COLLECTION_NAME)
    print(f"  Collection Status: {info.status}")
    print(f"  Points Count:      {info.points_count}")
    print(f"  Indexed Vectors:   {info.indexed_vectors_count}")
    print(f"Total time taken:   {round(time.time() - t0, 2)}s")
    print("==================================================")
    print("All visual embeddings successfully uploaded to Qdrant Cloud!")


if __name__ == "__main__":
    main()
