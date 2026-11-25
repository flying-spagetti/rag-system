What you write in this phase, in order

1. Scaffold (1 day)

Build: a uv project, Docker Compose with Postgres (pgvector image) and Redis, Alembic wired to your models.
Decide: config via environment variables, and where src/regrag/ modules live (use the layout from the roadmap).
Done when: docker compose up works and alembic upgrade head runs on an empty database.

2. Schema (1 to 2 days)

Build: the Core tier from your own ontology: works, work_identifiers, versions, files, provisions, relations, extraction_evidence, applicability, ingestion_runs.
Decide first:
Relation targets: will an edge always point at a Work (so stubs work), with optional narrowing to a version or provision key?
Where do amendment operations (action, old and new text) live?
How does a run roll back its own rows?
Which dates are legal time and which are system time?
Done when: you can insert a fixture for each acceptance criterion on your list, and the constraints reject bad data.

3. Read the documents (3 to 4 days, no code)

Build: the manifest CSV, and a notes file with real phrases, numbering styles, and amendment layouts from 10 to 15 documents.
Decide: the stable-key scheme for provisions. Settle it here, because your gold edges depend on it.
Done when: you can write down the key for any paragraph you pick, and ontology v1.0 is frozen.

4. Fetch and identity (3 days)

Build: a fetcher that hashes, uploads to R2, and creates the work, identifier, version, and file rows.
Decide: what counts as "the same document" (identifier match, content hash, or both), and what happens on a conflict.
Done when: running it twice changes nothing.

5. Parse to provisions (5 to 6 days, the hard one)

Build: PDF to a clause tree with heading paths, page numbers, and a quality score.
Decide: how you detect numbering levels, and what you do with tables.
Done when: a 20-page hand check gives you an error rate you can report.

6. Gold graph (3 days)

Build: about 50 hand-entered relations with exact evidence quotes, including at least one stub.
Done when: every quote is an exact substring of its source.

7. Rules extractor and validator (4 days)

Build: phrase detection, context extraction, and validation, with no LLM.
Done when: you can report precision and recall against your gold graph per relation type.

8. Verify (2 to 3 days)

Build: one test per acceptance criterion, and the five demo queries from my last message.
Done when: all of them pass on real data.