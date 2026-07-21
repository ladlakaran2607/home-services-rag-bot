# Setup

## Prerequisites

- Docker Desktop (Qdrant, Postgres, NocoDB run as containers)
- uv (Python toolchain; project pins its own Python)
- An OpenAI API key; a free Langfuse cloud account (optional but wired in)

## 1. Dependencies

```
uv sync
```

## 2. Environment

Create `.env` in the repo root:

```
OPENAI_API_KEY=sk-...
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com
DATABASE_URL=postgresql://summit:summit@localhost:5433/summit_crm
CHECKPOINT_DATABASE_URL=postgresql://summit:summit@localhost:5433/summit_graph
```

`.env` is gitignored. Without DATABASE_URL the CRM falls back to an
in-memory mock (fine for tests, nothing visible in the GUI).

## 3. Containers

```
docker run -d --name qdrant -p 6333:6333 -v qdrant_storage:/qdrant/storage qdrant/qdrant
docker compose up -d
docker exec summit-pg psql -U summit -d summit_crm -c "CREATE DATABASE summit_graph;"
```

The compose file boots Postgres (schema auto-applies from db/schema.sql on
first boot) and NocoDB. The CREATE DATABASE runs once, for checkpoints.

## 4. NocoDB (the CRM GUI, one-time)

Open localhost:8080, create the admin account, create a base, choose
Connect External Data → PostgreSQL: host `postgres`, port `5432`, user and
password `summit`, database `summit_crm`, schema `public`, SSL off. The
contacts and appointments grids appear. Two gotchas are pre-solved in the
compose file and worth knowing: NocoDB connects via the Docker-internal
hostname (not localhost:5433), and NC_ALLOW_LOCAL_EXTERNAL_DBS=true is set
because NocoDB's SSRF guard otherwise blocks private-network databases.

## 5. Ingest the knowledge base

```
uv run python ingest.py
```

Rebuilds the Qdrant collection from knowledge-base/ (seconds; run again after
any doc edit). Ends with retrieval verification checks; expect all
water-heaters hits on the filtered query.

## 6. Run

```
uv run uvicorn app.main:app          # the console, at http://localhost:8000
uv run python chat_v2.py             # or: terminal chat with the v2 graph
uv run python -m bot.router          # node smoke tests (also bot.retrieve, bot.answer)
uv run python run_baseline.py        # replay scripted conversations against v1
```

In the console: v1/v2 toggle keeps two separate conversations, the right
panel shows each turn's pipeline live, the CRM tab reads Postgres, Compare
summarizes both sessions once each has at least one turn.

## Resets

```
# demo data (contacts + appointments), keeps schema:
docker exec summit-pg psql -U summit -d summit_crm -c "TRUNCATE appointments, contacts RESTART IDENTITY CASCADE;"

# conversation checkpoints:
docker exec summit-pg psql -U summit -c "DROP DATABASE summit_graph;" && \
docker exec summit-pg psql -U summit -c "CREATE DATABASE summit_graph;"

# everything including CRM schema (re-runs schema.sql on next up):
docker compose down -v && docker compose up -d
```
