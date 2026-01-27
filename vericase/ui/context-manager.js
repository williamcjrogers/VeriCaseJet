/**
 * VeriCase Context Manager
 * Single canonical storage for navigation context with legacy migration.
 */
(function () {
  "use strict";

  const KEYS = {
    workspaceId: "vericase_context_workspace_id",
    workspaceName: "vericase_context_workspace_name",
    workspaceColor: "vericase_context_workspace_color",
    projectId: "vericase_context_project_id",
    projectName: "vericase_context_project_name",
    caseId: "vericase_context_case_id",
    caseName: "vericase_context_case_name",
    profileType: "vericase_context_profile_type",
  };

  const LEGACY_KEYS = {
    // Workspace
    currentWorkspaceId: KEYS.workspaceId,
    currentWorkspaceName: KEYS.workspaceName,
    workspaceId: KEYS.workspaceId,
    workspaceName: KEYS.workspaceName,
    workspaceColor: KEYS.workspaceColor,
    // Project
    vericase_current_project: KEYS.projectId,
    currentProjectId: KEYS.projectId,
    projectId: KEYS.projectId,
    currentProjectName: KEYS.projectName,
    vericase_current_project_name: KEYS.projectName,
    // Case
    currentCaseId: KEYS.caseId,
    caseId: KEYS.caseId,
    currentCaseName: KEYS.caseName,
    vericase_current_case_name: KEYS.caseName,
    // Profile type
    profileType: KEYS.profileType,
  };

  const LEGACY_WRITE_KEYS = {
    workspaceId: ["currentWorkspaceId", "workspaceId"],
    workspaceName: ["currentWorkspaceName", "workspaceName"],
    workspaceColor: ["workspaceColor"],
    projectId: ["vericase_current_project", "currentProjectId", "projectId"],
    projectName: ["currentProjectName", "vericase_current_project_name"],
    caseId: ["currentCaseId", "caseId"],
    caseName: ["currentCaseName", "vericase_current_case_name"],
    profileType: ["profileType"],
  };

  const isValidValue = (value) => {
    if (value === null || value === undefined) return false;
    const text = String(value).trim();
    return !!text && text !== "undefined" && text !== "null";
  };

  const resolveKey = (key) => KEYS[key] || key;

  function migrate() {
    try {
      Object.keys(LEGACY_KEYS).forEach((legacyKey) => {
        const canonicalKey = LEGACY_KEYS[legacyKey];
        const existing = localStorage.getItem(canonicalKey);
        if (isValidValue(existing)) return;
        const legacyValue = localStorage.getItem(legacyKey);
        if (isValidValue(legacyValue)) {
          localStorage.setItem(canonicalKey, legacyValue);
        }
      });
    } catch {
      // ignore
    }
  }

  function set(key, value) {
    const canonicalKey = resolveKey(key);
    if (!isValidValue(value)) {
      remove(key);
      return;
    }

    const normalized = String(value).trim();
    try {
      localStorage.setItem(canonicalKey, normalized);
      const legacyKeys = LEGACY_WRITE_KEYS[key] || LEGACY_WRITE_KEYS[canonicalKey];
      if (Array.isArray(legacyKeys)) {
        legacyKeys.forEach((legacyKey) => {
          try {
            localStorage.setItem(legacyKey, normalized);
          } catch {
            // ignore
          }
        });
      }
    } catch {
      // ignore
    }
  }

  function get(key) {
    const canonicalKey = resolveKey(key);
    let value = null;
    try {
      value = localStorage.getItem(canonicalKey);
    } catch {
      value = null;
    }

    if (!isValidValue(value)) {
      migrate();
      try {
        value = localStorage.getItem(canonicalKey);
      } catch {
        value = null;
      }
    }

    return isValidValue(value) ? String(value).trim() : "";
  }

  function remove(key) {
    const canonicalKey = resolveKey(key);
    try {
      localStorage.removeItem(canonicalKey);
      const legacyKeys = LEGACY_WRITE_KEYS[key] || LEGACY_WRITE_KEYS[canonicalKey];
      if (Array.isArray(legacyKeys)) {
        legacyKeys.forEach((legacyKey) => {
          try {
            localStorage.removeItem(legacyKey);
          } catch {
            // ignore
          }
        });
      }
    } catch {
      // ignore
    }
  }

  function clear(scope = "all") {
    if (scope === "project") {
      remove("projectId");
      remove("projectName");
      remove("caseId");
      remove("caseName");
      remove("profileType");
      return;
    }

    if (scope === "case") {
      remove("caseId");
      remove("caseName");
      remove("profileType");
      return;
    }

    Object.keys(KEYS).forEach((key) => remove(key));
  }

  window.VericaseContext = {
    KEYS,
    LEGACY_KEYS,
    set,
    get,
    remove,
    clear,
    migrate,
  };
})();
