from __future__ import annotations

import re
from pathlib import Path


EMAILS_CSV_HEADER = (
    "id,pst_file_id,project_id,case_id,message_id,in_reply_to,references_header,subject,"
    "from_header,to_header,cc_header,bcc_header,date_header,date_epoch,sender_email,sender_name,"
    "body_text,body_html,source_path"
)

ATTACHMENTS_CSV_HEADER = (
    "id,email_message_id,pst_file_id,project_id,case_id,filename,content_type,file_size_bytes,"
    "s3_bucket,s3_key,attachment_hash,is_inline,content_id,source_path"
)


def _extract_copy_columns(py_text: str, table_name: str) -> list[str]:
    # Find COPY <table> ( ... ) FROM STDIN
    pattern = re.compile(
        rf"COPY\s+{re.escape(table_name)}\s*\((?P<cols>[\s\S]*?)\)\s*FROM\s+STDIN",
        re.IGNORECASE,
    )
    m = pattern.search(py_text)
    assert m, f"COPY block not found for table={table_name}"
    cols_block = m.group("cols")
    cols = [c.strip() for c in cols_block.split(",") if c.strip()]
    return cols


def test_extractor_emails_csv_header_is_stable() -> None:
    text = Path("services/pst-extractor/src/main.rs").read_text(encoding="utf-8")
    assert EMAILS_CSV_HEADER in text


def test_extractor_attachments_csv_header_is_stable() -> None:
    text = Path("services/pst-extractor/src/main.rs").read_text(encoding="utf-8")
    assert ATTACHMENTS_CSV_HEADER in text


def test_loader_copy_columns_match_extractor_contract() -> None:
    text = Path("services/pst-loader/load_emails.py").read_text(encoding="utf-8")

    emails_cols = _extract_copy_columns(text, "pst_v2_emails_raw")
    assert ",".join(emails_cols) == EMAILS_CSV_HEADER

    atts_cols = _extract_copy_columns(text, "pst_v2_attachments_raw")
    assert ",".join(atts_cols) == ATTACHMENTS_CSV_HEADER
