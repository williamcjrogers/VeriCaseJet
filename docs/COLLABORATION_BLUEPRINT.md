# VeriCase Collaboration Blueprint (Unified, Optimised Baseline)

Status: Draft (recommended baseline)
Date: 2025-12-23
Owner: Product + Engineering

## 0) Executive summary
Collaboration should be a first-class capability in VeriCase: every case decision, evidence point, and claim position needs a clear discussion trail (who, what, when), fast navigation, and trustworthy auditability.

This blueprint unifies and improves on:
- docs/COLLABORATION_GUIDE.md (document collaboration)
- docs/COLLABORATION_3_LANE_PLAN.md (claim/evidence lanes)

It is written to be consistent with what exists today in this repo, and explicit about what to build next.

## 1) Product goals (what “major function” means)

### 1.1 Non-negotiables
- One obvious place to discuss every work object (document, claim, evidence item).
- Discussions are structured (threads + lanes), searchable, and linkable.
- Mentions, notifications, and read/unread make teams responsive.
- Activity feed and audit trail are reliable enough for legal work.
- Real-time (or near real-time) updates feel modern, not “refresh to see”.

### 1.2 MVP boundaries (so we can ship)
- Lanes organise discussion; they do not restrict access (permission stays separate).
- Prefer incremental delivery that preserves existing `/api/claims/*` behaviour.
- A unified data model is the long-term goal; we can bridge first.

## 2) Current baseline (already in repo)

### 2.1 Document collaboration (implemented)
Files:
- vericase/api/app/collaboration.py
- vericase/api/app/models.py

Models:
- DocumentComment (document_comments)
- DocumentAnnotation (document_annotations)
- CollaborationActivity (collaboration_activity)
- DocumentShare (document_shares)

Endpoints:
- POST /api/collaboration/documents/{doc_id}/comments
- GET  /api/collaboration/documents/{doc_id}/comments
- PATCH /api/collaboration/documents/{doc_id}/comments/{comment_id}
- DELETE /api/collaboration/documents/{doc_id}/comments/{comment_id}
- POST /api/collaboration/documents/{doc_id}/annotations
- GET  /api/collaboration/documents/{doc_id}/annotations
- PATCH /api/collaboration/documents/{doc_id}/annotations/{annotation_id}
- DELETE /api/collaboration/documents/{doc_id}/annotations/{annotation_id}
- POST /api/collaboration/cases/{case_id}/share
- GET  /api/collaboration/cases/{case_id}/shares
- GET  /api/collaboration/activity

Gaps to fix (high priority):
- Activity: CollaborationActivity is written, but `/api/collaboration/activity` currently derives activity from recent documents rather than the table.
- Mentions: API expects UUID user IDs in `mentions`, but the existing CommentsPanel extracts `@email`.
- Threading payload mismatch: the CommentsPanel assumes it receives a flat list with `parent_id` + replies present, but the API defaults to top-level-only unless `parent_id` is supplied.
- Audit requirements: comment/annotation deletion currently hard-deletes; legal workflows often require tombstones (soft delete) and edit history.

Related sharing:
- Document/folder sharing endpoints already exist in vericase/api/app/sharing.py and use the same DocumentShare/FolderShare models.

### 2.2 Claims and evidence collaboration (implemented)
Files:
- vericase/api/app/claims_module.py
- vericase/api/app/models.py

Models:
- ItemComment (item_comments)
- CommentReaction (comment_reactions)
- CommentReadStatus (comment_read_status)
- UserNotificationPreferences (user_notification_preferences)

Endpoints:
- GET  /api/claims/links/{link_id}/comments
- POST /api/claims/links/{link_id}/comments
- GET  /api/claims/comments/{item_type}/{item_id}
- POST /api/claims/comments
- GET  /api/claims/heads-of-claim/{claim_id}/evidence-comments
- GET  /api/claims/heads-of-claim/{claim_id}/team-members
- POST /api/claims/comments/{comment_id}/reactions
- GET  /api/claims/comments/{comment_id}/reactions
- DELETE /api/claims/comments/{comment_id}/reactions/{emoji}
- POST /api/claims/comments/{comment_id}/pin
- DELETE /api/claims/comments/{comment_id}/pin
- POST /api/claims/heads-of-claim/{claim_id}/mark-read
- GET  /api/claims/heads-of-claim/{claim_id}/unread-count

Notes:
- ItemComment already supports threading and pinning.
- ItemComment now supports 3 lanes: `core | counsel | expert` (DB + API + UI).

### 2.3 Workspace collaboration hub (implemented)
Files:
- vericase/api/app/workspace_collaboration.py
- vericase/ui/collaboration-workspace.html
- vericase/ui/nav-shell.js

Endpoints:
- GET  /api/workspace/{case|project}/{id}/discussion
- POST /api/workspace/{case|project}/{id}/discussion
- GET  /api/workspace/{case|project}/{id}/activity
- GET  /api/workspace/cases/{case_id}/team

Notes:
- Workspace discussion is implemented via `ItemComment.item_type in {'case','project'}`.
- Workspace activity merges `CollaborationActivity` + recent `ItemComment` activity.

## 3) Target experience (optimised)

### 3.1 Canonical collaboration model (conceptual)
Even if the database remains split initially, the product model should be consistent:
- Thread: a discussion attached to a resource (document, claim, evidence item, claim-link).
- Comment: a message in a thread (threaded replies).
- Lane: a tag that partitions the thread into 3 views (core/counsel/expert).
- Reaction: emoji reactions on comments.
- Pin: a “top note” for agreed position / key point.
- Read state: per-user “last read at” per thread/lane.
- Activity event: append-only audit log of collaboration actions.
- Notification: per-user inbox item (mentions, replies, assignments).
- Task (phase later): assignable actions created from comments.

### 3.2 Lanes for discussion (MVP)
Three fixed lanes for collaboration in claims and evidence:
- core: working position (facts, evidence points, next steps)
- counsel: legal submissions (tests, pleadings framing, authorities)
- expert: expert analysis (methodology, assumptions, conclusions)

Lanes are tags, not permissions, in MVP.

### 3.3 Activity and audit (make it trustworthy)
For collaboration to be "major", auditing cannot be an afterthought:
- Every create/update/delete/reaction/pin/read should generate an activity event.
- Deletes should be soft (tombstone) in collaboration tables, with the activity log preserving intent.
- Edits should preserve prior content (either via version table or by storing a diff/snapshot in activity details).

### 3.4 Thread mapping (how we identify a discussion)
In the current codebase, a “thread” is implied by the foreign key(s) on the comment model:
- Document thread: `DocumentComment.document_id`
- Claim discussion thread: `ItemComment.item_type='claim'` + `ItemComment.item_id=<claim_id>`
- Evidence thread (global): `ItemComment.item_type='evidence'` + `ItemComment.item_id=<evidence_item_id>`
- Evidence-in-claim-context thread: `ItemComment.item_claim_link_id=<link_id>`
- Workspace thread: `ItemComment.item_type in {'case','project'}` + `ItemComment.item_id=<workspace_id>`

This mapping lets us unify the UI component model even if the database remains split.

### 3.5 Capabilities matrix (current -> planned)
| Resource | Comments | Lanes | Reactions | Pin | Read/unread | Mentions | Annotations |
|---|---:|---:|---:|---:|---:|---:|---:|
| Document | Now | TBD (P2) | Planned (P2) | Planned (P2) | Planned (P2) | Fix (P0) | Now |
| Claim (Heads of Claim) | Now | Planned (P1) | Now | Now | Now | Now | n/a |
| Evidence item | Now | Planned (P1) | Now | TBD (P2) | TBD (P2) | Now | TBD (P2) |
| Claim-link (evidence in claim context) | Now | Planned (P1) | Now | TBD (P2) | TBD (P2) | Now | TBD (P2) |

## 4) Roadmap (prioritised delivery)

P0 — Stabilise existing collaboration (make it consistent)
1) Fix document comment threading expectations (either return full tree/flat list, or update UI to fetch replies).
2) Fix mentions normalization (accept emails + UUIDs; store UUIDs; consistent response payload).
3) Make `/api/collaboration/activity` use CollaborationActivity as source of truth.

P1 — Lanes for claim/evidence collaboration (fast product win)
1) Add `lane` to ItemComment with indexes.
2) Add `?lane=` filtering + lane field in responses across existing `/api/claims/*` comment endpoints.
3) Add lane tabs to Heads of Claim UI and Evidence UI.

P2 — Bring document collaboration up to parity
1) Add reactions, pinning, and read tracking to document comments (or unify with the claim/evidence system).
2) Expose unread counts and “mark read” for documents.

P3 — Notifications inbox (mentions/replies)
1) Add notifications table and API.
2) Generate notifications on mentions, replies, assignments; respect UserNotificationPreferences.

P4 — Real-time + presence (optional but high perceived value)
1) WebSocket channels per thread (document_id, claim_id, evidence item, claim-link).
2) Broadcast comment/annotation/task events; optional “typing” and “presence”.

P5 — Tasks + assignments (turn discussion into action)
1) Tasks linked to threads/comments; assignment, due dates, status.
2) “Create task from comment” UX and notifications.

## 5) Data model changes (proposed)

### 5.1 Add lane to ItemComment
Table: item_comments
- lane VARCHAR(20) NOT NULL DEFAULT 'core'
- allowed values: core, counsel, expert

Indexes:
- (item_type, item_id, lane, created_at)
- (item_claim_link_id, lane, created_at)

### 5.2 Mentions and notifications
Add a notifications table (new) and reuse existing preferences.

Table: collaboration_notifications (new)
- id UUID PK
- user_id UUID FK users.id
- type VARCHAR(32)  -- mention, reply, assignment, share, activity
- title VARCHAR(255)
- message TEXT
- link TEXT NULL
- is_read BOOLEAN DEFAULT false
- created_at TIMESTAMP TZ DEFAULT now()

### 5.3 Activity stream
Use collaboration_activity as the single source for the activity feed and
populate it from both /api/collaboration and /api/claims flows.

### 5.4 Read tracking (lanes-aware)
Lanes only feel “real” if unread counts behave intuitively.
Recommended approach:
- Extend `comment_read_status` to include `lane` and make it unique on `(user_id, claim_id, lane)`.
- Default to `lane='core'` for existing rows.
- If lane-specific unread is deferred, document that unread counts are aggregated across lanes (temporary).

### 5.5 Soft delete + edit history (audit-grade)
If collaboration is a major function, audit-grade behaviour is worth doing early:
- Add tombstone fields (`deleted_at`, `deleted_by`) rather than hard deletes for comments/annotations.
- Preserve edit history via either a `comment_versions` table or by storing snapshots in `collaboration_activity.details`.

### 5.6 Optional: converge on a single comments system (recommended long-term)
Today comments are split across DocumentComment and ItemComment.
If collaboration is truly central, consider converging to a single table in the long run:
- collaboration_comments(resource_type, resource_id, parent_id, lane, content, mentions, created_by, created_at, ...)
This avoids duplicated features and makes activity/notifications/search simpler.

## 6) API changes (proposed)

### 6.1 Lane support in existing claims endpoints
Requests:
- GET /api/claims/links/{link_id}/comments?lane=core|counsel|expert
- GET /api/claims/comments/{item_type}/{item_id}?lane=...
- GET /api/claims/heads-of-claim/{claim_id}/evidence-comments?lane=...
- POST /api/claims/comments (add lane in payload)
- POST /api/claims/links/{link_id}/comments (add lane in payload)

Responses:
- add lane to comment response objects

Defaults:
- If lane is omitted on create, server sets it to "core".

### 6.2 Mentions normalization
Add an endpoint to resolve @email to user IDs and normalize mentions:
- GET /api/collaboration/mentions/resolve?emails=a@b.com,c@d.com
  Returns list of {user_id, user_email, user_name}

On comment create:
- Accept mentions as emails or UUIDs.
- Normalize to UUIDs in storage.

### 6.3 Activity stream (single source)
Use collaboration_activity for:
- document comments and annotations
- claim and evidence comments
- reactions and pins

Add a new endpoint:
- GET /api/collaboration/activity?resource_type=document|claim|evidence&limit=50

## 7) UI integration (proposed)

### 7.1 Heads of Claim (contentious-matters.html)
- Add lane tabs (Core/Counsel/Expert).
- When fetching comments, append ?lane={activeLane}.
- When posting, include { lane: activeLane }.
- Render lane badge per comment.

### 7.2 Evidence repository (evidence.html)
- Add collaboration panel to evidence detail view.
- Use /api/claims/comments/evidence/{item_id}?lane=... for load.
- Post via /api/claims/comments with item_type=evidence, item_id, lane.

### 7.3 Document viewer (pdf viewer or doc detail)
- Use CommentsPanel for /api/collaboration/documents endpoints.
- Update comments UI to support mentions via user lookup (email -> user id).

## 8) Permissions (MVP)
- Existing CaseUser and DocumentShare rules remain unchanged.
- Lanes do not restrict access in MVP.
- Phase 2 can add lane-level access (case_user_lanes or case_users.collaboration_lane).

## 9) Operational concerns (so it scales)
- Pagination everywhere (comments, activity, notifications).
- Indexes aligned with common queries (resource + lane + created_at).
- Rate-limit high-volume endpoints (reactions, typing/presence if added).
- Retention policy for activity/notifications (e.g., keep forever for cases, or archive).
- Exports: ability to export discussion/audit trail for a case or claim.

## 10) Implementation plan (phased)

Phase 1: Lanes for ItemComment (core)
1) Add lane column + indexes via Alembic migration.
2) Update claims_module.py request/response models and queries.
3) Update UI panels for Heads of Claim and Evidence.

Phase 2: Mentions + notifications
1) Add collaboration_notifications table.
2) Normalize mentions (email -> user id).
3) Create notification records and expose a simple read/unread API.

Phase 3: Unified activity feed
1) Write collaboration_activity for claim/evidence events.
2) Update activity endpoint to read collaboration_activity only.

Phase 4: Real-time updates (optional)
1) Add websocket channels keyed by document_id or claim_id.
2) Broadcast comment and annotation events on create.

## 11) Testing checklist
- Create core/counsel/expert comments on claims and evidence.
- Lane filtering returns only matching lane.
- Reactions and pin/unpin still work.
- Read/unread counters still work.
- Document comments accept @email and resolve to users.
- Activity feed shows both document and claim events.

## 12) Default decisions (recommended unless you disagree)
- Apply lanes to claim/evidence first; decide on document lanes after P1 ships.
- Treat deletes as soft deletes (tombstones) for comments/annotations.
- Accept @email mentions in UI, but store UUIDs in DB (normalised).
- Use collaboration_activity as source of truth for activity feed and audit exports.

## 13) Open questions
- Should lanes apply to document comments as well (yes/no)?
- Should evidence items support annotations (PDF highlights) like documents (yes/no)?
- Should mentions support external emails (not yet users) (yes/no)?
- Should activity be retained forever per case, or archived (policy)?
