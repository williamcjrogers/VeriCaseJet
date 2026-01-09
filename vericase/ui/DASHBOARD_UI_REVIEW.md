# Dashboard UI Review (`dashboard.html`)

## Executive Summary
`dashboard.html` is the context-scoped “Project Dashboard” view (for a selected project/case profile). It’s designed around **action-first navigation** (Upload / Evidence / Correspondence / Research / Chronology / Programme / Delays / Refine) plus a set of status widgets.

The page is visually strong and consistent with the VeriCase brand system, but has a few recurring UX/implementation risks:
- **Keyboard/A11y is inconsistent** (some action cards are keyboard-enabled; most are click-only `<div>`s).
- A few flows use **`prompt()` / `alert()`**, which breaks the otherwise premium design language.
- **Context determinism relies heavily on localStorage**, and many links do not include explicit `?projectId=` / `?caseId=`.
- The file is large with substantial inline CSS/JS, which raises ongoing maintainability cost.

---

## Page Structure (what it loads / how it composes)
- Loads shared UI/shell helpers: `vericase-ui.js`, `nav-shell.js`.
- Loads config/state helpers: `config.js`, `app-state.js`.
- Contains its own `top-bar` header, but hides it when `.app-shell` is present:
  - `.app-shell .top-bar { display: none; }`
  - `.app-shell .app-header-title { display: none; }` (avoids duplicate titles)
- Main content sections:
  1) Welcome banner
  2) Quick Actions grid
  3) Widgets grid
- Settings is implemented via an injected modal template string (tabs: **General** / **AI Configuration**).

---

## ✅ Strengths

### 1) Strong “action-first” information architecture
The Quick Actions grid makes the app feel operable immediately:
- Upload Evidence
- Evidence & Files
- Correspondence
- VeriCase Analysis (deep research)
- The Chronology Lense™ (+ “Build” action)
- Programme
- The Delay Ripple
- VeriCase Refine (AI-based cleanup)

### 2) Brand-consistent, premium visual language
- Welcome banner is high-quality (navy gradient + subtle radial accents).
- Card hierarchy and iconography are consistent with the rest of the UI.

### 3) AI Refinement entry point is sensibly gated
`openAIRefinement()` (used by the “VeriCase Refine” card) protects the user from common dead-ends:
- Requires a selected profile.
- Checks AI availability via `/api/ai/status` before routing to `ai-refinement-wizard.html`.

### 4) Responsiveness exists and is thoughtfully staged
There are multiple breakpoints down to 480px, with sensible behavior changes (toolbar stacking, grid collapsing, padding reductions).

---

## ⚠️ Issues & Recommendations

### 1) Accessibility / keyboard interaction is inconsistent (High priority)
Observed pattern: some cards include `role="button"`, `tabindex="0"`, and Enter/Space handlers, while most are just `onclick` on a `<div>`.

**Recommendation:** standardize all actionable cards to either:
- `<button type="button" class="action-card">…</button>` (preferred), or
- `<div role="button" tabindex="0">…</div>` with consistent key handlers.

### 2) `prompt()` / `alert()` usage breaks UX consistency (Medium priority)
Examples:
- Chronology builder uses `prompt()`.
- Several error paths use `alert()`.

**Recommendation:** replace with `VericaseUI` primitives (modal/toast) so the experience stays cohesive.

### 3) Context propagation & deep-link determinism (Medium priority)
A number of navigation actions rely on localStorage state for `projectId`/`caseId` rather than explicit URL parameters.

**Recommendation:** for navigation actions, prefer explicit context queries (or a shell helper that generates them) so:
- back/forward navigation is more reliable,
- deep links are predictable,
- “Back to Dashboard” from other pages remains deterministic.

### 4) Settings modal: API keys in localStorage (Medium priority)
The settings modal includes a local-storage-based AI key configuration UI (OpenAI / Anthropic / Gemini / Perplexity).

**Recommendation:** make the “local testing only” nature impossible to miss (warning callout + optional “clear all keys” button).

### 5) Code organization / maintainability (Track as technical debt)
The page includes large inline CSS and sizeable inline JS, plus injected HTML for settings.

**Recommendation:** (only if/when refactoring is planned)
- Extract dashboard-specific CSS into `vericase/ui/styles/dashboard.css`.
- Extract dashboard JS into `vericase/ui/scripts/dashboard.js`.

---

## Cross-screen flow notes
- AI Refinement wizard success CTA returns to `dashboard.html`.
- “Home” button routes to `master-dashboard.html`.
- “VeriCase Refine” routes to `ai-refinement-wizard.html`, which can route to `correspondence-enterprise.html`.
