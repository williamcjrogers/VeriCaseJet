
# VeriCase — Configuration Wizard (Initial Profile Setup)
**Scope:** First‑run wizard for creating a profile by adding Users, or setting up a **Project** or a **Case**.  
**Audience:** Partners, Case Leads, Designers, and Developers (plain‑language spec).  
**Version:** 1.0

---

## 0) Entry Screen — “Create Profile”
**Goal:** Make it obvious there are three starting paths and that *Project* and *Case* are different.

```
[ Create Profile ]
Choose what you want to do:
( ) Add Users / Team
( ) Set up a Project (discovery / live project — not yet a formal legal case)
( ) Set up a Case (formal dispute record)

[Continue]
```

- **Helper copy beneath options:**
  - **Project:** Best for discovery or live projects where we’re gathering material to see if a case exists.
  - **Case:** Use when a dispute is formalising (adjudication, litigation, arbitration, etc.).
  - You can convert a Project into a Case later (nothing lost).

**Global wizard controls (all paths):** `[Back]  [Save Draft]  [Cancel]  [Continue]`

---

## 1) Add Users / Team (optional first step)
A simple two‑column table to capture people quickly. You can also skip and add later.

**Table (free entry):**
- **Column 1:** Role/Area (e.g., Partner, Case Lead, Reviewer, Data Steward, PM)
- **Column 2:** Name / Organisation (free entry)

*(Optional extra column for email can be enabled later; keep this screen minimal.)*

---

## 2) Project Setup (discovery or live project)
> **Intent:** This is *not yet a legal position*. We’re collecting context to refine what flows into **Correspondence** later.

### 2.1 Project Identification
- **Project Name** *(mandatory)*
- **Project Code** *(mandatory)*
- **Start Date** *(optional)* — **tooltip:** “Ensure all pre‑commencement and relevant tendering period is accounted for.”
- **Completion Date** *(optional)*

**Validation:**
- Project Name: 2–200 chars.
- Project Code: unique within tenant (allow letters/numbers/`-`/`_`/`/`).
- If both dates provided: Completion Date must be ≥ Start Date.
- UK date format in UI: **dd/mm/yyyy**

### 2.2 Key Stakeholders & Parties
**Heading:** “Key Stakeholders & Parties”  
**Guidance note:** “Examples include United Living and names of: Employer’s Agent, Client, Council, NHBC, Subcontractors, etc.”

**Two‑column table (linked):**
- **Column 1 (Role — dropdown):** Main Contractor, Council, Employers Agent, Project Manager, Client, Building Control, Subcontractor, Client Management Team, **Custom** (free text)
- **Column 2 (Name — free text):** Name/organisation corresponding to the selected role

**Default row:**  
- Column 1 = **Main Contractor**  
- Column 2 = **United Living** *(pre‑populated)*

**Behaviours:**
- [+ Add row] (unlimited)
- [Delete] on any non‑default row
- **Search-as-you-type** suggestions for repeat entries (e.g., councils, firms)

### 2.3 Keywords (Heads of Claim / Relevant words)
**Guidance note:** “Populate with keywords relevant to your potential claims / heads of claim. Include common variations.”

**Two‑column table:**
- **Column 1 (Keyword):** pre‑populated options + custom
- **Column 2 (Variations/Synonyms — comma‑separated):** e.g., *Section 278 → “Section 278, Highways Agreement, Section 106”*

**Pre‑populated list:** Relevant Event; Relevant Matter; Section 278; Delay; Risk; Change; Variation; **Custom**

**Behaviour:**
- Variations are treated as equivalent to the primary keyword for auto‑tagging and filtering in Correspondence.

### 2.4 Contract Type
- **Dropdown:** JCT, NEC, FIDIC, PPC, **Custom**
- If **Custom**, show a short free‑text field.

### 2.5 Review & Confirm
- Summary panel displaying: Identification, Stakeholders, Keywords, Contract Type
- Edits are inline or via “Edit” buttons per section
- CTA: `[Create Project]`

**After Create:** Land on **Upload & Ingest** (PST later / EML‑MSG now) or go to **Correspondence** if data already exists.

---

## 3) Case Setup (formal dispute)
> **Intent:** Very similar to Project but with legal framing and a few additional fields. The **Keywords** section remains identical.

### Label choice: “Dispute Type” alternative
Use **“Resolution Route”** (plain and neutral) or **“Proceeding Type”**. In UI label: **Resolution Route**.  
*(Dropdown values remain as provided.)*

### 3.1 Case Identification
- **Case ID** *(optional but recommended)*
- **Case Name** *(mandatory)*
- **Resolution Route (dropdown):** adjudication, litigation, arbitration, mediation, settlement, TBC, **Custom** (free entry appears if selected)
- **Claimant** *(free entry)*
- **Defendant** *(free entry)*
- **Case Status (dropdown):** discovery, preparation, pre‑adjudication, Live Adjudication, Pre‑action Protocol, Litigation Preparation, Live Litigation, **Custom** (free entry)

**Additional:**
- **Client** *(free entry)* — top‑level client party for whom we are acting
- **Legal Team** *(two‑column free entry section)*  
  - **Column 1:** Role/Area (free text, e.g., Partner, Counsel, Associate, Paralegal)  
  - **Column 2:** Name/Organisation (free text)

### 3.2 Heads of Claim (Case view)
**Three‑column table:**
- **Column 1: Head of Claim** *(free entry)*
- **Column 2: Status (dropdown):** Discovery; Merit Established; Collating Evidence; Bundling; Complete; **Custom**
- **Column 3: Actions (short free text):** e.g., “Request PM notes”, “Add Programmes Q4 2024”, “Draft chronology”

**Behaviours:**
- [Add row], [Delete row]
- Status chips visible on Correspondence filters later

### 3.3 Keywords (identical to Project)
- **Column 1:** Keyword (pre‑populated list + custom)  
- **Column 2:** Variations/Synonyms  
*(This drives auto‑tagging in Correspondence exactly as for Projects.)*

### 3.4 Case Deadlines
**Three‑column table:**
- **Column 1:** Deadline / Task (free entry) — e.g., “Respondent’s evidence”, “Position statement”
- **Column 2:** Description / Notes (free entry)
- **Column 3:** **Date** (UK date picker, dd/mm/yyyy)

**Optional behaviours:**
- Reminders (toggle per deadline: none / 7d / 3d / 24h)
- Export deadlines to calendar (future enhancement)

### 3.5 Review & Confirm
- Summary of Case Identification, Legal Team, Heads of Claim, Keywords, Case Deadlines
- CTA: `[Create Case]`

**After Create:** Land on **Correspondence** (case‑scoped) or **Bundles** if preparing an export.

---

## 4) Wireframe (Lo‑fi, text)
> **Legend:** ☐ input; ⌄ dropdown; 🛈 tooltip; 🧩 chip; ➕ add row; ✖ delete; ★ primary CTA

### 4.1 Project — Key screens
```
Header: VeriCase | New Project                                 [Save Draft] [Cancel]

Step 1 of 3 — Identification
  ☐ Project Name *                         (min 2 chars)
  ☐ Project Code *                         (unique)
  ☐ Start Date (dd/mm/yyyy)  🛈 “Ensure all pre‑commencement and relevant tendering period is accounted for.”
  ☐ Completion Date (dd/mm/yyyy)

[Back]                                   [Continue ★]

Step 2 of 3 — Stakeholders & Keywords
  Section: Key Stakeholders & Parties  🛈 “Examples: United Living; Employer’s Agent; Client; Council; NHBC; Subcontractors.”
   Role ⌄ [Main Contractor | Council | Employers Agent | Project Manager | Client | Building Control | Subcontractor | Client Management Team | Custom]
   Name ☐ [free text]
   Default row: [Main Contractor]  [United Living]
   ➕ Add row   ✖ Delete row

  Section: Keywords (Heads of Claim / Relevant words)  🛈 “Add keywords plus variations relevant to potential claims.”
   Keyword ☐ [Relevant Event | Relevant Matter | Section 278 | Delay | Risk | Change | Variation | Custom]
   Variations ☐ [comma‑separated variations]  (e.g., “Section 278, Highways Agreement, Section 106”)
   ➕ Add row   ✖ Delete row

[Back]                                   [Continue ★]

Step 3 of 3 — Contract
  Contract Type ⌄ [JCT | NEC | FIDIC | PPC | Custom]  (if Custom → ☐ free text)

Review Summary
[Create Project ★]                       [Back]
```

### 4.2 Case — Key screens
```
Header: VeriCase | New Case                                     [Save Draft] [Cancel]

Step 1 of 4 — Case Identification
  ☐ Case Name *                          (min 2 chars)
  ☐ Case ID                              (optional)
  Resolution Route ⌄ [adjudication | litigation | arbitration | mediation | settlement | TBC | Custom]
   (Custom → ☐ free text)
  ☐ Claimant                             (free entry)
  ☐ Defendant                            (free entry)
  Case Status ⌄ [discovery | preparation | pre-adjudication | Live Adjudication | Pre-action Protocol | Litigation Preparation | Live Litigation | Custom]
   (Custom → ☐ free text)
  ☐ Client                               (free entry)

[Back]                                   [Continue ★]

Step 2 of 4 — Legal Team
  Two‑column table (all free entry)
   Role/Area ☐       Name/Organisation ☐
   ➕ Add row   ✖ Delete row

[Back]                                   [Continue ★]

Step 3 of 4 — Heads of Claim & Keywords
  Heads of Claim
   Head of Claim ☐     Status ⌄ [Discovery | Merit Established | Collating Evidence | Bundling | Complete | Custom]   Actions ☐
   ➕ Add row   ✖ Delete row

  Keywords (same pattern as Project)
   Keyword ☐ [pre‑populated + custom]     Variations ☐ [comma‑separated]

[Back]                                   [Continue ★]

Step 4 of 4 — Case Deadlines
  Deadline/Task ☐     Description ☐     Date ☐ [dd/mm/yyyy picker]
  ➕ Add row   ✖ Delete row
  (Optional reminder toggle per row)

Review Summary
[Create Case ★]                          [Back]
```

---

## 5) Guidance text (exact copy, ready to paste)

- **Project > Start Date tooltip:** “Ensure all pre‑commencement and relevant tendering period is accounted for.”
- **Project > Stakeholders guidance:** “Examples include United Living and names of: Employer’s Agent, Client, Council, NHBC, Subcontractors, etc.”
- **Keywords guidance:** “Populate with keywords relevant to your potential claims / Heads of Claim. Include common variations so nothing is missed.”
- **Case vs Project intro (entry screen):** “Project is for discovery/live project work; Case is for a formalised dispute (adjudication, litigation, etc.). You can convert a Project into a Case later.”

---

## 6) Validation & Defaults (non‑technical)

**Common:**
- Required fields show an asterisk (*) and prevent progression if empty.
- UK dates (**dd/mm/yyyy**) with a date picker.
- “Custom” in any dropdown exposes a small free‑text box.
- “Save Draft” stores partial data and allows return later.

**Project defaults:**
- Stakeholders table first row pre‑filled with **Main Contractor — United Living**.

**Case defaults:**
- None mandatory beyond **Case Name**; encourage **Case ID** if known.

---

## 7) Downstream effects (how this helps Correspondence)
- **Stakeholders** become quick filters for sender/recipient facets (e.g., filter by “Employers Agent – Calfordseaden”).
- **Keywords + Variations** drive auto‑tagging of emails/attachments and appear as filter chips (e.g., “Section 278” → hits include “Highways Agreement”).  
- **Contract Type** may enable contract‑specific labels later (e.g., “Relevant Event” for JCT).
- **Heads of Claim (Case)** surface as filters with **Status** chips to track progress (Discovery → Complete).
- **Case Deadlines** can power reminders and appear in dashboards/calendars (future enhancement).

---

## 8) Acceptance Criteria (user‑visible)
1. I can create a **Project** by entering only **Project Name** and **Project Code** (dates optional).  
2. The **Start Date** tooltip appears exactly as specified.  
3. The Stakeholders section shows **Main Contractor — United Living** by default and allows additional rows with the prescribed role list + “Custom”.  
4. The **Keywords** section accepts pre‑populated items and custom ones with variations; these appear as filters in Correspondence.  
5. I can create a **Case** with **Case Name** and populate **Resolution Route**, **Claimant**, **Defendant**, **Case Status**, **Client**, **Legal Team**, **Heads of Claim** (with Status & Actions), and **Case Deadlines** (three columns with UK date picker).  
6. “Custom” in any dropdown opens a free‑text entry and persists correctly.  
7. “Save Draft” works at any step and resumes the wizard with all entries intact.  
8. After create, I’m taken to the next logical screen (Upload/Ingest for Projects, Correspondence for Case) and all entered data is available as filters/tags.

---

## 9) Implementation notes (UI components)
- Tables should support ➕ add / ✖ delete per row; default values where stated.
- Dropdown + “Custom” pattern used consistently.
- Guidance notes appear under section titles; tooltips for field‑level hints (e.g., Start Date).
- Keep screens uncluttered: split steps exactly as outlined to avoid long forms.
- Mobile/Small screens: stack inputs vertically; keep ➕/✖ within each row.

---

## 10) Future (optional enhancements)
- Convert Project → Case action that pre‑populates Case fields from Project.
- Role directory for stakeholders with autocomplete from prior projects.
- Calendar integration for Case Deadlines.
- Import/export CSV for Stakeholders, Keywords, Heads of Claim, Deadlines.
