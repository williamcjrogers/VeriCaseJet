"""
Email Spam Filter for VeriCase PST Processing

Classifies emails as spam/low-value based on subject line and sender patterns.
Results are stored in the existing `meta` JSON column (no new DB columns).

Usage:
    classifier = SpamClassifier()
    result = classifier.classify(subject="Webinar: Join us!", sender="noreply@marketing.com")
    # result = {"is_spam": True, "score": 95, "category": "marketing", "is_hidden": True}
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TypedDict


class SpamResult(TypedDict):
    is_spam: bool
    score: int  # 0-100 confidence
    category: str | None  # Category if spam, None if not
    is_hidden: bool  # Should be hidden from correspondence view


@dataclass
class PatternGroup:
    """A group of regex patterns with associated confidence and auto-hide behavior."""

    category: str
    patterns: list[str]
    confidence: int  # 0-100
    auto_hide: bool  # Automatically hide from correspondence view


# Canonical keyword list used to extract a human-friendly other-project name.
#
# Note: The classifier uses regex patterns (some with word boundaries / exclusions);
# this list is intentionally simple substring matching and is used only to populate
# meta fields for UI/analytics.
OTHER_PROJECT_KEYWORDS: list[str] = [
    "abbey road",
    "peabody",
    "merrick place",
    "southall",
    "oxlow lane",
    "dagenham",
    "befirst",
    "roxwell road",
    "kings crescent",
    "peckham library",
    "flaxyard",
    "loxford",
    "seven kings",
    "redbridge living",
    "frank towell court",
    "lisson arches",
    "beaulieu park",
    "chelmsford",
    "islay wharf",
    "victory place",
    "earlham grove",
    "canons park",
    "rayners lane",
    "clapham park",
    "mtvh",
    "osier way",
    "pocket living",
    "moreland gardens",
    "buckland",
    "south thames college",
    "robert whyte house",
    "bromley",
    "camley street",
    "lsa",
    "honeywell",
]


def extract_other_project(subject: str | None) -> str | None:
    """Extract the matched "other project" name from a subject line.

    This is a lightweight helper used to populate legacy top-level meta fields
    (e.g. `other_project`) from the centralized spam classifier output.
    """

    def _pretty_name(keyword: str) -> str:
        if keyword in {"mtvh", "lsa"}:
            return keyword.upper()
        if keyword == "befirst":
            return "BeFirst"
        return keyword.title()

    subject_lower = (subject or "").lower()
    for kw in OTHER_PROJECT_KEYWORDS:
        if kw in subject_lower:
            return _pretty_name(kw)
    return None


class SpamClassifier:
    """
    Pattern-based email spam classifier.

    Based on JA email analysis:
    - HIGH CONFIDENCE (auto-hide): Marketing, LinkedIn, news digests, date-only subjects
    - MEDIUM CONFIDENCE (tag only): Out of office, HR automated, surveys
    """

    # HIGH CONFIDENCE patterns - auto-hide these
    HIGH_CONFIDENCE_PATTERNS: list[PatternGroup] = [
        PatternGroup(
            category="non_email",
            patterns=[
                # Outlook message classes - not actual emails
                r"^IPM\.Activity$",
                r"^IPM\.Appointment",
                r"^IPM\.Task",
                r"^IPM\.Contact",
                r"^IPM\.StickyNote",
                r"^IPM\.Schedule",
                r"^IPM\.DistList",
                r"^IPM\.Post",
                # Empty/null subjects that indicate system items
                r"^-$",
                r"^$",
            ],
            confidence=100,
            auto_hide=True,
        ),
        PatternGroup(
            category="marketing",
            patterns=[
                r"\bwebinar\b",
                r"\bexhibition\b",
                r"\bconference\b",
                r"\bsummit\b",
                r"\d+%\s*off\b",
                r"\bdiscount\b",
                r"\bfree pass\b",
                r"\bstands? remaining\b",
                r"\bstands? sold\b",
                r"\bsecure yours\b",
                r"\bearly bird\b",
                r"\bregister now\b",
                r"\bbook your\b",
                r"\bspecial offer\b",
            ],
            confidence=95,
            auto_hide=True,
        ),
        PatternGroup(
            category="linkedin",
            patterns=[
                r"person is noticing",
                r"person noticed",
                r"people viewed your profile",
                r"new connection",
                r"linkedin\.com",
            ],
            confidence=98,
            auto_hide=True,
        ),
        PatternGroup(
            category="news_digest",
            patterns=[
                r"\.\.appointed to",
                r"\.\.framework",
                r"contractors? appointed",
                r"\d+\s*(?:firms?|contractors?)\s*appointed",
                r"contract (?:win|awarded)",
                r"framework (?:win|awarded)",
            ],
            confidence=90,
            auto_hide=True,
        ),
        PatternGroup(
            category="date_only",
            patterns=[
                # Subject is just a date/timestamp: "2021-07-08 12:32:33"
                r"^20\d{2}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:\.msg)?$",
            ],
            confidence=85,
            auto_hide=True,
        ),
        PatternGroup(
            category="vendor_discount",
            patterns=[
                r"ronacreteshop",
                r"toolstation",
                r"screwfix.*%\s*off",
                r"trade discount",
            ],
            confidence=90,
            auto_hide=True,
        ),
        PatternGroup(
            category="other_projects",
            patterns=[
                # Non-Welbourne projects - these are irrelevant to Welbourne analysis
                r"abbey road",
                r"peabody",
                r"merrick place",
                r"southall",
                r"oxlow lane",
                r"dagenham",
                r"befirst",
                r"roxwell road",
                r"kings crescent",
                r"peckham library",
                r"flaxyard",
                r"loxford",
                r"seven kings",
                r"redbridge living",
                r"frank towell court",
                r"lisson arches",
                r"\bgrove\b(?!.*welbourne)",  # Grove but not Welbourne context
                r"beaulieu park",
                r"chelmsford",
                r"islay wharf",
                r"victory place",
                r"earlham grove",
                r"canons park",
                r"rayners lane",
                r"clapham park",
                r"\bmtvh\b",
                r"osier way",
                r"pocket living",
                r"moreland gardens",
                r"buckland",
                r"south thames college",
                r"robert whyte house",
                r"bromley",
                r"camley street",
                r"\blsa\b",
                r"honeywell",
            ],
            confidence=92,
            auto_hide=True,
        ),
    ]

    # MEDIUM CONFIDENCE patterns - tag but don't auto-hide
    MEDIUM_CONFIDENCE_PATTERNS: list[PatternGroup] = [
        PatternGroup(
            category="out_of_office",
            patterns=[
                r"automatic reply[:\s]",
                r"out of (?:the )?office",
                r"away from (?:my )?(?:desk|office)",
                r"on (?:annual )?leave",
                r"currently unavailable",
            ],
            confidence=75,
            auto_hide=False,  # May contain useful info about availability
        ),
        PatternGroup(
            category="hr_automated",
            patterns=[
                r"\d+\s*(?:month|day|week)\s*check[- ]?up",
                r"check[- ]?up for",
                r"probation review",
                r"performance review reminder",
            ],
            confidence=70,
            auto_hide=False,
        ),
        PatternGroup(
            category="survey",
            patterns=[
                r"\bsurvey\b",
                r"feedback request",
                r"your opinion",
                r"rate your experience",
                r"how did we do",
            ],
            confidence=65,
            auto_hide=False,
        ),
        PatternGroup(
            category="training",
            patterns=[
                r"\bcpd\b",
                r"training (?:course|session)",
                r"learning module",
                r"certification expir",
            ],
            confidence=60,
            auto_hide=False,
        ),
        PatternGroup(
            category="leave_request",
            patterns=[
                r"leave request",
                r"holiday request",
                r"time off request",
                r"absence notification",
            ],
            confidence=55,
            auto_hide=False,
        ),
    ]

    # Known spam sender patterns
    SPAM_SENDER_PATTERNS: list[str] = [
        r"noreply@",
        r"no-reply@",
        r"donotreply@",
        r"marketing@",
        r"newsletter@",
        r"notifications?@linkedin",
        r"@eventbrite\.com$",
        r"@mailchimp\.com$",
        r"@sendgrid\.net$",
    ]

    def __init__(self) -> None:
        """Compile all patterns for efficiency."""
        self._compiled_high: list[tuple[PatternGroup, list[re.Pattern[str]]]] = []
        self._compiled_medium: list[tuple[PatternGroup, list[re.Pattern[str]]]] = []
        self._compiled_sender: list[re.Pattern[str]] = []

        for group in self.HIGH_CONFIDENCE_PATTERNS:
            compiled = [re.compile(p, re.IGNORECASE) for p in group.patterns]
            self._compiled_high.append((group, compiled))

        for group in self.MEDIUM_CONFIDENCE_PATTERNS:
            compiled = [re.compile(p, re.IGNORECASE) for p in group.patterns]
            self._compiled_medium.append((group, compiled))

        self._compiled_sender = [
            re.compile(p, re.IGNORECASE) for p in self.SPAM_SENDER_PATTERNS
        ]

    def classify(
        self,
        subject: str | None,
        sender: str | None,
        body: str | None = None,
    ) -> SpamResult:
        """
        Classify an email as spam or not.

        Args:
            subject: Email subject line
            sender: Sender email address
            body: Email body text (optional, for future enhancement)

        Returns:
            SpamResult with is_spam, score, category, and is_hidden flags
        """
        subject = (subject or "").strip()
        sender = (sender or "").strip().lower()

        # Check HIGH confidence patterns first
        for group, patterns in self._compiled_high:
            for pattern in patterns:
                if pattern.search(subject):
                    return SpamResult(
                        is_spam=True,
                        score=group.confidence,
                        category=group.category,
                        is_hidden=group.auto_hide,
                    )

        # Check sender patterns (boost confidence if matched)
        sender_is_spammy = any(p.search(sender) for p in self._compiled_sender)

        # Check MEDIUM confidence patterns
        for group, patterns in self._compiled_medium:
            for pattern in patterns:
                if pattern.search(subject):
                    # Boost confidence if sender is also spammy
                    confidence = group.confidence + (10 if sender_is_spammy else 0)
                    return SpamResult(
                        is_spam=True,
                        score=min(confidence, 100),
                        category=group.category,
                        is_hidden=group.auto_hide,
                    )

        # If sender is spammy but no subject match, flag as low-confidence spam
        if sender_is_spammy:
            return SpamResult(
                is_spam=True,
                score=40,
                category="automated",
                is_hidden=False,
            )

        # Not spam
        return SpamResult(
            is_spam=False,
            score=0,
            category=None,
            is_hidden=False,
        )

    def classify_batch(
        self,
        emails: list[dict[str, str | None]],
    ) -> list[SpamResult]:
        """
        Classify multiple emails.

        Args:
            emails: List of dicts with 'subject', 'sender', and optionally 'body'

        Returns:
            List of SpamResult for each email
        """
        return [
            self.classify(
                subject=e.get("subject"),
                sender=e.get("sender"),
                body=e.get("body"),
            )
            for e in emails
        ]


# Singleton instance for reuse
_classifier: SpamClassifier | None = None


def get_spam_classifier() -> SpamClassifier:
    """Get or create the singleton SpamClassifier instance."""
    global _classifier
    if _classifier is None:
        _classifier = SpamClassifier()
    return _classifier


def classify_email(
    subject: str | None,
    sender: str | None,
    body: str | None = None,
) -> SpamResult:
    """
    Convenience function to classify a single email.

    Args:
        subject: Email subject line
        sender: Sender email address
        body: Email body text (optional)

    Returns:
        SpamResult dict
    """
    return get_spam_classifier().classify(subject, sender, body)
