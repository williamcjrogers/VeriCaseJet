// VeriCase Frontend Configuration
// This file handles API URL configuration for both local development and AWS deployment

(function () {
  "use strict";

  // Configuration object
  window.VeriCaseConfig = {
    // AG Grid Enterprise license key
    // NOTE: This value is necessarily present client-side when using AG Grid Enterprise.
    // You can override at runtime by defining `window.VERICASE_AG_GRID_LICENSE_KEY` before
    // any page initializes AG Grid.
    get agGridLicenseKey() {
      return (
        window.VERICASE_AG_GRID_LICENSE_KEY ||
        "Using_this_{AG_Charts_and_AG_Grid}_Enterprise_key_{AG-113929}_in_excess_of_the_licence_granted_is_not_permitted___Please_report_misuse_to_legal@ag-grid.com___For_help_with_changing_this_key_please_contact_info@ag-grid.com___{Quantum_Commercial_Solutions}_is_granted_a_{Single_Application}_Developer_License_for_the_application_{VeriCase}_only_for_{1}_Front-End_JavaScript_developer___All_Front-End_JavaScript_developers_working_on_{VeriCase}_need_to_be_licensed___{VeriCase}_has_been_granted_a_Deployment_License_Add-on_for_{1}_Production_Environment___This_key_works_with_{AG_Charts_and_AG_Grid}_Enterprise_versions_released_before_{2_December_2026}____[v3]_[0102]_MTc5NjE2OTYwMDAwMA==3028fd492276b13c54c2a50715493e19"
      );
    },

    // API URL Configuration
    getApiUrl: function () {
      // Check if we're running locally
      if (
        window.location.hostname === "localhost" ||
        window.location.hostname === "127.0.0.1"
      ) {
        return window.location.protocol + "//localhost:8010";
      }

      // Check for explicit API URL (e.g. from Amplify environment variables)
      if (window.VERICASE_API_URL) {
        return window.VERICASE_API_URL;
      }

      // AWS App Runner deployment (Monolith fallback)
      // The API is hosted on the same App Runner service, accessible via the same URL
      // App Runner handles both static files (UI) and API routes
      return window.location.origin;
    },

    // Get the base API endpoint
    get apiUrl() {
      return this.getApiUrl();
    },

    // Check if we're in development mode
    get isDevelopment() {
      return (
        window.location.hostname === "localhost" ||
        window.location.hostname === "127.0.0.1"
      );
    },

    // Check if we're in production (AWS)
    get isProduction() {
      return !this.isDevelopment;
    },

    // S3/Storage Configuration
    get storageEndpoint() {
      if (this.isDevelopment) {
        // Local MinIO endpoint
        return "http://localhost:9002";
      }
      // AWS S3 - handled by the API backend
      return null; // API will use AWS SDK with proper credentials
    },

    // Feature flags
    features: {
      aiEnabled: true, // Can be disabled if AI services are not configured
      debugMode: false, // Set to true for additional logging
    },

    // Helper function to make API calls with proper error handling.
    // Delegates to secureApiFetch so that Authorization and X-CSRF-Token
    // are applied consistently across the frontend.
    async apiCall(endpoint, options = {}) {
      let response;
      try {
        response = await secureApiFetch(endpoint, options);
      } catch (error) {
        console.error("API call error:", error);
        throw error;
      }

      if (!response.ok) {
        // Log error details for debugging
        if (this.features.debugMode) {
          console.error(
            `API call failed: ${response.status} ${response.statusText}`,
          );
          console.error("Endpoint:", endpoint);
          try {
            const text = await response.clone().text();
            console.error("Response:", text);
          } catch (e) {
            // ignore body read errors
          }
        }

        // Handle specific error codes
        if (response.status === 401) {
          console.error("Authentication failed - redirecting to login");
          if (!window.location.pathname.includes("login")) {
            // Clear authentication tokens from localStorage
            ["vericase_token", "access_token", "token", "jwt"].forEach((key) =>
              localStorage.removeItem(key),
            );
            // Clear CSRF tokens from sessionStorage
            sessionStorage.removeItem("csrf-token");
            sessionStorage.removeItem("vericase_csrf");
            window.location.href = "/ui/login.html";
          }
        }

        const error = new Error(
          `API call failed: ${response.status} ${response.statusText}`,
        );
        console.error("API call error:", error);
        throw error;
      }

      return response;
    },

    // Initialize configuration
    init() {
      // Log configuration for debugging
      console.log("VeriCase Configuration:");
      console.log(
        "- Environment:",
        this.isDevelopment ? "Development" : "Production",
      );
      console.log("- API URL:", this.apiUrl);
      console.log(
        "- Storage Endpoint:",
        this.storageEndpoint || "AWS S3 (backend managed)",
      );

      // Check if we're on AWS and need to use HTTPS
      if (this.isProduction && window.location.protocol === "http:") {
        console.warn("Running on HTTP in production - consider using HTTPS");
      }

      // Set up global error handler for network issues
      window.addEventListener("unhandledrejection", (event) => {
        if (
          event.reason &&
          event.reason.message &&
          event.reason.message.includes("fetch")
        ) {
          console.error("Network error detected:", event.reason);
          // Could show a user-friendly error message here
        }
      });
    },
  };

  // Initialize on load
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => VeriCaseConfig.init());
  } else {
    VeriCaseConfig.init();
  }
})();
