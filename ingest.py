"""Ingest the knowledge base into Qdrant.

Full-rebuild strategy: every run drops the collection and re-ingests
everything under knowledge-base/. The markdown files are the source of
truth; Qdrant only ever holds a derived copy of them.

Run with:  uv run python ingest.py
"""

import uuid
from pathlib import Path

import yaml
from fastembed import TextEmbedding
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

KB_DIR = Path("knowledge-base")
COLLECTION = "home_services_kb"
MODEL_NAME = "BAAI/bge-small-en-v1.5"
VECTOR_SIZE = 384  # bge-small-en-v1.5 produces 384-dimensional vectors
MAX_CHUNK_CHARS = 1200  # ~300 tokens; sections longer than this get subsplit


def load_docs() -> list[dict]:
    """Read every markdown file and split YAML frontmatter from the body."""
    docs = []
    for path in sorted(KB_DIR.rglob("*.md")):
        raw = path.read_text(encoding="utf-8")
        _, front, body = raw.split("---", 2)
        meta = yaml.safe_load(front)
        docs.append({"meta": meta, "body": body.strip(), "source": path.name})
    return docs


def split_long(text: str) -> list[str]:
    """Split an oversized section on paragraph breaks into <= MAX_CHUNK_CHARS pieces."""
    pieces, current = [], ""
    for para in text.split("\n\n"):
        if current and len(current) + len(para) > MAX_CHUNK_CHARS:
            pieces.append(current.strip())
            current = ""
        current += para + "\n\n"
    if current.strip():
        pieces.append(current.strip())
    return pieces


def chunk_doc(doc: dict) -> list[dict]:
    """Split one doc into chunks: one per '## ' section, subsplit if long.

    Each chunk's text gets the doc title + section heading prepended, so a
    chunk still makes sense on its own when retrieved out of context.
    """
    meta = doc["meta"]
    title = meta["service_name"]
    chunks = []
    for section in doc["body"].split("\n## "):
        heading, _, text = section.partition("\n")
        heading = heading.lstrip("# ").strip()
        text = text.strip()
        if not text:
            continue
        pieces = split_long(text) if len(text) > MAX_CHUNK_CHARS else [text]
        for piece in pieces:
            chunks.append(
                {
                    "text": f"{title} | {heading}:\n{piece}",
                    "payload": {
                        "service_line": meta["service_line"],
                        "section": heading,
                        "source": doc["source"],
                    },
                }
            )
    return chunks


def rebuild_collection(client: QdrantClient) -> None:
    """Drop and recreate the collection, with a keyword index on service_line."""
    if client.collection_exists(COLLECTION):
        client.delete_collection(COLLECTION)
    client.create_collection(
        collection_name=COLLECTION,
        vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
    )
    client.create_payload_index(
        collection_name=COLLECTION,
        field_name="service_line",
        field_schema="keyword",
    )


def verify(client: QdrantClient, model: TextEmbedding) -> None:
    """The three P0 acceptance checks, printed for eyeballing."""
    print("\n-- verify 1: filtered search (service_line=water-heaters) --")
    qvec = list(model.query_embed("how much does a tankless water heater cost"))[0]
    hits = client.query_points(
        collection_name=COLLECTION,
        query=qvec.tolist(),
        limit=4,
        query_filter=Filter(
            must=[FieldCondition(key="service_line", match=MatchValue(value="water-heaters"))]
        ),
    ).points
    for h in hits:
        print(f"  {h.score:.3f}  {h.payload['service_line']:<14} {h.payload['section']}")

    print("\n-- verify 2: unfiltered search ('my sink is leaking') --")
    qvec = list(model.query_embed("my sink is leaking, can you help"))[0]
    hits = client.query_points(collection_name=COLLECTION, query=qvec.tolist(), limit=4).points
    for h in hits:
        print(f"  {h.score:.3f}  {h.payload['service_line']:<14} {h.payload['section']}")


def main() -> None:
    client = QdrantClient(url="http://localhost:6333")
    model = TextEmbedding(model_name=MODEL_NAME)

    docs = load_docs()
    chunks = [c for d in docs for c in chunk_doc(d)]
    print(f"{len(docs)} docs -> {len(chunks)} chunks")

    vectors = list(model.passage_embed([c["text"] for c in chunks]))

    rebuild_collection(client)
    points = [
        PointStruct(
            id=str(uuid.uuid4()),
            vector=vec.tolist(),
            payload={**chunk["payload"], "text": chunk["text"]},
        )
        for chunk, vec in zip(chunks, vectors)
    ]
    client.upsert(collection_name=COLLECTION, points=points)

    counts: dict[str, int] = {}
    for c in chunks:
        counts[c["payload"]["service_line"]] = counts.get(c["payload"]["service_line"], 0) + 1
    for service_line, n in sorted(counts.items()):
        print(f"  {service_line:<14} {n} chunks")

    verify(client, model)


if __name__ == "__main__":
    main()
