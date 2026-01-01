import hashlib
import unittest
import uuid

from vericase.api.app.email_threading import (
    ThreadNode,
    _conversation_index_parent,
    _conversation_index_root,
    _normalize_conversation_index,
    _make_thread_group_id,
)


class TestConversationIndexHelpers(unittest.TestCase):
    def test_conversation_index_parent_root(self) -> None:
        root = "0x" + ("A" * 44)
        child = ("A" * 44) + ("B" * 10) + ("C" * 10)

        self.assertEqual(_normalize_conversation_index(root), "a" * 44)
        self.assertEqual(_conversation_index_root(child), "a" * 44)
        self.assertEqual(_conversation_index_parent(child), ("a" * 44) + ("b" * 10))

    def test_thread_group_id_from_content_hash(self) -> None:
        node = ThreadNode(
            email_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            message_id=None,
            message_id_norm=None,
            in_reply_to_norm=None,
            references_norm=[],
            subject_key=None,
            participants=set(),
            date_sent=None,
            conversation_index=None,
            content_hash="abc123",
            body_anchor_hash=None,
            quoted_anchor_hash=None,
            sender=None,
            raw_subject=None,
        )

        thread_id = _make_thread_group_id(node)
        expected = (
            "thread_"
            + hashlib.sha256("content:abc123".encode("utf-8")).hexdigest()[:32]
        )
        self.assertEqual(thread_id, expected)


if __name__ == "__main__":
    unittest.main()
