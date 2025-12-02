/**
 * VeriCase UI System v2.0
 * Toast notifications, Progress tracking, Navigation state
 */

(function () {
  "use strict";

  // ============================================
  // TOAST NOTIFICATION SYSTEM
  // ============================================

  const ToastManager = {
    container: null,
    queue: [],

    init() {
      if (this.container) return;
      this.container = document.createElement("div");
      this.container.className = "toast-container";
      this.container.setAttribute("aria-live", "polite");
      document.body.appendChild(this.container);
    },

    show(message, options = {}) {
      this.init();

      const {
        type = "info",
        duration = 4000,
        action = null,
        actionLabel = "Undo",
      } = options;

      const toast = document.createElement("div");
      toast.className = `toast toast-${type}`;

      const icons = {
        success: "fa-check-circle",
        error: "fa-exclamation-circle",
        warning: "fa-exclamation-triangle",
        info: "fa-info-circle",
      };

      toast.innerHTML = `
                <span class="toast-icon"><i class="fas ${icons[type] || icons.info}"></i></span>
                <span class="toast-content">${message}</span>
                ${action ? `<button class="toast-action" onclick="(${action.toString()})()">${actionLabel}</button>` : ""}
                <button class="toast-close" aria-label="Close">
                    <i class="fas fa-times"></i>
                </button>
            `;

      const closeBtn = toast.querySelector(".toast-close");
      closeBtn.addEventListener("click", () => this.dismiss(toast));

      this.container.appendChild(toast);

      if (duration > 0) {
        setTimeout(() => this.dismiss(toast), duration);
      }

      return toast;
    },

    dismiss(toast) {
      if (!toast || !toast.parentNode) return;
      toast.classList.add("toast-exit");
      setTimeout(() => {
        if (toast.parentNode) {
          toast.parentNode.removeChild(toast);
        }
      }, 300);
    },

    success(message, options = {}) {
      return this.show(message, { ...options, type: "success" });
    },

    error(message, options = {}) {
      return this.show(message, { ...options, type: "error", duration: 6000 });
    },

    warning(message, options = {}) {
      return this.show(message, { ...options, type: "warning" });
    },

    info(message, options = {}) {
      return this.show(message, { ...options, type: "info" });
    },
  };

  // ============================================
  // PROGRESS TRACKER
  // ============================================

  const ProgressTracker = {
    stages: [
      {
        id: "profile",
        name: "Create Profile",
        icon: "fa-cog",
        url: "wizard.html",
      },
      {
        id: "upload",
        name: "Upload PST",
        icon: "fa-upload",
        url: "pst-upload.html",
      },
      {
        id: "refine",
        name: "AI Refinement",
        icon: "fa-magic",
        url: "ai-refinement-wizard.html",
      },
      {
        id: "evidence",
        name: "Review Evidence",
        icon: "fa-folder-open",
        url: "evidence.html",
      },
      {
        id: "analysis",
        name: "Analysis",
        icon: "fa-chart-line",
        url: "correspondence-enterprise.html",
      },
    ],

    getProjectProgress(projectId) {
      const key = `vericase_progress_${projectId}`;
      const stored = localStorage.getItem(key);
      return stored
        ? JSON.parse(stored)
        : { completedStages: [], currentStage: "profile" };
    },

    setProjectProgress(projectId, progress) {
      const key = `vericase_progress_${projectId}`;
      localStorage.setItem(key, JSON.stringify(progress));
    },

    markStageComplete(projectId, stageId) {
      const progress = this.getProjectProgress(projectId);
      if (!progress.completedStages.includes(stageId)) {
        progress.completedStages.push(stageId);
      }
      const currentIndex = this.stages.findIndex((s) => s.id === stageId);
      if (currentIndex < this.stages.length - 1) {
        progress.currentStage = this.stages[currentIndex + 1].id;
      }
      this.setProjectProgress(projectId, progress);
      return progress;
    },

    render(containerId, projectId) {
      const container = document.getElementById(containerId);
      if (!container) return;

      const progress = this.getProjectProgress(projectId);
      const currentPage = this.getCurrentPage();

      let html = '<div class="progress-tracker">';

      this.stages.forEach((stage, index) => {
        const isCompleted = progress.completedStages.includes(stage.id);
        const isActive = currentPage.includes(stage.url.replace(".html", ""));
        const isCurrent = stage.id === progress.currentStage;

        let stateClass = "";
        if (isCompleted) stateClass = "completed";
        else if (isActive || isCurrent) stateClass = "active";

        html += `
                    <a href="${stage.url}${projectId ? "?projectId=" + projectId : ""}" 
                       class="progress-step ${stateClass}">
                        <span class="step-icon">
                            ${isCompleted ? '<i class="fas fa-check"></i>' : `<i class="fas ${stage.icon}"></i>`}
                        </span>
                        <span class="step-label">${stage.name}</span>
                    </a>
                `;

        if (index < this.stages.length - 1) {
          html += `<div class="step-connector ${isCompleted ? "completed" : ""}"></div>`;
        }
      });

      html += "</div>";
      container.innerHTML = html;
    },

    getCurrentPage() {
      return window.location.pathname.toLowerCase();
    },
  };

  // ============================================
  // NAVIGATION STATE
  // ============================================

  const Navigation = {
    currentProject: null,

    init() {
      // Get project from URL or storage
      const urlParams = new URLSearchParams(window.location.search);
      this.currentProject =
        urlParams.get("projectId") ||
        localStorage.getItem("vericase_current_project");

      if (this.currentProject) {
        localStorage.setItem("vericase_current_project", this.currentProject);
      }

      // Mark active nav item
      this.markActiveNavItem();

      // Setup mobile menu toggle
      this.setupMobileMenu();
    },

    markActiveNavItem() {
      const currentPath = window.location.pathname.toLowerCase();
      document.querySelectorAll(".nav-item").forEach((item) => {
        const href = item.getAttribute("href");
        if (
          href &&
          currentPath.includes(href.replace(".html", "").toLowerCase())
        ) {
          item.classList.add("active");
        } else {
          item.classList.remove("active");
        }
      });
    },

    setupMobileMenu() {
      const toggle = document.getElementById("sidebarToggle");
      const sidebar = document.querySelector(".app-sidebar");

      if (toggle && sidebar) {
        toggle.addEventListener("click", () => {
          sidebar.classList.toggle("mobile-open");
        });
      }
    },

    goTo(page, params = {}) {
      const url = new URL(page, window.location.origin);
      if (this.currentProject) {
        url.searchParams.set("projectId", this.currentProject);
      }
      Object.entries(params).forEach(([key, value]) => {
        url.searchParams.set(key, value);
      });
      window.location.href = url.toString();
    },

    goToDashboard() {
      this.goTo("dashboard.html");
    },
    goToEvidence() {
      this.goTo("evidence.html");
    },
    goToCorrespondence() {
      this.goTo("correspondence-enterprise.html");
    },
    goToUpload() {
      this.goTo("pst-upload.html");
    },
    goToWizard() {
      this.goTo("wizard.html");
    },
    goToRefinement() {
      this.goTo("ai-refinement-wizard.html");
    },
  };

  // ============================================
  // LOADING STATES
  // ============================================

  const Loading = {
    showSkeleton(container, rows = 8) {
      const el =
        typeof container === "string"
          ? document.querySelector(container)
          : container;
      if (!el) return;

      let html = '<div class="loading-skeleton">';
      for (let i = 0; i < rows; i++) {
        html += `<div class="skeleton skeleton-row" style="animation-delay: ${i * 50}ms"></div>`;
      }
      html += "</div>";
      el.innerHTML = html;
    },

    showCardSkeleton(container, cards = 4) {
      const el =
        typeof container === "string"
          ? document.querySelector(container)
          : container;
      if (!el) return;

      let html =
        '<div class="loading-skeleton" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px;">';
      for (let i = 0; i < cards; i++) {
        html += `<div class="skeleton skeleton-card" style="animation-delay: ${i * 100}ms"></div>`;
      }
      html += "</div>";
      el.innerHTML = html;
    },

    showSpinner(container, message = "Loading...") {
      const el =
        typeof container === "string"
          ? document.querySelector(container)
          : container;
      if (!el) return;

      el.innerHTML = `
                <div class="empty-state">
                    <div class="loading" style="width: 32px; height: 32px; border-width: 3px;"></div>
                    <p style="margin-top: 16px; color: var(--text-secondary);">${message}</p>
                </div>
            `;
    },

    hidePreload() {
      document.body.classList.remove("preload");
    },
  };

  // ============================================
  // KEYBOARD SHORTCUTS
  // ============================================

  const Shortcuts = {
    handlers: {},

    init() {
      document.addEventListener("keydown", (e) => {
        // Don't trigger if typing in input
        if (e.target.matches("input, textarea, select, [contenteditable]"))
          return;

        const key = this.getKeyCombo(e);
        if (this.handlers[key]) {
          e.preventDefault();
          this.handlers[key](e);
        }
      });

      // Register default shortcuts
      this.register("ctrl+k", () => this.openCommandPalette());
      this.register("ctrl+/", () =>
        document.querySelector(".search-input")?.focus(),
      );
      this.register("escape", () => this.closeAll());
    },

    getKeyCombo(e) {
      const parts = [];
      if (e.ctrlKey || e.metaKey) parts.push("ctrl");
      if (e.shiftKey) parts.push("shift");
      if (e.altKey) parts.push("alt");
      parts.push(e.key.toLowerCase());
      return parts.join("+");
    },

    register(combo, handler) {
      this.handlers[combo.toLowerCase()] = handler;
    },

    openCommandPalette() {
      // Placeholder for command palette
      ToastManager.info("Command palette coming soon! (Ctrl+K)");
    },

    closeAll() {
      // Close any open panels/modals
      document
        .querySelectorAll(".slide-panel.open")
        .forEach((p) => p.classList.remove("open"));
      document
        .querySelectorAll(".slide-panel-backdrop.visible")
        .forEach((b) => b.classList.remove("visible"));
      document
        .querySelectorAll(".modal.open")
        .forEach((m) => m.classList.remove("open"));
    },
  };

  // ============================================
  // CONFIRMATION DIALOGS
  // ============================================

  const Confirm = {
    show(message, options = {}) {
      return new Promise((resolve) => {
        const {
          title = "Confirm",
          confirmText = "Confirm",
          cancelText = "Cancel",
          type = "warning",
        } = options;

        const backdrop = document.createElement("div");
        backdrop.className = "slide-panel-backdrop visible";
        backdrop.style.cssText =
          "display: flex; align-items: center; justify-content: center;";

        const dialog = document.createElement("div");
        dialog.className = "confirm-dialog animate-scaleIn";
        dialog.style.cssText = `
                    background: white;
                    border-radius: var(--radius-xl);
                    box-shadow: var(--shadow-2xl);
                    padding: 24px;
                    max-width: 400px;
                    width: 90%;
                `;

        dialog.innerHTML = `
                    <h3 style="margin-bottom: 12px; font-size: 1.125rem;">${title}</h3>
                    <p style="color: var(--text-secondary); margin-bottom: 24px;">${message}</p>
                    <div style="display: flex; gap: 12px; justify-content: flex-end;">
                        <button class="btn btn-ghost cancel-btn">${cancelText}</button>
                        <button class="btn ${type === "danger" ? "btn-danger" : "btn-vericase"} confirm-btn">${confirmText}</button>
                    </div>
                `;

        backdrop.appendChild(dialog);
        document.body.appendChild(backdrop);

        const cleanup = (result) => {
          backdrop.classList.remove("visible");
          setTimeout(() => backdrop.remove(), 300);
          resolve(result);
        };

        dialog
          .querySelector(".cancel-btn")
          .addEventListener("click", () => cleanup(false));
        dialog
          .querySelector(".confirm-btn")
          .addEventListener("click", () => cleanup(true));
        backdrop.addEventListener("click", (e) => {
          if (e.target === backdrop) cleanup(false);
        });
      });
    },
  };

  // ============================================
  // PROJECT CONTEXT BAR
  // ============================================

  const ProjectContext = {
    render(containerId, projectData) {
      const container = document.getElementById(containerId);
      if (!container || !projectData) return;

      container.innerHTML = `
                <div class="project-context-bar" style="
                    background: white;
                    border-bottom: 1px solid var(--gray-200);
                    padding: 12px 24px;
                    display: flex;
                    align-items: center;
                    gap: 24px;
                    font-size: 0.875rem;
                ">
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <i class="fas fa-building" style="color: var(--vericase-teal);"></i>
                        <span style="font-weight: 600; color: var(--text-primary);">${projectData.name || "Unnamed Project"}</span>
                    </div>
                    <div style="color: var(--text-secondary);">
                        <i class="fas fa-envelope"></i> ${projectData.emailCount?.toLocaleString() || 0} emails
                    </div>
                    <div style="color: var(--text-secondary);">
                        <i class="fas fa-folder"></i> ${projectData.evidenceCount?.toLocaleString() || 0} evidence items
                    </div>
                    <div style="margin-left: auto;">
                        <button class="btn btn-ghost btn-sm" onclick="VericaseUI.Navigation.goTo('wizard.html')">
                            <i class="fas fa-cog"></i> Settings
                        </button>
                    </div>
                </div>
            `;
    },
  };

  // ============================================
  // INIT & EXPORT
  // ============================================

  function init() {
    // Add preload class to prevent FOUC transitions
    document.body.classList.add("preload");

    // Initialize systems
    Navigation.init();
    Shortcuts.init();

    // Remove preload after page loads
    window.addEventListener("load", () => {
      requestAnimationFrame(() => {
        Loading.hidePreload();
      });
    });
  }

  // Auto-init when DOM ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  // Export to global
  window.VericaseUI = {
    Toast: ToastManager,
    Progress: ProgressTracker,
    Navigation,
    Loading,
    Shortcuts,
    Confirm,
    ProjectContext,
  };
})();
