CREATE TABLE IF NOT EXISTS articles (
    publication_id BIGINT PRIMARY KEY,
    title TEXT NOT NULL,
    doi VARCHAR(512) NULL,
    publication_year INT NULL,
    journal TEXT NULL,
    pdf_uuid VARCHAR(255) NULL,
    trdizin_raw_json JSON NULL,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    INDEX idx_articles_doi (doi(191)),
    INDEX idx_articles_updated (updated_at)
);

CREATE TABLE IF NOT EXISTS processing_runs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    publication_id BIGINT NOT NULL,
    status VARCHAR(32) NOT NULL,
    grobid_version VARCHAR(64) NOT NULL,
    grobid_parameters_json JSON NOT NULL,
    algorithm_version VARCHAR(64) NOT NULL,
    duration_ms BIGINT NULL,
    trdizin_reference_count INT NOT NULL DEFAULT 0,
    grobid_reference_count INT NOT NULL DEFAULT 0,
    matched_count INT NOT NULL DEFAULT 0,
    unmatched_trdizin_count INT NOT NULL DEFAULT 0,
    unmatched_grobid_count INT NOT NULL DEFAULT 0,
    tei_xml LONGTEXT NULL,
    error_code VARCHAR(128) NULL,
    error_message TEXT NULL,
    started_at TIMESTAMP(6) NOT NULL,
    completed_at TIMESTAMP(6) NULL,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_runs_article FOREIGN KEY (publication_id) REFERENCES articles(publication_id),
    INDEX idx_runs_cache (publication_id, status, grobid_version, algorithm_version, id),
    INDEX idx_runs_created (created_at)
);

CREATE TABLE IF NOT EXISTS extracted_references (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    processing_run_id BIGINT NOT NULL,
    publication_id BIGINT NOT NULL,
    source_type ENUM('trdizin', 'grobid', 'ground_truth') NOT NULL,
    reference_index INT NOT NULL,
    raw_reference TEXT NULL,
    title TEXT NULL,
    authors_json JSON NULL,
    year VARCHAR(32) NULL,
    journal TEXT NULL,
    volume VARCHAR(64) NULL,
    issue VARCHAR(64) NULL,
    pages VARCHAR(128) NULL,
    doi VARCHAR(512) NULL,
    raw_json JSON NULL,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_refs_run FOREIGN KEY (processing_run_id) REFERENCES processing_runs(id),
    CONSTRAINT fk_refs_article FOREIGN KEY (publication_id) REFERENCES articles(publication_id),
    UNIQUE KEY uq_run_source_reference (processing_run_id, source_type, reference_index),
    INDEX idx_refs_article_source (publication_id, source_type),
    INDEX idx_refs_doi (doi(191))
);

CREATE TABLE IF NOT EXISTS comparison_matches (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    processing_run_id BIGINT NOT NULL,
    trdizin_reference_index INT NOT NULL,
    grobid_reference_index INT NOT NULL,
    status VARCHAR(64) NOT NULL,
    score DECIMAL(7,3) NOT NULL,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_matches_run FOREIGN KEY (processing_run_id) REFERENCES processing_runs(id),
    UNIQUE KEY uq_run_match (processing_run_id, trdizin_reference_index, grobid_reference_index),
    INDEX idx_matches_run_status (processing_run_id, status)
);

CREATE TABLE IF NOT EXISTS ground_truth_annotations (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    publication_id BIGINT NOT NULL,
    processing_run_id BIGINT NULL,
    reference_index INT NULL,
    extracted_reference_id BIGINT NULL,
    annotation_type VARCHAR(64) NOT NULL,
    original_value TEXT NULL,
    corrected_value TEXT NULL,
    is_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
    note TEXT NULL,
    annotator VARCHAR(255) NOT NULL,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_annotations_article FOREIGN KEY (publication_id) REFERENCES articles(publication_id),
    CONSTRAINT fk_annotations_run FOREIGN KEY (processing_run_id) REFERENCES processing_runs(id),
    CONSTRAINT fk_annotations_reference FOREIGN KEY (extracted_reference_id) REFERENCES extracted_references(id),
    INDEX idx_annotations_article (publication_id, created_at)
);

CREATE TABLE IF NOT EXISTS experiment_runs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT NULL,
    grobid_version VARCHAR(64) NOT NULL,
    grobid_parameters_json JSON NOT NULL,
    matcher_version VARCHAR(64) NOT NULL,
    dataset_name VARCHAR(255) NULL,
    started_at TIMESTAMP(6) NULL,
    completed_at TIMESTAMP(6) NULL,
    status VARCHAR(32) NOT NULL,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    INDEX idx_experiments_created (created_at)
);

CREATE TABLE IF NOT EXISTS experiment_metrics (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    experiment_run_id BIGINT NOT NULL,
    metric_name VARCHAR(64) NOT NULL,
    metric_value DECIMAL(16,8) NOT NULL,
    sample_count INT NULL,
    metadata_json JSON NULL,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_metrics_experiment FOREIGN KEY (experiment_run_id) REFERENCES experiment_runs(id),
    UNIQUE KEY uq_experiment_metric (experiment_run_id, metric_name),
    INDEX idx_metrics_experiment (experiment_run_id)
);
