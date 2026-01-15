# VeriCase User Guide (Verified)

This guide describes how to use the VeriCase UI **based on what the shipped UI pages actually do** (under `vericase/ui/`) and the API endpoints they call. It’s intentionally practical and avoids “wishful features”.

If you’re running the Docker stack locally, common entry points are:

- Control Centre (Home): `http://localhost:8010/ui/control-centre.html`
- Workspaces (Directory): `http://localhost:8010/ui/workspace-hub.html`
- Quick Access (Flat list): `http://localhost:8010/ui/master-dashboard.html`
- Overview (Project/Case context): `http://localhost:8010/ui/dashboard.html`
- API docs: `http://localhost:8010/docs`

---

## Key concepts

### Workspace vs Project vs Case

- **Workspace**: a top-level container that groups projects/cases and provides a workspace overview for browsing, stats, and navigation.
- **Project**: a matter container used throughout the app for correspondence, evidence, programme uploads, claims modules, etc.
- **Case**: a case-centric container used by several modules (notably delays, and also chronology/programme in some flows).

### Context (Project/Case selection)

Most pages operate in a **current context** (project or case). The UI will try to get this from (in order):

- the navigation shell context,
- URL query parameters (`?projectId=...` / `?caseId=...`),
- browser storage (e.g., `vericase_current_project`, `vericase_current_case`).

If you see “Please select a case/project first”, go back to **Workspaces** (or **Quick Access**) and select one.

---

## Getting started

### 1) Log in

Use `login.html` to sign in. After login, the UI stores a bearer token in browser storage (exact key names vary across pages).

### 2) Open the Control Centre (optional) and Workspaces

- **Control Centre** (`control-centre.html`): a high-level status hub that loads user/stats/activity, workspaces, and deadlines.
- **Workspaces** (`workspace-hub.html`): browse workspaces, then enter a workspace to see its projects/cases.

### 3) Create a project quickly (fast path)

On the **Overview** page (`dashboard.html`) there is a “Quick Setup” flow that creates a minimal project and then sends you straight to upload.

If you want full setup, use:

- `workspace-setup.html` (workspace creation / setup)
- `project-setup.html` or `case-setup.html` (editing a specific project/case)

---

## Core modules

## Evidence repository (`evidence.html`)

The Evidence module is a server-driven grid with:

- **Upload** (direct upload endpoint) and evidence listing.
- **Collections** (including hierarchical folders/subfolders).
- **Bulk actions** (e.g., exclude/delete in bulk).
- **Detail panel** with:
  - full metadata view,
  - preview/text extraction (the UI can trigger extraction when needed),
  - **suggestions** for the item.

Common workflows:

- Upload evidence documents.
- Categorize evidence (including automated categorization rules).
- File evidence into collections.
- Open an item to view extracted text/metadata and suggestions.

## Correspondence (`correspondence-enterprise.html`)

Correspondence is an AG Grid Enterprise “server-side row model” view intended for large volumes (100k+ rows). It supports:

- browsing/searching/filtering emails in-grid,
- opening an email detail panel,
- working with attachments (download/preview),
- bulk operations (exclude / set category / add keywords),
- exporting emails,
- linking emails to claims/matters.

### Embedded assistant panel

The correspondence page includes a right-side “VeriCase Assistant” panel with:

- **Quick** query (Ctrl+Enter)
- **Deep** research (Ctrl+Shift+Enter)

The assistant is used for “ask about your evidence” style queries, scoped by the current context.

## PST Upload (`pst-upload.html`)

Use PST Upload to ingest email correspondence.

The UI supports multipart upload steps (init → part URLs → upload parts → complete) and also supports bulk evidence upload endpoints.

## Contract Intelligence Upload (`contract-upload.html`)

Use this page to upload a **PDF contract** and have the system extract and analyze clauses.

What you do in the UI:

- Select a **Contract Family** and then a **Contract Suite/Type** (the upload zone is disabled until a type is selected).
- Drag & drop a PDF (or browse and select a PDF).
- Watch the processing phases (upload → extract → analyze → vectorize).

What you get back:

- A results panel showing:
  - total clauses extracted,
  - a “high risk” clause count (high/critical),
  - extracted metadata (when available),
  - a list of clauses including clause number/title/text, risk badge, and entitlement tags.
- An upload history table (filtered by current project/case context when available).

## Contentious Matters & Heads of Claim (`contentious-matters.html`)

This module implements:

### Contentious Matters

- Create, edit, delete, and list “matters”.
- Set status/priority/value/currency.

### Heads of Claim

- Create, edit, delete, list, and open a specific claim.
- Attach claims to a matter.

### Linking

You can link:

- **Evidence** items
- **Correspondence** emails

…to either a contentious matter or a specific head of claim.

### Collaboration (claim discussion)

Inside a claim you can:

- post threaded comments (with replies),
- filter by “lane” (e.g., core/counsel/expert),
- pin/unpin comments,
- react to comments,
- see unread counts and mark a claim discussion as read,
- view “evidence notes” associated with linked items,
- view a claim activity feed,
- load team members for @mentions,
- set notification preferences.

### Claim AI helpers

Within a claim, the UI exposes AI helper actions including:

- summarize claim discussion,
- suggest evidence to link,
- draft a reply,
- auto-tag a comment.

## Collaboration Hub (`collaboration-workspace.html`)

This is a collaboration “home” for discussion and activity, scoped to the **current project or case**.

What it includes:

- **Lane tabs** (e.g., core / counsel / expert) to segment discussion.
- **Discussion threads** (with a large page size; intended as a working hub rather than a “one message at a time” chat).
- **Activity feed** showing recent changes/events.

Focus mode (link to a specific claim/matter):

- If opened with `focusType`/`focusId` in the URL, the page switches from workspace discussion to the **claim** or **matter** discussion threads.
- It also provides a quick link back into `contentious-matters.html` with the relevant claim/matter pre-selected.

Case-only extra:

- When the current context is a **case**, the hub also loads a “team” list for that case.

## Programme (`programme.html`)

Programme supports:

- uploading programmes,
- comparing programmes,
- loading programme data per project/case.

## The Delay Ripple (`delays.html`)

Delay Ripple is **case-centric**.

It supports:

- listing and filtering delay events,
- adding delay events (planned vs actual finish, cause, critical path flag),
- a detail panel for a delay,
- starting an AI delay analysis session and then analyzing the current delay set.

## The Chronology Lense™ (`chronology-lense.html`)

Chronology Lense provides:

- a chronology table (sorted, filterable by search/type/date range),
- CRUD for chronology events,
- importing events from a chosen source (with date range),
- exporting events to CSV,
- jumping to a visual timeline (`project-timeline.html`).

## VeriCase Analysis (Deep Analysis) (`vericase-analysis.html`)

This page runs a structured “deep analysis” session against a selected **project** (and optionally the current case).

Typical flow:

1) Enter a research topic/question.
2) Optionally select focus areas (e.g., chronology, causation, liability, quantum, communications, variations, programme, witnesses).
3) Start analysis.
4) The system creates a research plan and pauses at a **plan review** stage.
5) You can:
   - **Approve** the plan to proceed, or
   - **Request modifications** (describe what to change).
6) The page then shows progress through states (planning → researching → synthesizing → completed).
7) When complete, it renders a final report (with themes and metadata such as models used).

The page also includes a **history** sidebar of previous analysis sessions and lets you reload a prior session.

---

## AI features

### VeriCase Assistant page (`copilot.html`)

A dedicated assistant interface with:

- chat history,
- “mode” selector,
- model selection UI,
- new chat controls.

### AI Refinement Wizard (`ai-refinement-wizard.html`)

A guided flow that calls AI refinement endpoints (analyze/answer/session management) and is designed to operate against the current project/case context.

### Settings: AI provider configuration

On the **Overview** page (`dashboard.html`), there is a settings modal that checks AI provider status and can direct you to AI setup.

Admin configuration lives in `admin-settings.html` (AI models/functions/tools testing + provider configuration).

---

## Administration

### Control Centre (`control-centre.html`)

Control Centre loads:

- user profile summary (name/email/role),
- stats (emails/evidence/documents over time windows),
- activity feed (my/team),
- deadlines (from dashboard overview),
- pending user approvals (if you have access).

### Admin user management

- `admin-approvals.html`: approve pending users and view pending lists.
- `admin-users.html`: user listing and user operations.

### Invitations

The UI supports invitation-based registration (`register.html?invite=...`).

See also: `docs/USER_INVITATIONS_QUICK_GUIDE.md` (API-focused).

---

## Profile & security

### Profile (`profile.html`)

Profile supports:

- changing password,
- logging out,
- viewing/managing sessions.

### Password reset (`password-reset.html`)

Supports requesting a reset and completing a reset.

---

## Troubleshooting

- **“No profile selected” / “Select a case/project first”**: go to `workspace-hub.html` (or `master-dashboard.html`) and pick a workspace + project/case.
- **AI buttons do nothing / show “not configured”**: open settings and configure at least one AI provider (admin settings page controls provider/model setup).
- **Correspondence grid is empty**: confirm you uploaded PST and processing completed; ensure you’re in the correct project/case context.
- **Evidence preview missing**: open the evidence item detail; the UI can trigger metadata/text extraction and then re-load the full detail view.

---

## “What page should I use for…?” (quick index)

- Browse / create workspaces: `workspace-hub.html`, `workspace-setup.html`
- Home / directory: `control-centre.html` (Home), `workspace-hub.html` (Workspaces)
- Quick Access: `master-dashboard.html` (flat list of projects/cases)
- Project/Case Overview: `dashboard.html`
- Upload correspondence: `pst-upload.html`
- Browse correspondence: `correspondence-enterprise.html`
- Evidence repository: `evidence.html`
- Claims & disputes: `contentious-matters.html`
- Programme: `programme.html`
- Delay analysis: `delays.html`
- Chronology: `chronology-lense.html` (+ `project-timeline.html`)
- Contract intelligence upload: `contract-upload.html`
- Assistant: `copilot.html`
- Admin: `admin-settings.html`, `admin-users.html`, `admin-approvals.html`
