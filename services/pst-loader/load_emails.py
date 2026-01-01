import gzip
import os
import sys

import boto3
import psycopg2


def _normalize_db_url(db_url: str) -> str:
    # Accept SQLAlchemy-style URLs like postgresql+psycopg2://...
    return db_url.replace("postgresql+psycopg2://", "postgresql://", 1)


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


def main() -> int:
    database_url = _normalize_db_url(_require("DATABASE_URL"))
    pst_file_id = _require("PST_FILE_ID")
    output_bucket = _require("OUTPUT_BUCKET")
    output_prefix = _require("OUTPUT_PREFIX").lstrip("/")

    key = f"{output_prefix}emails.csv.gz"
    local_path = "/tmp/emails.csv.gz"

    s3 = boto3.client("s3")
    s3.download_file(output_bucket, key, local_path)

    conn = psycopg2.connect(database_url)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS pst_v2_emails_raw (
                    id uuid PRIMARY KEY,
                    pst_file_id uuid NOT NULL,
                    project_id text,
                    case_id text,
                    message_id text,
                    in_reply_to text,
                    references_header text,
                    subject text,
                    from_header text,
                    to_header text,
                    cc_header text,
                    bcc_header text,
                    date_header text,
                    body_text text,
                    source_path text,
                    ingested_at timestamptz NOT NULL DEFAULT now()
                );
                """
            )

            with gzip.open(local_path, "rt", encoding="utf-8", errors="replace") as f:
                # COPY expects header row present (extractor emits it).
                cur.copy_expert(
                    """
                    COPY pst_v2_emails_raw (
                        id,
                        pst_file_id,
                        project_id,
                        case_id,
                        message_id,
                        in_reply_to,
                        references_header,
                        subject,
                        from_header,
                        to_header,
                        cc_header,
                        bcc_header,
                        date_header,
                        body_text,
                        source_path
                    )
                    FROM STDIN WITH (FORMAT csv, HEADER true);
                    """,
                    f,
                )

            cur.execute(
                "SELECT count(*) FROM pst_v2_emails_raw WHERE pst_file_id = %s",
                (pst_file_id,),
            )
            count = cur.fetchone()[0]
            conn.commit()
            print(f"OK pst_file_id={pst_file_id} loaded={count}")
            return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
