# Workspace → Project/Case Navigation Refactor Plan

## Executive Summary

This plan addresses the "disjointed" workflow from Workspace Hub to Project/Case Overview by establishing **workspace containment** as a first-class navigation principle. The refactor is divided into **9 phases (0-7 + 3B)** with clear dependencies.

**Key Additions:**
- **Phase 3:** Sidebar workspace indicator (visible context)
- **Phase 3B:** Visual continuity & branding consistency (prevents "new app" feeling)
- **Phase 5:** Workspace ↔ Project integration with quick links to Documents/About/Purpose

**Estimated Scope:** 12 files, ~350-400 lines of changes

---

## Current Architecture Understanding

The `workspace-hub.html` operates in two modes:

1. **Directory Mode** (`/ui/workspace-hub.html`) — Lists all workspaces as cards
2. **Workspace Detail Mode** (`/ui/workspace-hub.html?workspaceId=xxx`) — Shows a specific workspace with tabs:
   - **Projects & Cases** — Project/Case tiles
   - **Deadlines** — Aggregated deadlines
   - **Documents** — Uploaded documents with AI ingestion
   - **About** — AI-powered workspace context & Q&A (critical)
   - **Purpose** — Baseline instructions & deliverables tracking (critical)
   - **Team** — Members
   - **Collaboration** — Notes & activity

### Current Issues Identified

| Issue | Location | Impact |
|-------|----------|--------|
| **Sidebar doesn't reflect workspace context** | `nav-shell.js` | User can't see which workspace they're in from sidebar |
| **"Develop Case" emphasized over "Open"** | `workspace-hub.html:3459` | Visual hierarchy mismatch (`primary` class on wrong button) |
| **"Open" → Project Dashboard feels disconnected** | Navigation flow | No clear link back to workspace tabs (Documents, About, Purpose) |
| **About/Purpose tabs are hidden gems** | UX flow | Critical AI features not accessible from Project Overview |

---

## Phase 0: Foundation — Context Storage Consolidation

**Goal:** Establish a single source of truth for navigation context before making UI changes.

### 0.1 Create Unified Context Manager

**File:** `vericase/ui/context-manager.js` (NEW)

```javascript
// Single canonical storage for navigation context
const VericaseContext = {
  KEYS: {
    workspaceId: 'vericase_context_workspace_id',
    workspaceName: 'vericase_context_workspace_name',
    projectId: 'vericase_context_project_id',
    projectName: 'vericase_context_project_name',
    caseId: 'vericase_context_case_id',
    caseName: 'vericase_context_case_name',
    profileType: 'vericase_context_profile_type'
  },
  
  set(key, value) { ... },
  get(key) { ... },
  clear(scope) { ... },  // 'all' | 'project' | 'case'
  
  // Migration: reads from legacy keys, writes to canonical
  migrate() { ... }
};
```

### 0.2 Migrate Legacy Keys

**Files to Update:**
- `nav-shell.js` — Replace direct `localStorage` calls with `VericaseContext`
- `workspace-hub.html` — Use `VericaseContext.set()` for workspace/project/case
- `project-setup.html` — Replace 6 duplicate `localStorage.setItem()` calls
- `case-setup.html` — Replace duplicate storage calls
- `dashboard.html` — Read from `VericaseContext`
- `projectdashboard.html` — Read from `VericaseContext`

### 0.3 Deprecation Path

```javascript
// In context-manager.js
const LEGACY_KEYS = {
  'currentProjectId': 'projectId',
  'vericase_current_project': 'projectId',
  'projectId': 'projectId',
  // ... map all legacy keys
};

// On read, check legacy keys and migrate if found
```

**Testing Checkpoint:**
- [ ] Open project in Tab 1, different project in Tab 2
- [ ] Refresh Tab 1 — should show correct project (not Tab 2's)
- [ ] All pages still function with new context manager

---

## Phase 1: Breadcrumb Standardization

**Goal:** Single breadcrumb system that always shows the full hierarchy.

### 1.1 Define Breadcrumb Contract

**File:** `nav-shell.js` — Add breadcrumb builder utility

```javascript
VericaseShell.buildHierarchicalBreadcrumbs = function(options) {
  // options: { includeHome, includeWorkspace, workspaceId, workspaceName, entityName, entityType }
  const crumbs = [];
  
  if (options.includeHome) {
    crumbs.push({ label: 'Control Centre', url: 'control-centre.html', icon: 'fa-compass' });
  }
  
  crumbs.push({ label: 'Workspaces', url: 'workspace-hub.html', icon: 'fa-layer-group' });
  
  if (options.workspaceId && options.workspaceName) {
    crumbs.push({ 
      label: options.workspaceName, 
      url: `workspace-hub.html?workspaceId=${options.workspaceId}`,
      icon: 'fa-folder'
    });
  }
  
  if (options.entityName) {
    crumbs.push({ label: options.entityName });  // Current page, no URL
  }
  
  return crumbs;
};
```

### 1.2 Update Breadcrumb Injection Points

| File | Current | Target |
|------|---------|--------|
| `workspace-hub.html` | In-page `#hub-breadcrumb` + shell | Shell only |
| `project-setup.html` | In-page only | Shell via `inject()` |
| `case-setup.html` | In-page only | Shell via `inject()` |
| `dashboard.html` | Shell (missing workspace) | Shell with workspace name |

### 1.3 Remove Edit Mode Breadcrumb Hiding

**File:** `project-setup.html`
```diff
- if (workspaceLink) workspaceLink.style.display = "none";
- if (workspaceLink?.previousElementSibling) workspaceLink.previousElementSibling.style.display = "none";
+ // Workspace context remains visible in edit mode
```

**File:** `case-setup.html`
```diff
- if (workspaceLink) workspaceLink.style.display = "none";
- if (workspaceLink?.previousElementSibling) workspaceLink.previousElementSibling.style.display = "none";
+ // Workspace context remains visible in edit mode
```

### 1.4 Remove Duplicate In-Page Breadcrumb

**File:** `workspace-hub.html`
```diff
- <nav id="hub-breadcrumb" class="hub-breadcrumb" aria-label="Breadcrumb">...</nav>
+ <!-- Breadcrumbs now managed by nav-shell -->
```

**Testing Checkpoint:**
- [ ] Every page shows `Workspaces › [Workspace Name] › [Entity Name]`
- [ ] Edit mode still shows workspace name (non-clickable OK)
- [ ] No duplicate breadcrumb rows anywhere

---

## Phase 2: Workspace Context Preservation

**Goal:** Overview and setup pages maintain workspace scoping.

### 2.1 Pass `workspaceId` Through Navigation Chain

**File:** `workspace-hub.html` — Update navigation functions

```diff
function openProject(id) {
  const projectName = projectsData.find(p => p.id === id)?.name || '';
  VericaseContext.set('projectId', id);
  VericaseContext.set('projectName', projectName);
  VericaseContext.set('profileType', 'project');
- window.location.href = `projectdashboard.html?projectId=${encodeURIComponent(id)}`;
+ window.location.href = `projectdashboard.html?projectId=${encodeURIComponent(id)}&workspaceId=${encodeURIComponent(workspaceId)}`;
}

function openCase(id) {
  const caseName = casesData.find(c => c.id === id)?.name || '';
  VericaseContext.set('caseId', id);
  VericaseContext.set('caseName', caseName);
  VericaseContext.set('profileType', 'case');
- window.location.href = `projectdashboard.html?caseId=${encodeURIComponent(id)}`;
+ window.location.href = `projectdashboard.html?caseId=${encodeURIComponent(id)}&workspaceId=${encodeURIComponent(workspaceId)}`;
}
```

### 2.2 Update Dashboard to Receive Workspace Context

**File:** `dashboard.html` — Read workspace from URL/context

```javascript
// Near initialization
const urlParams = new URLSearchParams(window.location.search);
const workspaceId = urlParams.get('workspaceId') || VericaseContext.get('workspaceId');
const workspaceName = VericaseContext.get('workspaceName') || 'Workspace';

// Update breadcrumb injection
window.VericaseShell.inject({
  title: "",
  breadcrumbs: VericaseShell.buildHierarchicalBreadcrumbs({
    includeHome: true,
    includeWorkspace: true,
    workspaceId: workspaceId,
    workspaceName: workspaceName,
    entityName: profileType === "case" ? "Case Overview" : "Project Overview",
    entityType: profileType
  })
});
```

### 2.3 Scope Project Selector to Workspace

**File:** `dashboard.html` — Modify `loadProjects()`

```diff
async function loadProjects() {
  try {
    const headers = token ? { Authorization: `Bearer ${token}` } : {};
+   const workspaceId = VericaseContext.get('workspaceId');
+   const endpoint = workspaceId 
+     ? `${apiUrl}/api/workspaces/${workspaceId}/projects`
+     : `${apiUrl}/api/projects`;
-   const response = await fetch(`${apiUrl}/api/projects`, { headers });
+   const response = await fetch(endpoint, { headers });
    if (!response.ok) throw new Error("Failed to load projects");
```

**API Note:** Ensure `/api/workspaces/{id}/projects` endpoint exists (check `workspaces.py`).

### 2.4 Add "Back to Workspace" Action

**File:** `dashboard.html` — Add navigation helper

```html
<!-- In header or action bar -->
<a id="back-to-workspace" href="#" class="btn btn-secondary">
  <i class="fas fa-arrow-left"></i> Back to Workspace
</a>

<script>
const backBtn = document.getElementById('back-to-workspace');
const workspaceId = VericaseContext.get('workspaceId');
if (workspaceId) {
  backBtn.href = `workspace-hub.html?workspaceId=${encodeURIComponent(workspaceId)}`;
} else {
  backBtn.href = 'workspace-hub.html';
}
</script>
```

### 2.5 Update Edit Mode Back Button

**File:** `project-setup.html`
```diff
backBtn.addEventListener("click", () => {
- window.location.href = `projectdashboard.html?projectId=${encodeURIComponent(currentProjectId)}`;
+ const workspaceId = VericaseContext.get('workspaceId');
+ if (workspaceId) {
+   window.location.href = `workspace-hub.html?workspaceId=${encodeURIComponent(workspaceId)}`;
+ } else {
+   window.location.href = `projectdashboard.html?projectId=${encodeURIComponent(currentProjectId)}`;
+ }
});
```

**File:** `case-setup.html` — Same pattern

**Testing Checkpoint:**
- [ ] Open project from workspace → Overview shows workspace name in breadcrumb
- [ ] Project selector on Overview only shows projects from that workspace
- [ ] "Back to Workspace" returns to correct workspace hub
- [ ] Edit → Back returns to workspace hub, not overview

---

## Phase 3: Sidebar Workspace Context Indicator (CRITICAL)

**Goal:** Sidebar should display which workspace the user is currently in.

### 3.1 Add Workspace Indicator to Sidebar

**File:** `nav-shell.js` — Add workspace display below "Current Project"

```javascript
// In buildSidebarContent() or equivalent
function renderWorkspaceIndicator() {
  const workspaceId = VericaseContext.get('workspaceId');
  const workspaceName = VericaseContext.get('workspaceName');
  
  if (!workspaceId || !workspaceName) return '';
  
  return `
    <div class="sidebar-context-indicator workspace-indicator">
      <div class="context-label">CURRENT WORKSPACE</div>
      <a href="workspace-hub.html?workspaceId=${encodeURIComponent(workspaceId)}" 
         class="context-value" title="Go to ${escapeHtml(workspaceName)}">
        <i class="fas fa-layer-group"></i>
        <span>${escapeHtml(workspaceName)}</span>
        <i class="fas fa-chevron-right context-arrow"></i>
      </a>
    </div>
  `;
}
```

### 3.2 Add CSS for Workspace Indicator

**File:** `nav-shell.js` (inline styles) or `design-system.css`

```css
.sidebar-context-indicator.workspace-indicator {
  margin-bottom: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border-subtle);
}

.workspace-indicator .context-value {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--vericase-teal);
  text-decoration: none;
  font-weight: 500;
  padding: 6px 10px;
  border-radius: 6px;
  transition: background 0.15s;
}

.workspace-indicator .context-value:hover {
  background: rgba(var(--vericase-teal-rgb), 0.08);
}

.workspace-indicator .context-arrow {
  margin-left: auto;
  opacity: 0.5;
  font-size: 0.75rem;
}
```

### 3.3 Ensure Workspace Context is Set on Entry

**File:** `workspace-hub.html` — In workspace detail load

```diff
async function loadWorkspace(id) {
  // ... existing code ...
  const workspaceName = workspaceData.name || workspaceData.workspace_name || 'Workspace';
+ 
+ // Persist workspace context for sidebar indicator
+ VericaseContext.set('workspaceId', id);
+ VericaseContext.set('workspaceName', workspaceName);
+ 
+ // Force sidebar re-render if shell is loaded
+ if (window.VericaseShell?.refreshSidebar) {
+   window.VericaseShell.refreshSidebar();
+ }
  
  // ... rest of function ...
}
```

**Testing Checkpoint:**
- [ ] Navigate to workspace detail → Sidebar shows "CURRENT WORKSPACE: West Mews"
- [ ] Click workspace indicator → Returns to workspace detail (not directory)
- [ ] Open project → Sidebar still shows workspace indicator

---

## Phase 3B: Visual Continuity & Branding Consistency (CRITICAL)

**Goal:** Ensure Project Overview feels like the *same application* as Workspace Hub — not a new app.

### Problem Analysis

| Issue | Workspace Hub | Dashboard (Project View) |
|-------|---------------|--------------------------|
| CSS Versions | `v=9` | `v=6` ← **outdated** |
| Workspace Identity | Hero block with icon, name, code, contract type | **None** — no workspace branding |
| Background | Cream with dot pattern | White with gradient overlay |
| Header Style | `workspace-header` (rich, branded) | `welcome-banner` (generic) |
| Visual Anchor | Workspace icon prominently displayed | No workspace context |

### 3B.1 Sync CSS Versions

**File:** `dashboard.html` — Update stylesheet versions

```diff
- <link rel="stylesheet" href="brand-styles.css?v=6" />
- <link rel="stylesheet" href="design-system.css?v=6" />
+ <link rel="stylesheet" href="brand-styles.css?v=9" />
+ <link rel="stylesheet" href="design-system.css?v=9" />
```

### 3B.2 Add Workspace Identity Badge to Dashboard

**File:** `dashboard.html` — Add workspace context above welcome banner

```html
<!-- Workspace Context Badge (visible when workspace is set) -->
<div id="workspaceContextBadge" class="workspace-context-badge" style="display: none;">
  <div class="workspace-badge-icon">
    <i class="fas fa-layer-group"></i>
  </div>
  <div class="workspace-badge-info">
    <span class="workspace-badge-label">Workspace</span>
    <a href="#" id="workspaceBadgeLink" class="workspace-badge-name">Loading...</a>
  </div>
  <div class="workspace-badge-actions">
    <a href="#" id="wsDocumentsLink" class="badge-action" title="Documents">
      <i class="fas fa-folder-open"></i>
    </a>
    <a href="#" id="wsAboutLink" class="badge-action" title="About">
      <i class="fas fa-info-circle"></i>
    </a>
    <a href="#" id="wsPurposeLink" class="badge-action" title="Purpose">
      <i class="fas fa-bullseye"></i>
    </a>
  </div>
</div>

<script>
(function initWorkspaceBadge() {
  const workspaceId = VericaseContext?.get('workspaceId') || 
                      new URLSearchParams(window.location.search).get('workspaceId') ||
                      localStorage.getItem('currentWorkspaceId');
  const workspaceName = VericaseContext?.get('workspaceName') || 
                        localStorage.getItem('currentWorkspaceName');
  
  if (!workspaceId) return;
  
  const badge = document.getElementById('workspaceContextBadge');
  badge.style.display = 'flex';
  
  const baseUrl = `workspace-hub.html?workspaceId=${encodeURIComponent(workspaceId)}`;
  document.getElementById('workspaceBadgeLink').href = baseUrl;
  document.getElementById('workspaceBadgeLink').textContent = workspaceName || 'Workspace';
  document.getElementById('wsDocumentsLink').href = `${baseUrl}&tab=documents`;
  document.getElementById('wsAboutLink').href = `${baseUrl}&tab=about`;
  document.getElementById('wsPurposeLink').href = `${baseUrl}&tab=purpose`;
})();
</script>
```

### 3B.3 Add CSS for Workspace Context Badge

**File:** `dashboard.html` (inline) or `design-system.css`

```css
.workspace-context-badge {
  display: flex;
  align-items: center;
  gap: 12px;
  background: linear-gradient(135deg, rgba(var(--vericase-teal-rgb), 0.08), rgba(var(--vericase-teal-rgb), 0.03));
  border: 1px solid rgba(var(--vericase-teal-rgb), 0.15);
  border-radius: 12px;
  padding: 12px 16px;
  margin-bottom: 20px;
}

.workspace-badge-icon {
  width: 40px;
  height: 40px;
  background: var(--vericase-teal);
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-size: 1.1rem;
}

.workspace-badge-info {
  flex: 1;
}

.workspace-badge-label {
  display: block;
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-muted);
  margin-bottom: 2px;
}

.workspace-badge-name {
  font-size: 1rem;
  font-weight: 600;
  color: var(--text-primary);
  text-decoration: none;
}

.workspace-badge-name:hover {
  color: var(--vericase-teal);
}

.workspace-badge-actions {
  display: flex;
  gap: 8px;
}

.badge-action {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: rgba(var(--vericase-teal-rgb), 0.1);
  color: var(--vericase-teal);
  display: flex;
  align-items: center;
  justify-content: center;
  text-decoration: none;
  transition: all 0.15s;
}

.badge-action:hover {
  background: var(--vericase-teal);
  color: white;
}
```

### 3B.4 Harmonize Background Treatment

**File:** `dashboard.html` — Match workspace hub background

```diff
/* Subtle background pattern */
.bg-pattern {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  z-index: -1;
- background:
-   linear-gradient(135deg, rgba(var(--vericase-teal-rgb), 0.02) 0%, transparent 50%),
-   linear-gradient(225deg, rgba(184, 134, 11, 0.02) 0%, transparent 50%);
+ background-color: var(--vericase-cream);
+ background-image: radial-gradient(var(--gray-200) 1px, transparent 1px);
+ background-size: 24px 24px;
  pointer-events: none;
}
```

### 3B.5 Add Workspace Color Accent

**Optional:** Carry forward workspace's accent color (if defined)

```javascript
// If workspace has a custom color, apply it as an accent
const workspaceColor = VericaseContext?.get('workspaceColor');
if (workspaceColor) {
  document.documentElement.style.setProperty('--workspace-accent', workspaceColor);
  document.querySelector('.workspace-badge-icon')?.style.setProperty('background', workspaceColor);
}
```

**Testing Checkpoint:**
- [ ] Project Overview has same background pattern as Workspace Hub
- [ ] Workspace badge visible at top of dashboard with correct name
- [ ] Badge links (Documents/About/Purpose) navigate to correct tabs
- [ ] Visual style feels continuous — not a "new application"

---

## Phase 4: Card UI & Interaction Pattern Fixes

**Goal:** Fix visual hierarchy and consistent behavior for project/case cards.

### 4.1 Fix Button Emphasis (Swap "Open" and "Develop Case")

**File:** `workspace-hub.html` — Line ~3458

```diff
<div class="card-actions">
  <button class="card-action-btn" data-action="configure"><i class="fas fa-cog"></i> Configure</button>
- <button class="card-action-btn primary" data-action="develop-case"><i class="fas fa-gavel"></i> Develop Case</button>
- <button class="card-action-btn" data-action="open"><i class="fas fa-arrow-right"></i> Open</button>
+ <button class="card-action-btn primary" data-action="open"><i class="fas fa-arrow-right"></i> Open</button>
+ <button class="card-action-btn" data-action="develop-case"><i class="fas fa-gavel"></i> Develop Case</button>
</div>
```

**Rationale:** "Open" is the primary user intent; "Develop Case" is a secondary action.

### 4.2 Unify Card Click Behavior

**File:** `workspace-hub.html` — Simplify click handler

```diff
function handleProjectClick(e) {
  const card = e.target.closest('[data-project-id]');
  if (!card) return;
  const id = card.dataset.projectId;
  const action = e.target.closest('[data-action]')?.dataset.action;
  
  if (action === 'configure') {
    window.location.href = `project-setup.html?workspaceId=${workspaceId}&projectId=${id}`;
  } else if (action === 'develop-case') {
    window.location.href = `case-setup.html?workspaceId=${workspaceId}&projectId=${id}`;
- } else if (action === 'open') {
-   openProject(id);
- } else if (!e.target.closest('button')) {
-   selectProjectContext(id);
+ } else {
+   // Default: clicking anywhere on card opens project
+   openProject(id);
  }
}
```

### 4.3 Optional: Add Visual Selection Feedback

If card selection without navigation is still needed, add toast notification:

```javascript
} else if (!e.target.closest('button')) {
  selectProjectContext(id);
  VericaseUI.Toast.info(`"${card.querySelector('.item-title').textContent}" set as current project`);
  card.classList.add('card--selected');
  document.querySelectorAll('[data-project-id]').forEach(c => {
    if (c !== card) c.classList.remove('card--selected');
  });
}
```

### 4.4 Unify Context Indicator Click Behavior

**File:** `nav-shell.js` — Make Cases behave like Projects

```diff
const clickHandler =
  contextType === "case"
-   ? `window.location.href='master-dashboard.html'`
+   ? "VericaseShell.showCaseSelector()"
    : "VericaseShell.showProjectSelector()";
```

**Add:** `VericaseShell.showCaseSelector()` function (mirror of `showProjectSelector`)

### 4.5 Update Sidebar "Workspaces" Link to Preserve Context

**File:** `nav-shell.js` — Don't strip `workspaceId`

```diff
function buildNavUrl(page, url) {
- if (page === "workspace-hub.html") {
-   return String(url || "").split("?")[0];
- }
+ // Preserve workspace context when navigating to hub
+ if (page === "workspace-hub.html") {
+   const currentWorkspaceId = VericaseContext.get('workspaceId');
+   if (currentWorkspaceId) {
+     return `workspace-hub.html?workspaceId=${encodeURIComponent(currentWorkspaceId)}`;
+   }
+   return "workspace-hub.html";
+ }
  return url || page;
}
```

**Testing Checkpoint:**
- [ ] Clicking project card opens project (no silent selection)
- [ ] Clicking "Current Case" indicator opens case selector (same as projects)
- [ ] Sidebar "Workspaces" link returns to current workspace, not directory
- [ ] "Open" button is visually primary, "Develop Case" is secondary

---

## Phase 5: Workspace ↔ Project Overview Integration (CRITICAL)

**Goal:** Project Overview should provide easy access back to workspace-level features (Documents, About, Purpose).

### 5.1 Add "Workspace Actions" Panel to Project Overview

**File:** `dashboard.html` — Add header panel linking back to workspace tabs

```html
<!-- Workspace Quick Links (visible when workspaceId is set) -->
<div id="workspace-quick-links" class="workspace-links-panel" style="display: none;">
  <div class="panel-header">
    <i class="fas fa-layer-group"></i>
    <span id="workspace-link-name">Workspace</span>
    <a id="workspace-link-hub" href="#" class="btn btn-sm btn-outline">
      <i class="fas fa-arrow-left"></i> Back to Workspace
    </a>
  </div>
  <div class="panel-tabs">
    <a href="#" id="ws-link-documents" class="ws-quick-tab">
      <i class="fas fa-folder-open"></i> Documents
    </a>
    <a href="#" id="ws-link-about" class="ws-quick-tab">
      <i class="fas fa-info-circle"></i> About
    </a>
    <a href="#" id="ws-link-purpose" class="ws-quick-tab">
      <i class="fas fa-bullseye"></i> Purpose
    </a>
  </div>
</div>

<script>
(function initWorkspaceLinks() {
  const workspaceId = VericaseContext.get('workspaceId');
  const workspaceName = VericaseContext.get('workspaceName');
  
  if (!workspaceId) return;
  
  const panel = document.getElementById('workspace-quick-links');
  panel.style.display = 'block';
  
  document.getElementById('workspace-link-name').textContent = workspaceName || 'Workspace';
  
  const baseUrl = `workspace-hub.html?workspaceId=${encodeURIComponent(workspaceId)}`;
  document.getElementById('workspace-link-hub').href = baseUrl;
  document.getElementById('ws-link-documents').href = `${baseUrl}&tab=documents`;
  document.getElementById('ws-link-about').href = `${baseUrl}&tab=about`;
  document.getElementById('ws-link-purpose').href = `${baseUrl}&tab=purpose`;
})();
</script>
```

### 5.2 Support Tab Deep-Linking in Workspace Hub

**File:** `workspace-hub.html` — Read `tab` param on load

```diff
async function init() {
  // ... existing code ...
  
+ // Deep-link to specific tab if specified
+ const tabParam = urlParams.get('tab');
+ if (tabParam && ['projects-cases', 'deadlines', 'documents', 'about', 'purpose', 'team', 'collaboration'].includes(tabParam)) {
+   setTimeout(() => switchTab(tabParam), 100);
+ }
}
```

### 5.3 Add CSS for Workspace Links Panel

**File:** `dashboard.html` (inline) or `design-system.css`

```css
.workspace-links-panel {
  background: rgba(255, 255, 255, 0.95);
  border: 1px solid var(--border-default);
  border-radius: 12px;
  padding: 16px;
  margin-bottom: 24px;
  box-shadow: var(--shadow-sm);
}

.workspace-links-panel .panel-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.workspace-links-panel .panel-header span {
  font-weight: 600;
  color: var(--text-primary);
  flex: 1;
}

.ws-quick-tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  background: rgba(var(--vericase-teal-rgb), 0.06);
  border: 1px solid rgba(var(--vericase-teal-rgb), 0.15);
  border-radius: 8px;
  color: var(--vericase-teal);
  text-decoration: none;
  font-size: 0.875rem;
  font-weight: 500;
  transition: all 0.15s;
  margin-right: 8px;
}

.ws-quick-tab:hover {
  background: rgba(var(--vericase-teal-rgb), 0.12);
  border-color: var(--vericase-teal);
}
```

**Testing Checkpoint:**
- [ ] Project Overview shows workspace quick links panel (when workspaceId is set)
- [ ] Clicking "Documents" → workspace hub with Documents tab active
- [ ] Clicking "About" → workspace hub with About tab active  
- [ ] Clicking "Purpose" → workspace hub with Purpose tab active

---

## Phase 6: "Develop Case" Flow Fix

**Goal:** Use the project-to-case API that clones configuration.

### 6.1 Create Dedicated "Develop Case from Project" Handler

**File:** `workspace-hub.html`

```diff
} else if (action === 'develop-case') {
- window.location.href = `case-setup.html?workspaceId=${workspaceId}&projectId=${id}`;
+ developCaseFromProject(id);
}

+ async function developCaseFromProject(projectId) {
+   const confirmed = await VericaseUI.Modal.confirm({
+     title: 'Develop Case from Project',
+     message: 'This will create a new case with stakeholders, keywords, and heads of claim copied from the project. Continue?',
+     confirmText: 'Create Case',
+     cancelText: 'Cancel'
+   });
+   
+   if (!confirmed) return;
+   
+   try {
+     const response = await fetch(`/api/projects/${projectId}/cases`, {
+       method: 'POST',
+       headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
+       body: JSON.stringify({
+         include_stakeholders: true,
+         include_keywords: true,
+         include_heads_of_claim: true
+       })
+     });
+     
+     if (!response.ok) throw new Error('Failed to create case');
+     const data = await response.json();
+     
+     VericaseUI.Toast.success('Case created successfully');
+     // Navigate to case setup to finalize details
+     window.location.href = `case-setup.html?workspaceId=${workspaceId}&caseId=${data.case_id}&fromProject=true`;
+   } catch (error) {
+     VericaseUI.Toast.error(error.message);
+   }
+ }
```

### 6.2 Update Case Setup to Handle "From Project" Mode

**File:** `case-setup.html`

```javascript
const fromProject = urlParams.get('fromProject') === 'true';

if (fromProject && caseId) {
  // Case was created from project - load it for review
  pageTitle.textContent = "Finalize Case from Project";
  pageSubtitle.textContent = "Review the inherited configuration and make any adjustments.";
  await loadCase(caseId);
}
```

### 6.3 Verify API Endpoint Exists

**File:** `vericase/api/app/simple_cases.py`

Confirm `POST /projects/{project_id}/cases` endpoint exists and includes:
- `include_stakeholders` parameter
- `include_keywords` parameter
- `include_heads_of_claim` parameter

**Testing Checkpoint:**
- [ ] "Develop Case" shows confirmation modal
- [ ] Case is created with stakeholders/keywords copied
- [ ] User lands on case setup with inherited data pre-filled

---

## Phase 7: Architecture Cleanup (Optional)

**Goal:** Remove technical debt and improve performance.

### 7.1 Eliminate `projectdashboard.html` Wrapper

**Option A: Inline Context Guard**

Move context validation to `dashboard.html` `<head>`:

```html
<head>
  <script>
    (function() {
      const params = new URLSearchParams(window.location.search);
      const projectId = params.get('projectId');
      const caseId = params.get('caseId');
      
      if (!projectId && !caseId) {
        // No context - redirect to workspace hub
        window.location.replace('workspace-hub.html');
        return;
      }
      
      // Context exists - continue loading
    })();
  </script>
</head>
```

**Option B: Keep Wrapper but Use `history.replaceState`**

```diff
// In projectdashboard.html
- document.open();
- document.write(html);
- document.close();
+ // Parse and inject content without replacing document
+ const parser = new DOMParser();
+ const doc = parser.parseFromString(html, 'text/html');
+ document.body.innerHTML = doc.body.innerHTML;
+ // Update URL to reflect actual page
+ history.replaceState(null, '', 'dashboard.html' + window.location.search);
```

### 7.2 Update Loader Copy for Cases

**File:** `projectdashboard.html`

```diff
- <p class="msg">Preparing your workspace and syncing your current project context.</p>
+ <p class="msg" id="loader-msg">Preparing your workspace...</p>

<script>
  const params = new URLSearchParams(window.location.search);
  const msg = document.getElementById('loader-msg');
  if (params.get('caseId')) {
    msg.textContent = 'Preparing your workspace and syncing your current case context.';
  } else {
    msg.textContent = 'Preparing your workspace and syncing your current project context.';
  }
</script>
```

---

## File Change Summary

| File | Phase | Changes |
|------|-------|---------|
| `context-manager.js` (NEW) | 0 | Unified context storage |
| `nav-shell.js` | 0, 1, 3, 4 | Context migration, breadcrumb builder, workspace indicator, unified click handlers |
| `workspace-hub.html` | 1, 2, 4, 5, 6 | Remove in-page breadcrumb, pass workspaceId, fix button emphasis, tab deep-linking, develop case |
| `project-setup.html` | 0, 1, 2 | Context manager, keep workspace in edit mode, fix back button |
| `case-setup.html` | 0, 1, 2, 6 | Context manager, keep workspace in edit mode, fix back button, from-project mode |
| `dashboard.html` | 0, 2, 3B, 5 | Context manager, workspace-scoped breadcrumbs, **visual continuity (CSS sync, workspace badge, background harmony)**, workspace quick links |
| `projectdashboard.html` | 7 | Loader copy, optional architecture change |
| `design-system.css` | 3, 3B, 5 | Workspace indicator styles, workspace context badge, quick links panel |

---

## Dependency Graph

```
Phase 0 (Context Manager)
    │
    ├──► Phase 1 (Breadcrumbs)
    │        │
    │        └──► Phase 2 (Workspace Context)
    │                 │
    │                 ├──► Phase 3 (Sidebar Workspace Indicator) ◄── CRITICAL
    │                 │        │
    │                 │        └──► Phase 3B (Visual Continuity) ◄── CRITICAL (same app feel)
    │                 │
    │                 └──► Phase 4 (Card UI Fixes)
    │                          │
    │                          └──► Phase 5 (Workspace ↔ Project Integration) ◄── CRITICAL
    │
    └──► Phase 6 (Develop Case) ◄── Can run in parallel after Phase 0
    
Phase 7 (Cleanup) ◄── Can run after all above complete
```

---

## Testing Checklist

### Smoke Tests (After Each Phase)
- [ ] Login → Workspaces → Select workspace → Open project → Overview loads
- [ ] Overview → Breadcrumb "Workspaces" → Returns to workspace directory
- [ ] Edit project → Back → Returns to expected location
- [ ] Develop Case → Case created with project data

### Regression Tests
- [ ] Multi-tab context isolation
- [ ] Direct URL access (bookmark to project overview)
- [ ] Quick Access (master-dashboard) still works
- [ ] Case flow mirrors project flow

### Edge Cases
- [ ] User without workspace access tries to open workspace-scoped project
- [ ] Project deleted while user is on overview
- [ ] Workspace deleted while user is on project within it

---

## Rollback Strategy

Each phase is independently revertible:

1. **Phase 0:** Remove `context-manager.js`, restore direct `localStorage` calls
2. **Phase 1:** Restore in-page breadcrumbs, revert shell breadcrumb builder
3. **Phase 2:** Remove `workspaceId` from URL params, revert scoped selectors
4. **Phase 3:** Remove workspace indicator from sidebar
5. **Phase 3B:** Revert CSS versions to v=6, remove workspace context badge, restore gradient background
6. **Phase 4:** Restore original button emphasis and click handlers
7. **Phase 5:** Remove workspace quick links panel from dashboard
8. **Phase 6:** Revert to generic case creation flow
9. **Phase 7:** No rollback needed (optional cleanup)

---

## Success Criteria

| Metric | Before | Target |
|--------|--------|--------|
| Sidebar shows current workspace | No | Yes |
| Breadcrumbs show workspace name | 0% of overview pages | 100% |
| "Open" is primary button (not "Develop Case") | No | Yes |
| Workspace tabs (Documents/About/Purpose) accessible from Project Overview | No | Yes |
| Tab deep-linking (e.g., `?tab=about`) | No | Yes |
| "Back" returns to workspace | 0% of edit flows | 100% |
| Project selector workspace-scoped | No | Yes |
| Card click behavior consistent | No | Yes |
| Context indicator behavior symmetric | No | Yes |
| "Develop Case" clones config | No | Yes |
| **CSS versions synced across all pages** | No (v6 vs v9) | Yes (v9) |
| **Workspace badge visible in Project Overview** | No | Yes |
| **Background treatment consistent** | No (gradient vs dots) | Yes (cream dots) |
| **"Same app" feel when entering project** | No | Yes |

---

## Priority Order

Based on user feedback, the recommended execution order is:

1. **Phase 0** — Foundation (required for all else)
2. **Phase 3** — Sidebar workspace indicator (most visible, high impact)
3. **Phase 3B** — Visual continuity (CSS sync, workspace badge, background harmony) ◄── **NEW**
4. **Phase 4.1** — Fix button emphasis (quick win)
5. **Phase 5** — Workspace ↔ Project integration (critical for Documents/About/Purpose)
6. **Phase 2** — Workspace context preservation
7. **Phase 1** — Breadcrumb standardization
8. **Phase 6** — Develop Case flow (nice-to-have)
9. **Phase 7** — Architecture cleanup (optional)

---

## Next Steps

1. **Review this plan** — Confirm priorities and approach
2. **Create `context-manager.js`** — Foundation for all other changes
3. **Execute Phase 3** — Sidebar workspace indicator (high visibility)
4. **Execute Phase 3B** — Visual continuity (CSS sync, workspace badge, background) ◄── **NEW**
5. **Execute Phase 4.1** — Fix "Open" vs "Develop Case" emphasis
6. **Execute Phase 5** — Add workspace quick links to Project Overview
7. **Execute remaining phases** — Breadcrumbs, context preservation, cleanup
