/**
 * Security Utilities for VeriCase Analysis Frontend
 *
 * This module provides security functions to protect against common web vulnerabilities:
 * - XSS (Cross-Site Scripting)
 * - CSRF (Cross-Site Request Forgery)
 * - Insecure connections
 */

/**
 * Sanitize user input to prevent XSS attacks
 * Escapes HTML special characters that could be used for injection
 *
 * @param {*} unsafe - User input that may contain malicious code
 * @returns {string} Sanitized string safe for HTML insertion
 *
 * @example
 * const userInput = '<script>alert("XSS")</script>';
 * const safe = escapeHtml(userInput);
 * // Result: '&lt;script&gt;alert(&quot;XSS&quot;)&lt;/script&gt;'
 */
function escapeHtml(unsafe) {
  if (unsafe === null || unsafe === undefined) {
    return "";
  }
  return String(unsafe)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

/**
 * Get or generate CSRF token for request protection
 * Generates a cryptographically secure random token if none exists
 *
 * @returns {string} CSRF token
 */
function getCsrfToken() {
  let token = localStorage.getItem("csrf-token");
  if (!token) {
    // Generate a cryptographically secure random token (64 hex characters = 32 bytes)
    token = Array.from(crypto.getRandomValues(new Uint8Array(32)))
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");
    localStorage.setItem("csrf-token", token);
  }
  return token;
}

/**
 * Get API base URL with appropriate protocol
 *
 * - Development (localhost): Uses current page protocol (http:// or https://)
 * - Production: Always uses current origin (enforces HTTPS in production)
 *
 * @returns {string} API base URL with protocol
 */
function getApiUrl() {
  if (
    window.location.hostname === "localhost" ||
    window.location.hostname === "127.0.0.1"
  ) {
    // Development: Use same protocol as current page
    return `${window.location.protocol}//localhost:8010`;
  }
  // Production: Use current origin (should be HTTPS)
  return window.location.origin || "";
}

/**
 * Make a secure API request with proper headers and error handling
 *
 * @param {string} endpoint - API endpoint path (e.g., '/api/cases')
 * @param {Object} options - Fetch options
 * @returns {Promise<Response>} Fetch response
 */
async function secureApiFetch(endpoint, options = {}) {
  const apiUrl = getApiUrl();
  const token = localStorage.getItem("token");
  const csrfToken = getCsrfToken();

  const defaultHeaders = {
    "Content-Type": "application/json",
    "X-CSRF-Token": csrfToken,
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };

  const fetchOptions = {
    ...options,
    headers: {
      ...defaultHeaders,
      ...(options.headers || {}),
    },
    credentials: "same-origin", // Include cookies for session-based auth
  };

  try {
    const response = await fetch(`${apiUrl}${endpoint}`, fetchOptions);
    return response;
  } catch (error) {
    console.error(`API request failed: ${endpoint}`, error);
    throw error;
  }
}

/**
 * Validate that the application is running over HTTPS in production
 * Logs a warning if running over HTTP in production environment
 */
function enforceHttpsInProduction() {
  const isProduction =
    window.location.hostname !== "localhost" &&
    window.location.hostname !== "127.0.0.1";

  if (isProduction && window.location.protocol !== "https:") {
    console.warn(
      "WARNING: Running over insecure HTTP connection in production environment",
    );
    console.warn("Please configure HTTPS for secure communication");

    // Optionally redirect to HTTPS (uncomment if desired)
    // window.location.href = `https://${window.location.host}${window.location.pathname}${window.location.search}`;
  }
}

// Run HTTPS enforcement check on load
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", enforceHttpsInProduction);
} else {
  enforceHttpsInProduction();
}

// Export functions for use in other scripts
// eslint-disable-next-line no-undef
if (typeof module !== "undefined" && module.exports) {
  module.exports = { escapeHtml, getCsrfToken, getApiUrl, secureApiFetch };
}
