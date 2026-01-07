# AI Refinement Wizard UI Review

## Executive Summary
`ai-refinement-wizard.html` delivers a strong, design-consistent “guided cleanup” workflow for email datasets (spam/newsletters, duplicates, cross-project leakage, unknown domains/people). The core interaction model is good: a step sidebar + AI “question cards” + optional item lists with select-all/none.

The main UX gaps are:
- **Progress steps don’t stay marked complete** (a logic bug caused by `setActiveStep()` clearing `.completed`).
- **Back navigation discards previous answers**, forcing re-selection.
- **A11y/keyboard support is limited** because primary controls are div-clickable cards.
- **Summary is incomplete** (“Estimated emails to remove: TBD”) and the `refined=true` query param appears unused client-side.

---

## ✅ Strengths

### 1) Design system & branding consistency
- Consistent use of the existing brand stack (`brand-styles.css`, `design-system.css`) and warm palette.
- Sidebar + card layout feels coherent with the rest of the app (dashboard/correspondence).
- Strong visual hierarchy: “AI Analyst” question header → detected items → response choices → action bar.

### 2) Workflow clarity (progress + context)
- Progress sidebar is clear and domain-specific (AI Analysis → People/Domain validation → Projects/Spam/Duplicates → Review).
- Live stats (emails analyzed / spam / duplicates / unknown domains) reinforce why the user is being asked questions.
- Breadcrumb injection via `VericaseShell.inject()` is a good fit for app-shell navigation.

### 3) Detected-items UI is strong
- Item cards include practical metadata: email count, confidence label, description, and sample emails.
- “Select All / Select None” supports high-volume triage.
- Sorting logic improves scanability (domains A→Z; otherwise recommended action → volume → name).

### 4) Background analysis handling is thoughtful
- `pollSessionUntilReady()` supports long-running analysis without forcing the user to manually refresh.
- Progress text uses `progress_percent` when available and falls back gracefully.

### 5) Dashboard entry-point gating (good UX)
`dashboard.html`’s `openAIRefinement()` prevents avoidable failures:
- If no profile is selected, it shows a contextual modal and routes the user to `workspace-setup.html`.
- It checks `/api/ai/status` and prompts the user to configure an AI provider before launching the wizard.

---

## ⚠️ Issues & Recommendations

### 1) **Progress steps don’t remain completed** (High priority)
**Problem:** `setActiveStep()` currently clears both `active` and `completed` classes on every step, so any `markStepComplete()` call is effectively undone on the next render.

**Why it matters:** Users lose a key “sense of progress” signal, especially in longer sessions.

**Recommendation:** Only clear `.active` in `setActiveStep()`.

```js
function setActiveStep(stepId) {
  document.querySelectorAll('.step').forEach((s) => {
    s.classList.remove('active');
  });
  document.getElementById(stepId)?.classList.add('active');
}
```

### 2) **Back navigation loses prior answers** (High priority)
**Problem:** `goBack()` pops `answeredQuestions` and calls `showQuestion()`, but the UI resets `selectedItems` and `selectedOption` every time, so users can’t “edit” an answer—they must redo it.

**Recommendation:** When navigating back, load the previous answer (if present) and pre-select:
- the option card
- the selected items

This can be done by storing answers keyed by `question_id`, and using them in `showQuestion()`.

### 3) **Accessibility: primary controls are not keyboard-friendly** (High priority)
Current patterns:
- option cards are clickable `<div>`s (no `role`, no `tabindex`, no Enter/Space support)
- item cards are clickable `<div>`s (checkbox helps somewhat, but the card itself isn’t keyboard reachable)

**Recommendations:**
- Convert option cards to `<button type="button">` or add `role="radio"` and keyboard handling.
- Convert item cards to `<button type="button">` or add `role="checkbox"`, `aria-checked`, `tabindex="0"`.
- Add focus-visible styling for card-like controls.

### 4) **Summary is incomplete: “Estimated emails to remove: TBD”** (Medium priority)
This is a credibility hit at the exact moment you need confidence to click “Apply Refinement”.

**Recommendation:** calculate estimates from `detected_items[].email_count` (sum counts for excluded items) and show it in the summary.

### 5) **`refined=true` param appears unused** (Medium priority)
The wizard routes to:
- `correspondence-enterprise.html?...&refined=true`

But a search across UI JS did not find any consumer for `refined`.

**Options:**
1) Use it: on correspondence load, detect `refined=true` and show a toast like “Refinement applied—refreshing results”.
2) Remove it: keep URLs minimal and avoid implying behavior that isn’t real.

### 6) **Return-to-dashboard link drops explicit context** (Medium priority)
On success, the button uses `window.location.href='dashboard.html'` (no `caseId`/`projectId`). The dashboard likely still works due to localStorage, but deep-linking is less deterministic.

**Recommendation:** either:
- link to `dashboard.html${buildContextQuery()}` for symmetry, or
- use the shell’s context-aware navigation helper if that’s the app convention.

### 7) **Auth/error UX could be more directive** (Medium priority)
If the token is missing/expired, the wizard may show a generic “Analysis Failed” state.

**Recommendation:** detect missing token early and provide a clear CTA (e.g., “Go to Login”) instead of relying on backend error strings.

### 8) **Code organization / maintainability** (Lower priority, but worth tracking)
This page includes large inline CSS + sizeable inline JS. It’s not as large as `correspondence-enterprise.html`, but the same maintainability concerns apply.

A pragmatic next step (without a big refactor): extract:
- wizard CSS into `styles/ai-refinement-wizard.css`
- wizard JS into `scripts/ai-refinement-wizard.js`

---

## 🎯 Quick Wins (high impact / low effort)
1) Fix `setActiveStep()` so completed steps stay visible.
2) Add keyboard semantics to option/item cards (role/tabindex + Enter/Space).
3) Replace `alert()` usage with `VericaseUI.Toast` for consistent UX.
4) Fill in “Estimated emails to remove” using known counts.
5) Decide whether `refined=true` should trigger a toast/filter on correspondence.

---

## Cross-screen flow notes (Wizard ⇄ Dashboard ⇄ Correspondence)
- **Dashboard → Wizard:** `openAIRefinement()` is a good gatekeeper (profile selected + AI configured) and routes to `ai-refinement-wizard.html?projectId=...` or `?caseId=...`.
- **Wizard → Correspondence:** `buildCorrespondenceUrl()` preserves context and adds optional params.
- **Wizard → Dashboard:** success CTA returns to `dashboard.html` (consider adding explicit context query for deterministic deep linking).

---

## Conclusion
The AI Refinement Wizard is already a strong UI: it looks like VeriCase, feels purposeful, and supports both quick triage and deep review. Addressing the progress-step bug, back-navigation state, and basic accessibility semantics would materially improve trust and usability with minimal implementation cost.
