## Project layout and configuration decisions

- Runtime configuration and secrets come from environment variables, loaded from
  an optional local `.env` file by `src/regrag/settings.py`. Compose environment
  variables can override the local defaults. `.env.example` documents the
  development settings; do not commit `.env`.
- `config/models.yaml` is reserved for non-secret model-role-to-backend mapping.
- Application code lives under `src/regrag/`, with each roadmap area as a
  package: `api/`, `workers/`, `db/`, `ingest/`, `lifecycle/`, `retrieval/`,
  `generation/`, `llm/`, and `evals/`. The `db/` package owns SQLAlchemy models
  and database access; Alembic revision scripts live at the repository-level
  `alembic/` directory.
- Evaluation fixtures live in `data/eval/`; tests and documentation live in
  the top-level `tests/` and `docs/` directories.

The initial database schema models works, their versions, and the files
associated with each version. Embeddings are deferred to retrieval; when added,
each embedding record should include its model name, model version, and vector
dimension so multiple indexes can coexist. The initial migration enables the
pgvector extension but does not create embedding columns.

Schema decisions:

- Legal dates (`effective_from`, `effective_to`, `issued_on`, `published_on`,
  and `consolidated_up_to`) are SQL `DATE`; effective date ranges are checked.
- Ordinary versions require a `version_label`; a consolidated version may omit
  it and records `is_consolidated = true`. Version status is constrained to
  `active`, `superseded`, or `withdrawn`.
- Works have constrained instrument type, authority tier, legal force, and
  resolution status fields. A stub may omit its title; source-specific,
  non-filtered extras use mutable JSONB.
- Instrument identifiers are separate rows with globally unique `(scheme,
  value)` pairs. URLs can be identifiers; the removed `external_id` field is
  not used.
- Files are immutable content-addressed records with a required unique SHA-256.
  Their storage key is derived from the hash. `version_files` permits reuse
  across versions and records the run that created each link.
- Ingestion-derived rows carry a `created_run_id`; deleting a run is restricted
  so rollback is an explicit, auditable operation rather than accidental
  cascade deletion. Rollback marks the run `rolled_back`; it removes that run's
  associations and unreferenced artifacts, but preserves shared files and
  identity works while later-run rows still reference them. Parent deletion is
  restricted by foreign keys rather than cascading into later-run data.