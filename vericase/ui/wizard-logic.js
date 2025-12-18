// cspell:ignore maxlength NHBC Organisation FIDIC Segoe
// ============================================================================
// Security Utilities
// ============================================================================

/**
 * Sanitize user input to prevent XSS attacks
 * Escapes HTML special characters
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
 */
function getCsrfToken() {
  let token = sessionStorage.getItem("csrf-token");
  if (!token) {
    // Generate a random token
    token = Array.from(crypto.getRandomValues(new Uint8Array(32)))
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");
    sessionStorage.setItem("csrf-token", token);
  }
  return token;
}

/**
 * Get API base URL with appropriate protocol
 * Uses HTTPS in production, respects current protocol in development
 */
function getApiUrl() {
  if (
    window.location.hostname === "localhost" ||
    window.location.hostname === "127.0.0.1"
  ) {
    // Development: Use same protocol as current page (supports both HTTP and HTTPS)
    return `${window.location.protocol}//localhost:8010`;
  }
  // Production: Use HTTPS
  return window.location.origin || "";
}

/**
 * Create a safe HTML element with sanitized text content
 */
/*
function createSafeElement(tag, attributes = {}, textContent = "") {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (key === "className") {
      element.className = value;
    } else if (key === "onclick") {
      element.onclick = value;
    } else {
      element.setAttribute(key, value);
    }
  }
  element.textContent = textContent;
  return element;
}
*/

// ============================================================================
// Wizard State Management
// ============================================================================

const wizardState = {
  currentStep: 0,
  profileType: "project",
  data: {},
  totalSteps: 0,
};

// Pre-populated keywords list
const prePopulatedKeywords = [
  "Relevant Event",
  "Relevant Matter",
  "Section 278",
  "Delay",
  "Risk",
  "Change",
  "Variation",
];

// Pre-populated roles
const stakeholderRoles = [
  "Main Contractor",
  "Council",
  "Employers Agent",
  "Project Manager",
  "Client",
  "Building Control",
  "Subcontractor",
  "Client Management Team",
];

// Define steps for each profile type
const projectSteps = [
  {
    id: "project-identification",
    title: "Identification",
    render: renderProjectIdentification,
    validate: validateProjectIdentification,
    save: saveProjectIdentification,
  },
  {
    id: "project-stakeholders",
    title: "Stakeholders",
    render: renderProjectStakeholders,
    validate: validateProjectStakeholders,
    save: saveProjectStakeholders,
  },
  {
    id: "project-keywords",
    title: "Contract",
    render: renderProjectKeywords,
    validate: validateProjectKeywords,
    save: saveProjectKeywords,
  },
  {
    id: "project-review",
    title: "Review",
    render: renderProjectReview,
    validate: () => true,
    save: () => { },
  },
];

const caseSteps = [
  {
    id: "case-identification",
    title: "Identification",
    render: renderCaseIdentification,
    validate: validateCaseIdentification,
    save: saveCaseIdentification,
  },
  {
    id: "case-legal-team",
    title: "Legal Team",
    render: renderCaseLegalTeam,
    validate: () => true,
    save: saveCaseLegalTeam,
  },
  {
    id: "case-heads-keywords",
    title: "Claims & Keywords",
    render: renderCaseHeadsKeywords,
    validate: () => true,
    save: saveCaseHeadsKeywords,
  },
  {
    id: "case-deadlines",
    title: "Deadlines",
    render: renderCaseDeadlines,
    validate: () => true,
    save: saveCaseDeadlines,
  },
  {
    id: "case-review",
    title: "Review",
    render: renderCaseReview,
    validate: () => true,
    save: () => { },
  },
];

const AUTO_SAVE_INTERVAL_MS = 30000;
const TOKEN_REFRESH_INTERVAL_MS = 15 * 60 * 1000;
let autoSaveIntervalId = null;
let tokenRefreshIntervalId = null;

// Initialize
document.addEventListener("DOMContentLoaded", () => {
  const authenticated = checkAuthentication();
  setupEventListeners();
  showDraftRecoveryBanner();

  if (authenticated) {
    startAutoSave();
    scheduleTokenRefresh();
  }
});

function setupEventListeners() {
  document.getElementById("btnContinue").onclick = nextStep;
  document.getElementById("btnBack").addEventListener("click", previousStep);
  document.getElementById("btnCancel").addEventListener("click", cancel);
  document
    .getElementById("btnSaveDraft")
    .addEventListener("click", () => saveDraft(false));

  document.querySelectorAll('input[name="profileType"]').forEach((radio) => {
    radio.addEventListener("change", (e) => {
      wizardState.profileType = e.target.value;
    });
  });
}

function checkAuthentication() {
  // TEMPORARY: Auth disabled until admin user creation is fixed
  return true;

  /*
  const token = localStorage.getItem("token") || localStorage.getItem("jwt");

  if (!token) {
    showWizardMessage(
      "You must be logged in to use the configuration wizard. Redirecting to login…",
      "error",
      5000,
    );
    setTimeout(() => {
      window.location.href =
        "login.html?redirect=" + encodeURIComponent(window.location.pathname);
    }, 2500);
    return false;
  }

  return true;
  */
}

function showDraftRecoveryBanner() {
  const banner = document.getElementById("draftBanner");
  if (!banner) {
    return;
  }

  if (getSavedDraft()) {
    banner.style.display = "flex";
  } else {
    banner.style.display = "none";
  }
}

function startAutoSave() {
  if (autoSaveIntervalId) {
    clearInterval(autoSaveIntervalId);
  }

  autoSaveIntervalId = setInterval(() => {
    saveDraft(true);
  }, AUTO_SAVE_INTERVAL_MS);
}

function scheduleTokenRefresh() {
  if (tokenRefreshIntervalId) {
    clearInterval(tokenRefreshIntervalId);
  }

  tokenRefreshIntervalId = setInterval(() => {
    refreshToken().catch(() => {
      // Errors handled within refreshToken
    });
  }, TOKEN_REFRESH_INTERVAL_MS);
}

async function refreshToken() {
  const token = localStorage.getItem("token") || localStorage.getItem("jwt");
  if (!token) {
    return;
  }

  try {
    const response = await fetch(`${getApiUrl()}/api/auth/refresh`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": getCsrfToken(),
      },
      body: JSON.stringify({ token }),
      credentials: "same-origin",
    });

    if (response.ok) {
      const data = await response.json();
      if (data && data.access_token) {
        localStorage.setItem("token", data.access_token);
        localStorage.setItem("jwt", data.access_token);
      }
      return;
    }

    if (response.status === 401 || response.status === 403) {
      handleSessionExpired();
      return;
    }

    console.warn("Token refresh failed with status", response.status);
  } catch (error) {
    console.warn("Token refresh error:", error);
  }
}

function handleSessionExpired() {
  saveDraft(true);
  showWizardMessage(
    "Your session has expired. We saved your work — please log in again to continue.",
    "error",
    6000,
  );
  setTimeout(() => {
    window.location.href =
      "login.html?redirect=" + encodeURIComponent(window.location.pathname);
  }, 3000);
}

function getSavedDraft() {
  const draft = localStorage.getItem("wizardDraft");
  if (!draft) {
    return null;
  }

  try {
    return JSON.parse(draft);
  } catch (e) {
    console.warn("Failed to parse wizard draft", e);
    return null;
  }
}

function applyDraftState(draftState) {
  if (!draftState) {
    return;
  }

  Object.assign(wizardState, draftState);

  if (wizardState.profileType && wizardState.profileType !== "intelligent") {
    const radio = document.querySelector(
      `input[name="profileType"][value="${wizardState.profileType}"]`,
    );
    if (radio) {
      radio.checked = true;
    }
  }

  if (wizardState.currentStep > 0) {
    document.getElementById("step-entry").classList.remove("active");

    const steps =
      wizardState.profileType === "project" ? projectSteps : caseSteps;
    wizardState.totalSteps = steps.length;

    updateStepIndicator(steps);
    renderCurrentStep();
    document.getElementById("btnBack").style.display = "block";
  }
}

function restoreDraft() {
  const draftState = getSavedDraft();
  if (!draftState) {
    showWizardMessage("No saved draft found.", "info");
    return;
  }

  applyDraftState(draftState);
  showDraftRecoveryBanner();
  showWizardMessage(
    "Draft restored. You can continue where you left off.",
    "success",
  );
}

function clearDraft(showMessage = true) {
  localStorage.removeItem("wizardDraft");
  showDraftRecoveryBanner();
  if (showMessage) {
    showWizardMessage("Draft removed. You will start fresh next time.", "info");
  }
}

// Navigation functions
async function nextStep() {
  // If on entry screen
  if (wizardState.currentStep === 0) {
    const selectedType = document.querySelector(
      'input[name="profileType"]:checked',
    ).value;
    wizardState.profileType = selectedType;

    if (selectedType === "intelligent") {
      // Start intelligent chat mode (no redirect)
      await startIntelligentMode();
      return;
    }

    if (selectedType === "users") {
      // Check if user is admin
      const user = JSON.parse(localStorage.getItem("user") || "{}");
      if (user.role === "ADMIN") {
        window.location.href = "/ui/admin-users.html";
      } else {
        showWizardMessage("You need admin privileges to manage users", "error");
      }
      return;
    }

    // Hide entry screen
    document.getElementById("step-entry").classList.remove("active");

    // Set up steps for selected type
    const steps = selectedType === "project" ? projectSteps : caseSteps;
    wizardState.totalSteps = steps.length;
    wizardState.currentStep = 1;

    // Update step indicator
    updateStepIndicator(steps);

    // Render first step
    renderCurrentStep();

    // Show back button
    document.getElementById("btnBack").style.display = "block";
    return;
  }

  // Get current steps array
  const steps =
    wizardState.profileType === "project" ? projectSteps : caseSteps;
  const currentStepObj = steps[wizardState.currentStep - 1];

  // Validate current step
  if (!currentStepObj.validate()) {
    return;
  }

  // Save current step data
  currentStepObj.save();

  // Move to next step
  if (wizardState.currentStep < steps.length) {
    wizardState.currentStep++;
    renderCurrentStep();
  }
}

function previousStep() {
  if (wizardState.currentStep > 0) {
    // Save current step data (without validation)
    const steps =
      wizardState.profileType === "project" ? projectSteps : caseSteps;
    if (
      wizardState.currentStep > 0 &&
      wizardState.currentStep <= steps.length
    ) {
      const currentStepObj = steps[wizardState.currentStep - 1];
      currentStepObj.save();
    }

    wizardState.currentStep--;

    if (wizardState.currentStep === 0) {
      // Show entry screen
      document.getElementById("step-entry").classList.add("active");
      document.getElementById("dynamicSteps").innerHTML = "";
      document.getElementById("btnBack").style.display = "none";
      document.getElementById("stepIndicator").innerHTML = "";

      // Reset continue button
      const btnContinue = document.getElementById("btnContinue");
      btnContinue.innerHTML = 'Continue <i class="fas fa-arrow-right"></i>';
      btnContinue.onclick = nextStep;
    } else {
      renderCurrentStep();
    }
  }
}

function renderCurrentStep() {
  const steps =
    wizardState.profileType === "project" ? projectSteps : caseSteps;
  const currentStepObj = steps[wizardState.currentStep - 1];

  // Create or get dynamic step container
  let container = document.getElementById("dynamicSteps");
  container.innerHTML =
    '<div class="wizard-step active" id="dynamicStep"></div>';

  // Render the step content
  currentStepObj.render();

  // Update step indicator
  updateStepIndicator(steps);

  // Update continue button
  const btnContinue = document.getElementById("btnContinue");
  if (wizardState.currentStep === steps.length) {
    btnContinue.innerHTML =
      wizardState.profileType === "project"
        ? '<i class="fas fa-check"></i> Create Project'
        : '<i class="fas fa-check"></i> Create Case';
    btnContinue.onclick = submitWizard;
  } else {
    btnContinue.innerHTML = 'Continue <i class="fas fa-arrow-right"></i>';
    btnContinue.onclick = nextStep;
  }
}

function updateStepIndicator(steps) {
  const indicator = document.getElementById("stepIndicator");
  let html = "";

  steps.forEach((step, index) => {
    const stepNumber = index + 1;
    const isActive = stepNumber === wizardState.currentStep;
    const isCompleted = stepNumber < wizardState.currentStep;

    html += `
            <div class="step ${isActive ? "active" : ""} ${isCompleted ? "completed" : ""}" data-step="${stepNumber}">
                <div class="step-circle">${stepNumber}</div>
                <div class="step-label">${step.title}</div>
            </div>
        `;
  });

  indicator.innerHTML = html;
}

// Project Step Renderers
function renderProjectIdentification() {
  const container = document.getElementById("dynamicStep");
  const data = wizardState.data["project-identification"] || {};

  container.innerHTML = `
        <h2>Step 1 of 3 — Identification</h2>
        
        <div class="guidance-note">
            <i class="fas fa-info-circle"></i> <strong>What to include:</strong> Provide basic identification details for your project. This helps organize and track your evidence.
        </div>
        
        <div class="form-group">
            <label>Project Name <span class="required">*</span></label>
            <input type="text" id="projectName" required minlength="2" maxlength="200" 
                   value="${escapeHtml(data.projectName || "")}" 
                   placeholder="e.g., Riverside Housing Development, City Centre Regeneration">
            <span class="helper-text">Example: "Riverside Housing Development Phase 2" or "City Centre Office Block"</span>
        </div>
        
        <div class="form-group">
            <label>Project Code <span class="required">*</span> 
                <i class="fas fa-question-circle tooltip" title="A unique identifier for this project. Use uppercase letters, numbers, hyphens. Example: PROJ-2024-001"></i>
            </label>
            <input type="text" id="projectCode" required 
                   value="${escapeHtml(data.projectCode || "")}" 
                   placeholder="e.g., PROJ-2024-001, RHD-PHASE2, CCO-2024">
            <span class="helper-text">Must be unique. Format: UPPERCASE-WITH-HYPHENS (e.g., PROJ-2024-001, ALPHA-TOWER)</span>
        </div>
        
        <div class="form-group">
            <label>Start Date 
                <i class="fas fa-info-circle tooltip" title="Ensure all pre‑commencement and relevant tendering period is accounted for"></i>
            </label>
            <input type="date" id="startDate" value="${escapeHtml(data.startDate || "")}">
            <span class="helper-text">Include pre-commencement and tendering period if relevant</span>
        </div>
        
        <div class="form-group">
            <label>Completion Date</label>
            <input type="date" id="completionDate" value="${escapeHtml(data.completionDate || "")}">
            <span class="helper-text">Planned or actual completion date</span>
        </div>
    `;
}

function renderProjectStakeholders() {
  const container = document.getElementById("dynamicStep");
  const data = wizardState.data["project-stakeholders"] || {};

  container.innerHTML = `
        <h2>Step 2 of 3 — Stakeholders & Keywords</h2>
        
        <h3>Key Stakeholders & Parties</h3>
        <div class="guidance-note">
            <i class="fas fa-users"></i> <strong>Who to include:</strong> List all key parties involved in the project. This helps identify correspondence and relationships.
            <br><strong>Examples:</strong> Main Contractor (United Living), Employer's Agent (Smith & Co), Client (City Council), Subcontractors, NHBC, Building Control, etc.
        </div>
        
        <div class="table-container">
            <table id="stakeholdersTable">
                <thead>
                    <tr>
                        <th style="width: 40%">Role <small style="font-weight: normal; opacity: 0.7;">(e.g., Main Contractor, Client)</small></th>
                        <th style="width: 50%">Name/Organisation <small style="font-weight: normal; opacity: 0.7;">(e.g., United Living, City Council)</small></th>
                        <th style="width: 10%">Actions</th>
                    </tr>
                </thead>
                <tbody>
                </tbody>
            </table>
            <button class="btn-add-row" onclick="addStakeholderRow()">
                <i class="fas fa-plus"></i> Add Row
            </button>
        </div>
        
        <h3 style="margin-top: 30px;">Keywords (Heads of Claim / Relevant words)</h3>
        <div class="guidance-note">
            <i class="fas fa-tags"></i> <strong>What to include:</strong> Add keywords relevant to potential claims, disputes, or important project events. Include variations to catch all mentions.
            <br><strong>Examples:</strong> "Delay" (delayed, postponed), "Variation" (change order, modification), "Relevant Event" (RE, relevant matter), "Section 278" (s278, highway works)
        </div>
        
        <div class="table-container">
            <table id="keywordsTable">
                <thead>
                    <tr>
                        <th style="width: 30%">Keyword <small style="font-weight: normal; opacity: 0.7;">(e.g., Delay, Variation)</small></th>
                        <th style="width: 60%">Variations/Synonyms <small style="font-weight: normal; opacity: 0.7;">(e.g., delayed, postponed, late)</small></th>
                        <th style="width: 10%">Actions</th>
                    </tr>
                </thead>
                <tbody>
                </tbody>
            </table>
            <button class="btn-add-row" onclick="addKeywordRow()">
                <i class="fas fa-plus"></i> Add Row
            </button>
        </div>
    `;

  // Load saved data
  if (data.stakeholders && data.stakeholders.length > 0) {
    data.stakeholders.forEach((stakeholder) => {
      addStakeholderRow(stakeholder.role, stakeholder.name);
    });
  } else {
    // Add default row with Main Contractor - United Living
    addStakeholderRow("Main Contractor", "United Living");
  }

  if (data.keywords) {
    data.keywords.forEach((keyword) => {
      addKeywordRow(keyword.name, keyword.variations);
    });
  }
}

function renderProjectKeywords() {
  const container = document.getElementById("dynamicStep");
  const data = wizardState.data["project-keywords"] || {};

  container.innerHTML = `
        <h2>Step 3 of 3 — Contract</h2>
        
        <div class="form-group">
            <label>Contract Type</label>
            <select id="contractType" onchange="toggleCustomContract(this)">
                <option value="">Select contract type...</option>
                <option value="JCT" ${data.contractType === "JCT" ? "selected" : ""}>JCT</option>
                <option value="NEC" ${data.contractType === "NEC" ? "selected" : ""}>NEC</option>
                <option value="FIDIC" ${data.contractType === "FIDIC" ? "selected" : ""}>FIDIC</option>
                <option value="PPC" ${data.contractType === "PPC" ? "selected" : ""}>PPC</option>
                <option value="Custom" ${data.contractType === "Custom" ? "selected" : ""}>Custom</option>
            </select>
            <input type="text" id="contractTypeCustom" class="custom-input ${data.contractType === "Custom" ? "visible" : ""}" 
                   placeholder="Specify contract type" value="${data.contractTypeCustom || ""}">
        </div>
    `;
}

function renderProjectReview() {
  const container = document.getElementById("dynamicStep");
  container.innerHTML = '<h2>Review Summary</h2><div id="reviewSummary"></div>';
  generateProjectReviewSummary();
}

// Case Step Renderers
function renderCaseIdentification() {
  const container = document.getElementById("dynamicStep");
  const data = wizardState.data["case-identification"] || {};

  container.innerHTML = `
        <h2>Step 1 of 4 — Case Identification</h2>
        
        <div class="form-group">
            <label>Case Name <span class="required">*</span></label>
            <input type="text" id="caseName" required minlength="2" maxlength="200" 
                   value="${data.caseName || ""}" placeholder="Enter case name">
        </div>
        
        <div class="form-group">
            <label>Case ID</label>
            <input type="text" id="caseId" value="${data.caseId || ""}" 
                   placeholder="Optional but recommended">
        </div>
        
        <div class="form-group">
            <label>Resolution Route</label>
            <select id="resolutionRoute" onchange="toggleCustomField(this, 'resolutionRouteCustom')">
                <option value="adjudication" ${data.resolutionRoute === "adjudication" ? "selected" : ""}>adjudication</option>
                <option value="litigation" ${data.resolutionRoute === "litigation" ? "selected" : ""}>litigation</option>
                <option value="arbitration" ${data.resolutionRoute === "arbitration" ? "selected" : ""}>arbitration</option>
                <option value="mediation" ${data.resolutionRoute === "mediation" ? "selected" : ""}>mediation</option>
                <option value="settlement" ${data.resolutionRoute === "settlement" ? "selected" : ""}>settlement</option>
                <option value="TBC" ${data.resolutionRoute === "TBC" ? "selected" : ""}>TBC</option>
                <option value="Custom" ${data.resolutionRoute === "Custom" ? "selected" : ""}>Custom</option>
            </select>
            <input type="text" id="resolutionRouteCustom" 
                   class="custom-input ${data.resolutionRoute === "Custom" ? "visible" : ""}" 
                   placeholder="Enter custom resolution route" value="${data.resolutionRouteCustom || ""}">
        </div>
        
        <div class="form-group">
            <label>Claimant</label>
            <input type="text" id="claimant" value="${data.claimant || ""}" 
                   placeholder="e.g., United Living Construction Ltd, John Smith">
            <span class="helper-text">The party bringing the claim</span>
        </div>
        
        <div class="form-group">
            <label>Defendant</label>
            <input type="text" id="defendant" value="${data.defendant || ""}" 
                   placeholder="e.g., City Council, ABC Developments Ltd">
            <span class="helper-text">The party defending against the claim</span>
        </div>
        
        <div class="form-group">
            <label>Case Status</label>
            <select id="caseStatus" onchange="toggleCustomField(this, 'caseStatusCustom')">
                <option value="discovery" ${data.caseStatus === "discovery" ? "selected" : ""}>discovery</option>
                <option value="preparation" ${data.caseStatus === "preparation" ? "selected" : ""}>preparation</option>
                <option value="pre-adjudication" ${data.caseStatus === "pre-adjudication" ? "selected" : ""}>pre-adjudication</option>
                <option value="Live Adjudication" ${data.caseStatus === "Live Adjudication" ? "selected" : ""}>Live Adjudication</option>
                <option value="Pre-action Protocol" ${data.caseStatus === "Pre-action Protocol" ? "selected" : ""}>Pre-action Protocol</option>
                <option value="Litigation Preparation" ${data.caseStatus === "Litigation Preparation" ? "selected" : ""}>Litigation Preparation</option>
                <option value="Live Litigation" ${data.caseStatus === "Live Litigation" ? "selected" : ""}>Live Litigation</option>
                <option value="Custom" ${data.caseStatus === "Custom" ? "selected" : ""}>Custom</option>
            </select>
            <input type="text" id="caseStatusCustom" 
                   class="custom-input ${data.caseStatus === "Custom" ? "visible" : ""}" 
                   placeholder="Enter custom case status" value="${data.caseStatusCustom || ""}">
        </div>
        
        <div class="form-group">
            <label>Client</label>
            <input type="text" id="client" value="${data.client || ""}" 
                   placeholder="e.g., United Living, Smith & Partners">
            <span class="helper-text">Your client (the party you're representing)</span>
        </div>
    `;
}

function renderCaseLegalTeam() {
  const container = document.getElementById("dynamicStep");
  const data = wizardState.data["case-legal-team"] || {};

  container.innerHTML = `
        <h2>Step 2 of 4 — Legal Team</h2>
        
        <div class="guidance-note">
            <i class="fas fa-users"></i> <strong>Who to include:</strong> List all legal team members and key parties involved in the case.
            <br><strong>Examples:</strong> Solicitor (Smith & Co), Barrister (John Doe QC), Expert Witness (Dr. Jane Smith), Adjudicator, Opposing Counsel, etc.
        </div>
        
        <div class="table-container">
            <table id="legalTeamTable">
                <thead>
                    <tr>
                        <th style="width: 40%">Role/Area <small style="font-weight: normal; opacity: 0.7;">(e.g., Solicitor, Barrister, Expert)</small></th>
                        <th style="width: 50%">Name/Organisation <small style="font-weight: normal; opacity: 0.7;">(e.g., Smith & Co, John Doe QC)</small></th>
                        <th style="width: 10%">Actions</th>
                    </tr>
                </thead>
                <tbody>
                </tbody>
            </table>
            <button class="btn-add-row" onclick="addLegalTeamRow()">
                <i class="fas fa-plus"></i> Add Row
            </button>
        </div>
    `;

  // Load saved data
  if (data.legalTeam) {
    data.legalTeam.forEach((member) => {
      addLegalTeamRow(member.role, member.name);
    });
  }
}

function renderCaseHeadsKeywords() {
  const container = document.getElementById("dynamicStep");
  const data = wizardState.data["case-heads-keywords"] || {};

  container.innerHTML = `
        <h2>Step 3 of 4 — Heads of Claim & Keywords</h2>
        
        <h3>Heads of Claim</h3>
        <div class="table-container">
            <table id="headsOfClaimTable">
                <thead>
                    <tr>
                        <th style="width: 30%">Head of Claim</th>
                        <th style="width: 25%">Status</th>
                        <th style="width: 35%">Actions</th>
                        <th style="width: 10%"></th>
                    </tr>
                </thead>
                <tbody>
                </tbody>
            </table>
            <button class="btn-add-row" onclick="addHeadOfClaimRow()">
                <i class="fas fa-plus"></i> Add Row
            </button>
        </div>
        
        <h3 style="margin-top: 30px;">Keywords</h3>
        <div class="guidance-note">
            Populate with keywords relevant to your potential claims / Heads of Claim. Include common variations so nothing is missed.
        </div>
        
        <div class="table-container">
            <table id="caseKeywordsTable">
                <thead>
                    <tr>
                        <th style="width: 30%">Keyword</th>
                        <th style="width: 60%">Variations/Synonyms</th>
                        <th style="width: 10%">Actions</th>
                    </tr>
                </thead>
                <tbody>
                </tbody>
            </table>
            <button class="btn-add-row" onclick="addCaseKeywordRow()">
                <i class="fas fa-plus"></i> Add Row
            </button>
        </div>
    `;

  // Load saved data
  if (data.headsOfClaim) {
    data.headsOfClaim.forEach((claim) => {
      addHeadOfClaimRow(claim.head, claim.status, claim.actions);
    });
  }

  if (data.keywords) {
    data.keywords.forEach((keyword) => {
      addCaseKeywordRow(keyword.name, keyword.variations);
    });
  }
}

function renderCaseDeadlines() {
  const container = document.getElementById("dynamicStep");
  const data = wizardState.data["case-deadlines"] || {};

  container.innerHTML = `
        <h2>Step 4 of 4 — Case Deadlines</h2>
        
        <div class="table-container">
            <table id="deadlinesTable">
                <thead>
                    <tr>
                        <th style="width: 30%">Deadline/Task</th>
                        <th style="width: 40%">Description/Notes</th>
                        <th style="width: 20%">Date</th>
                        <th style="width: 10%">Actions</th>
                    </tr>
                </thead>
                <tbody>
                </tbody>
            </table>
            <button class="btn-add-row" onclick="addDeadlineRow()">
                <i class="fas fa-plus"></i> Add Row
            </button>
        </div>
    `;

  // Load saved data
  if (data.deadlines) {
    data.deadlines.forEach((deadline) => {
      addDeadlineRow(deadline.task, deadline.description, deadline.date);
    });
  }
}

function renderCaseReview() {
  const container = document.getElementById("dynamicStep");
  container.innerHTML = '<h2>Review Summary</h2><div id="reviewSummary"></div>';
  generateCaseReviewSummary();
}

// Validation functions
function validateProjectIdentification() {
  const projectName = document.getElementById("projectName").value.trim();
  const projectCode = document.getElementById("projectCode").value.trim();
  const startDate = document.getElementById("startDate").value;
  const completionDate = document.getElementById("completionDate").value;

  // Relaxed validation - all fields are optional
  // Just show a warning in console if both name and code are missing
  if (!projectName && !projectCode) {
    console.warn("Project Name and Code are recommended but not required.");
  }

  // Date validation - only warn in console if dates are invalid
  if (
    startDate &&
    completionDate &&
    new Date(completionDate) < new Date(startDate)
  ) {
    console.warn(
      "Completion Date is before Start Date. This might be incorrect.",
    );
  }

  return true;
}

function validateProjectStakeholders() {
  // Stakeholders are completely optional - no warnings needed
  return true;
}

function validateProjectKeywords() {
  // Contract type is optional
  return true;
}

function validateCaseIdentification() {
  const caseName = document.getElementById("caseName").value.trim();

  // Relaxed validation - case name is completely optional
  if (!caseName) {
    console.warn("Case Name is recommended but not required.");
  }

  return true;
}

// Save functions
function saveProjectIdentification() {
  wizardState.data["project-identification"] = {
    projectName: document.getElementById("projectName").value,
    projectCode: document.getElementById("projectCode").value,
    startDate: document.getElementById("startDate").value,
    completionDate: document.getElementById("completionDate").value,
  };
}

function saveProjectStakeholders() {
  const stakeholders = [];
  const keywords = [];

  // Save stakeholders
  document.querySelectorAll("#stakeholdersTable tbody tr").forEach((row) => {
    const role = row.querySelector(".stakeholder-role").value;
    const name = row.querySelector(".stakeholder-name").value;
    if (role || name) {
      stakeholders.push({ role, name });
    }
  });

  // Save keywords
  document.querySelectorAll("#keywordsTable tbody tr").forEach((row) => {
    const nameInput = row.querySelector(".keyword-name");
    const name =
      nameInput.tagName === "SELECT" ? nameInput.value : nameInput.value;
    const variations = row.querySelector(".keyword-variations").value;
    if (name || variations) {
      keywords.push({ name, variations });
    }
  });

  wizardState.data["project-stakeholders"] = {
    stakeholders,
    keywords,
  };
}

function saveProjectKeywords() {
  const contractType = document.getElementById("contractType").value;
  const contractTypeCustom =
    document.getElementById("contractTypeCustom").value;

  wizardState.data["project-keywords"] = {
    contractType,
    contractTypeCustom,
  };
}

function saveCaseIdentification() {
  const resolutionRoute = document.getElementById("resolutionRoute").value;
  const caseStatus = document.getElementById("caseStatus").value;

  wizardState.data["case-identification"] = {
    caseName: document.getElementById("caseName").value,
    caseId: document.getElementById("caseId").value,
    resolutionRoute: resolutionRoute,
    resolutionRouteCustom:
      resolutionRoute === "Custom"
        ? document.getElementById("resolutionRouteCustom").value
        : "",
    claimant: document.getElementById("claimant").value,
    defendant: document.getElementById("defendant").value,
    caseStatus: caseStatus,
    caseStatusCustom:
      caseStatus === "Custom"
        ? document.getElementById("caseStatusCustom").value
        : "",
    client: document.getElementById("client").value,
  };
}

function saveCaseLegalTeam() {
  const legalTeam = [];

  document.querySelectorAll("#legalTeamTable tbody tr").forEach((row) => {
    const role = row.querySelector(".team-role").value;
    const name = row.querySelector(".team-name").value;
    if (role || name) {
      legalTeam.push({ role, name });
    }
  });

  wizardState.data["case-legal-team"] = { legalTeam };
}

function saveCaseHeadsKeywords() {
  const headsOfClaim = [];
  const keywords = [];

  // Save heads of claim
  document.querySelectorAll("#headsOfClaimTable tbody tr").forEach((row) => {
    const head = row.querySelector(".claim-head").value;
    const status = row.querySelector(".claim-status").value;
    const actions = row.querySelector(".claim-actions").value;
    if (head || status || actions) {
      headsOfClaim.push({ head, status, actions });
    }
  });

  // Save keywords
  document.querySelectorAll("#caseKeywordsTable tbody tr").forEach((row) => {
    const nameInput = row.querySelector(".keyword-name");
    const name =
      nameInput.tagName === "SELECT" ? nameInput.value : nameInput.value;
    const variations = row.querySelector(".keyword-variations").value;
    if (name || variations) {
      keywords.push({ name, variations });
    }
  });

  wizardState.data["case-heads-keywords"] = {
    headsOfClaim,
    keywords,
  };
}

function saveCaseDeadlines() {
  const deadlines = [];

  document.querySelectorAll("#deadlinesTable tbody tr").forEach((row) => {
    const task = row.querySelector(".deadline-task").value;
    const description = row.querySelector(".deadline-description").value;
    const date = row.querySelector(".deadline-date").value;
    if (task || description || date) {
      deadlines.push({ task, description, date });
    }
  });

  wizardState.data["case-deadlines"] = { deadlines };
}

// Table row functions
window.addStakeholderRow = function (role = "", name = "") {
  const tbody = document.querySelector("#stakeholdersTable tbody");
  const row = tbody.insertRow();

  // Create role dropdown options
  const roleOptions = stakeholderRoles
    .map(
      (r) =>
        `<option value="${r}" ${r === role ? "selected" : ""}>${r}</option>`,
    )
    .join("");

  row.innerHTML = `
        <td>
            <select class="stakeholder-role">
                ${roleOptions}
                <option value="Custom" ${role === "Custom" || (!stakeholderRoles.includes(role) && role) ? "selected" : ""}>Custom</option>
            </select>
        </td>
        <td><input type="text" class="stakeholder-name" value="${escapeHtml(name)}" placeholder="Name/Organisation"></td>
        <td>
            ${tbody.children.length > 0
      ? '<button class="btn-delete-row" onclick="deleteRow(this)"><i class="fas fa-trash"></i></button>'
      : ""
    }
        </td>
    `;
};

window.addKeywordRow = function (name = "", variations = "") {
  const tbody = document.querySelector("#keywordsTable tbody");
  const row = tbody.insertRow();

  // Check if name is a pre-populated keyword
  const isPrePopulated = prePopulatedKeywords.includes(name);

  if (isPrePopulated || !name) {
    // Create dropdown
    const keywordOptions = prePopulatedKeywords
      .map(
        (k) =>
          `<option value="${k}" ${k === name ? "selected" : ""}>${k}</option>`,
      )
      .join("");

    row.innerHTML = `
            <td>
                <select class="keyword-name">
                    ${keywordOptions}
                    <option value="Custom" ${!isPrePopulated && name ? "selected" : ""}>Custom</option>
                </select>
            </td>
            <td><input type="text" class="keyword-variations" value="${escapeHtml(variations)}" placeholder="e.g., Section 278, Highways Agreement, Section 106"></td>
            <td>
                <button class="btn-delete-row" onclick="deleteRow(this)">
                    <i class="fas fa-trash"></i>
                </button>
            </td>
        `;
  } else {
    // Create text input for custom keyword (sanitized to prevent XSS)
    row.innerHTML = `
            <td><input type="text" class="keyword-name" value="${escapeHtml(name)}" placeholder="Custom keyword"></td>
            <td><input type="text" class="keyword-variations" value="${escapeHtml(variations)}" placeholder="e.g., Section 278, Highways Agreement, Section 106"></td>
            <td>
                <button class="btn-delete-row" onclick="deleteRow(this)">
                    <i class="fas fa-trash"></i>
                </button>
            </td>
        `;
  }
};

window.addCaseKeywordRow = function (name = "", variations = "") {
  const tbody = document.querySelector("#caseKeywordsTable tbody");
  const row = tbody.insertRow();

  // Check if name is a pre-populated keyword
  const isPrePopulated = prePopulatedKeywords.includes(name);

  if (isPrePopulated || !name) {
    // Create dropdown
    const keywordOptions = prePopulatedKeywords
      .map(
        (k) =>
          `<option value="${k}" ${k === name ? "selected" : ""}>${k}</option>`,
      )
      .join("");

    row.innerHTML = `
            <td>
                <select class="keyword-name">
                    ${keywordOptions}
                    <option value="Custom" ${!isPrePopulated && name ? "selected" : ""}>Custom</option>
                </select>
            </td>
            <td><input type="text" class="keyword-variations" value="${escapeHtml(variations)}" placeholder="comma-separated"></td>
            <td>
                <button class="btn-delete-row" onclick="deleteRow(this)">
                    <i class="fas fa-trash"></i>
                </button>
            </td>
        `;
  } else {
    // Create text input for custom keyword (sanitized to prevent XSS)
    row.innerHTML = `
            <td><input type="text" class="keyword-name" value="${escapeHtml(name)}" placeholder="Custom keyword"></td>
            <td><input type="text" class="keyword-variations" value="${escapeHtml(variations)}" placeholder="comma-separated"></td>
            <td>
                <button class="btn-delete-row" onclick="deleteRow(this)">
                    <i class="fas fa-trash"></i>
                </button>
            </td>
        `;
  }
};

window.addLegalTeamRow = function (role = "", name = "") {
  const tbody = document.querySelector("#legalTeamTable tbody");
  const row = tbody.insertRow();
  // Sanitize user input to prevent XSS
  row.innerHTML = `
        <td><input type="text" class="team-role" value="${escapeHtml(role)}" placeholder="e.g., Partner, Counsel, Associate"></td>
        <td><input type="text" class="team-name" value="${escapeHtml(name)}" placeholder="Name/Organisation"></td>
        <td>
            <button class="btn-delete-row" onclick="deleteRow(this)">
                <i class="fas fa-trash"></i>
            </button>
        </td>
    `;
};

window.addHeadOfClaimRow = function (
  head = "",
  status = "Discovery",
  actions = "",
) {
  const tbody = document.querySelector("#headsOfClaimTable tbody");
  const row = tbody.insertRow();

  const statusOptions = [
    "Discovery",
    "Merit Established",
    "Collating Evidence",
    "Bundling",
    "Complete",
    "Custom",
  ];
  const statusOptionsHtml = statusOptions
    .map(
      (s) =>
        `<option value="${s}" ${s === status ? "selected" : ""}>${s}</option>`,
    )
    .join("");

  // Sanitize user input to prevent XSS
  row.innerHTML = `
        <td><input type="text" class="claim-head" value="${escapeHtml(head)}" placeholder="Enter head of claim"></td>
        <td>
            <select class="claim-status">
                ${statusOptionsHtml}
            </select>
        </td>
        <td><input type="text" class="claim-actions" value="${escapeHtml(actions)}" placeholder="e.g., Request PM notes"></td>
        <td>
            <button class="btn-delete-row" onclick="deleteRow(this)">
                <i class="fas fa-trash"></i>
            </button>
        </td>
    `;
};

window.addDeadlineRow = function (task = "", description = "", date = "") {
  const tbody = document.querySelector("#deadlinesTable tbody");
  const row = tbody.insertRow();
  // Sanitize user input to prevent XSS
  row.innerHTML = `
        <td><input type="text" class="deadline-task" value="${escapeHtml(task)}" placeholder="e.g., Respondent's evidence"></td>
        <td><input type="text" class="deadline-description" value="${escapeHtml(description)}" placeholder="Additional notes"></td>
        <td><input type="date" class="deadline-date" value="${escapeHtml(date)}"></td>
        <td>
            <button class="btn-delete-row" onclick="deleteRow(this)">
                <i class="fas fa-trash"></i>
            </button>
        </td>
    `;
};

window.deleteRow = function (button) {
  button.closest("tr").remove();
};

window.toggleCustomContract = function (select) {
  const customInput = document.getElementById("contractTypeCustom");
  if (select.value === "Custom") {
    customInput.classList.add("visible");
  } else {
    customInput.classList.remove("visible");
  }
};

window.toggleCustomField = function (select, customInputId) {
  const customInput = document.getElementById(customInputId);
  if (select.value === "Custom") {
    customInput.classList.add("visible");
    // Clear the field when Custom is selected (don't pre-fill with "Custom")
    if (customInput.value === "" || customInput.value === "Custom") {
      customInput.value = "";
    }
    customInput.focus();
  } else {
    customInput.classList.remove("visible");
  }
};

// Review summary functions
function generateProjectReviewSummary() {
  const container = document.getElementById("reviewSummary");
  const identification = wizardState.data["project-identification"] || {};
  const stakeholdersData = wizardState.data["project-stakeholders"] || {};
  const keywords = wizardState.data["project-keywords"] || {};

  let html = `
        <div class="summary-section">
            <h3><i class="fas fa-clipboard-list"></i> Project Identification</h3>
            <div class="summary-item">
                <div class="summary-label">Project Name:</div>
                <div class="summary-value">${escapeHtml(identification.projectName || "Not specified")}</div>
            </div>
            <div class="summary-item">
                <div class="summary-label">Project Code:</div>
                <div class="summary-value">${escapeHtml(identification.projectCode || "Not specified")}</div>
            </div>
            <div class="summary-item">
                <div class="summary-label">Start Date:</div>
                <div class="summary-value">${escapeHtml(identification.startDate || "Not specified")}</div>
            </div>
            <div class="summary-item">
                <div class="summary-label">Completion Date:</div>
                <div class="summary-value">${escapeHtml(identification.completionDate || "Not specified")}</div>
            </div>
        </div>
        
        <div class="summary-section">
            <h3><i class="fas fa-users"></i> Stakeholders</h3>
            ${(stakeholdersData.stakeholders || [])
      .map(
        (s) =>
          `<div class="summary-item">
                    <div class="summary-label">${escapeHtml(s.role)}:</div>
                    <div class="summary-value">${escapeHtml(s.name)}</div>
                </div>`,
      )
      .join("")}
        </div>
        
        <div class="summary-section">
            <h3><i class="fas fa-tags"></i> Keywords</h3>
            ${(stakeholdersData.keywords || [])
      .map(
        (k) =>
          `<div class="summary-item">
                    <div class="summary-label">${escapeHtml(k.name)}:</div>
                    <div class="summary-value">${escapeHtml(k.variations || "No variations")}</div>
                </div>`,
      )
      .join("")}
        </div>
        
        <div class="summary-section">
            <h3><i class="fas fa-file-contract"></i> Contract</h3>
            <div class="summary-item">
                <div class="summary-label">Contract Type:</div>
                <div class="summary-value">${escapeHtml(
        keywords.contractType === "Custom"
          ? keywords.contractTypeCustom
          : keywords.contractType || "Not specified",
      )}</div>
            </div>
        </div>
    `;

  container.innerHTML = html;
}

function generateCaseReviewSummary() {
  const container = document.getElementById("reviewSummary");
  const identification = wizardState.data["case-identification"] || {};
  const legalTeamData = wizardState.data["case-legal-team"] || {};
  const headsKeywordsData = wizardState.data["case-heads-keywords"] || {};
  const deadlinesData = wizardState.data["case-deadlines"] || {};

  let html = `
        <div class="summary-section">
            <h3><i class="fas fa-gavel"></i> Case Identification</h3>
            <div class="summary-item">
                <div class="summary-label">Case Name:</div>
                <div class="summary-value">${escapeHtml(identification.caseName || "Not specified")}</div>
            </div>
            <div class="summary-item">
                <div class="summary-label">Case ID:</div>
                <div class="summary-value">${escapeHtml(identification.caseId || "Not specified")}</div>
            </div>
            <div class="summary-item">
                <div class="summary-label">Resolution Route:</div>
                <div class="summary-value">${escapeHtml(
    identification.resolutionRoute === "Custom"
      ? identification.resolutionRouteCustom
      : identification.resolutionRoute || "Not specified",
  )}</div>
            </div>
            <div class="summary-item">
                <div class="summary-label">Claimant:</div>
                <div class="summary-value">${escapeHtml(identification.claimant || "Not specified")}</div>
            </div>
            <div class="summary-item">
                <div class="summary-label">Defendant:</div>
                <div class="summary-value">${escapeHtml(identification.defendant || "Not specified")}</div>
            </div>
            <div class="summary-item">
                <div class="summary-label">Client:</div>
                <div class="summary-value">${escapeHtml(identification.client || "Not specified")}</div>
            </div>
        </div>
        
        <div class="summary-section">
            <h3><i class="fas fa-user-tie"></i> Legal Team</h3>
            ${(legalTeamData.legalTeam || [])
      .map(
        (t) =>
          `<div class="summary-item">
                    <div class="summary-label">${escapeHtml(t.role)}:</div>
                    <div class="summary-value">${escapeHtml(t.name)}</div>
                </div>`,
      )
      .join("")}
        </div>
        
        <div class="summary-section">
            <h3><i class="fas fa-list"></i> Heads of Claim</h3>
            ${(headsKeywordsData.headsOfClaim || [])
      .map(
        (h) =>
          `<div class="summary-item">
                    <div class="summary-label">${escapeHtml(h.head)}:</div>
                    <div class="summary-value">${escapeHtml(h.status)}${h.actions ? " - " + escapeHtml(h.actions) : ""}</div>
                </div>`,
      )
      .join("")}
        </div>
        
        <div class="summary-section">
            <h3><i class="fas fa-calendar"></i> Case Deadlines</h3>
            ${(deadlinesData.deadlines || [])
      .map(
        (d) =>
          `<div class="summary-item">
                    <div class="summary-label">${escapeHtml(d.task)}:</div>
                    <div class="summary-value">${escapeHtml(d.date)}${d.description ? " - " + escapeHtml(d.description) : ""}</div>
                </div>`,
      )
      .join("")}
        </div>
    `;

  container.innerHTML = html;
}

// Submit wizard
async function submitWizard() {
  // Save the current step (review step)
  const steps =
    wizardState.profileType === "project" ? projectSteps : caseSteps;
  const currentStepObj = steps[wizardState.currentStep - 1];
  currentStepObj.save();

  try {
    const apiUrl = getApiUrl();
    const csrfToken = getCsrfToken();

    // TEMPORARY: Auth check disabled
    // if (!token) {
    //     handleSessionExpired();
    //     return;
    // }

    let endpoint, requestData;

    if (wizardState.profileType === "project") {
      endpoint = "/api/projects";
      const identification = wizardState.data["project-identification"] || {};
      const stakeholdersData = wizardState.data["project-stakeholders"] || {};
      const keywordsData = wizardState.data["project-keywords"] || {};

      const normalizedContractType =
        keywordsData.contractType === "Custom"
          ? keywordsData.contractTypeCustom
          : keywordsData.contractType;

      // Match the ProjectCreate schema from simple_cases.py
      requestData = {
        project_name: identification.projectName || "Untitled Project",
        project_code: identification.projectCode || `PROJ-${Date.now()}`,
        start_date: identification.startDate || null,
        completion_date: identification.completionDate || null,
        contract_type: normalizedContractType || null,
        stakeholders: (stakeholdersData.stakeholders || []).map((s) => ({
          role: s.role || "",
          name: s.name || "",
          email: s.email || null,
          organization: s.name || null,
        })),
        keywords: (stakeholdersData.keywords || []).map((k) => ({
          name: k.name || "",
          variations: k.variations || null,
        })),
      };
    } else {
      endpoint = "/api/cases";
      const identification = wizardState.data["case-identification"] || {};
      const legalTeamData = wizardState.data["case-legal-team"] || {};
      const headsKeywordsData = wizardState.data["case-heads-keywords"] || {};
      const deadlinesData = wizardState.data["case-deadlines"] || {};

      const normalizedResolutionRoute =
        identification.resolutionRoute === "Custom"
          ? identification.resolutionRouteCustom
          : identification.resolutionRoute;
      const normalizedCaseStatus =
        identification.caseStatus === "Custom"
          ? identification.caseStatusCustom
          : identification.caseStatus;

      // Match the CaseCreate schema from simple_cases.py
      requestData = {
        case_name: identification.caseName || "Untitled Case",
        case_id: identification.caseId || null,
        resolution_route: normalizedResolutionRoute || "TBC",
        claimant: identification.claimant || null,
        defendant: identification.defendant || null,
        case_status: normalizedCaseStatus || "discovery",
        client: identification.client || null,
        legal_team: (legalTeamData.legalTeam || []).map((t) => ({
          role: t.role || "",
          name: t.name || "",
        })),
        heads_of_claim: (headsKeywordsData.headsOfClaim || []).map((h) => ({
          head: h.head || "",
          status: h.status || "Discovery",
          actions: h.actions || null,
        })),
        keywords: (headsKeywordsData.keywords || []).map((k) => ({
          name: k.name || "",
          variations: k.variations || null,
        })),
        deadlines: (deadlinesData.deadlines || []).map((d) => ({
          task: d.task || "",
          description: d.description || null,
          date: d.date || null,
        })),
      };
    }

    const response = await fetch(`${apiUrl}${endpoint}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfToken,
      },
      body: JSON.stringify(requestData),
      credentials: "same-origin", // Include cookies for session-based auth
    });

    if (!response.ok) {
      if (response.status === 401 || response.status === 403) {
        handleSessionExpired();
        return;
      }

      let errorMessage = `Failed to create ${wizardState.profileType}`;
      try {
        const errorData = await response.json();
        errorMessage = errorData.detail || errorMessage;
      } catch (parseError) {
        console.warn("Failed to parse error response", parseError);
      }

      throw new Error(errorMessage);
    }

    const result = await response.json();

    // Clear draft
    localStorage.removeItem("wizardDraft");

    // Show message if fields were auto-generated
    if (result.message && result.message.includes("Auto-generated")) {
      showWizardMessage(result.message, "info");
    }

    // Store ID and profile type for future use
    const isProject = wizardState.profileType === "project";
    localStorage.setItem("profileType", isProject ? "project" : "case");
    localStorage.setItem(
      isProject ? "currentProjectId" : "currentCaseId",
      result.id,
    );
    // Also store generic keys used by dashboard fallbacks
    try {
      localStorage.setItem(isProject ? "projectId" : "caseId", result.id);
    } catch (e) {
      // Ignore storage errors
    }

    // Redirect to dashboard for next steps
    const redirectParam = isProject ? "projectId" : "caseId";
    window.location.href = `projectdashboard.html?${redirectParam}=${result.id}&firstTime=true`;
  } catch (error) {
    console.error("Error creating profile:", error);
    showWizardMessage(
      `Error creating ${wizardState.profileType}: ${error.message}`,
      "error",
    );
  }
}

// Draft management
function saveDraft(silent = false) {
  // Save current step data
  const steps =
    wizardState.profileType === "project" ? projectSteps : caseSteps;
  if (wizardState.currentStep > 0 && wizardState.currentStep <= steps.length) {
    const currentStepObj = steps[wizardState.currentStep - 1];
    currentStepObj.save();
  }

  if (wizardState.currentStep > 0) {
    localStorage.setItem("wizardDraft", JSON.stringify(wizardState));
    if (!silent) {
      showWizardMessage("Draft saved successfully!", "success");
    }
    showDraftRecoveryBanner();
  }
}

async function cancel() {
  const ok = await confirmWizard(
    "Are you sure you want to cancel? Any unsaved progress will be lost.",
  );
  if (ok) window.location.href = "projectdashboard.html";
}

// ----------------------------------------
// Non-blocking notifications and confirm
// ----------------------------------------
function ensureWizardBanner() {
  let el = document.getElementById("wizardBanner");
  if (!el) {
    el = document.createElement("div");
    el.id = "wizardBanner";
    el.style.cssText =
      "position:fixed;top:0;left:0;right:0;z-index:9999;display:none;padding:10px 16px;font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial;border-bottom:1px solid #e2e8f0;";
    document.body.appendChild(el);
  }
  return el;
}
function showWizardMessage(message, type = "info", timeoutMs = 4000) {
  const el = ensureWizardBanner();
  el.textContent = message;
  el.style.background =
    type === "error" ? "#fee2e2" : type === "success" ? "#ecfdf5" : "#eef2ff";
  el.style.color =
    type === "error" ? "#991b1b" : type === "success" ? "#065f46" : "#1e3a8a";
  el.style.display = "block";
  if (timeoutMs > 0) {
    setTimeout(() => {
      el.style.display = "none";
    }, timeoutMs);
  }
}
function confirmWizard(message) {
  return new Promise((resolve) => {
    // Build lightweight modal
    let overlay = document.getElementById("wizardConfirmOverlay");
    if (!overlay) {
      overlay = document.createElement("div");
      overlay.id = "wizardConfirmOverlay";
      overlay.style.cssText =
        "position:fixed;inset:0;background:rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;z-index:10000;";
      const box = document.createElement("div");
      box.style.cssText =
        "background:#fff;min-width:320px;max-width:90vw;border-radius:8px;box-shadow:0 10px 30px rgba(0,0,0,0.2);padding:16px;";
      box.innerHTML =
        '<div id="wizardConfirmMsg" style="margin-bottom:12px;color:#0f172a;"></div>' +
        '<div style="display:flex;gap:8px;justify-content:flex-end">' +
        '<button id="wizardConfirmNo" style="padding:8px 12px;border:1px solid #e2e8f0;background:#fff;border-radius:6px;cursor:pointer">No</button>' +
        '<button id="wizardConfirmYes" style="padding:8px 12px;border:0;background:#2563eb;color:#fff;border-radius:6px;cursor:pointer">Yes</button>' +
        "</div>";
      overlay.appendChild(box);
      document.body.appendChild(overlay);
    } else {
      overlay.style.display = "flex";
    }
    overlay.querySelector("#wizardConfirmMsg").textContent = message;
    const onClose = (val) => {
      overlay.style.display = "none";
      resolve(val);
    };
    overlay.querySelector("#wizardConfirmYes").onclick = () => onClose(true);
    overlay.querySelector("#wizardConfirmNo").onclick = () => onClose(false);
  });
}

// Expose draft helpers for banner buttons
window.restoreWizardDraft = restoreDraft;
window.clearWizardDraft = () => clearDraft(false);

// ============================================================================
// Intelligent Chat Mode
// ============================================================================

let conversationHistory = [];
let intelligentConfigData = {};
let intelligentCurrentStep = "introduction";
let intelligentFinalConfiguration = null;
let aiAvailable = false;

async function startIntelligentMode() {
  // Hide traditional wizard UI
  document.getElementById("step-entry").style.display = "none";
  document.getElementById("dynamicSteps").style.display = "none";
  document.querySelector(".wizard-actions").style.display = "none";
  document.getElementById("stepIndicator").style.display = "none";
  document.getElementById("draftBanner").style.display = "none";
  document.getElementById("btnSaveDraft").style.display = "none";

  // Show chat interface
  document.getElementById("chatContainer").classList.add("active");
  document.getElementById("progressBar").style.display = "block";

  // Update header
  document.getElementById("wizardHeaderTitle").innerHTML =
    '<i class="fas fa-robot"></i> Intelligent Configuration';
  document.getElementById("wizardHeaderSubtitle").textContent =
    "Let AI help you configure your system correctly";

  // Setup chat
  setupChatInput();
  await checkAIAvailability();

  if (aiAvailable) {
    startConversation();
  } else {
    showAIUnavailableMessage();
  }
}

async function checkAIAvailability() {
  if (hasStoredAIKey()) {
    aiAvailable = true;
    return;
  }

  try {
    const response = await fetch(`${getApiUrl()}/api/ai/status`, {
      headers: {
        "X-Requested-With": "wizard",
      },
    });

    if (response.ok) {
      const status = await response.json();
      aiAvailable = status.any_available;

      if (!aiAvailable) {
        console.warn(
          "No AI services available. API keys need to be configured.",
        );
      }
    } else {
      console.error("Failed to check AI availability");
      aiAvailable = false;
    }
  } catch (error) {
    console.error("Error checking AI availability:", error);
    aiAvailable = false;
  }
}

function showAIUnavailableMessage() {
  addBotMessage(
    "⚠️ **AI Services Not Configured**\n\nThe intelligent configuration wizard uses AI to guide you through setup, but no AI API keys are currently configured.\n\n**Quick Setup:**\nYou can enter your API key directly below to enable AI features immediately.\n\n**Supported providers:**\n• OpenAI (GPT-4) - Recommended\n• Anthropic (Claude)\n• Google (Gemini)\n\n**Alternative:** Use the manual configuration wizard by going back.",
    ["Enter API key", "Go to dashboard", "Use manual wizard"],
  );

  document.getElementById("chatInput").placeholder =
    "AI not configured - enter API key or use manual wizard...";
}

function getStoredAIKeys() {
  return {
    openai: localStorage.getItem("ai_key_openai") || "",
    anthropic: localStorage.getItem("ai_key_anthropic") || "",
    google: localStorage.getItem("ai_key_google") || "",
  };
}

function hasStoredAIKey() {
  const keys = getStoredAIKeys();
  return Object.values(keys).some(
    (key) => typeof key === "string" && key.trim().length > 0,
  );
}

function showAPIKeyEntryForm() {
  const messagesDiv = document.getElementById("chatMessages");
  if (!messagesDiv) return;

  const existingForm = document.getElementById("aiKeyEntryMessage");
  if (existingForm) {
    existingForm.remove();
  }

  const messageDiv = document.createElement("div");
  messageDiv.className = "message bot ai-key-message";
  messageDiv.id = "aiKeyEntryMessage";
  messageDiv.innerHTML = `
        <div class="message-avatar">
            <i class="fas fa-key"></i>
        </div>
        <div class="message-content">
            <strong>Enable AI guidance instantly</strong><br>
            <p>Add an API key for one of the supported providers. Your key is stored locally in this browser only and used just for this session.</p>
            <div class="ai-key-form">
                <label for="aiProvider">Select provider</label>
                <select id="aiProvider">
                    <option value="openai">OpenAI (GPT-4/GPT-4.1)</option>
                    <option value="anthropic">Anthropic (Claude)</option>
                    <option value="google">Google (Gemini)</option>
                </select>
                <label for="aiApiKey">API key</label>
                <input type="password" id="aiApiKey" placeholder="Enter API key, e.g. sk-..." autocomplete="off">
                <div class="ai-key-actions">
                    <button type="button" class="btn-primary" id="btnSaveAIKey">
                        <i class="fas fa-check"></i> Save key
                    </button>
                    <button type="button" class="btn-secondary" id="btnCancelAIKey">
                        <i class="fas fa-times"></i> Cancel
                    </button>
                </div>
            </div>
            <small class="ai-key-disclaimer">Keys are stored locally for testing only. Configure AWS Secrets Manager for production.</small>
        </div>
    `;

  messagesDiv.appendChild(messageDiv);
  scrollChatToBottom();

  const storedKeys = getStoredAIKeys();
  const providerWithKey = Object.entries(storedKeys).find(([, value]) => value);
  if (providerWithKey) {
    messageDiv.querySelector("#aiProvider").value = providerWithKey[0];
  }

  messageDiv.querySelector("#btnSaveAIKey").onclick = saveAIKey;
  messageDiv.querySelector("#btnCancelAIKey").onclick = () => {
    messageDiv.remove();
    addBotMessage(
      "No worries. You can enter an API key at any time from the quick actions.",
      ["Enter API key", "Use manual wizard", "Go to dashboard"],
    );
  };
}

async function saveAIKey() {
  const messageDiv = document.getElementById("aiKeyEntryMessage");
  if (!messageDiv) return;

  const providerSelect = messageDiv.querySelector("#aiProvider");
  const keyInput = messageDiv.querySelector("#aiApiKey");
  const provider = providerSelect.value;
  const apiKey = (keyInput.value || "").trim();

  if (!apiKey) {
    keyInput.classList.add("input-error");
    setTimeout(() => keyInput.classList.remove("input-error"), 1500);
    addBotMessage(
      "Please enter an API key so I can enable the intelligent assistant.",
      ["Enter API key", "Use manual wizard"],
    );
    return;
  }

  localStorage.setItem(`ai_key_${provider}`, apiKey);

  aiAvailable = true;
  document.getElementById("chatInput").placeholder = "Type your message...";

  messageDiv.remove();

  const providerNames = {
    openai: "OpenAI",
    anthropic: "Anthropic Claude",
    google: "Google Gemini",
  };

  addBotMessage(
    `Great! I've stored your ${providerNames[provider] || provider} API key for this browser session.`,
    ["Continue configuration", "Go to dashboard"],
  );

  if (conversationHistory.length === 0) {
    intelligentCurrentStep = "introduction";
    intelligentConfigData = {};
    startConversation();
  }
}

function setupChatInput() {
  const textarea = document.getElementById("chatInput");
  const sendBtn = document.getElementById("sendBtn");

  textarea.addEventListener("input", function () {
    this.style.height = "auto";
    this.style.height = Math.min(this.scrollHeight, 120) + "px";
  });

  textarea.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendIntelligentMessage();
    }
  });

  sendBtn.onclick = sendIntelligentMessage;
}

async function startConversation() {
  addBotMessage(
    "Welcome to VeriCase! I'll help you get set up quickly. Choose what you'd like to configure first:",
    ["Configure Team", "Set up Project", "Set up Case"],
  );
}

function addBotMessage(text, quickActions = []) {
  const messagesDiv = document.getElementById("chatMessages");
  const messageDiv = document.createElement("div");
  messageDiv.className = "message bot";

  messageDiv.innerHTML = `
        <div class="message-avatar">
            <i class="fas fa-robot"></i>
        </div>
        <div class="message-content">
            ${formatChatMessage(text)}
            ${quickActions.length > 0
      ? `
                <div class="quick-actions">
                    ${quickActions
        .map(
          (action) => `
                        <button class="quick-action-btn" onclick="handleIntelligentQuickAction('${escapeHtml(action)}')">${escapeHtml(action)}</button>
                    `,
        )
        .join("")}
                </div>
            `
      : ""
    }
        </div>
    `;

  messagesDiv.appendChild(messageDiv);
  scrollChatToBottom();
}

function addUserMessage(text) {
  const messagesDiv = document.getElementById("chatMessages");
  const messageDiv = document.createElement("div");
  messageDiv.className = "message user";

  messageDiv.innerHTML = `
        <div class="message-avatar">
            <i class="fas fa-user"></i>
        </div>
        <div class="message-content">${escapeHtml(text)}</div>
    `;

  messagesDiv.appendChild(messageDiv);
  scrollChatToBottom();
}

function showTyping() {
  const messagesDiv = document.getElementById("chatMessages");
  const typingDiv = document.createElement("div");
  typingDiv.className = "message bot";
  typingDiv.id = "typingIndicator";

  typingDiv.innerHTML = `
        <div class="message-avatar">
            <i class="fas fa-robot"></i>
        </div>
        <div class="message-content">
            <div class="typing-indicator">
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
            </div>
        </div>
    `;

  messagesDiv.appendChild(typingDiv);
  scrollChatToBottom();
}

function hideTyping() {
  const typing = document.getElementById("typingIndicator");
  if (typing) typing.remove();
}

async function sendIntelligentMessage() {
  const input = document.getElementById("chatInput");
  const message = input.value.trim();

  if (!message) return;

  // Warn if AI is not available but let them try
  if (!aiAvailable) {
    addBotMessage(
      "⚠️ AI services are not configured. Please add API keys in Dashboard → Settings → AI Configuration first.",
    );
    return;
  }

  // Disable input while processing
  input.disabled = true;
  document.getElementById("sendBtn").disabled = true;

  // Add user message
  addUserMessage(message);
  conversationHistory.push({ role: "user", content: message });
  input.value = "";
  input.style.height = "auto";

  // Show typing indicator
  showTyping();

  try {
    const response = await fetch(`${getApiUrl()}/api/ai/intelligent-config`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        message: message,
        conversation_history: conversationHistory,
        current_step: intelligentCurrentStep,
        configuration_data: intelligentConfigData,
      }),
    });

    if (!response.ok) {
      throw new Error("Failed to get AI response");
    }

    const data = await response.json();

    hideTyping();

    // Update configuration data
    if (data.configuration_data) {
      intelligentConfigData = {
        ...intelligentConfigData,
        ...data.configuration_data,
      };
    }

    // Update current step
    if (data.next_step) {
      intelligentCurrentStep = data.next_step;
    }

    // Update progress
    if (data.progress !== undefined) {
      updateIntelligentProgress(data.progress);
    }

    // Add bot response
    addBotMessage(data.response, data.quick_actions || []);

    // If configuration is complete, capture final IDs and show summary
    if (data.configuration_complete) {
      intelligentFinalConfiguration = data.final_configuration || null;
      storeIntelligentProfileContext(intelligentFinalConfiguration);
      await showIntelligentConfigurationSummary(data.final_configuration);
    }
  } catch (error) {
    hideTyping();
    console.error("Error:", error);
    addBotMessage(
      "I'm sorry, I encountered an error. Could you please try rephrasing your message?",
    );
  } finally {
    input.disabled = false;
    document.getElementById("sendBtn").disabled = false;
    input.focus();
  }
}

// eslint-disable-next-line no-unused-vars
function handleIntelligentQuickAction(action) {
  // Handle AI key entry
  if (action === "Enter API key") {
    showAPIKeyEntryForm();
    return;
  }

  // Handle AI unavailable actions
  if (action === "Go to dashboard") {
    storeIntelligentProfileContext(intelligentFinalConfiguration);
    let navigateUrl = "projectdashboard.html";
    if (intelligentFinalConfiguration) {
      if (intelligentFinalConfiguration.project_id) {
        navigateUrl = `projectdashboard.html?projectId=${intelligentFinalConfiguration.project_id}`;
        localStorage.setItem("profileType", "project");
      } else if (intelligentFinalConfiguration.case_id) {
        navigateUrl = `projectdashboard.html?caseId=${intelligentFinalConfiguration.case_id}`;
        localStorage.setItem("profileType", "case");
      }
    }
    window.location.href = navigateUrl;
    return;
  }

  if (action === "Use manual wizard") {
    window.location.reload();
    return;
  }

  if (action === "Try anyway") {
    // User wants to try even without AI configured
    document.getElementById("chatInput").placeholder = "Type your message...";
    aiAvailable = true; // Let them try
    return;
  }

  // Handle new friendly quick actions
  if (action === "Configure Team") {
    document.getElementById("chatInput").value =
      "I want to add my team members";
    sendIntelligentMessage();
    return;
  }

  if (action === "Set up Project") {
    document.getElementById("chatInput").value = "I need to set up a project";
    sendIntelligentMessage();
    return;
  }

  if (action === "Set up Case") {
    document.getElementById("chatInput").value = "I need to set up a case";
    sendIntelligentMessage();
    return;
  }

  if (action === "Review setup") {
    let review = "**Current Configuration Summary:**\n\n";
    if (
      intelligentConfigData.team_members &&
      intelligentConfigData.team_members.length > 0
    ) {
      review += `**Team Members (${intelligentConfigData.team_members.length}):**\n`;
      intelligentConfigData.team_members.forEach((member, idx) => {
        review += `${idx + 1}. ${member.name || "Unknown"}`;
        if (member.role) review += ` - ${member.role}`;
        if (member.email) review += ` (${member.email})`;
        review += "\n";
      });
      review += "\n";
    }
    if (intelligentConfigData.project_name || intelligentConfigData.case_name) {
      review += `**Project/Case:** ${intelligentConfigData.project_name || intelligentConfigData.case_name}\n`;
    }
    if (intelligentConfigData.project_code) {
      review += `**Project Code:** ${intelligentConfigData.project_code}\n`;
    }
    if (intelligentConfigData.case_number) {
      review += `**Case Number:** ${intelligentConfigData.case_number}\n`;
    }
    review += "\n";
    if (
      intelligentConfigData.keywords &&
      intelligentConfigData.keywords.length > 0
    ) {
      review += `**Keywords:** ${intelligentConfigData.keywords.join(", ")}\n\n`;
    }
    review += "Would you like to continue configuring, or go to the dashboard?";
    addBotMessage(review, ["Continue configuration", "Go to dashboard"]);
    return;
  }

  // Default: send as message
  document.getElementById("chatInput").value = action;
  sendIntelligentMessage();
}

function updateIntelligentProgress(percentage) {
  document.getElementById("progressFill").style.width = percentage + "%";
}

function storeIntelligentProfileContext(config) {
  if (!config) return;

  if (config.project_id) {
    localStorage.setItem("profileType", "project");
    localStorage.setItem("currentProjectId", config.project_id);
    try {
      localStorage.setItem("projectId", config.project_id);
    } catch (e) {
      // Ignore storage errors
    }
  } else if (config.case_id) {
    localStorage.setItem("profileType", "case");
    localStorage.setItem("currentCaseId", config.case_id);
    try {
      localStorage.setItem("caseId", config.case_id);
    } catch (e) {
      // Ignore storage errors
    }
  }
}

async function showIntelligentConfigurationSummary(config) {
  await new Promise((resolve) => setTimeout(resolve, 1000));

  let summary = "Perfect! I've configured the basics for your system:\n\n";

  if (config.team_members && config.team_members.length > 0) {
    summary += `✓ **Team Members:** ${config.team_members.length} members added\n`;
  }

  if (config.project_name || config.case_name) {
    summary += `✓ **Project/Case:** ${config.project_name || config.case_name}\n`;
  }

  if (config.project_code) {
    summary += `✓ **Project Code:** ${config.project_code}\n`;
  }

  if (config.case_number) {
    summary += `✓ **Case Number:** ${config.case_number}\n`;
  }

  if (config.keywords && config.keywords.length > 0) {
    summary += `✓ **Keywords:** ${config.keywords.join(", ")}\n`;
  }

  summary += "\n**Your system is ready to use!**\n\n";
  summary +=
    "Head to the dashboard to upload evidence, view correspondence, and access all features. Your configuration will work immediately with the basics we've set up.\n\n";
  summary += "**What happens next:**\n";
  summary +=
    "• After you upload files, the **Refinement Wizard** will analyze your actual evidence\n";
  summary +=
    "• It will intelligently prompt you with direct, specific questions based on what it finds\n";
  summary +=
    "• For example: \"I found emails mentioning 'variation order #123' - is this a key document?\"\n";
  summary +=
    "• The two wizards work together - I handle initial setup, Refinement Wizard fine-tunes with real data\n\n";
  summary += "**Benefits of configuring more now:**\n";
  summary +=
    "• Better initial analysis and categorization from the first upload\n";
  summary +=
    "• More accurate keyword matching and email threading from the start\n";
  summary += "• Improved relationship mapping between team members\n";
  summary += "• Faster evidence processing with fewer corrections needed\n";
  summary +=
    "• Example: If we configure contract types (FIDIC, JCT) now, emails will be categorized correctly immediately\n\n";
  summary +=
    "**Remember:** You can always come back to this configuration wizard at any time to add more details.\n\n";
  summary += "**What would you like to do?**\n";
  summary +=
    "1. Continue with more configuration now (recommended for best initial results)\n";
  summary +=
    "2. Go to the project dashboard (from there you can upload evidence, view reports, and more)\n";
  summary += "3. Review what we've set up";

  addBotMessage(summary, [
    "Continue configuration",
    "Go to dashboard",
    "Review setup",
  ]);
}

function formatChatMessage(text) {
  // Convert markdown-style formatting to HTML
  return escapeHtml(text)
    .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
    .replace(/\n/g, "<br>");
}

function scrollChatToBottom() {
  const messagesDiv = document.getElementById("chatMessages");
  if (messagesDiv) {
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
  }
}
