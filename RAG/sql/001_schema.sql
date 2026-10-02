-- Schéma de la base vectorielle du RAG (sous-projet E1). Idempotent : exécuté par
-- rag-postgres-init à chaque démarrage de la stack. Les mots de passe arrivent par
-- des variables psql (-v), jamais écrites dans ce fichier.
\set ON_ERROR_STOP on

CREATE EXTENSION IF NOT EXISTS vector;

-- Comptes au moindre privilège : rag_indexer (Airflow) écrit les lignes,
-- rag_reader (API de E2) les lit seulement. Aucun des deux ne peut modifier le schéma.
SELECT format('CREATE ROLE rag_indexer LOGIN PASSWORD %L', :'indexer_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rag_indexer') \gexec
SELECT format('CREATE ROLE rag_reader LOGIN PASSWORD %L', :'reader_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rag_reader') \gexec
ALTER ROLE rag_indexer PASSWORD :'indexer_password';
ALTER ROLE rag_reader PASSWORD :'reader_password';

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

REVOKE ALL ON rag_documents FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON rag_documents TO rag_indexer;
GRANT SELECT ON rag_documents TO rag_reader;
