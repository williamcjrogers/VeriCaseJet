/**
 * VeriCase Application State Manager
 *
 * Centralized state management that:
 * - Gets project from URL param OR fetches/creates default
 * - Caches in memory (not localStorage as source of truth)
 * - Provides navigation helpers
 * - Never blocks - always resolves to valid state
 */

window.VeriCaseApp = {
  // State
  projectId: null,
  projectName: null,
  caseId: null,
  caseName: null,
  config: {}, // Optional: keywords, stakeholders, etc.

  // API base URL
  apiBase: "/api",

  /**
   * Initialize the app state
   * Always succeeds - creates default project if needed
   */
  async init() {
    try {
      // 1. Check URL params first (source of truth)
      const params = new URLSearchParams(window.location.search);
      const urlProjectId = params.get("projectId");
      const urlCaseId = params.get("caseId");

      if (urlProjectId) {
        // Validate and use URL project
        const project = await this._fetchProject(urlProjectId);
        if (project) {
          this.projectId = project.id;
          this.projectName = project.project_name || project.name;
          this.config = project.meta || {};
          console.log("[VeriCaseApp] Using URL project:", this.projectId);
          return this;
        }
      }

      if (urlCaseId) {
        // Validate and use URL case
        const caseData = await this._fetchCase(urlCaseId);
        if (caseData) {
          this.caseId = caseData.id;
          this.caseName = caseData.name;
          console.log("[VeriCaseApp] Using URL case:", this.caseId);
          return this;
        }
      }

      // 2. No valid URL param - get or create default project
      const defaultProject = await this._getOrCreateDefaultProject();
      this.projectId = defaultProject.id;
      this.projectName = defaultProject.project_name || defaultProject.name;
      this.config = defaultProject.meta || {};
      console.log("[VeriCaseApp] Using default project:", this.projectId);

      return this;
    } catch (error) {
      console.error("[VeriCaseApp] Init error:", error);
      // Even on error, we should have a fallback
      // The API will create a default project on first upload
      return this;
    }
  },

  /**
   * Fetch a project by ID
   */
  async _fetchProject(projectId) {
    try {
      const response = await fetch(`${this.apiBase}/projects/${projectId}`, {
        credentials: "include",
      });
      if (response.ok) {
        return await response.json();
      }
    } catch (e) {
      console.warn("[VeriCaseApp] Failed to fetch project:", projectId, e);
    }
    return null;
  },

  /**
   * Fetch a case by ID
   */
  async _fetchCase(caseId) {
    try {
      const response = await fetch(`${this.apiBase}/cases/${caseId}`, {
        credentials: "include",
      });
      if (response.ok) {
        return await response.json();
      }
    } catch (e) {
      console.warn("[VeriCaseApp] Failed to fetch case:", caseId, e);
    }
    return null;
  },

  /**
   * Get or create the default project
   * This endpoint always returns a valid project
   */
  async _getOrCreateDefaultProject() {
    try {
      const response = await fetch(`${this.apiBase}/projects/default`, {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
        },
      });
      if (response.ok) {
        return await response.json();
      }
      throw new Error(`Failed to get default project: ${response.status}`);
    } catch (e) {
      console.error("[VeriCaseApp] Failed to get default project:", e);
      // Return a placeholder - the upload endpoint will handle this
      return {
        id: null,
        project_name: "Evidence Uploads",
        meta: {},
      };
    }
  },

  /**
   * Set optional configuration (from wizard, settings, etc.)
   */
  setConfig(config) {
    this.config = { ...this.config, ...config };
  },

  /**
   * Get the current context ID (project or case)
   */
  getContextId() {
    return this.projectId || this.caseId;
  },

  /**
   * Get the context type
   */
  getContextType() {
    if (this.projectId) return "project";
    if (this.caseId) return "case";
    return "project";
  },

  /**
   * Get URL params for current context
   */
  getContextParams() {
    if (this.projectId) {
      return `projectId=${this.projectId}`;
    }
    if (this.caseId) {
      return `caseId=${this.caseId}`;
    }
    return "";
  },

  /**
   * Navigate to a page with context
   */
  goto(page, additionalParams = {}) {
    let url = page;
    const params = new URLSearchParams();

    // Add context
    if (this.projectId) {
      params.set("projectId", this.projectId);
    } else if (this.caseId) {
      params.set("caseId", this.caseId);
    }

    // Add additional params
    for (const [key, value] of Object.entries(additionalParams)) {
      params.set(key, value);
    }

    const paramString = params.toString();
    if (paramString) {
      url += (url.includes("?") ? "&" : "?") + paramString;
    }

    window.location.href = url;
  },

  /**
   * Navigate to dashboard
   */
  gotoDashboard() {
    this.goto("dashboard.html");
  },

  /**
   * Navigate to correspondence view
   */
  gotoCorrespondence() {
    this.goto("correspondence-enterprise.html");
  },

  /**
   * Navigate to evidence repository
   */
  gotoEvidence() {
    this.goto("evidence.html");
  },

  /**
   * Navigate to PST upload
   */
  gotoUpload() {
    this.goto("pst-upload.html");
  },

  /**
   * Navigate to refinement wizard
   */
  gotoRefinement() {
    this.goto("refinement-wizard.html");
  },

  /**
   * Build API URL with context
   */
  buildApiUrl(endpoint, params = {}) {
    const url = new URL(endpoint, window.location.origin);

    // Add context
    if (this.projectId) {
      url.searchParams.set("project_id", this.projectId);
    } else if (this.caseId) {
      url.searchParams.set("case_id", this.caseId);
    }

    // Add additional params
    for (const [key, value] of Object.entries(params)) {
      url.searchParams.set(key, value);
    }

    return url.toString();
  },

  /**
   * Get display name for current context
   */
  getContextName() {
    return this.projectName || this.caseName || "Evidence Uploads";
  },

  /**
   * Check if we have a valid context
   */
  hasContext() {
    return !!(this.projectId || this.caseId);
  },

  /**
   * Update URL to reflect current state (without reload)
   */
  updateUrl() {
    const params = new URLSearchParams(window.location.search);

    if (this.projectId) {
      params.set("projectId", this.projectId);
      params.delete("caseId");
    } else if (this.caseId) {
      params.set("caseId", this.caseId);
      params.delete("projectId");
    }

    const newUrl = `${window.location.pathname}?${params.toString()}`;
    window.history.replaceState({}, "", newUrl);
  },
};

// Auto-initialize when DOM is ready (optional - pages can call init() explicitly)
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => {
    // Don't auto-init - let pages control this
    console.log("[VeriCaseApp] Ready - call VeriCaseApp.init() to initialize");
  });
}
