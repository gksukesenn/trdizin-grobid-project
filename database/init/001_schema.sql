CREATE DATABASE IF NOT EXISTS trdizin_grobid
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_0900_ai_ci;

USE trdizin_grobid;


CREATE TABLE IF NOT EXISTS articles (
    publication_id BIGINT UNSIGNED NOT NULL,

    title TEXT NULL,
    doi VARCHAR(255) NULL,
    publication_year SMALLINT UNSIGNED NULL,
    journal_name TEXT NULL,

    pdf_uuid CHAR(36) NULL,
    pdf_path VARCHAR(512) NULL,
    pdf_size_bytes BIGINT UNSIGNED NULL,

    source_page INT UNSIGNED NULL,
    download_status VARCHAR(30) NOT NULL DEFAULT 'unknown',

    trdizin_raw_json JSON NOT NULL,

    created_at TIMESTAMP NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMP NOT NULL
        DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (publication_id),

    INDEX idx_articles_doi (doi),
    INDEX idx_articles_year (publication_year),
    INDEX idx_articles_pdf_uuid (pdf_uuid),
    INDEX idx_articles_download_status (download_status)
);


CREATE TABLE IF NOT EXISTS trdizin_references (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

    publication_id BIGINT UNSIGNED NOT NULL,
    reference_index INT UNSIGNED NOT NULL,

    raw_reference LONGTEXT NULL,
    title TEXT NULL,
    authors_json JSON NULL,
    publication_year VARCHAR(20) NULL,
    journal_name TEXT NULL,
    doi VARCHAR(255) NULL,

    trdizin_raw_json JSON NULL,

    created_at TIMESTAMP NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (id),

    UNIQUE KEY uq_trdizin_reference (
        publication_id,
        reference_index
    ),

    INDEX idx_trdizin_reference_publication (
        publication_id
    ),

    CONSTRAINT fk_trdizin_reference_article
        FOREIGN KEY (publication_id)
        REFERENCES articles (publication_id)
        ON DELETE CASCADE
);


CREATE TABLE IF NOT EXISTS grobid_documents (
    publication_id BIGINT UNSIGNED NOT NULL,

    tei_file_path VARCHAR(512) NULL,
    tei_xml LONGTEXT NULL,

    reference_count INT UNSIGNED NOT NULL DEFAULT 0,
    processing_status VARCHAR(30) NOT NULL DEFAULT 'pending',
    processing_message TEXT NULL,

    processed_at DATETIME NULL,

    created_at TIMESTAMP NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMP NOT NULL
        DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (publication_id),

    INDEX idx_grobid_processing_status (
        processing_status
    ),

    CONSTRAINT fk_grobid_document_article
        FOREIGN KEY (publication_id)
        REFERENCES articles (publication_id)
        ON DELETE CASCADE
);


CREATE TABLE IF NOT EXISTS grobid_references (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

    publication_id BIGINT UNSIGNED NOT NULL,
    reference_index INT UNSIGNED NOT NULL,

    xml_id VARCHAR(100) NULL,
    raw_reference LONGTEXT NULL,

    title TEXT NULL,
    authors_json JSON NULL,
    publication_year VARCHAR(20) NULL,
    journal_name TEXT NULL,
    doi VARCHAR(255) NULL,

    grobid_raw_json JSON NULL,

    created_at TIMESTAMP NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (id),

    UNIQUE KEY uq_grobid_reference (
        publication_id,
        reference_index
    ),

    INDEX idx_grobid_reference_publication (
        publication_id
    ),

    CONSTRAINT fk_grobid_reference_article
        FOREIGN KEY (publication_id)
        REFERENCES articles (publication_id)
        ON DELETE CASCADE
);


CREATE TABLE IF NOT EXISTS comparison_results (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

    publication_id BIGINT UNSIGNED NOT NULL,

    trdizin_reference_index INT UNSIGNED NULL,
    grobid_reference_index INT UNSIGNED NULL,

    field_name VARCHAR(100) NOT NULL,

    trdizin_value LONGTEXT NULL,
    grobid_value LONGTEXT NULL,

    similarity_score DECIMAL(6, 5) NULL,
    comparison_status VARCHAR(30) NOT NULL,

    created_at TIMESTAMP NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (id),

    INDEX idx_comparison_publication (
        publication_id
    ),

    INDEX idx_comparison_status (
        comparison_status
    ),

    CONSTRAINT fk_comparison_article
        FOREIGN KEY (publication_id)
        REFERENCES articles (publication_id)
        ON DELETE CASCADE
);
