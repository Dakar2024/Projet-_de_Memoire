-- Schéma idempotent de la base vectorielle, rejoué à chaque démarrage ; mots de passe lus par \getenv.
\set ON_ERROR_STOP on
-- Instruction en échec jamais journalisée : elle pourrait contenir un mot de passe.
SET log_min_error_statement = panic;

\getenv indexer_password RAG_INDEXER_PASSWORD
\getenv reader_password RAG_READER_PASSWORD
-- Variable absente : erreur SQL volontaire (`\quit` terminerait psql en succès).
\if :{?indexer_password}
\else
  \echo 'RAG_INDEXER_PASSWORD absente'
  DO $$ BEGIN RAISE EXCEPTION 'RAG_INDEXER_PASSWORD absente'; END $$;
\endif
\if :{?reader_password}
\else
  \echo 'RAG_READER_PASSWORD absente'
  DO $$ BEGIN RAISE EXCEPTION 'RAG_READER_PASSWORD absente'; END $$;
\endif

CREATE EXTENSION IF NOT EXISTS vector;

-- Moindre privilège : rag_indexer écrit les lignes, rag_reader les lit ; aucun ne modifie le schéma.
SELECT format('CREATE ROLE rag_indexer LOGIN PASSWORD %L', :'indexer_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rag_indexer') \gexec
SELECT format('CREATE ROLE rag_reader LOGIN PASSWORD %L', :'reader_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rag_reader') \gexec
ALTER ROLE rag_indexer PASSWORD :'indexer_password';
ALTER ROLE rag_reader PASSWORD :'reader_password';

-- Attributs rétablis à chaque démarrage, même après une modification manuelle.
ALTER ROLE rag_indexer NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOREPLICATION LOGIN;
ALTER ROLE rag_reader  NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOREPLICATION LOGIN;

-- Ni tables temporaires ni création d'objets pour quiconque n'en a pas besoin.
REVOKE TEMPORARY, CREATE ON DATABASE rag FROM PUBLIC;
-- Bases d'administration fermées aux comptes applicatifs.
REVOKE CONNECT, TEMPORARY ON DATABASE postgres, template1 FROM PUBLIC;

REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO rag_indexer, rag_reader;

CREATE TABLE IF NOT EXISTS rag_documents (
    panel                 text        NOT NULL,
    doc_id                text        NOT NULL,
    chunk_id              text        NOT NULL,
    doc_type              text        NOT NULL,
    text                  text        NOT NULL,
    gene_symbol           text,
    clinical_significance text,
    review_status         text,
    rs_dbsnp              bigint,
    hgvs_c                text,
    hgvs_p                text,
    clinvar_variation_id  text,
    clinvar_url           text,
    source_version        text,
    collected_at          text,
    embedding             vector(768) NOT NULL,
    embedding_model       text        NOT NULL,
    indexed_at            timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (panel, doc_id)
);

CREATE INDEX IF NOT EXISTS rag_documents_embedding_hnsw
    ON rag_documents USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS rag_documents_gene_symbol ON rag_documents (gene_symbol);
CREATE INDEX IF NOT EXISTS rag_documents_clinical_significance ON rag_documents (clinical_significance);
CREATE INDEX IF NOT EXISTS rag_documents_rs_dbsnp ON rag_documents (rs_dbsnp);
CREATE INDEX IF NOT EXISTS rag_documents_hgvs_c ON rag_documents (hgvs_c);
CREATE INDEX IF NOT EXISTS rag_documents_hgvs_p ON rag_documents (hgvs_p);

-- Une seule transaction : les droits ne disparaissent jamais pendant un redémarrage.
BEGIN;
REVOKE ALL ON rag_documents FROM PUBLIC, rag_indexer, rag_reader;
GRANT SELECT, INSERT, UPDATE, DELETE ON rag_documents TO rag_indexer;
GRANT SELECT ON rag_documents TO rag_reader;
COMMIT;
