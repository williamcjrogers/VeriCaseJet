# Email Threading Upgrade (Design)

Goal: make threading explicit, defensible, and portable (Relativity/Reveal style) while staying compatible with current PST ingestion and `EmailMessage` schema.

## Target metadata per email

- `thread_group_id` (string, stable per thread)
- `thread_path` (e.g., "0/1/3" or numeric depth index) for ordering
- `thread_position` (int) optional convenience
- `parent_message_id` (string, if we can map) for tree edges
- `is_inclusive` (bool) – contains unique content not present elsewhere in thread
- `near_dup_group_id` (string, optional)
- `near_dup_score` (float 0–1, optional)
- Existing fields reused: `message_id`, `in_reply_to`, `email_references`, `conversation_index`, `thread_id` (can alias to `thread_group_id` if desired), `content_hash`, sender/recipients, dates, attachments.

## Schema deltas (proposed)

- Add columns to `email_messages`:
  - `thread_group_id` (String(128), index)
  - `thread_path` (String(64)) and/or `thread_position` (Integer)
  - `parent_message_id` (String(512), nullable)
  - `is_inclusive` (Boolean, default False)
  - `near_dup_group_id` (String(128), nullable)
  - `near_dup_score` (Float, nullable)
- Indexes: `(thread_group_id)`, `(thread_group_id, thread_path)`, `(thread_group_id, is_inclusive)`.

## Processing logic (PST ingestion)

1. **Build spine (deterministic):**
   - Use `message_id`, `in_reply_to`, `email_references`, `conversation_index`, `thread_topic`, `date_sent`.
   - Assign `thread_group_id` deterministically (e.g., root message_id or a generated UUID per thread).
   - Build parent/child links where `in_reply_to` matches a known `message_id` in the map; otherwise fall back to conversation_index heuristics.
   - Derive `thread_path` from the tree walk; root = "0", children get dot/ slash suffix.
2. **Inclusivity:**
   - Compute segment fingerprints (subject + canonical body + attachments hash set) per email.
   - Mark `is_inclusive=True` for emails that introduce unique segments/attachments not already present higher in the chain.
3. **Near-dupe snowball (optional in v1):**
   - Textual similarity on canonical body + subject; group into `near_dup_group_id`, record `near_dup_score`.
   - Use to flag forks/forwards with minor signature/banner changes.
4. **QA checks (log + optional warnings):**
   - Continuity: every non-root with missing parent logged.
   - Recipient drift: To/CC sets change across siblings.
   - Attachment divergence: same `thread_group_id` + different attachment hashes.
   - Time anomalies: large gaps within a thread.

## API / export

- Expose new fields in email detail and list APIs (`correspondence` routes) for UI filtering/sorting.
- Export load file (later) with: `ThreadGroupID`, `ThreadPath`, `ParentMessageID`, `IsInclusive`, `NearDupGroupID`, `NearDupScore`, `MessageID`, `InReplyTo`, `HasAttachments`, attachment MD5s.

## Rollout plan

1. Migration: add columns + indexes to `email_messages` (Alembic rev `0004_threading`).
2. Processor: extend `_build_thread_relationships` in `pst_processor.py` to compute new fields, mark inclusivity, optionally near-dupe groups.
3. API: surface fields in `/correspondence` responses.
4. QA: add a summary report (counts, anomalies) after ingestion; optionally a `POST /admin/threading/rebuild` for reprocessing.
5. UI: show thread group, inclusive flag, and anomalies; allow filters.

Open choices (need confirmation):

- Do we persist `thread_path` as a slash path or integer depth + sibling index? (default: slash path as string)
- Do we enable near-dupe grouping in v1, or defer to v2?
- How strict should inclusivity be (exact segment match vs. fuzzy)?
