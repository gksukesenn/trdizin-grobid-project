START TRANSACTION;

DELETE FROM comparison_results
WHERE field_name = 'doi'
  AND comparison_status = 'exact_match';

INSERT INTO comparison_results (
    publication_id,
    trdizin_reference_index,
    grobid_reference_index,
    field_name,
    trdizin_value,
    grobid_value,
    similarity_score,
    comparison_status
)
SELECT
    tr.publication_id,
    tr.reference_index,
    gr.reference_index,
    'doi',
    tr.normalized_doi,
    gr.normalized_doi,
    1.00000,
    'exact_match'
FROM (
    SELECT
        publication_id,
        normalized_doi,
        MIN(reference_index) AS reference_index
    FROM (
        SELECT
            publication_id,
            reference_index,
            LOWER(
                TRIM(
                    REPLACE(
                        REPLACE(
                            REPLACE(
                                REPLACE(
                                    doi,
                                    'https://doi.org/',
                                    ''
                                ),
                                'http://doi.org/',
                                ''
                            ),
                            'https://dx.doi.org/',
                            ''
                        ),
                        'doi:',
                        ''
                    )
                )
            ) AS normalized_doi
        FROM trdizin_references
        WHERE doi IS NOT NULL
          AND TRIM(doi) <> ''
    ) AS normalized_trdizin
    GROUP BY
        publication_id,
        normalized_doi
) AS tr

INNER JOIN (
    SELECT
        publication_id,
        normalized_doi,
        MIN(reference_index) AS reference_index
    FROM (
        SELECT
            publication_id,
            reference_index,
            LOWER(
                TRIM(
                    REPLACE(
                        REPLACE(
                            REPLACE(
                                REPLACE(
                                    doi,
                                    'https://doi.org/',
                                    ''
                                ),
                                'http://doi.org/',
                                ''
                            ),
                            'https://dx.doi.org/',
                            ''
                        ),
                        'doi:',
                        ''
                    )
                )
            ) AS normalized_doi
        FROM grobid_references
        WHERE doi IS NOT NULL
          AND TRIM(doi) <> ''
    ) AS normalized_grobid
    GROUP BY
        publication_id,
        normalized_doi
) AS gr
    ON gr.publication_id = tr.publication_id
   AND gr.normalized_doi = tr.normalized_doi;

COMMIT;
