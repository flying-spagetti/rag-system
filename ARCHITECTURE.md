# Repository structure

```text
Rag-agent/                                                     # Project root
├── alembic/                                                   # Database migration configuration and revisions
│   ├── versions/                                              # Versioned database schema migrations
│   │   ├── 20261114_0001_initial.py                           # Initial schema migration
│   │   └── 87cb71f716d8_refine_legal_ontology_and_provenance.py # Legal schema and provenance updates
│   ├── env.py                                                 # Alembic runtime configuration
│   └── script.py.mako                                         # Template for new migration scripts
├── config/                                                    # Static application configuration
│   └── models.yaml                                           # Model-role configuration
├── src/                                                       # Python source tree
│   └── regrag/                                                # Regrag application package
│       ├── db/                                                # Database models and helpers
│       │   ├── __init__.py                                    # Database package exports
│       │   ├── models.py                                      # SQLAlchemy models, constraints, and indexes
│       │   ├── normalization.py                               # Identifier and URL normalization
│       │   └── rollback.py                                    # Run-aware rollback operations
│       ├── __init__.py                                        # Application package entry point
│       └── settings.py                                        # Environment-based application settings
├── tests/                                                     # Automated tests
│   └── test_db_models.py                                      # Database constraints, rollback, and migration tests
├── .env.example                                               # Example local environment variables
├── .gitignore                                                 # Files excluded from version control
├── .python-version                                            # Project Python version
├── alembic.ini                                                # Alembic command-line configuration
├── ARCHITECTURE.md                                            # This repository structure map
├── compose.yaml                                               # Local PostgreSQL/pgvector and Redis services
├── pyproject.toml                                             # Project metadata, dependencies, and tool configuration
├── README.md                                                  # Setup and development instructions
├── ROADMAP.md                                                 # Architecture and schema decisions
└── uv.lock                                                    # Locked Python dependency versions
```
