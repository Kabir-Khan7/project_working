-- Neural Ledger — Medallion Architecture Schema (DuckDB)

-- BRONZE LAYER: Raw data exactly as received
CREATE TABLE IF NOT EXISTS bronze_transactions (
    bronze_id           VARCHAR DEFAULT (CAST(uuid() AS VARCHAR)) PRIMARY KEY,
    source_type         VARCHAR NOT NULL,
    source_software     VARCHAR NOT NULL,
    source_file         VARCHAR NOT NULL,
    source_file_hash    VARCHAR NOT NULL,
    source_row_number   INTEGER,
    raw_content         VARCHAR NOT NULL,
    raw_headers         VARCHAR,
    ingestion_batch_id  VARCHAR NOT NULL,
    processing_status   VARCHAR NOT NULL DEFAULT 'pending',
    ingested_at         TIMESTAMP DEFAULT current_timestamp,
    updated_at          TIMESTAMP DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS bronze_schema_mappings (
    mapping_id          VARCHAR DEFAULT (CAST(uuid() AS VARCHAR)) PRIMARY KEY,
    source_software     VARCHAR NOT NULL,
    original_column     VARCHAR NOT NULL,
    mapped_to           VARCHAR NOT NULL,
    confidence          DOUBLE NOT NULL DEFAULT 0.5,
    confirmed_by_user   BOOLEAN NOT NULL DEFAULT FALSE,
    times_seen          INTEGER NOT NULL DEFAULT 1,
    created_at          TIMESTAMP DEFAULT current_timestamp,
    updated_at          TIMESTAMP DEFAULT current_timestamp,
    UNIQUE (source_software, original_column)
);

-- SILVER LAYER: Cleaned, normalized, PII-masked
CREATE TABLE IF NOT EXISTS silver_transactions (
    silver_id           VARCHAR DEFAULT (CAST(uuid() AS VARCHAR)) PRIMARY KEY,
    bronze_id           VARCHAR NOT NULL,
    transaction_date    DATE,
    year_month          VARCHAR(7),
    fiscal_year         VARCHAR(9),
    description         VARCHAR,
    description_masked  VARCHAR,
    vendor              VARCHAR,
    category            VARCHAR,
    amount_debit        DOUBLE DEFAULT 0.0,
    amount_credit       DOUBLE DEFAULT 0.0,
    net_amount          DOUBLE GENERATED ALWAYS AS (amount_credit - amount_debit) VIRTUAL,
    currency            VARCHAR(3) DEFAULT 'PKR',
    language_detected   VARCHAR(5) DEFAULT 'en',
    is_duplicate        BOOLEAN DEFAULT FALSE,
    duplicate_of        VARCHAR,
    pii_masked          BOOLEAN DEFAULT FALSE,
    pii_types_found     VARCHAR,
    quality_score       DOUBLE DEFAULT 0.0,
    normalised_at       TIMESTAMP DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS silver_quarantine (
    quarantine_id       VARCHAR DEFAULT (CAST(uuid() AS VARCHAR)) PRIMARY KEY,
    bronze_id           VARCHAR NOT NULL,
    reason              VARCHAR NOT NULL,
    raw_content         VARCHAR,
    error_detail        VARCHAR,
    quarantined_at      TIMESTAMP DEFAULT current_timestamp
);

-- GOLD LAYER: AI-ready, quality-gated
CREATE TABLE IF NOT EXISTS gold_transactions (
    transaction_id      VARCHAR DEFAULT (CAST(uuid() AS VARCHAR)) PRIMARY KEY,
    silver_id           VARCHAR NOT NULL,
    bronze_id           VARCHAR NOT NULL,
    transaction_date    DATE NOT NULL,
    year_month          VARCHAR(7) NOT NULL,
    fiscal_year         VARCHAR(9),
    description_masked  VARCHAR,
    vendor              VARCHAR,
    category            VARCHAR,
    subcategory         VARCHAR,
    category_confidence DOUBLE DEFAULT 0.0,
    amount_debit        DOUBLE DEFAULT 0.0,
    amount_credit       DOUBLE DEFAULT 0.0,
    net_amount          DOUBLE GENERATED ALWAYS AS (amount_credit - amount_debit) VIRTUAL,
    currency            VARCHAR(3) DEFAULT 'PKR',
    embedding_text      VARCHAR NOT NULL,
    fbr_category        VARCHAR,
    fbr_tax_applicable  BOOLEAN DEFAULT FALSE,
    quality_score       DOUBLE NOT NULL CHECK (quality_score >= 0.7),
    qdrant_indexed      BOOLEAN DEFAULT FALSE,
    gold_version        INTEGER DEFAULT 1,
    promoted_at         TIMESTAMP DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS gold_period_summaries (
    summary_id          VARCHAR DEFAULT (CAST(uuid() AS VARCHAR)) PRIMARY KEY,
    period_type         VARCHAR NOT NULL,
    period_start        DATE NOT NULL,
    period_end          DATE NOT NULL,
    year_month          VARCHAR(7),
    fiscal_year         VARCHAR(9),
    total_income        DOUBLE DEFAULT 0.0,
    total_expenses      DOUBLE DEFAULT 0.0,
    net_amount          DOUBLE DEFAULT 0.0,
    transaction_count   INTEGER DEFAULT 0,
    category_breakdown  VARCHAR,
    anomaly_flag        BOOLEAN DEFAULT FALSE,
    vs_prior_period_pct DOUBLE,
    computed_at         TIMESTAMP DEFAULT current_timestamp,
    UNIQUE (period_type, period_start)
);

-- AUDIT LAYER: Immutable pipeline log
CREATE TABLE IF NOT EXISTS pipeline_audit_log (
    log_id              VARCHAR DEFAULT (CAST(uuid() AS VARCHAR)) PRIMARY KEY,
    operation           VARCHAR NOT NULL,
    source_layer        VARCHAR NOT NULL,
    batch_id            VARCHAR,
    status              VARCHAR NOT NULL,
    rows_affected       INTEGER DEFAULT 0,
    error_detail        VARCHAR,
    duration_ms         INTEGER,
    created_at          TIMESTAMP DEFAULT current_timestamp
);

-- INDEXES
CREATE INDEX IF NOT EXISTS idx_bronze_batch ON bronze_transactions(ingestion_batch_id);
CREATE INDEX IF NOT EXISTS idx_bronze_status ON bronze_transactions(processing_status);
CREATE INDEX IF NOT EXISTS idx_bronze_hash ON bronze_transactions(source_file_hash);
CREATE INDEX IF NOT EXISTS idx_silver_date ON silver_transactions(transaction_date);
CREATE INDEX IF NOT EXISTS idx_silver_month ON silver_transactions(year_month);
CREATE INDEX IF NOT EXISTS idx_silver_bronze ON silver_transactions(bronze_id);
CREATE INDEX IF NOT EXISTS idx_gold_date ON gold_transactions(transaction_date);
CREATE INDEX IF NOT EXISTS idx_gold_month ON gold_transactions(year_month);
CREATE INDEX IF NOT EXISTS idx_gold_category ON gold_transactions(category);
CREATE INDEX IF NOT EXISTS idx_gold_qdrant ON gold_transactions(qdrant_indexed);
CREATE INDEX IF NOT EXISTS idx_audit_operation ON pipeline_audit_log(operation);
CREATE INDEX IF NOT EXISTS idx_audit_batch ON pipeline_audit_log(batch_id);
