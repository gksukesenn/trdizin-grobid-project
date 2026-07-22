USE trdizin_grobid;


CREATE TABLE IF NOT EXISTS reference_matching_progress (
    publication_id BIGINT UNSIGNED NOT NULL,

    matching_status VARCHAR(30) NOT NULL DEFAULT 'pending',

    doi_match_count INT UNSIGNED NOT NULL DEFAULT 0,
    text_match_count INT UNSIGNED NOT NULL DEFAULT 0,
    clean_match_count INT UNSIGNED NOT NULL DEFAULT 0,
    merged_count INT UNSIGNED NOT NULL DEFAULT 0,
    partial_count INT UNSIGNED NOT NULL DEFAULT 0,
    unmatched_trdizin_count INT UNSIGNED NOT NULL DEFAULT 0,
    unmatched_grobid_count INT UNSIGNED NOT NULL DEFAULT 0,

    error_message TEXT NULL,

    started_at DATETIME NULL,
    completed_at DATETIME NULL,

    created_at TIMESTAMP NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMP NOT NULL
        DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (publication_id),

    INDEX idx_reference_matching_status (
        matching_status
    ),

    CONSTRAINT fk_reference_matching_progress_article
        FOREIGN KEY (publication_id)
        REFERENCES articles (publication_id)
        ON DELETE CASCADE
);
