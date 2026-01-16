/*
 * admin-users.js
 * User Management (Admin) page logic for admin-users.html
 *
 * Rationale:
 * - Avoid inline <script> and inline onclick= handlers so the page keeps working
 *   under stricter CSP settings.
 * - Use event delegation for table actions.
 */

(() => {
  "use strict";

  console.info("[admin-users] script loaded");

  const $ = (id) => document.getElementById(id);

  const escape = (value) => {
    try {
      if (typeof window.escapeHtml === "function") return window.escapeHtml(value);
    } catch {
      // ignore
    }
    // Minimal safe fallback
    if (value === null || value === undefined) return "";
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\"/g, "&quot;")
      .replace(/'/g, "&#039;");
  };

  let users = [];
  let invitations = [];
  let currentEditId = null;
  let currentUserRole = "USER";

  function normalizeRoleValue(role) {
    const raw = (role || "").toString().trim();
    if (!raw) return "USER";

    const upper = raw.toUpperCase();

    // Backward-compatible mappings from older UI terminology.
    const legacy = {
      VIEWER: "USER",
      EDITOR: "USER",
      MANAGER: "MANAGEMENT_USER",
      MANAGEMENT: "MANAGEMENT_USER",
      POWER: "POWER_USER",
    };

    return legacy[upper] || upper;
  }

  function requireAuthOrRedirect() {
    const token =
      localStorage.getItem("vericase_token") ||
      localStorage.getItem("token") ||
      localStorage.getItem("jwt") ||
      localStorage.getItem("access_token");
    if (!token) {
      window.location.href = "login.html";
      return false;
    }
    return true;
  }

  async function apiCall(endpoint, method = "GET", body = null) {
    // Use secureApiFetch to ensure Authorization + CSRF are applied consistently.
    if (typeof window.secureApiFetch !== "function") {
      throw new Error("secureApiFetch is not available (security.js not loaded?)");
    }

    const options = { method };
    if (body) {
      options.body = JSON.stringify(body);
    }

    const response = await window.secureApiFetch(endpoint, options);

    if (response.status === 401) {
      localStorage.removeItem("token");
      localStorage.removeItem("user");
      window.location.href = "login.html";
      return null;
    }

    if (response.status === 403) {
      // Distinguish "not authenticated" (often returned as 403 by HTTPBearer)
      // from actual permission errors.
      let detail = "";
      try {
        const err = await response.clone().json();
        detail = err?.detail || "";
      } catch {
        // ignore
      }
      const norm = String(detail || "").toLowerCase();
      if (norm.includes("not authenticated") || norm.includes("authentication")) {
        localStorage.removeItem("token");
        localStorage.removeItem("user");
        window.location.href = "login.html";
        return null;
      }
      return response;
    }

    return response;
  }

  async function loadCurrentUser() {
    try {
      const response = await apiCall("/api/users/me");
      if (response && response.ok) {
        const user = await response.json();
        currentUserRole = normalizeRoleValue(user?.role || "USER");
        const el = $("currentUser");
        if (el) el.textContent = user.email || "";
        applyRoleRestrictions();
      }
    } catch (error) {
      console.error("[admin-users] Failed to load current user:", error);
    }
  }

  function applyRoleRestrictions() {
    const roleSelect = $("userRole");
    if (!roleSelect) return;

    const allowed =
      currentUserRole === "ADMIN"
        ? new Set(["USER", "MANAGEMENT_USER", "POWER_USER", "ADMIN"])
        : currentUserRole === "MANAGEMENT_USER"
          ? new Set(["USER", "MANAGEMENT_USER"])
          : new Set(["USER"]);

    Array.from(roleSelect.options || []).forEach((opt) => {
      const v = normalizeRoleValue(opt.value);
      opt.disabled = !allowed.has(v);
    });

    // If current selection becomes invalid (e.g. switching user), reset to USER.
    if (!allowed.has(normalizeRoleValue(roleSelect.value))) {
      roleSelect.value = "USER";
    }
  }

  function canManageRole(targetRole) {
    const normalized = normalizeRoleValue(targetRole || "USER");
    if (currentUserRole === "ADMIN") return true;
    if (currentUserRole === "MANAGEMENT_USER") {
      return normalized === "USER" || normalized === "MANAGEMENT_USER";
    }
    return false;
  }

  function updateStats() {
    const total = users.length;
    const active = users.filter((u) => u?.is_active).length;
    const admins = users.filter((u) => (u?.role || "").toUpperCase() === "ADMIN").length;
    const verified = users.filter((u) => !!u?.email_verified).length;

    const totalEl = $("totalUsers");
    const activeEl = $("activeUsers");
    const adminEl = $("adminCount");
    const verifiedEl = $("verifiedCount");

    if (totalEl) totalEl.textContent = String(total);
    if (activeEl) activeEl.textContent = String(active);
    if (adminEl) adminEl.textContent = String(admins);
    if (verifiedEl) verifiedEl.textContent = String(verified);
  }

  function initialsForUser(user) {
    const displayName = (user?.display_name || "").trim();
    if (displayName) {
      return displayName
        .split(/\s+/)
        .filter(Boolean)
        .slice(0, 2)
        .map((n) => (n[0] || "").toUpperCase())
        .join("");
    }

    const email = (user?.email || "").trim();
    return (email[0] || "?").toUpperCase();
  }

  function formatLastLogin(user) {
    const raw = user?.last_login_at;
    if (!raw) return "Never";
    try {
      const d = new Date(raw);
      if (Number.isNaN(d.getTime())) return "Never";
      return d.toLocaleDateString();
    } catch {
      return "Never";
    }
  }

  function renderUsersTable() {
    const tableHost = $("tableContent");
    if (!tableHost) return;

    const searchTerm = (($("searchInput")?.value || "") + "").toLowerCase();

    const filteredUsers = users.filter((u) => {
      const email = (u?.email || "").toLowerCase();
      const name = (u?.display_name || "").toLowerCase();
      return email.includes(searchTerm) || name.includes(searchTerm);
    });

    if (filteredUsers.length === 0) {
      tableHost.innerHTML = `
        <div class="loading">
          <p>No users found</p>
        </div>
      `;
      return;
    }

    tableHost.innerHTML = `
      <table class="users-table">
        <thead>
          <tr>
            <th>User</th>
            <th>Role</th>
            <th>Status</th>
            <th>Email Verified</th>
            <th>Last Login</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          ${filteredUsers
            .map((user) => {
              const id = escape(user?.id || "");
              const email = escape(user?.email || "");
              const displayName = escape(user?.display_name || "No name");
              const initials = escape(initialsForUser(user));

              const role = normalizeRoleValue((user?.role || "USER") + "");
              const roleLower = escape(role.toLowerCase());
              const roleLabel = role.replace(/_/g, " ");

              const isActive = !!user?.is_active;
              const isVerified = !!user?.email_verified;

              const lastLogin = escape(formatLastLogin(user));

              return `
                <tr>
                  <td>
                    <div class="user-info">
                      <div class="user-avatar">${initials}</div>
                      <div class="user-details">
                        <div class="name">${displayName}</div>
                        <div class="email">${email}</div>
                      </div>
                    </div>
                  </td>
                  <td>
                    <span class="badge badge-${roleLower}">${escape(roleLabel)}</span>
                  </td>
                  <td>
                    <span class="badge badge-${isActive ? "active" : "inactive"}">
                      ${isActive ? "Active" : "Inactive"}
                    </span>
                  </td>
                  <td>
                    <span class="badge badge-${isVerified ? "verified" : "unverified"}">
                      ${isVerified ? "Verified" : "Unverified"}
                    </span>
                  </td>
                  <td>${lastLogin}</td>
                  <td>
                    <div class="actions">
                      <button class="btn btn-secondary btn-sm" type="button" data-action="edit" data-user-id="${id}">
                        <i class="fas fa-edit"></i> Edit
                      </button>
                      <button class="btn btn-secondary btn-sm" type="button" data-action="reset" data-user-id="${id}">
                        <i class="fas fa-key"></i> Reset
                      </button>
                    </div>
                  </td>
                </tr>
              `;
            })
            .join(" ")}
        </tbody>
      </table>
    `;

    // Disable actions for users outside the current operator's scope.
    if (currentUserRole !== "ADMIN") {
      tableHost.querySelectorAll?.("button[data-action][data-user-id]")?.forEach?.((btn) => {
        const userId = btn.getAttribute("data-user-id");
        const u = users.find((x) => String(x?.id) === String(userId));
        if (!u) return;
        if (!canManageRole(u?.role)) {
          btn.disabled = true;
          btn.title = "You don't have permission to manage this user";
        }
      });
    }
  }

  function openCreateModal() {
    currentEditId = null;

    const modal = $("userModal");
    if (!modal) return;

    $("modalTitle").textContent = "Invite User";
    $("saveButtonText").textContent = "Send Invite";
    $("userForm")?.reset();

    $("userActive").checked = true;
    $("sendInvite").checked = true;

    const activeGroup = $("activeGroup");
    const inviteGroup = $("inviteGroup");
    if (activeGroup) activeGroup.style.display = "none";
    if (inviteGroup) inviteGroup.style.display = "block";

    $("userEmail").disabled = false;
    applyRoleRestrictions();

    modal.classList.add("open");
    const alert = $("modalAlert");
    if (alert) alert.style.display = "none";
  }

  function openEditModal(userId) {
    currentEditId = userId;
    const user = users.find((u) => String(u?.id) === String(userId));
    if (!user) return;

    if (!canManageRole(user?.role)) {
      if (window.VericaseUI?.Toast) {
        window.VericaseUI.Toast.error("You don't have permission to edit this user.");
      } else {
        alert("You don't have permission to edit this user.");
      }
      return;
    }

    const modal = $("userModal");
    if (!modal) return;

    $("modalTitle").textContent = "Edit User";
    $("saveButtonText").textContent = "Update User";

    $("userId").value = user.id || "";
    $("userEmail").value = user.email || "";
    $("userEmail").disabled = true;
    $("userDisplayName").value = user.display_name || "";
    $("userRole").value = normalizeRoleValue(user.role || "USER");
    applyRoleRestrictions();
    $("userActive").checked = !!user.is_active;

    const activeGroup = $("activeGroup");
    const inviteGroup = $("inviteGroup");
    if (activeGroup) activeGroup.style.display = "block";
    if (inviteGroup) inviteGroup.style.display = "none";

    modal.classList.add("open");
    const alert = $("modalAlert");
    if (alert) alert.style.display = "none";
  }

  function closeModal() {
    const modal = $("userModal");
    if (modal) modal.classList.remove("open");
    currentEditId = null;
  }

  function showModalError(message) {
    const alert = $("modalAlert");
    if (!alert) return;

    alert.className = "alert alert-error";
    alert.textContent = message || "An error occurred";
    alert.style.display = "block";
  }

  async function saveUser() {
    const alert = $("modalAlert");
    if (alert) alert.style.display = "none";

    const emailEl = $("userEmail");
    const displayNameEl = $("userDisplayName");
    const roleEl = $("userRole");
    const activeEl = $("userActive");

    const data = {
      email: (emailEl?.value || "").trim(),
      display_name: (displayNameEl?.value || "").trim(),
      role: (roleEl?.value || "USER").trim(),
      is_active: !!activeEl?.checked,
    };

    try {
      let response;

      if (currentEditId) {
        // Update existing user (email cannot be updated)
        delete data.email;
        response = await apiCall(`/api/users/${encodeURIComponent(currentEditId)}`, "PATCH", data);
      } else {
        // Invite flow (preferred onboarding): create an invitation token.
        const inviteReq = {
          email: data.email,
          role: data.role,
        };
        response = await apiCall("/api/users/invitations", "POST", inviteReq);
      }

      if (!response) return;

      if (response.ok) {
        if (currentEditId) {
          closeModal();
          await loadUsers();
          if (window.VericaseUI?.Toast) {
            window.VericaseUI.Toast.success("User updated");
          }
          return;
        }

        // Invite created: show/copy link and refresh invitations list.
        let invite = null;
        try {
          invite = await response.json();
        } catch {
          // ignore
        }

        closeModal();
        await loadInvitations();

        const token = invite?.token;
        const inviteUrl = token
          ? `${window.location.origin}/ui/register.html?invite=${encodeURIComponent(token)}`
          : null;

        const shouldCopy = !!$("sendInvite")?.checked;
        if (inviteUrl && shouldCopy) {
          try {
            await navigator.clipboard.writeText(inviteUrl);
            if (window.VericaseUI?.Toast) {
              window.VericaseUI.Toast.success("Invitation link copied to clipboard");
            } else {
              alert("Invitation link copied to clipboard");
            }
          } catch (e) {
            // Fallback for browsers without clipboard permissions
            if (window.VericaseUI?.Toast) {
              window.VericaseUI.Toast.info("Copy this invitation link from the prompt");
            }
            window.prompt("Copy invitation link:", inviteUrl);
          }
        } else if (inviteUrl) {
          if (window.VericaseUI?.Toast) {
            window.VericaseUI.Toast.success("Invitation created");
          } else {
            alert("Invitation created");
          }
        } else {
          if (window.VericaseUI?.Toast) {
            window.VericaseUI.Toast.success("Invitation created");
          }
        }
        return;
      }

      let detail = "Failed to save user";
      try {
        const err = await response.json();
        detail = err?.detail || detail;
      } catch {
        // ignore
      }
      showModalError(detail);
    } catch (error) {
      console.error("[admin-users] saveUser failed:", error);
      showModalError("An error occurred. Please try again.");
    }
  }

  async function resetPassword(userId) {
    const user = users.find((u) => String(u?.id) === String(userId));
    if (!user) return;

    if (!confirm(`Send password reset email to ${user.email}?`)) {
      return;
    }

    try {
      const response = await apiCall("/api/auth/request-reset", "POST", {
        email: user.email,
      });

      if (response && response.ok) {
        alert("Password reset email sent successfully!");
      }
    } catch (error) {
      console.error("[admin-users] resetPassword failed:", error);
      alert("Failed to send reset email");
    }
  }

  async function loadUsers() {
    try {
      const response = await apiCall("/api/users");
      if (response && response.ok) {
        users = await response.json();
        updateStats();
        renderUsersTable();
        return;
      }

      if (response && response.status === 403) {
        const tableHost = $("tableContent");
        if (tableHost) {
          tableHost.innerHTML = `
            <div class="loading">
              <p style="color: #ef4444;">Access denied. You need Admin or Management permissions.</p>
            </div>
          `;
        }
        return;
      }
    } catch (error) {
      console.error("[admin-users] Failed to load users:", error);
    }

    const tableHost = $("tableContent");
    if (tableHost) {
      tableHost.innerHTML = `
        <div class="loading">
          <p style="color: #ef4444;">Failed to load users</p>
        </div>
      `;
    }
  }

  function formatInviteExpiry(inv) {
    const raw = inv?.expires_at;
    if (!raw) return "";
    try {
      const d = new Date(raw);
      if (Number.isNaN(d.getTime())) return "";
      return d.toLocaleString();
    } catch {
      return "";
    }
  }

  function renderInvitationsTable() {
    const host = $("invitesContent");
    if (!host) return;

    if (!invitations || invitations.length === 0) {
      host.innerHTML = `
        <div class="loading">
          <p>No active invitations</p>
        </div>
      `;
      return;
    }

    host.innerHTML = `
      <table class="users-table">
        <thead>
          <tr>
            <th>Email</th>
            <th>Role</th>
            <th>Expires</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          ${invitations
            .map((inv) => {
              const token = escape(inv?.token || "");
              const email = escape(inv?.email || "");
              const role = normalizeRoleValue(inv?.role || "USER");
              const roleLabel = escape(role.replace(/_/g, " "));
              const expires = escape(formatInviteExpiry(inv));

              return `
                <tr>
                  <td>${email}</td>
                  <td><span class="badge badge-${escape(role.toLowerCase())}">${roleLabel}</span></td>
                  <td>${expires}</td>
                  <td>
                    <div class="actions">
                      <button class="btn btn-secondary btn-sm" type="button" data-action="copy-invite" data-token="${token}">
                        <i class="fas fa-link"></i> Copy Link
                      </button>
                      <button class="btn btn-secondary btn-sm" type="button" data-action="revoke-invite" data-token="${token}">
                        <i class="fas fa-trash"></i> Revoke
                      </button>
                    </div>
                  </td>
                </tr>
              `;
            })
            .join(" ")}
        </tbody>
      </table>
    `;
  }

  async function loadInvitations() {
    const host = $("invitesContent");
    if (host) {
      host.innerHTML = `
        <div class="loading">
          <div class="spinner"></div>
          <p>Loading invitations...</p>
        </div>
      `;
    }

    try {
      const response = await apiCall("/api/users/invitations");
      if (response && response.ok) {
        invitations = await response.json();
        renderInvitationsTable();
        return;
      }

      if (response && response.status === 403) {
        if (host) {
          host.innerHTML = `
            <div class="loading">
              <p style="color: #ef4444;">Access denied. You need Admin or Management permissions.</p>
            </div>
          `;
        }
        return;
      }
    } catch (error) {
      console.error("[admin-users] Failed to load invitations:", error);
    }

    if (host) {
      host.innerHTML = `
        <div class="loading">
          <p style="color: #ef4444;">Failed to load invitations</p>
        </div>
      `;
    }
  }

  async function copyInviteLink(token) {
    const inviteUrl = `${window.location.origin}/ui/register.html?invite=${encodeURIComponent(token)}`;
    try {
      await navigator.clipboard.writeText(inviteUrl);
      if (window.VericaseUI?.Toast) {
        window.VericaseUI.Toast.success("Invitation link copied to clipboard");
      } else {
        alert("Invitation link copied to clipboard");
      }
    } catch {
      window.prompt("Copy invitation link:", inviteUrl);
    }
  }

  async function revokeInvite(token) {
    if (!confirm("Revoke this invitation?")) return;

    try {
      const response = await apiCall(`/api/users/invitations/${encodeURIComponent(token)}`, "DELETE");
      if (response && response.ok) {
        await loadInvitations();
        if (window.VericaseUI?.Toast) {
          window.VericaseUI.Toast.success("Invitation revoked");
        }
      } else {
        if (window.VericaseUI?.Toast) {
          window.VericaseUI.Toast.error("Failed to revoke invitation");
        } else {
          alert("Failed to revoke invitation");
        }
      }
    } catch (error) {
      console.error("[admin-users] revokeInvite failed:", error);
      if (window.VericaseUI?.Toast) {
        window.VericaseUI.Toast.error("Failed to revoke invitation");
      } else {
        alert("Failed to revoke invitation");
      }
    }
  }

  function bindEvents() {
    $("searchInput")?.addEventListener("input", renderUsersTable);
    $("addUserBtn")?.addEventListener("click", openCreateModal);
    $("cancelModalBtn")?.addEventListener("click", closeModal);
    $("saveUserBtn")?.addEventListener("click", saveUser);
    $("refreshInvitesBtn")?.addEventListener("click", loadInvitations);

    // Table actions (event delegation)
    $("tableContent")?.addEventListener("click", (e) => {
      const btn = e.target?.closest?.("button[data-action]");
      if (!btn) return;

      const action = btn.getAttribute("data-action");
      const userId = btn.getAttribute("data-user-id");

      if (action === "edit") {
        openEditModal(userId);
      } else if (action === "reset") {
        resetPassword(userId);
      }
    });

    // Invitations actions (event delegation)
    $("invitesContent")?.addEventListener("click", (e) => {
      const btn = e.target?.closest?.("button[data-action]");
      if (!btn) return;

      const action = btn.getAttribute("data-action");
      const token = btn.getAttribute("data-token");
      if (!token) return;

      if (action === "copy-invite") {
        copyInviteLink(token);
      } else if (action === "revoke-invite") {
        revokeInvite(token);
      }
    });

    // Escape key closes modal
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        const modal = $("userModal");
        if (modal?.classList?.contains("open")) {
          closeModal();
        }
      }
    });
  }

  function injectShell() {
    try {
      if (window.VericaseShell?.inject) {
        window.VericaseShell.inject({
          title: "",
          breadcrumbs: [
            { label: "Control Centre", url: "control-centre.html", icon: "fa-compass" },
            { label: "User Management", icon: "fa-id-badge" },
          ],
          headerActions:
            '<span id="currentUser" style="color: var(--text-muted); font-size: 14px;"></span>',
        });
      }
    } catch (error) {
      console.warn("[admin-users] Shell injection failed:", error);
    }

    // Remove preload class after shell is injected
    requestAnimationFrame(() => {
      document.body.classList.remove("preload");
    });
  }

  async function init() {
    if (!requireAuthOrRedirect()) return;

    injectShell();
    bindEvents();

    await loadCurrentUser();
    await loadUsers();
    await loadInvitations();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
