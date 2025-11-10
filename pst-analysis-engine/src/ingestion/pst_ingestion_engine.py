"""PST ingestion engine that keeps PST files intact and only extracts attachments."""

from __future__ import annotations

import hashlib
import logging
import os
import re
import sqlite3
from datetime import datetime
from email.parser import Parser
from pathlib import Path
from typing import Dict, Optional, Tuple

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PSTIngestionEngine:
    """Ingest PST files by indexing email metadata and extracting attachments only."""

    def __init__(self, db_path: str = "vericase.db", attachments_root: str | Path = "evidence") -> None:
        self.db_path = db_path
        self.attachments_root = Path(attachments_root)
        self.attachments_root.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------
    def ingest_pst_file(
        self,
        pst_file_path: str,
        profile_id: str,
        profile_type: str = "project",
        keywords: Optional[list] = None,
        stakeholders: Optional[list] = None,
    ) -> Dict[str, object]:
        """Parse the PST and populate `email_index` + `attachments` tables."""

        stats = {
            "total_emails": 0,
            "successful": 0,
            "failed": 0,
            "attachments": 0,
            "start_time": datetime.utcnow().isoformat(),
            "threads_identified": 0,
        }

        try:
            import pypff  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "pypff is required to ingest PST files. Install libpff/pypff first."
            ) from exc

        if not os.path.exists(pst_file_path):
            raise FileNotFoundError(f"PST file not found: {pst_file_path}")

        # Thread tracking maps
        thread_by_msgid: Dict[str, str] = {}
        thread_by_conv: Dict[str, str] = {}
        thread_by_subject: Dict[str, str] = {}

        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            keyword_list = (
                keywords if keywords is not None else self._load_keywords(conn, profile_id, profile_type)
            )
            stakeholder_list = (
                stakeholders if stakeholders is not None else self._load_stakeholders(conn, profile_id, profile_type)
            )

            pst = pypff.file()
            pst.open(pst_file_path)
            root = pst.get_root_folder()

            self._process_folder(
                root,
                profile_id=profile_id,
                profile_type=profile_type,
                pst_path=os.path.abspath(pst_file_path),
                cursor=cursor,
                conn=conn,
                stats=stats,
                thread_by_msgid=thread_by_msgid,
                thread_by_conv=thread_by_conv,
                thread_by_subject=thread_by_subject,
                keywords=keyword_list,
                stakeholders=stakeholder_list,
            )

            pst.close()
            conn.commit()

            stats["end_time"] = datetime.utcnow().isoformat()
            stats["threads_identified"] = len({tid for tid in thread_by_msgid.values() if tid})
            stats["duration_seconds"] = self._compute_duration(stats)
            logger.info(
                "PST ingestion complete: %s processed, %s attachments",
                stats["successful"],
                stats["attachments"],
            )
            return stats
        except Exception as exc:  # noqa: BLE001
            conn.rollback()
            stats["error"] = str(exc)
            logger.exception("PST ingestion failed")
            return stats
        finally:
            conn.close()

    def get_ingestion_status(self, profile_id: str) -> Dict[str, object]:
        """Return simple statistics for a profile."""

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM email_index WHERE profile_id = ?",
                (profile_id,),
            )
            total = cursor.fetchone()[0]
            return {"total_emails": total, "status": "complete"}
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to fetch ingestion status")
            return {"total_emails": 0, "status": "error", "error": str(exc)}
        finally:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _process_folder(
        self,
        folder,
        *,
        profile_id: str,
        profile_type: str,
        pst_path: str,
        cursor: sqlite3.Cursor,
        conn: sqlite3.Connection,
        stats: Dict[str, object],
        thread_by_msgid: Dict[str, str],
        thread_by_conv: Dict[str, str],
        thread_by_subject: Dict[str, str],
        keywords: list,
        stakeholders: list,
        folder_path: str = "",
    ) -> None:
        folder_name = folder.name or "Root"
        current_path = f"{folder_path}/{folder_name}" if folder_path else folder_name

        for index in range(folder.number_of_sub_messages):
            stats["total_emails"] += 1
            try:
                message = folder.get_sub_message(index)
                success = self._process_message(
                    message=message,
                    profile_id=profile_id,
                    profile_type=profile_type,
                    pst_path=pst_path,
                    folder_path=current_path,
                    cursor=cursor,
                    conn=conn,
                    stats=stats,
                    thread_by_msgid=thread_by_msgid,
                    thread_by_conv=thread_by_conv,
                    thread_by_subject=thread_by_subject,
                    keywords=keywords,
                    stakeholders=stakeholders,
                )
                if success:
                    stats["successful"] += 1
                else:
                    stats["failed"] += 1
            except Exception:  # noqa: BLE001
                stats["failed"] += 1
                logger.exception("Failed to process message in folder %s", current_path)

        for sub_index in range(folder.number_of_sub_folders):
            try:
                subfolder = folder.get_sub_folder(sub_index)
                self._process_folder(
                    subfolder,
                    profile_id=profile_id,
                    profile_type=profile_type,
                    pst_path=pst_path,
                    cursor=cursor,
                    conn=conn,
                    stats=stats,
                    thread_by_msgid=thread_by_msgid,
                    thread_by_conv=thread_by_conv,
                    thread_by_subject=thread_by_subject,
                    keywords=keywords,
                    stakeholders=stakeholders,
                    folder_path=current_path,
                )
            except Exception:  # noqa: BLE001
                logger.exception("Failed to traverse subfolder in %s", current_path)

    def _process_message(
        self,
        *,
        message,
        profile_id: str,
        profile_type: str,
        pst_path: str,
        folder_path: str,
        cursor: sqlite3.Cursor,
        conn: sqlite3.Connection,
        stats: Dict[str, object],
        thread_by_msgid: Dict[str, str],
        thread_by_conv: Dict[str, str],
        thread_by_subject: Dict[str, str],
        keywords: list,
        stakeholders: list,
    ) -> bool:
        headers = self._parse_headers(message)
        message_id = self._first_not_empty(
            self._safe_attr(message, "internet_message_identifier"),
            headers.get("message-id"),
        )
        if message_id:
            message_id = message_id.strip()

        in_reply_to = self._normalize_header(headers.get("in-reply-to"))
        references = self._normalize_header(headers.get("references"))
        conversation_index = self._conversation_index(message)

        subject = self._safe_attr(message, "subject", "") or ""

        thread_id = self._resolve_thread_id(
            message_id=message_id,
            in_reply_to=in_reply_to,
            references=references,
            conversation_index=conversation_index,
            subject=subject,
            thread_by_msgid=thread_by_msgid,
            thread_by_conv=thread_by_conv,
            thread_by_subject=thread_by_subject,
        )

        sender = self._first_not_empty(
            self._safe_attr(message, "sender_email_address"),
            self._safe_attr(message, "sender_name"),
        )
        to_addresses = self._safe_attr(message, "display_to", "")
        cc_addresses = self._safe_attr(message, "display_cc", "")
        date_sent = self._format_datetime(
            self._safe_attr(message, "delivery_time")
            or self._safe_attr(message, "client_submit_time")
            or self._safe_attr(message, "creation_time")
        )

        plain_body = self._safe_attr(message, "plain_text_body", "") or ""
        html_body = self._safe_attr(message, "html_body", "") or ""
        body_text = plain_body or self._html_to_text(html_body)

        # Collect attachments metadata & binary
        attachment_records = []
        for index in range(self._safe_attr(message, "number_of_attachments", 0) or 0):
            try:
                attachment = message.get_attachment(index)
                binary = self._extract_attachment_bytes(attachment)
                if binary is None:
                    continue
                att_name = self._safe_attr(attachment, "name", f"attachment_{index}")
                mime_type = self._safe_attr(attachment, "mime_type", "") or self._safe_attr(attachment, "content_type", "")
                size = len(binary)
                is_inline = bool(self._safe_attr(attachment, "is_inline", False) or self._safe_attr(attachment, "content_id", None))
                attachment_records.append(
                    {
                        "name": att_name,
                        "mime_type": mime_type,
                        "size": size,
                        "is_inline": is_inline,
                        "data": binary,
                    }
                )
            except Exception:  # noqa: BLE001
                logger.exception("Failed to extract attachment from email")

        matched_keywords = self._match_keywords(subject, body_text, attachment_records, keywords)
        identified_stakeholders = self._identify_stakeholders(sender, to_addresses, cc_addresses, stakeholders)

        email_row = (
            profile_id,
            profile_type,
            pst_path,
            message_id,
            in_reply_to,
            self._safe_attr(message, "subject", ""),
            sender or "",
            to_addresses or "",
            cc_addresses or "",
            date_sent,
            conversation_index,
            thread_id,
            folder_path,
            ",".join(matched_keywords),
            ",".join(identified_stakeholders),
            len(attachment_records),
            1 if attachment_records else 0,
            datetime.utcnow().isoformat(),
            os.path.basename(pst_path),
        )

        try:
            cursor.execute(
                """
                INSERT OR REPLACE INTO email_index (
                    profile_id, profile_type, pst_file_path, pst_message_id, pst_in_reply_to,
                    subject, from_address, to_addresses, cc_addresses, date_sent,
                    conversation_index, thread_id, folder_path, keywords, stakeholders,
                    attachments_count, has_attachments, indexed_date, source_pst
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                email_row,
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to insert email metadata")
            conn.rollback()
            return False

        for attachment in attachment_records:
            stored = self._store_attachment(
                attachment=attachment,
                profile_id=profile_id,
                email_message_id=message_id,
                sender=sender or "",
                date_sent=date_sent,
                pst_source=os.path.basename(pst_path),
                keywords=matched_keywords,
                stakeholders=identified_stakeholders,
                cursor=cursor,
            )
            if stored:
                stats["attachments"] += 1

        conn.commit()
        return True

    def _load_keywords(self, conn: sqlite3.Connection, profile_id: str, profile_type: str) -> list:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT keyword_name, variations FROM keywords WHERE profile_id = ? AND profile_type = ?",
            (profile_id, profile_type),
        )
        items = []
        for row in cursor.fetchall():
            name = (row["keyword_name"] if isinstance(row, sqlite3.Row) else row[0]) or ""
            variations = (row["variations"] if isinstance(row, sqlite3.Row) else row[1]) or ""
            variation_list = [v.strip().lower() for v in variations.split(',') if v.strip()]
            items.append({
                'label': name,
                'needle': name.lower(),
                'variations': variation_list,
            })
        return items

    def _load_stakeholders(self, conn: sqlite3.Connection, profile_id: str, profile_type: str) -> list:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name, email, role FROM stakeholders WHERE profile_id = ? AND profile_type = ?",
            (profile_id, profile_type),
        )
        items = []
        for row in cursor.fetchall():
            if isinstance(row, sqlite3.Row):
                name = row["name"] or ""
                email = (row["email"] or "").lower()
                role = row["role"] or ""
            else:
                name = row[0] or ""
                email = (row[1] or "").lower()
                role = row[2] or ""
            display = name or row[1] or role or "Stakeholder"
            items.append({
                'name': name,
                'name_lower': name.lower(),
                'email': email,
                'role': role,
                'display': display,
            })
        return items

    def _match_keywords(self, subject: str, body_text: str, attachments: list, keywords: list) -> list:
        if not keywords:
            return []
        combined_text = " ".join(filter(None, [subject.lower(), body_text.lower()])).strip()
        results = set()
        for keyword in keywords:
            label = keyword.get('label') or keyword.get('needle') or ''
            if not label:
                continue
            needle = keyword.get('needle', '').lower()
            variations = keyword.get('variations', [])

            def _match_in_text(text: str) -> bool:
                if not text:
                    return False
                if needle and needle in text:
                    return True
                return any(var in text for var in variations)

            if _match_in_text(combined_text):
                results.add(label)
                continue

            for attachment in attachments:
                att_name = str(attachment.get('name', '')).lower()
                if _match_in_text(att_name):
                    results.add(label)
                    break

        return sorted(results)

    def _identify_stakeholders(self, sender: Optional[str], to_addresses: Optional[str], cc_addresses: Optional[str], stakeholders: list) -> list:
        if not stakeholders:
            return []
        emails, tokens = self._normalise_addresses(sender, to_addresses, cc_addresses)
        matches = set()
        for stakeholder in stakeholders:
            email = stakeholder.get('email')
            name_lower = stakeholder.get('name_lower', '')
            display = stakeholder.get('display') or stakeholder.get('name') or stakeholder.get('email')
            if email and email in emails:
                matches.add(display)
                continue
            if name_lower and any(name_lower in token for token in tokens):
                matches.add(display)
        return sorted(matches)

    @staticmethod
    def _html_to_text(html: str) -> str:
        if not html:
            return ""
        text = re.sub(r'<[^>]+>', ' ', html)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    @staticmethod
    def _normalise_addresses(*fields: Optional[str]) -> Tuple[set, set]:
        email_pattern = re.compile(r'[\w.+-]+@[\w.-]+')
        emails = set()
        tokens = set()
        for field in fields:
            if not field:
                continue
            parts = re.split(r'[;,]', field)
            for part in parts:
                cleaned = part.strip()
                if not cleaned:
                    continue
                lower = cleaned.lower()
                tokens.add(lower)
                emails.update(email_pattern.findall(lower))
        return emails, tokens

    def _store_attachment(
        self,
        *,
        attachment: Dict[str, object],
        profile_id: str,
        email_message_id: Optional[str],
        sender: str,
        date_sent: Optional[str],
        pst_source: str,
        keywords: list,
        stakeholders: list,
        cursor: sqlite3.Cursor,
    ) -> bool:
        data = attachment["data"]  # type: ignore[assignment]
        if not isinstance(data, (bytes, bytearray)):
            return False

        hash_hex = hashlib.sha256(data).hexdigest()
        ext = Path(str(attachment.get("name", ""))).suffix
        safe_name = f"{hash_hex}{ext or ''}"
        dest_dir = self.attachments_root / "attachments" / profile_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / safe_name

        if not dest_path.exists():
            with open(dest_path, "wb") as handle:
                handle.write(data)

        cursor.execute(
            """
            INSERT INTO attachments (
                profile_id, email_reference_id, filename, file_path, file_size,
                mime_type, pst_source, hash, is_inline, from_email, date_sent,
                keywords, stakeholders, extracted_date, document_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile_id,
                email_message_id,
                attachment.get("name", "attachment"),
                str(dest_path),
                attachment.get("size", 0),
                attachment.get("mime_type", ""),
                pst_source,
                hash_hex,
                1 if attachment.get("is_inline") else 0,
                sender,
                date_sent,
                ",".join(keywords),
                ",".join(stakeholders),
                datetime.utcnow().isoformat(),
                None,
            ),
        )
        return True

    # ------------------------------------------------------------------
    # Value helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _safe_attr(obj, name, default=None):
        try:
            value = getattr(obj, name)
        except Exception:  # noqa: BLE001
            return default
        return value if value not in (None, "") else default

    @staticmethod
    def _format_datetime(dt) -> Optional[str]:
        if not dt:
            return None
        try:
            return dt.isoformat()
        except Exception:  # noqa: BLE001
            return str(dt)

    @staticmethod
    def _extract_attachment_bytes(attachment) -> Optional[bytes]:
        size = PSTIngestionEngine._safe_attr(attachment, "size")
        try:
            if size and hasattr(attachment, "read_buffer"):
                return attachment.read_buffer(size)
        except Exception:  # noqa: BLE001
            pass
        try:
            data = PSTIngestionEngine._safe_attr(attachment, "data")
            if isinstance(data, (bytes, bytearray)):
                return bytes(data)
        except Exception:  # noqa: BLE001
            pass
        return None

    @staticmethod
    def _parse_headers(message) -> Dict[str, str]:
        raw = PSTIngestionEngine._safe_attr(message, "transport_headers")
        if not raw:
            return {}
        try:
            parsed = Parser().parsestr(raw, headersonly=True)
            return {key.lower(): parsed.get(key) for key in parsed.keys()}
        except Exception:  # noqa: BLE001
            return {}

    @staticmethod
    def _normalize_header(value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        return value.strip()

    @staticmethod
    def _conversation_index(message) -> Optional[str]:
        conv = PSTIngestionEngine._safe_attr(message, "conversation_index")
        if not conv:
            return None
        try:
            if isinstance(conv, bytes):
                return conv.hex()
            return str(conv)
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _first_not_empty(*values):
        for value in values:
            if value:
                return value
        return None

    def _resolve_thread_id(
        self,
        *,
        message_id: Optional[str],
        in_reply_to: Optional[str],
        references: Optional[str],
        conversation_index: Optional[str],
        subject: str,
        thread_by_msgid: Dict[str, str],
        thread_by_conv: Dict[str, str],
        thread_by_subject: Dict[str, str],
    ) -> str:
        # 1. Reply chain based on In-Reply-To
        if in_reply_to and in_reply_to in thread_by_msgid:
            thread_id = thread_by_msgid[in_reply_to]
        else:
            thread_id = None

        # 2. References chain
        if not thread_id and references:
            for ref in references.split():
                if ref in thread_by_msgid:
                    thread_id = thread_by_msgid[ref]
                    break

        # 3. Conversation index root
        if not thread_id and conversation_index:
            conv_root = conversation_index[:22]
            thread_id = thread_by_conv.get(conv_root)
            if not thread_id:
                thread_id = f"thread-{conv_root}"
                thread_by_conv[conv_root] = thread_id

        # 4. Normalised subject fallback
        if not thread_id:
            norm_subject = self._normalise_subject(subject)
            thread_id = thread_by_subject.get(norm_subject)
            if not thread_id:
                thread_id = f"thread-{hashlib.sha256(norm_subject.encode('utf-8', 'ignore')).hexdigest()[:12]}"
                thread_by_subject[norm_subject] = thread_id

        if message_id:
            thread_by_msgid[message_id] = thread_id

        return thread_id

    @staticmethod
    def _normalise_subject(subject: str) -> str:
        subject = (subject or "").lower().strip()
        for prefix in ("re:", "fw:", "fwd:", "aw:"):
            if subject.startswith(prefix):
                subject = subject[len(prefix) :].strip()
        return subject or "(no subject)"

    @staticmethod
    def _compute_duration(stats: Dict[str, object]) -> Optional[float]:
        start = stats.get("start_time")
        end = stats.get("end_time")
        if not isinstance(start, str) or not isinstance(end, str):
            return None
        try:
            start_dt = datetime.fromisoformat(start)
            end_dt = datetime.fromisoformat(end)
            return (end_dt - start_dt).total_seconds()
        except Exception:  # noqa: BLE001
            return None


def main():  # pragma: no cover - manual CLI helper
    import argparse

    parser = argparse.ArgumentParser(description="VeriCase PST Ingestion Engine")
    parser.add_argument("pst_file", help="Path to PST file")
    parser.add_argument("--profile-id", required=True, help="Project or Case ID")
    parser.add_argument("--profile-type", default="project", choices=["project", "case"])
    parser.add_argument("--db", default="vericase.db", help="Database path")

    args = parser.parse_args()
    engine = PSTIngestionEngine(db_path=args.db)
    result = engine.ingest_pst_file(args.pst_file, args.profile_id, args.profile_type)
    print("Ingestion stats:")
    for key, value in result.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":  # pragma: no cover
    main()

