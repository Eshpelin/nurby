-- Enable the pgvector extension on a fresh Postgres data volume.
--
-- The official Postgres image runs every .sql file in
-- /docker-entrypoint-initdb.d exactly once, the first time the data
-- directory is initialized. Creating the extension here means vector
-- columns work out of the box on a brand-new install, before any
-- migration that uses the vector type runs.
--
-- Idempotent. safe to keep even if the extension already exists.
CREATE EXTENSION IF NOT EXISTS vector;
