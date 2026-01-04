/**
 * VeriCase Navigation Shell
 * Injects consistent navigation into all pages
 */

(function () {
  "use strict";

  // ==========================================
  // Error Tracking & Telemetry
  // ==========================================
  (function initErrorTracking() {
    // Buffer for logs
    window.__vericase_logs = window.__vericase_logs || [];
    window.__jetski_console_buffer = window.__vericase_logs; // Alias for compatibility
    const MAX_LOGS = 1000;

    function addLog(type, args, stack) {
      try {
        const entry = {
          timestamp: new Date().toISOString(),
          type: type,
          message: args
            .map((a) => {
              try {
                if (a instanceof Error) return a.toString();
                return typeof a === "object" ? JSON.stringify(a) : String(a);
              } catch (e) {
                return "[Circular/Unserializable]";
              }
            })
            .join(" "),
          stack: stack || new Error().stack,
          url: window.location.href,
        };

        window.__vericase_logs.push(entry);
        if (window.__vericase_logs.length > MAX_LOGS) {
          window.__vericase_logs.shift();
        }
      } catch (e) {
        // Failsafe to prevent logging from crashing the app
      }
    }

    // Capture Console Methods
    const methods = ["log", "warn", "error", "info", "debug"];
    methods.forEach((method) => {
      const original = console[method];
      console[method] = function (...args) {
        // Call original first to ensure devtools behavior is preserved
        if (original) original.apply(console, args);
        addLog(method, args);
      };
    });

    // Capture Global Errors
    window.addEventListener("error", function (event) {
      addLog(
        "uncaught_error",
        [event.message],
        event.error ? event.error.stack : null
      );
    });

    // Capture Unhandled Rejections
    window.addEventListener("unhandledrejection", function (event) {
      addLog("unhandled_rejection", [event.reason]);
    });

    console.info("VeriCase Error Tracking Initialized");
  })();

  const COMMAND_CENTER_PAGE = "control-centre.html";

  const NAV_ITEMS = [
    {
      section: "HOME",
      items: [
        {
          id: "help",
          label: "Control Centre",
          icon: "fa-compass",
          url: COMMAND_CENTER_PAGE,
        },
        {
          id: "dashboard",
          label: "Master Dashboard",
          icon: "fa-th-large",
          url: "master-dashboard.html",
        },
      ],
    },
    {
      section: "WORKSPACE",
      // Workspace navigation is only meaningful once a workspace (project OR case) is selected.
      requiresContext: true,
      hideOn: [COMMAND_CENTER_PAGE, "master-dashboard.html"],
      sectionLabel: (ctx) => {
        if (ctx?.type === "case") return "CASE";
        if (ctx?.type === "project") return "PROJECT";
        return "WORKSPACE";
      },
      items: [
        {
          id: "dashboard",
          label: (ctx) =>
            ctx?.type === "case" ? "Case Dashboard" : "Project Dashboard",
          icon: "fa-gauge-high",
          url: "projectdashboard.html",
          contexts: ["project", "case"],
        },
        {
          id: "evidence",
          label: "Evidence & Files",
          icon: "fa-folder-tree",
          url: "evidence.html",
          contexts: ["project", "case"],
        },
        {
          id: "correspondence",
          label: "Correspondence",
          icon: "fa-envelope-open-text",
          url: "correspondence-enterprise.html",
          contexts: ["project", "case"],
        },
        {
          id: "claims",
          label: "Claims & Matters",
          icon: "fa-balance-scale",
          url: "contentious-matters.html",
          contexts: ["project", "case"],
        },
        {
          id: "collaboration-hub",
          label: "Collaboration Hub",
          icon: "fa-comments",
          url: "collaboration-workspace.html",
          contexts: ["project", "case"],
        },
        {
          id: "programme",
          label: "Programme",
          icon: "fa-project-diagram",
          url: "programme.html",
          contexts: ["project", "case"],
        },
        {
          id: "delays",
          label: "The Delay Ripple",
          icon: "fa-hourglass-half",
          url: "delays.html",
          contexts: ["project", "case"],
        },
        {
          id: "chronology",
          label: "The Chronology Lense\u2122",
          icon: "fa-history",
          url: "chronology-lense.html",
          contexts: ["project", "case"],
        },
        {
          id: "stakeholders",
          label: "Stakeholders",
          icon: "fa-id-badge",
          url: "stakeholders.html",
          contexts: ["project", "case"],
        },
      ],
    },
    {
      section: "TOOLS",
      // Tools are available elsewhere on the Command Center page (cards + quick actions).
      // Hide here to avoid showing project/case-specific tools before a workspace is chosen.
      hideOn: [COMMAND_CENTER_PAGE, "master-dashboard.html"],
      items: [
        {
          id: "upload",
          label: "Upload PST",
          icon: "fa-upload",
          url: "pst-upload.html",
        },
        {
          id: "workspace-setup",
          label: "Workspace Setup",
          icon: "fa-diagram-project",
          url: "workspace-setup.html",
          requiresContext: true,
          contexts: ["project", "case"],
        },
        {
          id: "refinement",
          label: "VeriCase Refine",
          icon: "fa-wand-magic-sparkles",
          url: "ai-refinement-wizard.html",
        },
        {
          id: "research",
          label: "VeriCase Analysis",
          icon: "fa-microscope",
          url: "vericase-analysis.html",
          badge: "NEW",
          contexts: ["project", "case"],
          adminOnly: true,
        },
      ],
    },
    {
      section: "ADMIN",
      adminOnly: true,
      items: [
        {
          id: "settings",
          label: "Settings",
          icon: "fa-cog",
          url: "admin-settings.html",
        },
        {
          id: "users",
          label: "Users",
          icon: "fa-id-badge",
          url: "admin-users.html",
        },
      ],
    },
  ];

  function getCurrentPage() {
    return (
      window.location.pathname.split("/").pop().toLowerCase() ||
      "projectdashboard.html"
    );
  }

  function getContext() {
    const urlParams = new URLSearchParams(window.location.search);
    const urlCaseId = (urlParams.get("caseId") || "").trim();
    const urlProjectId = (urlParams.get("projectId") || "").trim();
    const logContext = (ctx) => {
      console.log("[FLOW] NavShell context:", ctx);
      return ctx;
    };

    if (urlCaseId && urlCaseId !== "undefined" && urlCaseId !== "null") {
      return logContext({ type: "case", id: urlCaseId });
    }

    if (
      urlProjectId &&
      urlProjectId !== "undefined" &&
      urlProjectId !== "null"
    ) {
      return logContext({ type: "project", id: urlProjectId });
    }

    const storedProfileType = (localStorage.getItem("profileType") || "").trim();
    const storedCaseId = (
      localStorage.getItem("currentCaseId") ||
      localStorage.getItem("caseId") ||
      ""
    ).trim();
    const storedProjectId = (
      localStorage.getItem("vericase_current_project") ||
      localStorage.getItem("currentProjectId") ||
      localStorage.getItem("projectId") ||
      ""
    ).trim();

    const normalizedCaseId =
      storedCaseId && storedCaseId !== "undefined" && storedCaseId !== "null"
        ? storedCaseId
        : "";
    const normalizedProjectId =
      storedProjectId &&
        storedProjectId !== "undefined" &&
        storedProjectId !== "null"
        ? storedProjectId
        : "";

    if (storedProfileType === "case" && normalizedCaseId) {
      return logContext({ type: "case", id: normalizedCaseId });
    }

    if (normalizedProjectId) {
      return logContext({ type: "project", id: normalizedProjectId });
    }

    if (normalizedCaseId) {
      return logContext({ type: "case", id: normalizedCaseId });
    }

    return logContext({ type: "", id: "" });
  }

  function getProjectId() {
    const ctx = getContext();
    return ctx.type === "project" ? ctx.id : "";
  }

  function getWorkspaceId() {
    const urlParams = new URLSearchParams(window.location.search);
    const urlWorkspaceId = (urlParams.get("workspaceId") || "").trim();
    if (urlWorkspaceId && urlWorkspaceId !== "undefined" && urlWorkspaceId !== "null") {
      return urlWorkspaceId;
    }

    const storedWorkspaceId = (localStorage.getItem("currentWorkspaceId") || "").trim();
    if (storedWorkspaceId && storedWorkspaceId !== "undefined" && storedWorkspaceId !== "null") {
      return storedWorkspaceId;
    }

    return "";
  }

  function getUserRole() {
    try {
      const user = JSON.parse(localStorage.getItem("user") || "{}");
      return user.role || "VIEWER";
    } catch {
      return "VIEWER";
    }
  }

  function isAdmin() {
    return getUserRole() === "ADMIN";
  }

  function buildNavUrl(url) {
    const ctx = getContext();
    const page = getUrlPage(url).split("?")[0];
    const workspaceId = getWorkspaceId();

    if (page === "workspace-setup.html" || page === "workspace-hub.html") {
      if (workspaceId) {
        const u = new URL(url, window.location.href);
        u.searchParams.set("workspaceId", workspaceId);
        u.searchParams.delete("projectId");
        u.searchParams.delete("caseId");
        return u.toString();
      }
      return url;
    }
    // Don't add context to home page
    if (url === COMMAND_CENTER_PAGE) {
      return url;
    }

    if (ctx && ctx.id) {
      const u = new URL(url, window.location.href);
      if (ctx.type === "case") {
        u.searchParams.set("caseId", ctx.id);
        u.searchParams.delete("projectId");
      } else {
        u.searchParams.set("projectId", ctx.id);
        u.searchParams.delete("caseId");
      }
      return u.toString();
    }

    return url;
  }

  function resolveNavLabel(label, ctx) {
    try {
      return typeof label === "function" ? label(ctx) : label;
    } catch (e) {
      return "";
    }
  }

  function getUrlPage(url) {
    return (url || "").split("/").pop().toLowerCase();
  }

  function isItemVisibleForContext(item, ctx, hasContext) {
    const contexts = Array.isArray(item?.contexts) ? item.contexts : null;
    if (!contexts || contexts.length === 0) return true;

    const ctxType = (ctx?.type || "").trim();

    // Without a selected workspace, avoid showing project-only/case-only items.
    if (!hasContext) {
      return contexts.includes("project") && contexts.includes("case");
    }

    return contexts.includes(ctxType);
  }

  function renderSidebar() {
    const currentPage = getCurrentPage();
    const userIsAdmin = isAdmin();
    const rawCtx = getContext();
    const isCommandCenter = currentPage === COMMAND_CENTER_PAGE;
    const isMasterDashboard = currentPage === "master-dashboard.html";
    const ctx = isCommandCenter || isMasterDashboard ? { type: "", id: "" } : rawCtx;
    const hasContext = !!(ctx && ctx.id);

    let navHtml = "";
    NAV_ITEMS.forEach((section) => {
      // Skip admin section for non-admins
      if (section.adminOnly && !userIsAdmin) {
        return;
      }

      // Some sections (workspace nav, tools) should never appear on the Command Center or Master Dashboard.
      if (Array.isArray(section.hideOn) && section.hideOn.includes(currentPage)) {
        return;
      }
      
      // Also hide WORKSPACE and TOOLS sections on master dashboard
      if (isMasterDashboard && (section.section === "WORKSPACE" || section.section === "TOOLS")) {
        return;
      }

      const needsContext = !!section.requiresContext;
      const sectionClass =
        needsContext && !hasContext
          ? "nav-section needs-workspace"
          : "nav-section";

      const sectionTitle = resolveNavLabel(
        section.sectionLabel || section.section,
        ctx
      );

      // Filter items for the current context (project vs case)
      const visibleItems = (section.items || []).filter((item) => {
        // Check item-level admin restriction
        if (item.adminOnly && !userIsAdmin) return false;
        return isItemVisibleForContext(item, ctx, hasContext);
      });

      if (!visibleItems.length) return;

      navHtml += `<div class="${sectionClass}">`;
      navHtml += `<div class="nav-section-title">${sectionTitle}</div>`;

      visibleItems.forEach((item) => {
        const itemPage = getUrlPage(item.url);
        const isDashboardAlias =
          itemPage === "projectdashboard.html" && currentPage === "dashboard.html";
        const isActive = currentPage === itemPage || isDashboardAlias;
        const isDisabled = (needsContext && !hasContext) || (item.requiresContext && !hasContext);
        const itemLabel = resolveNavLabel(item.label, ctx);

        navHtml += `
                    <a href="${isDisabled ? "#" : buildNavUrl(item.url)}" data-base-url="${item.url}" class="nav-item ${isActive ? "active" : ""
          } ${isDisabled ? "disabled" : ""}" data-nav="${item.id}"${isActive ? ' aria-current="page"' : ""
          }${isDisabled ? ' aria-disabled="true" tabindex="-1"' : ""}">
                        <i class="fas ${item.icon} ${item.iconClass || ""}"></i>
                        <span>${itemLabel}</span>
                        ${item.badge
            ? `<span class="nav-badge">${item.badge}</span>`
            : ""
          }
                    </a>
                `;
      });

      navHtml += `</div>`;
    });

    // Add context indicator (hide it on Command Center and Master Dashboard to reduce confusion)
    let projectContext = "";
    if (!isCommandCenter && !isMasterDashboard) {
      const contextType =
        ctx?.type || (localStorage.getItem("profileType") || "project");
      const contextId = ctx?.id || "";

      // Get cached context name to show immediately (avoids flash of "Loading...")
      const cachedContextName =
        contextType === "case"
          ? localStorage.getItem("currentCaseName") ||
          localStorage.getItem("vericase_current_case_name") ||
          "Loading..."
          : localStorage.getItem("currentProjectName") ||
          localStorage.getItem("vericase_current_project_name") ||
          "Loading...";

      const contextLabel =
        contextType === "case" ? "Current Case" : "Current Project";
      const clickHandler =
        contextType === "case"
          ? `window.location.href='master-dashboard.html'`
          : "VericaseShell.showProjectSelector()";
      const clickTitle =
        contextType === "case"
          ? "Click to change workspace"
          : "Click to switch project";

      projectContext = contextId
        ? `
              <div class="project-context" onclick="${clickHandler}" style="cursor: pointer;" title="${clickTitle}">
                  <div class="project-context-label">${contextLabel} <i class="fas fa-exchange-alt" style="float:right;opacity:0.5;font-size:0.75rem;"></i></div>
                  <div class="project-context-name" id="currentProjectName">${cachedContextName}</div>
              </div>
          `
        : `
              <div class="project-context no-project" onclick="window.location.href='master-dashboard.html'" style="cursor: pointer;" title="Click to select a workspace">
                  <div class="project-context-label"><i class="fas fa-exclamation-circle" style="margin-right:4px;"></i> No Workspace</div>
                  <div class="project-context-name" style="font-size:0.75rem;">Click to select →</div>
              </div>
          `;
    }

    return `
            <aside class="app-sidebar" id="appSidebar">
                <div class="sidebar-header">
                    <a href="master-dashboard.html" class="sidebar-logo">
                    <img src="/ui/assets/LOGOTOBEUSED.png" alt="VeriCase" />
                    </a>
                </div>
                ${projectContext}
                <nav class="sidebar-nav">
                    ${navHtml}
                </nav>
                <div class="sidebar-footer">
                    <a href="profile.html" class="nav-item">
                        <i class="fas fa-user-circle"></i>
                        <span>Profile</span>
                    </a>
                </div>
                <div class="sidebar-collapse-toggle" id="sidebarCollapseToggle" title="Collapse sidebar">
                    <button class="sidebar-collapse-btn" aria-label="Collapse sidebar">
                        <i class="fas fa-chevron-left"></i>
                    </button>
                </div>
            </aside>
        `;
  }

  function renderHeader(title = "", actions = "", breadcrumbs = null) {
    const breadcrumbHtml = breadcrumbs ? renderBreadcrumbs(breadcrumbs) : "";
    return `
            <header class="app-header">
                <button class="btn btn-icon btn-ghost" id="sidebarToggle" style="display: none;">
                    <i class="fas fa-bars"></i>
                </button>
                ${breadcrumbHtml
        ? `
                <div class="app-header-breadcrumb">
                    ${breadcrumbHtml}
                </div>
                <div class="app-header-divider"></div>
                `
        : ""
      }
                <h1 class="app-header-title">${title}</h1>
                <div class="app-header-actions">
                    ${actions}
                </div>
            </header>
        `;
  }

  function renderBreadcrumbs(breadcrumbs) {
    if (!breadcrumbs || breadcrumbs.length === 0) return "";

    return breadcrumbs
      .map((crumb, index) => {
        const isLast = index === breadcrumbs.length - 1;
        const icon = crumb.icon
          ? `<i class="fas ${crumb.icon} ${crumb.iconClass || ""}"></i> `
          : "";

        if (isLast) {
          return `<span class="breadcrumb-current">${icon}${crumb.label}</span>`;
        }

        return `
        <a href="${crumb.url || "#"}" class="breadcrumb-link">${icon}${crumb.label
          }</a>
        <span class="separator"><i class="fas fa-chevron-right"></i></span>
      `;
      })
      .join("");
  }

  // Load and display the current context name in the sidebar
  async function loadCurrentProjectName() {
    const ctx = getContext();
    const contextType =
      ctx?.type || (localStorage.getItem("profileType") || "project");
    const contextId = ctx?.id || "";

    const nameElement = document.getElementById("currentProjectName");
    if (!nameElement) return;

    const cachedName =
      contextType === "case"
        ? localStorage.getItem("currentCaseName") ||
        localStorage.getItem("vericase_current_case_name") ||
        ""
        : localStorage.getItem("currentProjectName") ||
        localStorage.getItem("vericase_current_project_name") ||
        "";

    // If we don't have an ID (or API fails later), still show the last-known name.
    if (!contextId) {
      if (cachedName) nameElement.textContent = cachedName;
      return;
    }

    try {
      const apiUrl = window.location.origin;
      const token =
        localStorage.getItem("vericase_token") ||
        localStorage.getItem("token") ||
        localStorage.getItem("jwt");
      const headers = token ? { Authorization: `Bearer ${token}` } : {};

      if (contextType === "case") {
        const response = await fetch(`${apiUrl}/api/cases/${contextId}`, {
          headers,
        });

        if (response.ok) {
          const caseData = await response.json();
          const name =
            caseData.case_name ||
            caseData.name ||
            caseData.case_number ||
            "Unnamed Case";
          nameElement.textContent = name;
          localStorage.setItem("currentCaseName", name);
          localStorage.setItem("vericase_current_case_name", name);
        } else {
          nameElement.textContent = cachedName || "Case";
        }
        return;
      }

      // Project context
      // Try to get from cache first
      if (projectsCache && projectsCache.length > 0) {
        const project = projectsCache.find(
          (p) => String(p.id) === String(contextId)
        );
        if (project) {
          const name = project.project_name || project.name || "Unnamed Project";
          nameElement.textContent = name;
          localStorage.setItem("currentProjectName", name);
          localStorage.setItem("vericase_current_project_name", name);
          return;
        }
      }

      const response = await fetch(`${apiUrl}/api/projects/${contextId}`, {
        headers,
      });

      if (response.ok) {
        const project = await response.json();
        const name = project.project_name || project.name || "Unnamed Project";
        nameElement.textContent = name;
        localStorage.setItem("currentProjectName", name);
        localStorage.setItem("vericase_current_project_name", name);
      } else {
        // Fallback: try to load all projects and find this one
        const projects = await fetchProjects();
        const project = projects.find(
          (p) => String(p.id) === String(contextId)
        );
        if (project) {
          const name = project.project_name || project.name || "Unnamed Project";
          nameElement.textContent = name;
          localStorage.setItem("currentProjectName", name);
          localStorage.setItem("vericase_current_project_name", name);
        } else {
          nameElement.textContent = cachedName || "Unnamed Project";
        }
      }
    } catch (error) {
      console.error("[VeriCaseShell] Failed to load context name:", error);
      nameElement.textContent = cachedName || "Workspace";
    }
  }

  function injectShell(options = {}) {
    const {
      title = document.title.replace("VeriCase - ", ""),
      headerActions = "",
      showProgress = false,
      projectId = null,
      breadcrumbs = null,
      contentClass = "",
    } = options;

    // Don't inject if already has shell
    if (document.querySelector(".app-shell")) return;

    // Wrap existing body content WITHOUT recreating the DOM.
    // Replacing `document.body.innerHTML` destroys event listeners registered by page scripts
    // (e.g., buttons that "don't work" after the shell is injected). Moving nodes preserves them.
    const existingFragment = document.createDocumentFragment();
    while (document.body.firstChild) {
      existingFragment.appendChild(document.body.firstChild);
    }

    const wrapper = document.createElement("div");
    wrapper.innerHTML = `
            <div class="app-shell">
                ${renderSidebar()}
                <main class="app-main">
                    ${renderHeader(title, headerActions, breadcrumbs)}
                    ${showProgress ? '<div id="progressTracker"></div>' : ""}
                    <div class="app-content ${contentClass}"></div>
                </main>
            </div>
            <div class="toast-container" id="toastContainer"></div>
        `;

    const appShell = wrapper.querySelector(".app-shell");
    const toastContainer = wrapper.querySelector("#toastContainer");
    const appContent = appShell?.querySelector(".app-content");

    if (!appShell || !appContent) {
      // Failsafe: restore original DOM so the page remains usable.
      document.body.appendChild(existingFragment);
      return;
    }

    document.body.appendChild(appShell);
    if (toastContainer) document.body.appendChild(toastContainer);

    // Move existing DOM into the new content container.
    appContent.appendChild(existingFragment);

    // Initialize progress tracker if needed
    if (showProgress && projectId && window.VericaseUI) {
      window.VericaseUI.Progress.render("progressTracker", projectId);
    }

    // Load and display the current project name
    loadCurrentProjectName();

    // Setup responsive sidebar toggle
    const mediaQuery = window.matchMedia("(max-width: 1024px)");
    const sidebar = document.getElementById("appSidebar");
    const toggle = document.getElementById("sidebarToggle");

    function handleMediaChange(e) {
      if (!toggle || !sidebar) return;
      // Keep toggle visible on all breakpoints; adjust behavior per viewport
      toggle.style.display = "flex";

      if (e.matches) {
        // Mobile: use slide-in drawer and clear desktop state
        sidebar.classList.remove("collapsed");
        toggle.setAttribute("aria-label", "Open navigation");
        toggle.setAttribute("title", "Open navigation");
      } else {
        // Desktop: ensure mobile drawer class is removed
        sidebar.classList.remove("mobile-open");
        toggle.setAttribute("aria-label", "Hide sidebar");
        toggle.setAttribute("title", "Hide sidebar");
      }
    }

    mediaQuery.addListener(handleMediaChange);
    handleMediaChange(mediaQuery);

    if (toggle && sidebar) {
      toggle.addEventListener("click", () => {
        if (mediaQuery.matches) {
          const open = sidebar.classList.toggle("mobile-open");
          toggle.setAttribute(
            "aria-label",
            open ? "Close navigation" : "Open navigation"
          );
          toggle.setAttribute(
            "title",
            open ? "Close navigation" : "Open navigation"
          );
        } else {
          const collapsed = sidebar.classList.toggle("collapsed");
          toggle.setAttribute(
            "aria-label",
            collapsed ? "Show sidebar" : "Hide sidebar"
          );
          toggle.setAttribute(
            "title",
            collapsed ? "Show sidebar" : "Hide sidebar"
          );
          // Save preference
          localStorage.setItem("vericase_sidebar_collapsed", collapsed);
          updateCollapseToggleState(collapsed);
        }
      });
    }

    // Setup sidebar collapse toggle (chevron button inside sidebar)
    const collapseToggle = document.getElementById("sidebarCollapseToggle");
    if (collapseToggle && sidebar) {
      // Restore collapsed state from localStorage
      const savedCollapsed = localStorage.getItem("vericase_sidebar_collapsed") === "true";
      if (savedCollapsed && !mediaQuery.matches) {
        sidebar.classList.add("collapsed");
        updateCollapseToggleState(true);
      }

      collapseToggle.addEventListener("click", () => {
        if (!mediaQuery.matches) {
          const collapsed = sidebar.classList.toggle("collapsed");
          localStorage.setItem("vericase_sidebar_collapsed", collapsed);
          updateCollapseToggleState(collapsed);
        }
      });
    }

    function updateCollapseToggleState(collapsed) {
      const collapseToggle = document.getElementById("sidebarCollapseToggle");
      if (collapseToggle) {
        collapseToggle.setAttribute(
          "title",
          collapsed ? "Expand sidebar" : "Collapse sidebar"
        );
        const btn = collapseToggle.querySelector(".sidebar-collapse-btn");
        if (btn) {
          btn.setAttribute(
            "aria-label",
            collapsed ? "Expand sidebar" : "Collapse sidebar"
          );
        }
      }
    }
  }

  // ==========================================
  // Live Project Context Sync (for pages that switch projects without reload)
  // ==========================================

  function refreshNavUrls() {
    try {
      document.querySelectorAll("a.nav-item[data-base-url]").forEach((a) => {
        const base = a.getAttribute("data-base-url");
        if (!base) return;
        a.setAttribute("href", buildNavUrl(base));
      });
    } catch (e) {
      // Best-effort; never crash UI
    }
  }

  function setProjectContext({ projectId, projectName } = {}) {
    try {
      if (projectId && String(projectId).trim()) {
        localStorage.setItem("profileType", "project");
        localStorage.setItem("vericase_current_project", String(projectId));
        localStorage.setItem("currentProjectId", String(projectId));
        // Clear case context if switching back to a project
        localStorage.removeItem("currentCaseId");
        localStorage.removeItem("caseId");
      }

      if (projectName && String(projectName).trim()) {
        const name = String(projectName).trim();
        localStorage.setItem("currentProjectName", name);
        localStorage.setItem("vericase_current_project_name", name);

        const el = document.getElementById("currentProjectName");
        if (el) el.textContent = name;
      }

      // Ensure sidebar URLs match the *current* project context.
      refreshNavUrls();
    } catch {
      // ignore
    }
  }

  // ==========================================
  // Project Selector Modal
  // ==========================================
  let projectSelectorOptions = {};
  let projectsCache = null;

  function renderProjectSelectorModal() {
    return `
      <div class="project-selector-modal" id="projectSelectorModal">
        <div class="project-selector-content">
          <div class="project-selector-header">
            <h3><i class="fas fa-project-diagram"></i> Select a Project</h3>
            <button class="close-btn" onclick="VericaseShell.closeProjectSelector()" id="projectSelectorCloseBtn">
              <i class="fas fa-times"></i>
            </button>
          </div>
          <div class="project-selector-body">
            <select id="globalProjectSelect" class="form-input">
              <option value="">-- Select a project --</option>
            </select>
            <p class="project-selector-hint">Select a project to continue working with project-specific features.</p>
          </div>
          <div class="project-selector-actions">
            <button class="btn btn-secondary" onclick="VericaseShell.closeProjectSelector()" id="projectSelectorCancelBtn">Cancel</button>
            <button class="btn btn-vericase" onclick="VericaseShell.confirmProjectSelection()" id="projectSelectorConfirmBtn">
              <i class="fas fa-check"></i> Continue
            </button>
          </div>
        </div>
      </div>
    `;
  }

  async function fetchProjects() {
    if (projectsCache) return projectsCache;

    try {
      const apiUrl = window.location.origin;
      const token =
        localStorage.getItem("vericase_token") ||
        localStorage.getItem("token") ||
        localStorage.getItem("jwt");
      const headers = token ? { Authorization: `Bearer ${token}` } : {};

      const response = await fetch(`${apiUrl}/api/projects`, { headers });
      if (response.ok) {
        projectsCache = await response.json();
        return projectsCache;
      }
    } catch (error) {
      console.error("[VeriCaseShell] Failed to fetch projects:", error);
    }
    return [];
  }

  async function showProjectSelector(options = {}) {
    projectSelectorOptions = options;

    // Ensure modal exists in DOM
    let modal = document.getElementById("projectSelectorModal");
    if (!modal) {
      const modalContainer = document.createElement("div");
      modalContainer.innerHTML = renderProjectSelectorModal();
      document.body.appendChild(modalContainer.firstElementChild);
      modal = document.getElementById("projectSelectorModal");
    }

    // Hide cancel button if required
    const cancelBtn = document.getElementById("projectSelectorCancelBtn");
    const closeBtn = document.getElementById("projectSelectorCloseBtn");
    if (options.required) {
      if (cancelBtn) cancelBtn.style.display = "none";
      if (closeBtn) closeBtn.style.display = "none";
    } else {
      if (cancelBtn) cancelBtn.style.display = "";
      if (closeBtn) closeBtn.style.display = "";
    }

    // Populate dropdown
    const select = document.getElementById("globalProjectSelect");
    if (select) {
      select.innerHTML = '<option value="">Loading projects...</option>';

      const projects = await fetchProjects();
      const currentProjectId = getProjectId();

      select.innerHTML = '<option value="">-- Select a project --</option>';
      projects.forEach((project) => {
        const selected =
          String(project.id) === String(currentProjectId) ? "selected" : "";
        select.innerHTML += `<option value="${project.id}" ${selected}>${project.project_name || project.name || "Unnamed Project"
          } ${project.project_code ? `(${project.project_code})` : ""}</option>`;
      });
    }

    // Show modal
    modal.classList.add("active");
  }

  function closeProjectSelector() {
    const modal = document.getElementById("projectSelectorModal");
    if (modal && !projectSelectorOptions.required) {
      modal.classList.remove("active");
    }
  }

  function confirmProjectSelection() {
    const select = document.getElementById("globalProjectSelect");
    const selectedId = select?.value;

    if (!selectedId) {
      if (window.VericaseUI?.Toast) {
        window.VericaseUI.Toast.warning("Please select a project");
      } else {
        alert("Please select a project");
      }
      return;
    }

    // Store in localStorage
    localStorage.setItem("profileType", "project");
    localStorage.setItem("vericase_current_project", selectedId);
    localStorage.setItem("currentProjectId", selectedId);
    // Clear any case context when switching to a project
    localStorage.removeItem("currentCaseId");
    localStorage.removeItem("caseId");

    // Best-effort store of current project name for other pages
    try {
      const selectedText = select?.options?.[select.selectedIndex]?.textContent;
      if (selectedText) {
        // Strip a trailing "(CODE)" if present in the display option text.
        const normalized = selectedText
          .trim()
          .replace(/\s*\(([A-Z0-9_-]{1,20})\)\s*$/, "");
        localStorage.setItem("currentProjectName", normalized);
        localStorage.setItem("vericase_current_project_name", normalized);
      }
    } catch {
      // ignore
    }

    // Close modal
    const modal = document.getElementById("projectSelectorModal");
    if (modal) {
      modal.classList.remove("active");
    }

    // Call callback if provided
    if (projectSelectorOptions.onSelect) {
      projectSelectorOptions.onSelect(selectedId);
    } else {
      // Default behavior: reload page with projectId in URL
      const url = new URL(window.location.href);
      url.searchParams.set("projectId", selectedId);
      window.location.href = url.toString();
    }
  }

  // Export
  window.VericaseShell = {
    inject: injectShell,
    NAV_ITEMS,
    buildNavUrl,
    getContext,
    getProjectId,
    showProjectSelector,
    closeProjectSelector,
    confirmProjectSelection,
    renderBreadcrumbs,
    refreshNavUrls,
    setProjectContext,
  };
})();
