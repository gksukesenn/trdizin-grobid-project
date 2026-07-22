from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import mysql.connector

from trdizin_app.application.ports.persistence import RepositoryUnavailableError


LOGGER = logging.getLogger(__name__)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _plain(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    result = {}
    for key, value in row.items():
        if isinstance(value, (datetime,)):
            value = value.isoformat()
        elif isinstance(value, Decimal):
            value = float(value)
        result[key] = value
    return result


class MySqlRepositories:
    def __init__(self, connection_factory):
        self.connection_factory = connection_factory

    @contextmanager
    def _cursor(self, *, transaction: bool = False):
        db = self.connection_factory.connect()
        cursor = db.cursor(dictionary=True)
        try:
            yield db, cursor
            if transaction:
                db.commit()
        except mysql.connector.Error as error:
            if transaction:
                db.rollback()
            LOGGER.exception("MySQL repository işlemi başarısız")
            raise RepositoryUnavailableError("Veritabanı işlemi tamamlanamadı.") from error
        except Exception:
            if transaction:
                db.rollback()
            raise
        finally:
            cursor.close()
            db.close()

    def ping(self) -> bool:
        with self._cursor() as (_, cursor):
            cursor.execute("SELECT 1 AS healthy")
            return cursor.fetchone()["healthy"] == 1

    @staticmethod
    def _upsert_article(cursor, article) -> None:
        cursor.execute(
            """INSERT INTO articles
            (publication_id,title,doi,publication_year,journal,pdf_uuid,trdizin_raw_json)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE title=VALUES(title),doi=VALUES(doi),
            publication_year=VALUES(publication_year),journal=VALUES(journal),
            pdf_uuid=VALUES(pdf_uuid),trdizin_raw_json=VALUES(trdizin_raw_json)""",
            (article.publication_id, article.title, article.doi, article.year,
             article.journal, article.pdf_uuid, _json(article.raw)),
        )

    def find_compatible_success(self, publication_id, grobid_version,
                                algorithm_version, parameters):
        with self._cursor() as (_, cursor):
            cursor.execute(
                """SELECT * FROM processing_runs WHERE publication_id=%s AND status='success'
                AND grobid_version=%s AND algorithm_version=%s
                AND grobid_parameters_json=CAST(%s AS JSON) ORDER BY id DESC LIMIT 1""",
                (publication_id, grobid_version, algorithm_version, _json(parameters)),
            )
            run = cursor.fetchone()
            if not run:
                return None
            return self._load_result(cursor, run)

    def find_compatible_success_statuses(self, publication_ids, grobid_version,
                                         algorithm_version, parameters):
        if not publication_ids:
            return {}
        placeholders = ",".join(["%s"] * len(publication_ids))
        query = f"""SELECT publication_id, id AS processing_run_id, grobid_version,
            algorithm_version, duration_ms, trdizin_reference_count,
            grobid_reference_count, matched_count, unmatched_trdizin_count,
            unmatched_grobid_count
            FROM (
                SELECT processing_runs.*,
                    ROW_NUMBER() OVER (PARTITION BY publication_id ORDER BY id DESC) AS cache_rank
                FROM processing_runs
                WHERE publication_id IN ({placeholders}) AND status='success'
                    AND grobid_version=%s AND algorithm_version=%s
                    AND grobid_parameters_json=CAST(%s AS JSON)
            ) compatible_runs WHERE cache_rank=1"""
        parameters_sql = (*publication_ids, grobid_version, algorithm_version, _json(parameters))
        with self._cursor() as (_, cursor):
            cursor.execute(query, parameters_sql)
            return {
                str(row["publication_id"]): {
                    "processed": True,
                    "processing_run_id": row["processing_run_id"],
                    "cache_hit": True,
                    "grobid_version": row["grobid_version"],
                    "algorithm_version": row["algorithm_version"],
                    "trdizin_reference_count": row["trdizin_reference_count"],
                    "grobid_reference_count": row["grobid_reference_count"],
                    "matched_count": row["matched_count"],
                    "unmatched_trdizin_count": row["unmatched_trdizin_count"],
                    "unmatched_grobid_count": row["unmatched_grobid_count"],
                    "duration_ms": row["duration_ms"],
                }
                for row in cursor.fetchall()
            }

    def _load_result(self, cursor, run):
        run_id = run["id"]
        cursor.execute("SELECT * FROM articles WHERE publication_id=%s", (run["publication_id"],))
        article = cursor.fetchone()
        cursor.execute(
            "SELECT * FROM extracted_references WHERE processing_run_id=%s ORDER BY source_type,reference_index",
            (run_id,),
        )
        references = cursor.fetchall()
        mapped = {"trdizin": [], "grobid": []}
        for row in references:
            source = row["source_type"]
            if source not in mapped:
                continue
            value = {
                "reference_index": row["reference_index"], "raw_reference": row["raw_reference"] or "",
                "title": row["title"], "authors": json.loads(row["authors_json"] or "[]"),
                "year": row["year"], "journal": row["journal"], "volume": row["volume"],
                "issue": row["issue"], "pages": row["pages"], "doi": row["doi"],
            }
            mapped[source].append(value)
        cursor.execute("SELECT * FROM comparison_matches WHERE processing_run_id=%s ORDER BY id", (run_id,))
        matches = []
        matched_tr, matched_gr = set(), set()
        for row in cursor.fetchall():
            ti, gi = row["trdizin_reference_index"], row["grobid_reference_index"]
            matched_tr.add(ti); matched_gr.add(gi)
            matches.append({
                "trdizin_index": ti, "grobid_index": gi, "status": row["status"],
                "score": float(row["score"]),
                "trdizin_reference": mapped["trdizin"][ti] if ti < len(mapped["trdizin"]) else None,
                "grobid_reference": mapped["grobid"][gi] if gi < len(mapped["grobid"]) else None,
            })
        comparison = {
            "matches": matches,
            "unmatched_trdizin": [r for pos, r in enumerate(mapped["trdizin"]) if pos not in matched_tr],
            "unmatched_grobid": [r for pos, r in enumerate(mapped["grobid"]) if pos not in matched_gr],
        }
        return {
            "publication_id": run["publication_id"],
            "article": {"publication_id": article["publication_id"], "title": article["title"],
                        "doi": article["doi"], "year": article["publication_year"],
                        "journal": article["journal"] or "", "has_pdf": bool(article["pdf_uuid"])},
            "processing": {"source": "trdizin_api", "extractor": "grobid",
                "duration_ms": run["duration_ms"], "trdizin_reference_count": run["trdizin_reference_count"],
                "grobid_reference_count": run["grobid_reference_count"], "matched_count": run["matched_count"],
                "unmatched_trdizin_count": run["unmatched_trdizin_count"],
                "unmatched_grobid_count": run["unmatched_grobid_count"], "cache_hit": True,
                "processing_run_id": run_id, "grobid_version": run["grobid_version"],
                "algorithm_version": run["algorithm_version"], "persisted": True},
            "trdizin_references": mapped["trdizin"], "grobid_references": mapped["grobid"],
            "comparison": comparison, "tei_xml": run["tei_xml"] or "",
        }

    def save_success(self, article, result, grobid_version, algorithm_version, parameters):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        p = result["processing"]
        with self._cursor(transaction=True) as (_, cursor):
            self._upsert_article(cursor, article)
            cursor.execute(
                """INSERT INTO processing_runs
                (publication_id,status,grobid_version,grobid_parameters_json,algorithm_version,duration_ms,
                trdizin_reference_count,grobid_reference_count,matched_count,unmatched_trdizin_count,
                unmatched_grobid_count,tei_xml,started_at,completed_at)
                VALUES (%s,'success',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (article.publication_id, grobid_version, _json(parameters), algorithm_version,
                 p["duration_ms"], p["trdizin_reference_count"], p["grobid_reference_count"],
                 p["matched_count"], p["unmatched_trdizin_count"], p["unmatched_grobid_count"],
                 result["tei_xml"], now, now),
            )
            run_id = cursor.lastrowid
            for source, key in (("trdizin", "trdizin_references"), ("grobid", "grobid_references")):
                for ref in result[key]:
                    cursor.execute(
                        """INSERT INTO extracted_references
                        (processing_run_id,publication_id,source_type,reference_index,raw_reference,title,
                        authors_json,year,journal,volume,issue,pages,doi,raw_json)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (run_id, article.publication_id, source, ref.get("reference_index", 0),
                         ref.get("raw_reference"), ref.get("title"), _json(ref.get("authors") or []),
                         ref.get("year"), ref.get("journal"), ref.get("volume"), ref.get("issue"),
                         ref.get("pages"), ref.get("doi"), _json(ref)),
                    )
            for match in result["comparison"]["matches"]:
                cursor.execute(
                    """INSERT INTO comparison_matches
                    (processing_run_id,trdizin_reference_index,grobid_reference_index,status,score)
                    VALUES (%s,%s,%s,%s,%s)""",
                    (run_id, match["trdizin_index"], match["grobid_index"],
                     match["status"], match["score"]),
                )
            return run_id

    def save_failure(self, article, grobid_version, algorithm_version, parameters,
                     duration_ms, error_code, error_message):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with self._cursor(transaction=True) as (_, cursor):
            self._upsert_article(cursor, article)
            cursor.execute(
                """INSERT INTO processing_runs
                (publication_id,status,grobid_version,grobid_parameters_json,algorithm_version,duration_ms,
                error_code,error_message,started_at,completed_at) VALUES (%s,'failed',%s,%s,%s,%s,%s,%s,%s,%s)""",
                (article.publication_id, grobid_version, _json(parameters), algorithm_version,
                 duration_ms, error_code, error_message[:4000], now, now),
            )
            return cursor.lastrowid

    def list_articles(self):
        with self._cursor() as (_, cursor):
            cursor.execute("""SELECT a.publication_id,a.title,a.doi,a.publication_year,a.journal,
                COUNT(r.id) run_count,MAX(r.created_at) last_processed_at FROM articles a
                LEFT JOIN processing_runs r ON r.publication_id=a.publication_id
                GROUP BY a.publication_id ORDER BY last_processed_at DESC""")
            return [_plain(row) for row in cursor.fetchall()]

    def list_runs(self, publication_id):
        with self._cursor() as (_, cursor):
            cursor.execute("SELECT * FROM processing_runs WHERE publication_id=%s ORDER BY id DESC", (publication_id,))
            return [_plain(row) for row in cursor.fetchall()]

    def get_run(self, run_id):
        with self._cursor() as (_, cursor):
            cursor.execute("SELECT * FROM processing_runs WHERE id=%s", (run_id,))
            return _plain(cursor.fetchone())

    def get_comparison(self, run_id):
        with self._cursor() as (_, cursor):
            cursor.execute("SELECT * FROM processing_runs WHERE id=%s", (run_id,))
            run = cursor.fetchone()
            return self._load_result(cursor, run) if run else None

    def list_annotations(self, publication_id):
        with self._cursor() as (_, cursor):
            cursor.execute("SELECT * FROM ground_truth_annotations WHERE publication_id=%s ORDER BY id", (publication_id,))
            return [_plain(row) for row in cursor.fetchall()]

    def create_annotation(self, publication_id, data):
        with self._cursor(transaction=True) as (_, cursor):
            cursor.execute("""INSERT INTO ground_truth_annotations
                (publication_id,processing_run_id,reference_index,extracted_reference_id,annotation_type,
                original_value,corrected_value,is_confirmed,note,annotator)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (publication_id, data.get("processing_run_id"), data.get("reference_index"),
                 data.get("extracted_reference_id"), data["annotation_type"], data.get("original_value"),
                 data.get("corrected_value"), data.get("is_confirmed", False), data.get("note"), data["annotator"]))
            annotation_id = cursor.lastrowid
        return self._get_annotation(annotation_id)

    def _get_annotation(self, annotation_id):
        with self._cursor() as (_, cursor):
            cursor.execute("SELECT * FROM ground_truth_annotations WHERE id=%s", (annotation_id,))
            return _plain(cursor.fetchone())

    def update_annotation(self, annotation_id, data):
        allowed = [k for k in ("corrected_value", "is_confirmed", "note", "annotator") if k in data]
        if not allowed:
            return self._get_annotation(annotation_id)
        with self._cursor(transaction=True) as (_, cursor):
            assignments = ",".join(f"{key}=%s" for key in allowed)
            cursor.execute(f"UPDATE ground_truth_annotations SET {assignments} WHERE id=%s",
                           tuple(data[key] for key in allowed) + (annotation_id,))
        return self._get_annotation(annotation_id)

    def create_experiment(self, data):
        with self._cursor(transaction=True) as (_, cursor):
            cursor.execute("""INSERT INTO experiment_runs
                (name,description,grobid_version,grobid_parameters_json,matcher_version,dataset_name,
                started_at,completed_at,status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (data["name"], data.get("description"), data["grobid_version"],
                 _json(data.get("grobid_parameters") or {}), data["matcher_version"],
                 data.get("dataset_name"), data.get("started_at"), data.get("completed_at"), data["status"]))
            experiment_id = cursor.lastrowid
        return self.get_experiment(experiment_id)

    def list_experiments(self):
        with self._cursor() as (_, cursor):
            cursor.execute("SELECT * FROM experiment_runs ORDER BY id DESC")
            return [_plain(row) for row in cursor.fetchall()]

    def get_experiment(self, experiment_id):
        with self._cursor() as (_, cursor):
            cursor.execute("SELECT * FROM experiment_runs WHERE id=%s", (experiment_id,))
            result = _plain(cursor.fetchone())
            if result:
                cursor.execute("SELECT * FROM experiment_metrics WHERE experiment_run_id=%s ORDER BY id", (experiment_id,))
                result["metrics"] = [_plain(row) for row in cursor.fetchall()]
            return result

    def add_metric(self, experiment_id, data):
        with self._cursor(transaction=True) as (_, cursor):
            cursor.execute("""INSERT INTO experiment_metrics
                (experiment_run_id,metric_name,metric_value,sample_count,metadata_json)
                VALUES (%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE metric_value=VALUES(metric_value),sample_count=VALUES(sample_count),
                metadata_json=VALUES(metadata_json)""",
                (experiment_id, data["metric_name"], data["metric_value"], data.get("sample_count"),
                 _json(data.get("metadata") or {})))
        return self.get_experiment(experiment_id)
