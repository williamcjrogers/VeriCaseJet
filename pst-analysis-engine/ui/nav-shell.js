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
        event.error ? event.error.stack : null,
      );
    });

    // Capture Unhandled Rejections
    window.addEventListener("unhandledrejection", function (event) {
      addLog("unhandled_rejection", [event.reason]);
    });

    console.info("VeriCase Error Tracking Initialized");
  })();

  const NAV_ITEMS = [
    {
      section: "HOME",
      items: [
        {
          id: "home",
          label: "Command Center",
          icon: "fa-home",
          url: "master-dashboard.html",
        },
      ],
    },
    {
      section: "PROJECT",
      items: [
        {
          id: "dashboard",
          label: "Project Dashboard",
          icon: "fa-th-large",
          url: "dashboard.html",
        },
        {
          id: "evidence",
          label: "Evidence Repository",
          icon: "fa-folder-open",
          url: "evidence.html",
        },
        {
          id: "correspondence",
          label: "Correspondence",
          icon: "fa-envelope-open-text",
          url: "correspondence-enterprise.html",
        },
        {
          id: "claims",
          label: "Claims & Matters",
          icon: "fa-balance-scale",
          url: "contentious-matters.html",
        },
      ],
    },
    {
      section: "TOOLS",
      items: [
        {
          id: "upload",
          label: "Upload PST",
          icon: "fa-upload",
          url: "pst-upload.html",
        },
        {
          id: "wizard",
          label: "Project Setup",
          icon: "fa-magic",
          url: "wizard.html",
        },
        {
          id: "refinement",
          label: "AI Refinement",
          icon: "fa-robot",
          url: "ai-refinement-wizard.html",
        },
        {
          id: "research",
          label: "Deep Research",
          icon: "fa-microscope",
          url: "deep-research.html",
          badge: "NEW",
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
          icon: "fa-users",
          url: "admin-users.html",
        },
      ],
    },
  ];

  function getCurrentPage() {
    return (
      window.location.pathname.split("/").pop().toLowerCase() ||
      "dashboard.html"
    );
  }

  function getProjectId() {
    const urlParams = new URLSearchParams(window.location.search);
    return (
      urlParams.get("projectId") ||
      localStorage.getItem("vericase_current_project") ||
      ""
    );
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
    const projectId = getProjectId();
    // Don't add projectId to home page
    if (url === "master-dashboard.html") {
      return url;
    }
    if (projectId) {
      const u = new URL(url, window.location.href);
      u.searchParams.set("projectId", projectId);
      return u.toString();
    }
    return url;
  }

  function renderSidebar() {
    const currentPage = getCurrentPage();
    const userIsAdmin = isAdmin();
    const hasProject = !!getProjectId();

    let navHtml = "";
    NAV_ITEMS.forEach((section) => {
      // Skip admin section for non-admins
      if (section.adminOnly && !userIsAdmin) {
        return;
      }

      // Add visual indicator if project section but no project selected
      const needsProject = section.section === "PROJECT";
      const sectionClass =
        needsProject && !hasProject
          ? "nav-section needs-project"
          : "nav-section";

      navHtml += `<div class="${sectionClass}">`;
      navHtml += `<div class="nav-section-title">${section.section}</div>`;

      section.items.forEach((item) => {
        const isActive = currentPage.includes(item.url.replace(".html", ""));
        const itemDisabled = needsProject && !hasProject ? "disabled" : "";
        navHtml += `
                    <a href="${buildNavUrl(item.url)}" class="nav-item ${isActive ? "active" : ""} ${itemDisabled}" data-nav="${item.id}">
                        <i class="fas ${item.icon}"></i>
                        <span>${item.label}</span>
                        ${item.badge ? `<span class="nav-badge">${item.badge}</span>` : ""}
                    </a>
                `;
      });

      navHtml += `</div>`;
    });

    // Add project context indicator - always show, clickable to switch projects
    const projectId = getProjectId();
    const projectContext = projectId
      ? `
            <div class="project-context" onclick="VericaseShell.showProjectSelector()" style="cursor: pointer;" title="Click to switch project">
                <div class="project-context-label">Current Project <i class="fas fa-exchange-alt" style="float:right;opacity:0.5;font-size:0.75rem;"></i></div>
                <div class="project-context-name" id="currentProjectName">Loading...</div>
            </div>
        `
      : `
            <div class="project-context no-project" onclick="VericaseShell.showProjectSelector()" style="cursor: pointer;" title="Click to select project">
                <div class="project-context-label">No Project Selected</div>
                <div class="project-context-name" style="font-size:0.75rem;opacity:0.7;">Click to select</div>
            </div>
        `;

    return `
            <aside class="app-sidebar" id="appSidebar">
                <div class="sidebar-header">
                    <a href="master-dashboard.html" class="sidebar-logo">
                        <img src="assets/Gemini_Generated_Image_iaegbtiaegbtiaeg.png" alt="VeriCase" />
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
            </aside>
        `;
  }

  function renderHeader(title = "", actions = "") {
    return `
            <header class="app-header">
                <button class="btn btn-icon btn-ghost" id="sidebarToggle" style="display: none;">
                    <i class="fas fa-bars"></i>
                </button>
                <h1 class="app-header-title">${title}</h1>
                <div class="app-header-actions">
                    ${actions}
                </div>
            </header>
        `;
  }

  // Load and display the current project name in the sidebar
  async function loadCurrentProjectName() {
    const projectId = getProjectId();
    const nameElement = document.getElementById("currentProjectName");

    if (!projectId || !nameElement) return;

    try {
      // Try to get from cache first
      if (projectsCache && projectsCache.length > 0) {
        const project = projectsCache.find((p) => p.id === projectId);
        if (project) {
          nameElement.textContent =
            project.project_name || project.name || "Unnamed Project";
          return;
        }
      }

      // Fetch project details from API
      const apiUrl = window.location.origin;
      const token = localStorage.getItem("token");
      const headers = token ? { Authorization: `Bearer ${token}` } : {};

      const response = await fetch(`${apiUrl}/api/projects/${projectId}`, {
        headers,
      });

      if (response.ok) {
        const project = await response.json();
        nameElement.textContent =
          project.project_name || project.name || "Unnamed Project";
      } else {
        // Fallback: try to load all projects and find this one
        const projects = await fetchProjects();
        const project = projects.find((p) => p.id === projectId);
        if (project) {
          nameElement.textContent =
            project.project_name || project.name || "Unnamed Project";
        } else {
          nameElement.textContent = "Unknown Project";
        }
      }
    } catch (error) {
      console.error("[VericaseShell] Failed to load project name:", error);
      nameElement.textContent = "Project";
    }
  }

  function injectShell(options = {}) {
    const {
      title = document.title.replace("VeriCase - ", ""),
      headerActions = "",
      showProgress = false,
      projectId = null,
    } = options;

    // Don't inject if already has shell
    if (document.querySelector(".app-shell")) return;

    // Wrap existing body content
    const existingContent = document.body.innerHTML;

    document.body.innerHTML = `
            <div class="app-shell">
                ${renderSidebar()}
                <main class="app-main">
                    ${renderHeader(title, headerActions)}
                    ${showProgress ? '<div id="progressTracker"></div>' : ""}
                    <div class="app-content">
                        ${existingContent}
                    </div>
                </main>
            </div>
            <div class="toast-container" id="toastContainer"></div>
        `;

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
      if (toggle) {
        toggle.style.display = e.matches ? "flex" : "none";
      }
    }

    mediaQuery.addListener(handleMediaChange);
    handleMediaChange(mediaQuery);

    if (toggle && sidebar) {
      toggle.addEventListener("click", () => {
        sidebar.classList.toggle("mobile-open");
      });
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
      const token = localStorage.getItem("token");
      const headers = token ? { Authorization: `Bearer ${token}` } : {};

      const response = await fetch(`${apiUrl}/api/projects`, { headers });
      if (response.ok) {
        projectsCache = await response.json();
        return projectsCache;
      }
    } catch (error) {
      console.error("[VericaseShell] Failed to fetch projects:", error);
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
        const selected = project.id === currentProjectId ? "selected" : "";
        select.innerHTML += `<option value="${project.id}" ${selected}>${project.project_name || project.name || "Unnamed Project"} ${project.project_code ? `(${project.project_code})` : ""}</option>`;
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
    localStorage.setItem("vericase_current_project", selectedId);

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
    getProjectId,
    showProjectSelector,
    closeProjectSelector,
    confirmProjectSelection,
  };
})();
