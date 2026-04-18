-- Runs once on a fresh Postgres data volume (docker-entrypoint-initdb.d).
-- Enables the pgvector extension so VECTOR(...) columns can be created by Alembic.
CREATE EXTENSION IF NOT EXISTS vector;
