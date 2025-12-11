#!/usr/bin/env python3
"""
Deep analysis of Welbourne emails using project-specific keywords and domains.
"""

import sys
from collections import defaultdict

sys.path.insert(0, '/code')

from app.db import SessionLocal
from app.models import EmailMessage, Project

# Project identifiers
PROJECT_TERMS = [
    "welbourne", "welbourn", "tottenham hale", "thw", "n17",
    "wr200625", "02809", "ashley road", "monument way"
]

# Relevant domains from the project
RELEVANT_DOMAINS = [
    "ljjcontractors.co.uk", "czwgarchitects.co.uk", "calfordseaden.com",
    "keyloninteriors.co.uk", "grangewood.co.uk", "haringey.gov.uk",
    "tpsmanagement.uk", "phdaccess.com", "argentllp.co.uk", "bulgroup.co.uk",
    "tps.eu.com", "closeltd.co.uk", "acsstainless.co.uk", "ellisandmoore.com",
    "weldriteuk.com", "taylor.maxwell.co.uk", "oliverconnell.com",
    "hodkinsonconsultancy.com", "ptea.co.uk", "whitbywood.com",
    "vobsterarchitectural.co.uk", "patrickparsons.co.uk", "stanta.com",
    "aconex.com", "completewaterproofing.co.uk", "falconcranes.co.uk",
    "phibbs.info", "quinnross.com", "esd-uk.com", "leiab.se",
    "markeygroup.co.uk", "quod.com", "future-paradise.co.uk", "cfs-fixings.co.uk",
    "kone.com", "aztecscreeding.com", "dacbeachcroft.com", "fmdc.co.uk",
    "ashridgeinteriors.co.uk", "nhbc.co.uk", "dptltd.co.uk", "pellings.co.uk",
    "emsuk.net", "hpgl.com", "gardiner.com"
]

# Key project-specific terms that indicate Welbourne relevance
WELBOURNE_KEYWORDS = [
    # Locations specific to Welbourne
    "block a", "block b", "block c", "podium", "health centre",
    # Key subcontractors
    "ljj", "grangewood", "keylon", "weldrite", "taylor maxwell",
    "vobster", "stanta", "phibbs", "acs stainless", "kone",
    "quinnross", "quinn ross", "hodkinson", "oliver connell",
    "complete waterproofing", "phd access", "future paradise",
    "aztec", "ellis and moore", "ashridge", "cfs fixings",
    # Design team
    "calfordseaden", "czwg", "argent", "tps management", "pte architects",
    "pellings", "fmdc", "patrick parsons", "whitby wood",
    # Technical terms specific to the project
    "s278", "s106", "loading bay", "vobster stone",
]

# Other projects to EXCLUDE (pure only, keep cross-refs)
OTHER_PROJECTS = {
    "lisson arches": ["lisson arches", "lisson arch"],
    "kings crescent": ["kings crescent", "kingscrescent"],
    "merrick place": ["merrick place", "merrick", "r160123", "southall"],
    "camley street": ["camley street", "camley st"],
    "oxlow lane": ["oxlow lane", "oxlow", "befirst", "be first"],
    "peckham library": ["peckham library", "peckham square", "flaxyard"],
    "beaulieu park": ["beaulieu park", "beaulieu", "chelmsford"],
    "abbey road": ["500 abbey", "abbey road"],
    "middlesex hospital": ["middlesex hospital", "sqq middlesex"],
    "mapleton crescent": ["mapleton crescent", "mapleton", "pocket living"],
}

# Spam/marketing domains to exclude
SPAM_DOMAINS = [
    "ciob-mail.org.uk", "ukconstructionweek.com", "noreply.mail.zetadocs.com",
    "offsite.trendingnow.uk.com", "adjacentecomms.co.uk", "glenigan.com",
    "housingforum.org.uk", "rvtgroup.co.uk", "nfb.builders.org.uk",
    "concrete.trendingnow.uk.com", "homeseventemail.co.uk", "dotdigital-email.com",
    "r1.dotdigital-email.com", "openaccessdigital.org", "notifications.service.gov.uk",
    "dutypoint.com", "r1.dotmailer-email.com", "concreteexpo.co.uk",
    "urbanonetwork.co.uk", "ccsend.com",
]


def has_welbourne_context(text: str) -> bool:
    """Check if text has Welbourne project context."""
    text_lower = text.lower()
    for term in PROJECT_TERMS:
        if term in text_lower:
            return True
    return False


def has_other_project(text: str) -> tuple[bool, str]:
    """Check if text references another project (without Welbourne context)."""
    text_lower = text.lower()
    for proj_name, terms in OTHER_PROJECTS.items():
        for term in terms:
            if term in text_lower:
                return True, proj_name
    return False, ""


def has_welbourne_keywords(text: str) -> tuple[bool, list]:
    """Check if text has Welbourne-specific keywords."""
    text_lower = text.lower()
    matched = []
    for kw in WELBOURNE_KEYWORDS:
        if kw in text_lower:
            matched.append(kw)
    return len(matched) > 0, matched


def is_from_relevant_domain(email_addr: str) -> tuple[bool, str]:
    """Check if email is from a relevant project domain."""
    email_lower = email_addr.lower()
    for domain in RELEVANT_DOMAINS:
        if domain in email_lower:
            return True, domain
    return False, ""


def is_spam_domain(email_addr: str) -> bool:
    """Check if email is from a spam/marketing domain."""
    email_lower = email_addr.lower()
    for domain in SPAM_DOMAINS:
        if domain in email_lower:
            return True
    return False


def main():
    db = SessionLocal()

    try:
        project = db.query(Project).filter(
            Project.project_name == "S3 Recovered Project"
        ).first()

        if not project:
            print("ERROR: Project not found!")
            return

        project_id = str(project.id)

        print("=" * 100)
        print("WELBOURNE PROJECT - COMPREHENSIVE EMAIL ANALYSIS")
        print("=" * 100)
        print(f"Project: Welbourne, Tottenham Hale, London N17")
        print(f"Project Code: WR200625 / 02809")

        # Load all emails
        print("\nLoading all emails...")
        emails = db.query(EmailMessage).filter(
            EmailMessage.project_id == project_id
        ).all()

        print(f"Total emails: {len(emails)}")

        # Categorize emails
        categories = {
            "welbourne_explicit": [],      # Explicitly mentions Welbourne
            "welbourne_keywords": [],      # Has Welbourne keywords but no explicit mention
            "relevant_domain_only": [],    # From relevant domain but no keywords
            "other_project_pure": [],      # Pure other project (EXCLUDE)
            "other_project_mixed": [],     # Other project + Welbourne context (KEEP)
            "spam": [],                    # Spam/marketing
            "unitedliving_internal": [],   # UL internal without project context
            "unknown": [],                 # Unclassified
        }

        other_project_breakdown = defaultdict(list)

        for email in emails:
            subject = email.subject or ""
            body = (email.body_text or "")[:5000]
            sender = email.sender_email or ""
            full_text = f"{subject} {body}"

            # Check spam first
            if is_spam_domain(sender):
                categories["spam"].append(email)
                continue

            # Check explicit Welbourne mention
            if has_welbourne_context(full_text):
                # Check if also mentions other project (mixed)
                is_other, other_name = has_other_project(full_text)
                if is_other:
                    categories["other_project_mixed"].append(email)
                else:
                    categories["welbourne_explicit"].append(email)
                continue

            # No explicit Welbourne - check for other projects
            is_other, other_name = has_other_project(full_text)
            if is_other:
                categories["other_project_pure"].append(email)
                other_project_breakdown[other_name].append(email)
                continue

            # Check for Welbourne keywords
            has_kw, matched_kw = has_welbourne_keywords(full_text)
            if has_kw:
                categories["welbourne_keywords"].append(email)
                continue

            # Check if from relevant domain
            is_relevant, domain = is_from_relevant_domain(sender)
            if is_relevant:
                categories["relevant_domain_only"].append(email)
                continue

            # Check if United Living internal
            if "unitedliving.co.uk" in sender.lower():
                categories["unitedliving_internal"].append(email)
                continue

            # Unknown
            categories["unknown"].append(email)

        # Print results
        print("\n" + "=" * 100)
        print("CATEGORIZATION RESULTS")
        print("=" * 100)

        print(f"\n{'Category':<40} {'Count':>10} {'Action':>15}")
        print("-" * 65)
        print(f"{'Explicit Welbourne mention':<40} {len(categories['welbourne_explicit']):>10} {'KEEP':>15}")
        print(f"{'Welbourne keywords (no explicit)':<40} {len(categories['welbourne_keywords']):>10} {'KEEP':>15}")
        print(f"{'Relevant domain only':<40} {len(categories['relevant_domain_only']):>10} {'KEEP':>15}")
        print(f"{'Other project + Welbourne (mixed)':<40} {len(categories['other_project_mixed']):>10} {'KEEP':>15}")
        print(f"{'United Living internal':<40} {len(categories['unitedliving_internal']):>10} {'REVIEW':>15}")
        print(f"{'Pure other project':<40} {len(categories['other_project_pure']):>10} {'EXCLUDE':>15}")
        print(f"{'Spam/marketing':<40} {len(categories['spam']):>10} {'EXCLUDE':>15}")
        print(f"{'Unknown/unclassified':<40} {len(categories['unknown']):>10} {'REVIEW':>15}")

        keep_count = (len(categories['welbourne_explicit']) +
                      len(categories['welbourne_keywords']) +
                      len(categories['relevant_domain_only']) +
                      len(categories['other_project_mixed']))
        exclude_count = len(categories['other_project_pure']) + len(categories['spam'])
        review_count = len(categories['unitedliving_internal']) + len(categories['unknown'])

        print("-" * 65)
        print(f"{'TOTAL KEEP':<40} {keep_count:>10}")
        print(f"{'TOTAL EXCLUDE':<40} {exclude_count:>10}")
        print(f"{'TOTAL REVIEW NEEDED':<40} {review_count:>10}")

        # Other project breakdown
        print("\n" + "=" * 100)
        print("OTHER PROJECTS TO EXCLUDE (PURE - NO WELBOURNE CONTEXT)")
        print("=" * 100)

        for proj_name, proj_emails in sorted(other_project_breakdown.items(), key=lambda x: -len(x[1])):
            print(f"\n{proj_name.upper()}: {len(proj_emails)} emails")
            # Sample subjects
            for e in proj_emails[:3]:
                print(f"  - {(e.subject or 'No subject')[:70]}")

        # Analyze unknown emails
        print("\n" + "=" * 100)
        print("UNKNOWN EMAILS ANALYSIS")
        print("=" * 100)

        unknown_domains = defaultdict(int)
        for email in categories["unknown"]:
            sender = email.sender_email or ""
            if "@" in sender:
                domain = sender.split("@")[-1].lower()
                unknown_domains[domain] += 1

        print(f"\nTop domains in unknown emails ({len(categories['unknown'])} total):")
        for domain, count in sorted(unknown_domains.items(), key=lambda x: -x[1])[:30]:
            print(f"  {domain:<45} {count:>5} emails")

        print("\nSample unknown email subjects:")
        for email in categories["unknown"][:15]:
            subj = (email.subject or "No subject")[:60]
            sender = (email.sender_email or "unknown")[:35]
            print(f"  - [{sender}] {subj}")

        # Analyze UL internal
        print("\n" + "=" * 100)
        print("UNITED LIVING INTERNAL (NO PROJECT CONTEXT)")
        print("=" * 100)
        print(f"\nTotal: {len(categories['unitedliving_internal'])} emails")

        print("\nSample subjects:")
        for email in categories['unitedliving_internal'][:20]:
            subj = (email.subject or "No subject")[:70]
            print(f"  - {subj}")

        # Final summary
        print("\n" + "=" * 100)
        print("FINAL RECOMMENDATION")
        print("=" * 100)
        print(f"\nTotal emails: {len(emails)}")
        print(f"\n✅ KEEP (Welbourne relevant): {keep_count} emails")
        print(f"   - Explicit Welbourne: {len(categories['welbourne_explicit'])}")
        print(f"   - Welbourne keywords: {len(categories['welbourne_keywords'])}")
        print(f"   - Relevant domains: {len(categories['relevant_domain_only'])}")
        print(f"   - Mixed project refs: {len(categories['other_project_mixed'])}")

        print(f"\n❌ EXCLUDE: {exclude_count} emails")
        print(f"   - Pure other projects: {len(categories['other_project_pure'])}")
        print(f"   - Spam/marketing: {len(categories['spam'])}")

        print(f"\n⚠️  REVIEW NEEDED: {review_count} emails")
        print(f"   - UL internal: {len(categories['unitedliving_internal'])}")
        print(f"   - Unknown: {len(categories['unknown'])}")

        # Output IDs for exclusion
        print("\n" + "=" * 100)
        print("EXCLUSION EMAIL IDS")
        print("=" * 100)

        exclude_ids = []
        for email in categories['other_project_pure']:
            exclude_ids.append(str(email.id))
        for email in categories['spam']:
            exclude_ids.append(str(email.id))

        print(f"\nTotal emails to exclude: {len(exclude_ids)}")
        print(f"First 10 IDs: {exclude_ids[:10]}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
