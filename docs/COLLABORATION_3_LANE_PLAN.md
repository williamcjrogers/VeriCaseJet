# 3‑Lane Collaboration Plan (Core / Counsel / Expert)

**Status:** Draft (first run)

**Date:** 2025-12-19

## 1) Objective
Provide a collaboration model in VeriCase where **lawyers, KCs, experts, and project managers** can work from one place, with structured discussion around:
- **Heads of Claim** (claim discussion and claim‑specific decisions)
- **Evidence** (notes on evidence items, both globally and in the context of a claim)

The MVP constraint is:
- **Lanes-only** (no private threads)
- **Exactly 3 lanes**: **Core**, **Counsel**, **Expert**

## 2) What already exists in this repo (we will reuse)

### 2.1 Existing data models
Located in `vericase/api/app/models.py`:
- `CaseUser` (`case_users`) — case team membership with `role` = `admin | editor | viewer`
- `HeadOfClaim` (`heads_of_claim`) + `ContentiousMatter` (`contentious_matters`)
- `EvidenceItem` (`evidence_items`) — evidence repository, optionally associated to `case_id` and/or `project_id`
- `ItemClaimLink` (`item_claim_links`) — links evidence/correspondence to a claim or matter
- `ItemComment` (`item_comments`) — universal comments table already used by the claims module
  - Supports threading via `parent_comment_id`
  - Includes pinning fields (`is_pinned`, `pinned_at`, `pinned_by`)
- `CommentReaction` (`comment_reactions`)
- `CommentReadStatus` (`comment_read_status`) — per-user per-claim last read timestamp
- `UserNotificationPreferences` (`user_notification_preferences`)

### 2.2 Existing API endpoints
Located in `vericase/api/app/claims_module.py`:

**Evidence link comments** (claim-specific evidence notes):
- `GET  /api/claims/links/{link_id}/comments`
- `POST /api/claims/links/{link_id}/comments`

**Direct item comments** (comment directly on evidence/correspondence/matter/claim):
- `GET  /api/claims/comments/{item_type}/{item_id}`
- `POST /api/claims/comments`

**Claim evidence notes aggregation** (evidence notes tab):
- `GET /api/claims/heads-of-claim/{claim_id}/evidence-comments`

**Team members for @mentions**:
- `GET /api/claims/heads-of-claim/{claim_id}/team-members`
  - Uses `CaseUser` membership when `HeadOfClaim.case_id` exists.

**Collaboration features already present**:
- Reactions: `POST/GET /api/claims/comments/{comment_id}/reactions`
- Pinning: `POST/DELETE /api/claims/comments/{comment_id}/pin` (claim-level only)
- Read/unread: `POST /api/claims/heads-of-claim/{claim_id}/mark-read`, `GET /api/claims/heads-of-claim/{claim_id}/unread-count`

Evidence repository listing lives under `vericase/api/app/evidence_repository.py`:
- `GET /api/evidence/items`

### 2.3 Existing UI surfaces
- `vericase/ui/contentious-matters.html` — heads-of-claim UI already wired to `/api/claims/*` collaboration endpoints.
- `vericase/ui/evidence.html` — evidence repository UI (grid + detail panel), best place to add evidence-level collaboration.

## 3) MVP collaboration UX (lanes-only)

### 3.1 Lanes (fixed for MVP)
Each comment is recorded in one of the three lanes:
1. **Core** — working position: facts, evidence points, chronology points, and next steps.
2. **Counsel** — submissions: legal test, pleadings framing, authorities, concessions.
3. **Expert** — expert analysis: methodology, assumptions, calculations, conclusions.

### 3.2 Where collaboration happens
**Heads of Claim**
- Claim Discussion: lane-filtered comment stream for the claim itself.
- Evidence Notes: lane-filtered notes attached to linked evidence/correspondence for that claim.
- Pinned note (claim discussion only): used as the **agreed position**.

**Evidence**
- Evidence Notes (global): lane-filtered notes attached directly to an `EvidenceItem`.
- Evidence Notes (claim context): notes attached to the `ItemClaimLink` (so the note is explicitly tied to a claim).

### 3.3 Recommended MVP semantics (simplest)
- Lanes are **organisational tags**, not access-control.
  - Any authorised case member can read/write all three lanes.
- If confidentiality is later required (e.g., counsel-only lane), it becomes Phase 2 (see §8).

## 4) Build plan (repo touchpoints)

### Step 1 — Database: add lane to `ItemComment`
**Files:**
- `vericase/api/app/models.py`
- `vericase/api/app/alembic/versions/<new_revision>_add_comment_lanes.py`

**Schema change (required):**
- Add `lane` column to `item_comments`:
  - type: string (e.g., `VARCHAR(20)`)
  - not null
  - default: `core`
  - allowed values: `core | counsel | expert`

**Indexes (recommended):**
- `(item_type, item_id, lane, created_at)`
- `(item_claim_link_id, lane, created_at)`

### Step 2 — API: extend existing endpoints
**Primary file:** `vericase/api/app/claims_module.py`

**Required API changes:**
1) Extend comment request/response models:
- Add optional `lane` to `CommentCreate` (default server-side to `core`).
- Add `lane` to `CommentResponse`.

2) Add lane filtering via querystring:
- `GET /api/claims/links/{link_id}/comments?lane=core|counsel|expert`
- `GET /api/claims/comments/{item_type}/{item_id}?lane=...`
- `GET /api/claims/heads-of-claim/{claim_id}/evidence-comments?lane=...`
- Ensure the claim discussion endpoint (already in this file) also accepts `?lane=`.

3) Set lane on create:
- When creating `ItemComment`, set `lane = request.lane or 'core'`.

**Backwards compatibility behaviour (recommended):**
- If `lane` is omitted on create → default to `core`.
- If `?lane` is omitted on reads → return all lanes (so existing UI does not unexpectedly hide content).

### Step 3 — UI: add lane switcher to existing claim collaboration panels
**File:** `vericase/ui/contentious-matters.html`

**Required UI changes:**
- Add a lane switcher (Core / Counsel / Expert) at the top of:
  1) Claim Discussion panel
  2) Evidence Notes panel

- Store `activeLane` in JS.
- When fetching comments, append `?lane=${activeLane}`.
- When posting comments, include `{ lane: activeLane }` in payload.
- Render a lane badge on each comment.

### Step 4 — UI: add evidence-level collaboration panel
**File:** `vericase/ui/evidence.html`

**Required UI changes:**
- Add a Collaboration/Evidence Notes panel in the evidence detail area.
- Use the existing item-comments endpoint pattern:
  - Load: `GET /api/claims/comments/evidence/{evidenceItemId}?lane=${activeLane}`
  - Post: `POST /api/claims/comments` with `{ item_type: 'evidence', item_id: evidenceItemId, content, lane }`

### Step 5 — Tests + smoke checks
**Minimal unit coverage (high-value):**
- Creating a comment without lane defaults to `core`.
- Fetching with `?lane=counsel` filters correctly.

**Smoke tests:**
- Create Core/Counsel/Expert comments on a claim.
- Create Core/Counsel/Expert comments on an evidence item.
- Verify reactions still work.
- Verify pin/unpin still works on claim discussion.
- Verify mark-read/unread-count still works.

## 5) Formal microcopy pack (for lane UI)

### 5.1 Lane tooltips
- **Core**: “Working position: facts, evidence, chronology points, and next steps.”
- **Counsel**: “Counsel’s submissions: legal test, pleadings framing, authorities, and concessions.”
- **Expert**: “Expert analysis: methodology, assumptions, calculations, and conclusions.”

### 5.2 Panel headings
**Head of Claim → Discussion**
- Title: `Discussion`
- Subheading: “Use lanes to separate working position, submissions, and expert analysis. Maintain the pinned note as the agreed position.”
- Pinned label: `Pinned: Agreed position`

**Head of Claim → Evidence notes**
- Title: `Evidence notes`
- Subheading: “Notes recorded here relate to items linked to this Head of Claim.”
- Link meta: `Link classification: Supporting | Contradicting | Neutral | Key`

**Evidence repository → Evidence notes**
- Title: `Evidence notes`
- Subheading: “Notes recorded here apply to this evidence item generally. For claim-specific notes, open the item from the relevant Head of Claim.”

### 5.3 Composer placeholders
- Core: `Record working position… (facts, evidence points, next steps)`
- Counsel: `Record submissions… (legal test, pleadings framing, authorities)`
- Expert: `Record expert analysis… (methodology, assumptions, calculations)`

Helper text:
- `Use @ to refer a point to a named team member.`

### 5.4 Empty states
- Lane empty state title: `No notes recorded in this lane.`
- Core body: `Record the working position and outstanding steps.`
- Counsel body: `Record submissions suitable for drafting and pleading.`
- Expert body: `Record analysis suitable for expert reporting.`

### 5.5 Optional template chips (prefill text only)
Core:
- `Position:`
- `Steps:`
- `Evidence required:`

Counsel:
- `Legal test:`
- `Authorities:`
- `Proposed pleading language:`

Expert:
- `Assumptions:`
- `Methodology:`
- `Conclusion:`

## 6) UI layout (wireframe)

### Heads of Claim — discussion panel
```
[Discussion]
Core | Counsel | Expert
---------------------------------
Pinned: Agreed position
• ... pinned note ...
---------------------------------
[Comments list for selected lane]
• Author · 2h   [COUNSEL]
  ...
---------------------------------
[ Composer ]
<textarea placeholder="Record submissions…">...</textarea>
Post note to Counsel
Use @ to refer a point to a named team member.
```

### Evidence repository — evidence detail panel
```
[Evidence notes]
Core | Counsel | Expert
Linked to 3 Heads of Claim   (Open in claim context)
---------------------------------
[Comments list]
---------------------------------
<textarea placeholder="Record expert analysis…">...</textarea>
Post note
```

## 7) Notes on permissions (MVP)
- For MVP, lanes do not change permissions.
- Where `HeadOfClaim.case_id` exists, `case_users` can be used as the team-membership authority (this is already used for the mentions list).

## 8) Phase 2 (optional): confidentiality by lane
If you later decide that Counsel lane must be hidden from Experts:

Option A (simple, 1 lane per user):
- Add `collaboration_lane` to `case_users`.

Option B (better, multi-lane per user):
- Add a junction table `case_user_lanes(case_user_id, lane)`.

Then enforce in `claims_module.py`:
- Before reading/writing comments for a given lane, verify the current user has access to that lane.

---

## Appendix: References
- Core tables:
  - `heads_of_claim`, `contentious_matters`, `evidence_items`, `item_claim_links`, `item_comments`, `comment_read_status`, `comment_reactions`, `case_users`
- Primary implementation files:
  - `vericase/api/app/models.py`
  - `vericase/api/app/claims_module.py`
  - `vericase/ui/contentious-matters.html`
  - `vericase/ui/evidence.html`
