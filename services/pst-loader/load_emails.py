import gzip
import base64
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


def _require_database_url() -> str:
    """
    Prefer DATABASE_URL, but allow DATABASE_URL_B64 for compatibility with existing
    Batch job definitions that store connection strings base64-encoded.
    """

    direct = os.getenv("DATABASE_URL")
    if direct:
        return direct

    b64 = os.getenv("DATABASE_URL_B64")
    if b64:
        try:
            return base64.b64decode(b64).decode("utf-8")
        except Exception as exc:
            raise RuntimeError("Invalid DATABASE_URL_B64") from exc

    raise RuntimeError("Missing required env var: DATABASE_URL (or DATABASE_URL_B64)")


def main() -> int:
    database_url = _normalize_db_url(_require_database_url())
    pst_file_id = _require("PST_FILE_ID")
    output_bucket = _require("OUTPUT_BUCKET")
    output_prefix = _require("OUTPUT_PREFIX").lstrip("/")

    emails_key = f"{output_prefix}emails.csv.gz"
    atts_key = f"{output_prefix}attachments.csv.gz"
    emails_path = "/tmp/emails.csv.gz"
    atts_path = "/tmp/attachments.csv.gz"

    s3 = boto3.client("s3")
    s3.download_file(output_bucket, emails_key, emails_path)
    # Attachments file may not exist for older runs; treat as optional but recommended.
    try:
        s3.download_file(output_bucket, atts_key, atts_path)
        has_attachments_file = True
    except Exception:
        has_attachments_file = False

    conn = psycopg2.connect(database_url)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            # ------------------------------------------------------------------
            # Staging tables (idempotent schema evolution)
            # ------------------------------------------------------------------
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS pst_v2_emails_raw (
                    id uuid PRIMARY KEY,
                    pst_file_id uuid NOT NULL,
                    project_id uuid,
                    case_id uuid,
                    message_id text,
                    in_reply_to text,
                    references_header text,
                    subject text,
                    from_header text,
                    to_header text,
                    cc_header text,
                    bcc_header text,
                    date_header text,
                    date_epoch bigint,
                    sender_email text,
                    sender_name text,
                    body_text text,
                    body_html text,
                    source_path text,
                    ingested_at timestamptz NOT NULL DEFAULT now()
                );
                """
            )
            # In case earlier runs created the old schema, add missing columns.
            cur.execute(
                """
                ALTER TABLE pst_v2_emails_raw
                  ADD COLUMN IF NOT EXISTS date_epoch bigint,
                  ADD COLUMN IF NOT EXISTS sender_email text,
                  ADD COLUMN IF NOT EXISTS sender_name text,
                  ADD COLUMN IF NOT EXISTS body_html text;
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS pst_v2_attachments_raw (
                    id uuid PRIMARY KEY,
                    email_message_id uuid NOT NULL,
                    pst_file_id uuid NOT NULL,
                    project_id uuid,
                    case_id uuid,
                    filename text,
                    content_type text,
                    file_size_bytes bigint,
                    s3_bucket text,
                    s3_key text,
                    attachment_hash text,
                    is_inline boolean,
                    content_id text,
                    source_path text,
                    ingested_at timestamptz NOT NULL DEFAULT now()
                );
                """
            )

            # Clean previous staging rows for this PST run (keeps the staging table bounded).
            cur.execute(
                "DELETE FROM pst_v2_emails_raw WHERE pst_file_id = %s", (pst_file_id,)
            )
            cur.execute(
                "DELETE FROM pst_v2_attachments_raw WHERE pst_file_id = %s",
                (pst_file_id,),
            )

            # ------------------------------------------------------------------
            # COPY in extractor output
            # ------------------------------------------------------------------
            with gzip.open(emails_path, "rt", encoding="utf-8", errors="replace") as f:
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
                        date_epoch,
                        sender_email,
                        sender_name,
                        body_text,
                        body_html,
                        source_path
                    )
                    FROM STDIN WITH (FORMAT csv, HEADER true, NULL '');
                    """,
                    f,
                )

            if has_attachments_file:
                with gzip.open(
                    atts_path, "rt", encoding="utf-8", errors="replace"
                ) as f:
                    cur.copy_expert(
                        """
                        COPY pst_v2_attachments_raw (
                            id,
                            email_message_id,
                            pst_file_id,
                            project_id,
                            case_id,
                            filename,
                            content_type,
                            file_size_bytes,
                            s3_bucket,
                            s3_key,
                            attachment_hash,
                            is_inline,
                            content_id,
                            source_path
                        )
                        FROM STDIN WITH (FORMAT csv, HEADER true, NULL '');
                        """,
                        f,
                    )

            # ------------------------------------------------------------------
            # UPSERT into core tables
            # ------------------------------------------------------------------
            # 1) email_messages
            cur.execute(
                """
                INSERT INTO email_messages (
                    id,
                    pst_file_id,
                    project_id,
                    case_id,
                    message_id,
                    in_reply_to,
                    email_references,
                    subject,
                    sender_email,
                    sender_name,
                    recipients_to,
                    recipients_cc,
                    recipients_bcc,
                    date_sent,
                    body_text,
                    body_html,
                    body_preview,
                    pst_message_path,
                    metadata
                )
                SELECT
                    e.id,
                    e.pst_file_id,
                    e.project_id,
                    e.case_id,
                    NULLIF(e.message_id, ''),
                    NULLIF(e.in_reply_to, ''),
                    NULLIF(e.references_header, ''),
                    NULLIF(e.subject, ''),
                    NULLIF(e.sender_email, ''),
                    NULLIF(e.sender_name, ''),
                    CASE
                        WHEN e.to_header IS NULL OR e.to_header = '' THEN NULL
                        ELSE array_remove(regexp_split_to_array(e.to_header, '\\s*[;,]\\s*'), '')
                    END,
                    CASE
                        WHEN e.cc_header IS NULL OR e.cc_header = '' THEN NULL
                        ELSE array_remove(regexp_split_to_array(e.cc_header, '\\s*[;,]\\s*'), '')
                    END,
                    CASE
                        WHEN e.bcc_header IS NULL OR e.bcc_header = '' THEN NULL
                        ELSE array_remove(regexp_split_to_array(e.bcc_header, '\\s*[;,]\\s*'), '')
                    END,
                    CASE
                        WHEN e.date_epoch IS NOT NULL THEN to_timestamp(e.date_epoch)
                        ELSE NULL
                    END,
                    NULLIF(e.body_text, ''),
                    NULLIF(e.body_html, ''),
                    LEFT(COALESCE(NULLIF(e.body_text, ''), NULLIF(e.body_html, ''), ''), 10000),
                    NULLIF(e.source_path, ''),
                    jsonb_build_object(
                        'pst_v2', true,
                        'pst_v2_source_path', e.source_path,
                        'raw_headers', jsonb_build_object(
                            'from', e.from_header,
                            'to', e.to_header,
                            'cc', e.cc_header,
                            'bcc', e.bcc_header,
                            'date', e.date_header
                        ),
                        'recipients_display', jsonb_build_object(
                            'to', e.to_header,
                            'cc', e.cc_header,
                            'bcc', e.bcc_header
                        )
                    )::json
                FROM pst_v2_emails_raw e
                ON CONFLICT (id) DO UPDATE SET
                    pst_file_id = EXCLUDED.pst_file_id,
                    project_id = EXCLUDED.project_id,
                    case_id = EXCLUDED.case_id,
                    message_id = EXCLUDED.message_id,
                    in_reply_to = EXCLUDED.in_reply_to,
                    email_references = EXCLUDED.email_references,
                    subject = EXCLUDED.subject,
                    sender_email = EXCLUDED.sender_email,
                    sender_name = EXCLUDED.sender_name,
                    recipients_to = EXCLUDED.recipients_to,
                    recipients_cc = EXCLUDED.recipients_cc,
                    recipients_bcc = EXCLUDED.recipients_bcc,
                    date_sent = EXCLUDED.date_sent,
                    body_text = EXCLUDED.body_text,
                    body_html = EXCLUDED.body_html,
                    body_preview = EXCLUDED.body_preview,
                    pst_message_path = EXCLUDED.pst_message_path,
                    metadata = (
                        COALESCE(email_messages.metadata::jsonb, '{}'::jsonb)
                        || COALESCE(EXCLUDED.metadata::jsonb, '{}'::jsonb)
                    )::json
                ;
                """
            )

            # 2) email_attachments (if provided)
            if has_attachments_file:
                cur.execute(
                    """
                    INSERT INTO email_attachments (
                        id,
                        email_message_id,
                        filename,
                        content_type,
                        file_size_bytes,
                        s3_bucket,
                        s3_key,
                        attachment_hash,
                        is_inline,
                        content_id,
                        is_duplicate
                    )
                    SELECT
                        a.id,
                        a.email_message_id,
                        NULLIF(a.filename, ''),
                        NULLIF(a.content_type, ''),
                        a.file_size_bytes,
                        NULLIF(a.s3_bucket, ''),
                        NULLIF(a.s3_key, ''),
                        NULLIF(a.attachment_hash, ''),
                        COALESCE(a.is_inline, false),
                        NULLIF(a.content_id, ''),
                        false
                    FROM pst_v2_attachments_raw a
                    ON CONFLICT (id) DO UPDATE SET
                        email_message_id = EXCLUDED.email_message_id,
                        filename = EXCLUDED.filename,
                        content_type = EXCLUDED.content_type,
                        file_size_bytes = EXCLUDED.file_size_bytes,
                        s3_bucket = EXCLUDED.s3_bucket,
                        s3_key = EXCLUDED.s3_key,
                        attachment_hash = EXCLUDED.attachment_hash,
                        is_inline = EXCLUDED.is_inline,
                        content_id = EXCLUDED.content_id
                    ;
                    """
                )

                # Ensure has_attachments is set for any emails that have non-inline attachments.
                cur.execute(
                    """
                    UPDATE email_messages em
                    SET has_attachments = true
                    WHERE em.id IN (
                        SELECT DISTINCT email_message_id
                        FROM pst_v2_attachments_raw
                        WHERE COALESCE(is_inline, false) = false
                    );
                    """
                )

                # 3) evidence_items: one per attachment (non-inline) to support Evidence UI.
                cur.execute(
                    """
                    INSERT INTO evidence_items (
                        id,
                        filename,
                        original_path,
                        file_type,
                        mime_type,
                        file_size,
                        file_hash,
                        s3_bucket,
                        s3_key,
                        evidence_type,
                        source_type,
                        source_email_id,
                        project_id,
                        case_id,
                        processing_status,
                        auto_tags,
                        meta
                    )
                    SELECT
                        a.id,
                        COALESCE(NULLIF(a.filename, ''), 'unnamed_attachment'),
                        ('PSTV2:' || a.pst_file_id::text || '/' || COALESCE(a.source_path, '') || '/' || COALESCE(a.filename, '')) AS original_path,
                        NULL,
                        NULLIF(a.content_type, ''),
                        a.file_size_bytes,
                        NULLIF(a.attachment_hash, ''),
                        COALESCE(NULLIF(a.s3_bucket, ''), %s),
                        a.s3_key,
                        'email_attachment',
                        'pst_extraction',
                        a.email_message_id,
                        a.project_id,
                        a.case_id,
                        'pending',
                        '["email-attachment","from-pst-v2"]'::jsonb,
                        jsonb_build_object(
                            'pst_v2', true,
                            'email_attachment_id', a.id::text,
                            'email_message_id', a.email_message_id::text
                        )
                    FROM pst_v2_attachments_raw a
                    WHERE COALESCE(a.is_inline, false) = false
                      AND a.s3_key IS NOT NULL
                      AND a.attachment_hash IS NOT NULL
                      AND a.attachment_hash <> ''
                    ON CONFLICT (id) DO UPDATE SET
                        filename = EXCLUDED.filename,
                        original_path = EXCLUDED.original_path,
                        mime_type = EXCLUDED.mime_type,
                        file_size = EXCLUDED.file_size,
                        file_hash = EXCLUDED.file_hash,
                        s3_bucket = EXCLUDED.s3_bucket,
                        s3_key = EXCLUDED.s3_key,
                        source_email_id = EXCLUDED.source_email_id,
                        project_id = EXCLUDED.project_id,
                        case_id = EXCLUDED.case_id
                    ;
                    """,
                    (os.getenv("S3_BUCKET") or output_bucket,),
                )

            # Stats
            cur.execute(
                "SELECT count(*) FROM pst_v2_emails_raw WHERE pst_file_id = %s",
                (pst_file_id,),
            )
            email_count = cur.fetchone()[0]
            att_count = 0
            if has_attachments_file:
                cur.execute(
                    "SELECT count(*) FROM pst_v2_attachments_raw WHERE pst_file_id = %s",
                    (pst_file_id,),
                )
                att_count = cur.fetchone()[0]

            conn.commit()
            print(
                f"OK pst_file_id={pst_file_id} loaded_emails={email_count} loaded_attachments={att_count} upserted=true"
            )
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
