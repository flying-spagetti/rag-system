# regrag

## Local development

Requirements: Python 3.12+, [`uv`](https://docs.astral.sh/uv/), and Docker
Compose.

```sh
cp .env.example .env
uv sync
docker compose up -d --wait
uv run alembic upgrade head
```

The Compose stack starts PostgreSQL with the pgvector extension available and
Redis. Alembic enables the `vector` extension and creates `works`, `versions`,
`identifiers`, `runs`, content-addressed `files`, and the `version_files`
association table. Embedding columns are deferred until the retrieval phase,
when the embedding model, version, and dimension can be stored alongside each
embedding.

Versions use calendar `Date` columns for legal dates. A missing version label is
allowed only for consolidated versions. File hashes are unique; `files` stores
the content once and `version_files` links it to one or more versions. The
link's run id records when that association was created.

Use `regrag.db.rollback.rollback_run(session, run_id)` to roll back a completed
run inside a caller-managed transaction. The run is retained with
`status='rolled_back'` for provenance. Rows created by other runs are never
cascade-deleted: shared files and works referenced by later-run rows remain
until those references are rolled back. Unreferenced rows owned by rolled-back
runs are cleaned up. Foreign keys restrict direct deletes as a final safeguard.

Runtime settings are environment variables (`DATABASE_URL` and `REDIS_URL`).
For local development, `src/regrag/settings.py` also reads the optional `.env`
file. Compose settings such as database credentials and published ports are
configurable through the variables in `.env.example`.

To stop the services while retaining local data:

```sh
docker compose down
```

Database constraint tests use isolated PostgreSQL schemas:

```sh
docker compose up -d --wait
uv run pytest
```
