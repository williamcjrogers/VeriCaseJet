import unittest
import uuid
from datetime import datetime, timezone

from vericase.api.app.email_threading import (
    ThreadLinkDecision,
    ThreadNode,
    _assign_thread_groups,
    _break_parent_cycles,
)


class TestEmailThreadingCycles(unittest.TestCase):
    def _node(
        self, email_id: uuid.UUID, message_id: str, date_sent: datetime
    ) -> ThreadNode:
        return ThreadNode(
            email_id=email_id,
            message_id=message_id,
            message_id_norm=message_id,
            in_reply_to_norm=None,
            references_norm=[],
            subject_key="project update",
            participants=set(),
            date_sent=date_sent,
            conversation_index=None,
            content_hash=None,
            body_anchor_hash=None,
            quoted_anchor_hash=None,
            sender=None,
            raw_subject="Project Update",
        )

    def test_breaks_parent_cycle(self) -> None:
        node_a = self._node(
            uuid.UUID("00000000-0000-0000-0000-000000000001"),
            "a@example.com",
            datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        node_b = self._node(
            uuid.UUID("00000000-0000-0000-0000-000000000002"),
            "b@example.com",
            datetime(2025, 1, 2, tzinfo=timezone.utc),
        )
        nodes_by_id = {node_a.email_id: node_a, node_b.email_id: node_b}
        decisions = {
            node_a.email_id: ThreadLinkDecision(
                parent_email_id=node_b.email_id,
                methods=["InReplyTo"],
                evidence={},
                confidence=0.9,
                alternatives=[],
            ),
            node_b.email_id: ThreadLinkDecision(
                parent_email_id=node_a.email_id,
                methods=["InReplyTo"],
                evidence={},
                confidence=0.9,
                alternatives=[],
            ),
        }

        cycles_broken = _break_parent_cycles(nodes_by_id, decisions)
        self.assertEqual(cycles_broken, 1)
        self.assertIsNone(decisions[node_a.email_id].parent_email_id)

        thread_groups = _assign_thread_groups(nodes_by_id, decisions)
        self.assertEqual(len(set(thread_groups.values())), 1)


if __name__ == "__main__":
    unittest.main()
