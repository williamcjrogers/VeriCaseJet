// Wizard state management
const wizardState = {
    currentStep: 0,
    profileType: 'project',
    data: {}
};

// Templates for quick setup
const projectTemplates = {
    'construction': {
        name: 'Construction Project',
        stakeholders: [
            { role: 'Main Contractor', name: '' },
            { role: 'Client', name: '' },
            { role: 'Employers Agent', name: '' },
            { role: 'Project Manager', name: '' }
        ],
        keywords: [
            { name: 'Delay', variations: 'delays, delayed, postponement' },
            { name: 'Variation', variations: 'variations, change order, modification' },
            { name: 'Relevant Event', variations: '' },
            { name: 'Extension of Time', variations: 'EOT, time extension' }
        ],
        contractType: 'JCT'
    },
    'infrastructure': {
        name: 'Infrastructure Project',
        stakeholders: [
            { role: 'Main Contractor', name: '' },
            { role: 'Council', name: '' },
            { role: 'Client', name: '' }
        ],
        keywords: [
            { name: 'Section 278', variations: 'Section 278, Highways Agreement, Section 106' },
            { name: 'Delay', variations: 'delays, programme slippage' },
            { name: 'Variation', variations: 'variations, instructed works' }
        ],
        contractType: 'NEC'
    }
};

const caseTemplates = {
    'adjudication': {
        name: 'Adjudication',
        deadlines: [
            { task: 'Notice of Adjudication', description: 'Serve notice', date: '' },
            { task: 'Referral Notice', description: 'Submit referral (7 days)', date: '' },
            { task: 'Response', description: 'Respondent\'s response (14 days)', date: '' },
            { task: 'Decision', description: 'Expected decision (28 days)', date: '' }
        ],
        keywords: [
            { name: 'Payment', variations: 'payment, valuation, application' },
            { name: 'Extension of Time', variations: 'EOT, time extension, delay' },
            { name: 'Loss and Expense', variations: 'loss, expense, prolongation' }
        ]
    },
    'litigation': {
        name: 'Litigation',
        deadlines: [
            { task: 'Pre-action Protocol', description: 'Letter of claim', date: '' },
            { task: 'Disclosure', description: 'Initial disclosure', date: '' },
            { task: 'Witness Statements', description: 'Exchange statements', date: '' }
        ],
        keywords: [
            { name: 'Breach', variations: 'breach of contract, contractual breach' },
            { name: 'Negligence', variations: 'negligent, duty of care' },
            { name: 'Damages', variations: 'damages, loss, compensation' }
        ]
    }
};

// Load token from URL or localStorage
const urlParams = new URLSearchParams(window.location.search);
const token = urlParams.get('token') || localStorage.getItem('token');

// Token is optional - allow wizard to load without authentication

// Step templates
const projectSteps = [
    {
        id: 'project-identification',
        title: 'Project Identification',
        template: `
            <h2>Step 1 of 3 — Identification</h2>
            <div class="form-group">
                <label>Project Name <span class="required">*</span></label>
                <input type="text" id="projectName" required minlength="2" maxlength="200" placeholder="Enter project name">
            </div>
            <div class="form-group">
                <label>Project Code <span class="required">*</span></label>
                <input type="text" id="projectCode" required placeholder="Unique project code">
                <span class="helper-text">Must be unique within your organization</span>
            </div>
            <div class="form-group">
                <label>Start Date <i class="fas fa-info-circle tooltip" title="Ensure all pre-commencement and relevant tendering period is accounted for"></i></label>
                <input type="date" id="startDate">
            </div>
            <div class="form-group">
                <label>Completion Date</label>
                <input type="date" id="completionDate">
            </div>
        `
    },
    {
        id: 'project-stakeholders',
        title: 'Stakeholders & Keywords',
        template: `
            <h2>Step 2 of 3 — Stakeholders & Keywords</h2>
            
            <h3 style="margin-bottom: 10px;">Key Stakeholders & Parties</h3>
            <div class="guidance-note">
                Examples include United Living and names of: Employer's Agent, Client, Council, NHBC, Subcontractors, etc.
            </div>
            
            <div class="table-container">
                <table id="stakeholdersTable">
                    <thead>
                        <tr>
                            <th>Role</th>
                            <th>Name / Organisation</th>
                            <th width="100">Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr>
                            <td>
                                <select class="stakeholder-role">
                                    <option value="Main Contractor">Main Contractor</option>
                                    <option value="Council">Council</option>
                                    <option value="Employers Agent">Employers Agent</option>
                                    <option value="Project Manager">Project Manager</option>
                                    <option value="Client">Client</option>
                                    <option value="Building Control">Building Control</option>
                                    <option value="Subcontractor">Subcontractor</option>
                                    <option value="Client Management Team">Client Management Team</option>
                                    <option value="Custom">Custom</option>
                                </select>
                            </td>
                            <td><input type="text" class="stakeholder-name" value="United Living"></td>
                            <td></td>
                        </tr>
                    </tbody>
                </table>
                <button class="btn-add-row" onclick="addStakeholderRow()">
                    <i class="fas fa-plus"></i> Add Row
                </button>
            </div>

            <h3 style="margin: 30px 0 10px 0;">Keywords (Heads of Claim / Relevant words)</h3>
            <div class="guidance-note">
                Populate with keywords relevant to your potential claims / Heads of Claim. Include common variations so nothing is missed.
            </div>
            
            <div style="margin-bottom: 15px; display: flex; gap: 10px; flex-wrap: wrap;">
                <button class="btn-secondary" onclick="loadProjectTemplate('construction')" style="font-size: 12px; padding: 6px 12px;">
                    <i class="fas fa-building"></i> Load Construction Template
                </button>
                <button class="btn-secondary" onclick="loadProjectTemplate('infrastructure')" style="font-size: 12px; padding: 6px 12px;">
                    <i class="fas fa-road"></i> Load Infrastructure Template
                </button>
                <button class="btn-secondary" onclick="importStakeholdersCSV()" style="font-size: 12px; padding: 6px 12px;">
                    <i class="fas fa-file-csv"></i> Import CSV
                </button>
            </div>
            
            <div class="table-container">
                <table id="keywordsTable">
                    <thead>
                        <tr>
                            <th>Keyword</th>
                            <th>Variations / Synonyms (comma-separated)</th>
                            <th width="100">Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr>
                            <td>
                                <select class="keyword-name">
                                    <option value="Relevant Event">Relevant Event</option>
                                    <option value="Relevant Matter">Relevant Matter</option>
                                    <option value="Section 278">Section 278</option>
                                    <option value="Delay">Delay</option>
                                    <option value="Risk">Risk</option>
                                    <option value="Change">Change</option>
                                    <option value="Variation">Variation</option>
                                    <option value="Custom">Custom</option>
                                </select>
                            </td>
                            <td><input type="text" class="keyword-variations" placeholder="e.g., Section 278, Highways Agreement, Section 106"></td>
                            <td>
                                <button class="btn-delete-row" onclick="deleteRow(this)">
                                    <i class="fas fa-trash"></i>
                                </button>
                            </td>
                        </tr>
                    </tbody>
                </table>
                <button class="btn-add-row" onclick="addKeywordRow()">
                    <i class="fas fa-plus"></i> Add Row
                </button>
            </div>

            <h3 style="margin: 30px 0 10px 0;">Contract Type</h3>
            <div class="form-group">
                <select id="contractType" onchange="toggleCustomContract(this)">
                    <option value="JCT">JCT</option>
                    <option value="NEC">NEC</option>
                    <option value="FIDIC">FIDIC</option>
                    <option value="PPC">PPC</option>
                    <option value="Custom">Custom</option>
                </select>
                <input type="text" id="contractTypeCustom" class="custom-input" placeholder="Enter custom contract type">
            </div>
        `
    },
    {
        id: 'project-review',
        title: 'Review & Confirm',
        template: `
            <h2>Review & Confirm</h2>
            <div id="reviewSummary"></div>
        `
    }
];

const caseSteps = [
    {
        id: 'case-identification',
        title: 'Case Identification',
        template: `
            <h2>Step 1 of 4 — Case Identification</h2>
            <div class="form-group">
                <label>Case Name <span class="required">*</span></label>
                <input type="text" id="caseName" required minlength="2" maxlength="200" placeholder="Enter case name">
            </div>
            <div class="form-group">
                <label>Case ID</label>
                <input type="text" id="caseId" placeholder="Optional but recommended">
            </div>
            <div class="form-group">
                <label>Resolution Route</label>
                <select id="resolutionRoute" onchange="toggleCustomField(this, 'resolutionRouteCustom')">
                    <option value="adjudication">Adjudication</option>
                    <option value="litigation">Litigation</option>
                    <option value="arbitration">Arbitration</option>
                    <option value="mediation">Mediation</option>
                    <option value="settlement">Settlement</option>
                    <option value="TBC">TBC</option>
                    <option value="Custom">Custom</option>
                </select>
                <input type="text" id="resolutionRouteCustom" class="custom-input" placeholder="Enter custom resolution route">
            </div>
            <div class="form-group">
                <label>Claimant</label>
                <input type="text" id="claimant" placeholder="Enter claimant name">
            </div>
            <div class="form-group">
                <label>Defendant</label>
                <input type="text" id="defendant" placeholder="Enter defendant name">
            </div>
            <div class="form-group">
                <label>Case Status</label>
                <select id="caseStatus" onchange="toggleCustomField(this, 'caseStatusCustom')">
                    <option value="discovery">Discovery</option>
                    <option value="preparation">Preparation</option>
                    <option value="pre-adjudication">Pre-adjudication</option>
                    <option value="Live Adjudication">Live Adjudication</option>
                    <option value="Pre-action Protocol">Pre-action Protocol</option>
                    <option value="Litigation Preparation">Litigation Preparation</option>
                    <option value="Live Litigation">Live Litigation</option>
                    <option value="Custom">Custom</option>
                </select>
                <input type="text" id="caseStatusCustom" class="custom-input" placeholder="Enter custom case status">
            </div>
            <div class="form-group">
                <label>Client</label>
                <input type="text" id="client" placeholder="Enter client name">
            </div>
        `
    },
    {
        id: 'case-legal-team',
        title: 'Legal Team',
        template: `
            <h2>Step 2 of 4 — Legal Team</h2>
            <div class="table-container">
                <table id="legalTeamTable">
                    <thead>
                        <tr>
                            <th>Role / Area</th>
                            <th>Name / Organisation</th>
                            <th width="100">Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr>
                            <td><input type="text" class="team-role" placeholder="e.g., Partner, Counsel, Associate"></td>
                            <td><input type="text" class="team-name" placeholder="Enter name or organisation"></td>
                            <td>
                                <button class="btn-delete-row" onclick="deleteRow(this)">
                                    <i class="fas fa-trash"></i>
                                </button>
                            </td>
                        </tr>
                    </tbody>
                </table>
                <button class="btn-add-row" onclick="addLegalTeamRow()">
                    <i class="fas fa-plus"></i> Add Row
                </button>
            </div>
        `
    },
    {
        id: 'case-heads-keywords',
        title: 'Heads of Claim & Keywords',
        template: `
            <h2>Step 3 of 4 — Heads of Claim & Keywords</h2>
            
            <h3 style="margin-bottom: 10px;">Heads of Claim</h3>
            <div class="table-container">
                <table id="headsOfClaimTable">
                    <thead>
                        <tr>
                            <th>Head of Claim</th>
                            <th>Status</th>
                            <th>Actions (short notes)</th>
                            <th width="100"></th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr>
                            <td><input type="text" class="claim-head" placeholder="Enter head of claim"></td>
                            <td>
                                <select class="claim-status">
                                    <option value="Discovery">Discovery</option>
                                    <option value="Merit Established">Merit Established</option>
                                    <option value="Collating Evidence">Collating Evidence</option>
                                    <option value="Bundling">Bundling</option>
                                    <option value="Complete">Complete</option>
                                    <option value="Custom">Custom</option>
                                </select>
                            </td>
                            <td><input type="text" class="claim-actions" placeholder="e.g., Request PM notes"></td>
                            <td>
                                <button class="btn-delete-row" onclick="deleteRow(this)">
                                    <i class="fas fa-trash"></i>
                                </button>
                            </td>
                        </tr>
                    </tbody>
                </table>
                <button class="btn-add-row" onclick="addHeadOfClaimRow()">
                    <i class="fas fa-plus"></i> Add Row
                </button>
            </div>

            <h3 style="margin: 30px 0 10px 0;">Keywords</h3>
            <div class="guidance-note">
                Populate with keywords relevant to your potential claims / Heads of Claim. Include common variations so nothing is missed.
            </div>
            
            <div class="table-container">
                <table id="caseKeywordsTable">
                    <thead>
                        <tr>
                            <th>Keyword</th>
                            <th>Variations / Synonyms (comma-separated)</th>
                            <th width="100">Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr>
                            <td>
                                <select class="keyword-name">
                                    <option value="Relevant Event">Relevant Event</option>
                                    <option value="Relevant Matter">Relevant Matter</option>
                                    <option value="Section 278">Section 278</option>
                                    <option value="Delay">Delay</option>
                                    <option value="Risk">Risk</option>
                                    <option value="Change">Change</option>
                                    <option value="Variation">Variation</option>
                                    <option value="Custom">Custom</option>
                                </select>
                            </td>
                            <td><input type="text" class="keyword-variations" placeholder="e.g., Section 278, Highways Agreement, Section 106"></td>
                            <td>
                                <button class="btn-delete-row" onclick="deleteRow(this)">
                                    <i class="fas fa-trash"></i>
                                </button>
                            </td>
                        </tr>
                    </tbody>
                </table>
                <button class="btn-add-row" onclick="addCaseKeywordRow()">
                    <i class="fas fa-plus"></i> Add Row
                </button>
            </div>
        `
    },
    {
        id: 'case-deadlines',
        title: 'Case Deadlines',
        template: `
            <h2>Step 4 of 4 — Case Deadlines</h2>
            <div class="table-container">
                <table id="deadlinesTable">
                    <thead>
                        <tr>
                            <th>Deadline / Task</th>
                            <th>Description / Notes</th>
                            <th>Date</th>
                            <th width="100">Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr>
                            <td><input type="text" class="deadline-task" placeholder="e.g., Respondent's evidence"></td>
                            <td><input type="text" class="deadline-description" placeholder="Additional notes"></td>
                            <td><input type="date" class="deadline-date"></td>
                            <td>
                                <button class="btn-delete-row" onclick="deleteRow(this)">
                                    <i class="fas fa-trash"></i>
                                </button>
                            </td>
                        </tr>
                    </tbody>
                </table>
                <button class="btn-add-row" onclick="addDeadlineRow()">
                    <i class="fas fa-plus"></i> Add Row
                </button>
            </div>
        `
    },
    {
        id: 'case-review',
        title: 'Review & Confirm',
        template: `
            <h2>Review & Confirm</h2>
            <div id="reviewSummary"></div>
        `
    }
];

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    setupEventListeners();
    loadDraft();
});

function setupEventListeners() {
    document.getElementById('btnContinue').addEventListener('click', nextStep);
    document.getElementById('btnBack').addEventListener('click', previousStep);
    document.getElementById('btnCancel').addEventListener('click', cancel);
    document.getElementById('btnSaveDraft').addEventListener('click', saveDraft);
    
    document.querySelectorAll('input[name="profileType"]').forEach(radio => {
        radio.addEventListener('change', (e) => {
            wizardState.profileType = e.target.value;
        });
    });
}

function nextStep() {
    if (wizardState.currentStep === 0) {
        // First step - choose type
        const selectedType = document.querySelector('input[name="profileType"]:checked').value;
        wizardState.profileType = selectedType;
        
        if (selectedType === 'users') {
            // Skip to users management
            alert('Users management will be available in the main application');
            return;
        }
        
        // Hide step 0
        document.getElementById('step0').classList.remove('active');
        
        // Load appropriate steps
        loadStepsForType(selectedType);
        wizardState.currentStep = 1;
        updateStepIndicator();
        document.getElementById('btnBack').style.display = 'block';
        return;
    }
    
    // Validate current step
    if (!validateCurrentStep()) {
        return;
    }
    
    // Save current step data
    saveStepData();
    
    const steps = wizardState.profileType === 'project' ? projectSteps : caseSteps;
    
    if (wizardState.currentStep < steps.length) {
        wizardState.currentStep++;
        renderCurrentStep();
        updateStepIndicator();
    }
}

function previousStep() {
    if (wizardState.currentStep > 0) {
        saveStepData();
        wizardState.currentStep--;
        
        if (wizardState.currentStep === 0) {
            document.getElementById('step0').classList.add('active');
            document.getElementById('dynamicSteps').innerHTML = '';
            document.getElementById('btnBack').style.display = 'none';
        } else {
            renderCurrentStep();
        }
        updateStepIndicator();
    }
}

function loadStepsForType(type) {
    const container = document.getElementById('dynamicSteps');
    container.innerHTML = '<div class="wizard-step active" id="dynamicStep"></div>';
    renderCurrentStep();
}

function renderCurrentStep() {
    const steps = wizardState.profileType === 'project' ? projectSteps : caseSteps;
    const currentStepIndex = wizardState.currentStep - 1;
    
    if (currentStepIndex < 0 || currentStepIndex >= steps.length) return;
    
    const step = steps[currentStepIndex];
    const container = document.getElementById('dynamicStep');
    
    container.innerHTML = step.template;
    
    // Load saved data if exists
    loadStepData();
    
    // Update continue button text
    const btnContinue = document.getElementById('btnContinue');
    if (currentStepIndex === steps.length - 1) {
        if (wizardState.profileType === 'project') {
            btnContinue.innerHTML = '<i class="fas fa-check"></i> Create Project';
        } else {
            btnContinue.innerHTML = '<i class="fas fa-check"></i> Create Case';
        }
        btnContinue.onclick = submitWizard;
    } else {
        btnContinue.innerHTML = 'Continue <i class="fas fa-arrow-right"></i>';
        btnContinue.onclick = nextStep;
    }
    
    // If it's review step, generate summary
    if (step.id.includes('review')) {
        generateReviewSummary();
    }
}

function validateCurrentStep() {
    const requiredFields = document.querySelectorAll('#dynamicStep [required]');
    let isValid = true;
    
    requiredFields.forEach(field => {
        if (!field.value.trim()) {
            field.style.borderColor = '#e74c3c';
            isValid = false;
        } else {
            field.style.borderColor = '#e0e0e0';
        }
    });
    
    if (!isValid) {
        alert('Please fill in all required fields');
    }
    
    return isValid;
}

function saveStepData() {
    const steps = wizardState.profileType === 'project' ? projectSteps : caseSteps;
    const currentStepIndex = wizardState.currentStep - 1;
    
    if (currentStepIndex < 0 || currentStepIndex >= steps.length) return;
    
    const step = steps[currentStepIndex];
    const stepData = {};
    
    // Save all input values
    document.querySelectorAll('#dynamicStep input, #dynamicStep select, #dynamicStep textarea').forEach(field => {
        if (field.id) {
            stepData[field.id] = field.value;
        }
    });
    
    // Save table data
    if (step.id === 'project-stakeholders') {
        stepData.stakeholders = getTableData('stakeholdersTable', ['stakeholder-role', 'stakeholder-name']);
        stepData.keywords = getTableData('keywordsTable', ['keyword-name', 'keyword-variations']);
    } else if (step.id === 'case-legal-team') {
        stepData.legalTeam = getTableData('legalTeamTable', ['team-role', 'team-name']);
    } else if (step.id === 'case-heads-keywords') {
        stepData.headsOfClaim = getTableData('headsOfClaimTable', ['claim-head', 'claim-status', 'claim-actions']);
        stepData.keywords = getTableData('caseKeywordsTable', ['keyword-name', 'keyword-variations']);
    } else if (step.id === 'case-deadlines') {
        stepData.deadlines = getTableData('deadlinesTable', ['deadline-task', 'deadline-description', 'deadline-date']);
    }
    
    wizardState.data[step.id] = stepData;
}

function loadStepData() {
    const steps = wizardState.profileType === 'project' ? projectSteps : caseSteps;
    const currentStepIndex = wizardState.currentStep - 1;
    
    if (currentStepIndex < 0 || currentStepIndex >= steps.length) return;
    
    const step = steps[currentStepIndex];
    const stepData = wizardState.data[step.id];
    
    if (!stepData) return;
    
    // Load input values
    Object.keys(stepData).forEach(key => {
        const field = document.getElementById(key);
        if (field && typeof stepData[key] === 'string') {
            field.value = stepData[key];
        }
    });
    
    // Load table data
    if (stepData.stakeholders) {
        loadTableData('stakeholdersTable', stepData.stakeholders, addStakeholderRow);
    }
    if (stepData.keywords) {
        loadTableData('keywordsTable', stepData.keywords, addKeywordRow);
    }
    if (stepData.legalTeam) {
        loadTableData('legalTeamTable', stepData.legalTeam, addLegalTeamRow);
    }
    if (stepData.headsOfClaim) {
        loadTableData('headsOfClaimTable', stepData.headsOfClaim, addHeadOfClaimRow);
    }
    if (stepData.deadlines) {
        loadTableData('deadlinesTable', stepData.deadlines, addDeadlineRow);
    }
}

function getTableData(tableId, columnClasses) {
    const table = document.getElementById(tableId);
    if (!table) return [];
    
    const rows = table.querySelectorAll('tbody tr');
    const data = [];
    
    rows.forEach(row => {
        const rowData = {};
        columnClasses.forEach((className, index) => {
            const field = row.querySelector(`.${className}`);
            if (field) {
                rowData[className] = field.tagName === 'SELECT' ? field.value : field.value;
            }
        });
        data.push(rowData);
    });
    
    return data;
}

function loadTableData(tableId, data, addRowFunction) {
    const table = document.getElementById(tableId);
    if (!table || !data) return;
    
    const tbody = table.querySelector('tbody');
    tbody.innerHTML = '';
    
    data.forEach(rowData => {
        addRowFunction();
        const lastRow = tbody.lastElementChild;
        Object.keys(rowData).forEach(key => {
            const field = lastRow.querySelector(`.${key}`);
            if (field) {
                field.value = rowData[key];
            }
        });
    });
}

function updateStepIndicator() {
    const steps = document.querySelectorAll('.step');
    steps.forEach((step, index) => {
        step.classList.remove('active', 'completed');
        if (index < wizardState.currentStep) {
            step.classList.add('completed');
        } else if (index === wizardState.currentStep) {
            step.classList.add('active');
        }
    });
}

function generateReviewSummary() {
    const container = document.getElementById('reviewSummary');
    let html = '';
    
    if (wizardState.profileType === 'project') {
        const identification = wizardState.data['project-identification'] || {};
        const stakeholders = wizardState.data['project-stakeholders'] || {};
        
        html += `
            <div class="summary-section">
                <h3><i class="fas fa-clipboard-list"></i> Project Identification</h3>
                <div class="summary-item">
                    <div class="summary-label">Project Name:</div>
                    <div class="summary-value">${identification.projectName || 'Not specified'}</div>
                </div>
                <div class="summary-item">
                    <div class="summary-label">Project Code:</div>
                    <div class="summary-value">${identification.projectCode || 'Not specified'}</div>
                </div>
                <div class="summary-item">
                    <div class="summary-label">Start Date:</div>
                    <div class="summary-value">${identification.startDate || 'Not specified'}</div>
                </div>
                <div class="summary-item">
                    <div class="summary-label">Completion Date:</div>
                    <div class="summary-value">${identification.completionDate || 'Not specified'}</div>
                </div>
                <div class="summary-item">
                    <div class="summary-label">Contract Type:</div>
                    <div class="summary-value">${identification.contractType || 'Not specified'}</div>
                </div>
            </div>
            
            <div class="summary-section">
                <h3><i class="fas fa-users"></i> Stakeholders</h3>
                ${(stakeholders.stakeholders || []).map(s => 
                    `<div class="summary-item">
                        <div class="summary-label">${s['stakeholder-role']}:</div>
                        <div class="summary-value">${s['stakeholder-name']}</div>
                    </div>`
                ).join('')}
            </div>
            
            <div class="summary-section">
                <h3><i class="fas fa-tags"></i> Keywords</h3>
                ${(stakeholders.keywords || []).map(k => 
                    `<div class="summary-item">
                        <div class="summary-label">${k['keyword-name']}:</div>
                        <div class="summary-value">${k['keyword-variations'] || 'No variations'}</div>
                    </div>`
                ).join('')}
            </div>
        `;
    } else {
        // Case summary
        const identification = wizardState.data['case-identification'] || {};
        const legalTeam = wizardState.data['case-legal-team'] || {};
        const headsKeywords = wizardState.data['case-heads-keywords'] || {};
        const deadlines = wizardState.data['case-deadlines'] || {};
        
        html += `
            <div class="summary-section">
                <h3><i class="fas fa-gavel"></i> Case Identification</h3>
                <div class="summary-item">
                    <div class="summary-label">Case Name:</div>
                    <div class="summary-value">${identification.caseName || 'Not specified'}</div>
                </div>
                <div class="summary-item">
                    <div class="summary-label">Case ID:</div>
                    <div class="summary-value">${identification.caseId || 'Not specified'}</div>
                </div>
                <div class="summary-item">
                    <div class="summary-label">Resolution Route:</div>
                    <div class="summary-value">${identification.resolutionRoute || 'Not specified'}</div>
                </div>
                <div class="summary-item">
                    <div class="summary-label">Claimant:</div>
                    <div class="summary-value">${identification.claimant || 'Not specified'}</div>
                </div>
                <div class="summary-item">
                    <div class="summary-label">Defendant:</div>
                    <div class="summary-value">${identification.defendant || 'Not specified'}</div>
                </div>
            </div>
            
            <div class="summary-section">
                <h3><i class="fas fa-user-tie"></i> Legal Team</h3>
                ${(legalTeam.legalTeam || []).map(t => 
                    `<div class="summary-item">
                        <div class="summary-label">${t['team-role']}:</div>
                        <div class="summary-value">${t['team-name']}</div>
                    </div>`
                ).join('')}
            </div>
            
            <div class="summary-section">
                <h3><i class="fas fa-list-check"></i> Heads of Claim</h3>
                ${(headsKeywords.headsOfClaim || []).map(h => 
                    `<div class="summary-item">
                        <div class="summary-label">${h['claim-head']}:</div>
                        <div class="summary-value">${h['claim-status']} - ${h['claim-actions']}</div>
                    </div>`
                ).join('')}
            </div>
        `;
    }
    
    container.innerHTML = html;
}

async function submitWizard() {
    // Save current step (in case user edited something)
    saveStepData();
    
    // Validate we have required data
    const steps = wizardState.profileType === 'project' ? projectSteps : caseSteps;
    const identificationStep = steps.find(s => s.id.includes('identification'));
    
    if (identificationStep) {
        const identificationData = wizardState.data[identificationStep.id] || {};
        const requiredFields = wizardState.profileType === 'project' 
            ? ['projectName', 'projectCode']
            : ['caseName'];
        
        const missingFields = requiredFields.filter(field => !identificationData[field] || identificationData[field].trim() === '');
        
        if (missingFields.length > 0) {
            alert(`Please fill in the required fields:\n${missingFields.join(', ')}\n\nGo back and complete the identification step.`);
            return;
        }
    }
    
    // Debug: Log what we're sending
    console.log('Submitting wizard data:', JSON.stringify(wizardState.data, null, 2));
    
    try {
        const apiUrl = window.location.hostname === 'localhost' ? 
            'http://localhost:8010' : 
            (process.env.REACT_APP_API_URL || '');
        
        const endpoint = wizardState.profileType === 'project' ? '/api/projects' : '/api/cases';
        
        const response = await fetch(`${apiUrl}${endpoint}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify(wizardState.data)
        });
        
        // Get error details if request failed
        if (!response.ok) {
            let errorMessage = `Failed to create ${wizardState.profileType}`;
            try {
                const errorData = await response.json();
                console.error('Server error response:', errorData);
                errorMessage = errorData.error || errorMessage;
                
                // Show specific validation errors
                if (errorData.received) {
                    errorMessage += `\n\nReceived data: ${JSON.stringify(errorData.received, null, 2)}`;
                }
            } catch (e) {
                errorMessage += `: ${response.status} ${response.statusText}`;
            }
            throw new Error(errorMessage);
        }
        
        const result = await response.json();
        console.log('Success! Created:', result);
        
        // Clear draft
        localStorage.removeItem('wizardDraft');
        
        // Store case ID for future use
        localStorage.setItem('activeCaseId', result.id);
        localStorage.setItem('currentCaseId', result.id);
        localStorage.setItem('profileType', wizardState.profileType);
        
        // Redirect to dispute intelligence dashboard
        window.location.href = `/ui/dashboard.html?${wizardState.profileType}Id=${result.id}&firstTime=true`;
        
    } catch (error) {
        console.error('Error creating profile:', error);
        alert(`Error creating ${wizardState.profileType}:\n\n${error.message}\n\nCheck the browser console (F12) for full details.`);
    }
}

function saveDraft() {
    saveStepData();
    localStorage.setItem('wizardDraft', JSON.stringify(wizardState));
    alert('Draft saved successfully!');
}

function loadDraft() {
    const draft = localStorage.getItem('wizardDraft');
    if (draft) {
        const shouldLoad = confirm('Would you like to continue from your saved draft?');
        if (shouldLoad) {
            Object.assign(wizardState, JSON.parse(draft));
            if (wizardState.currentStep > 0) {
                document.getElementById('step0').classList.remove('active');
                loadStepsForType(wizardState.profileType);
                renderCurrentStep();
                updateStepIndicator();
                document.getElementById('btnBack').style.display = 'block';
            }
        }
    }
}

function cancel() {
    if (confirm('Are you sure you want to cancel? Any unsaved progress will be lost.')) {
        localStorage.removeItem('wizardDraft');
        window.location.href = '/ui/wizard.html';
    }
}

// Table row functions
function addStakeholderRow() {
    const tbody = document.querySelector('#stakeholdersTable tbody');
    const row = tbody.insertRow();
    row.innerHTML = `
        <td>
            <select class="stakeholder-role">
                <option value="Main Contractor">Main Contractor</option>
                <option value="Council">Council</option>
                <option value="Employers Agent">Employers Agent</option>
                <option value="Project Manager">Project Manager</option>
                <option value="Client">Client</option>
                <option value="Building Control">Building Control</option>
                <option value="Subcontractor">Subcontractor</option>
                <option value="Client Management Team">Client Management Team</option>
                <option value="Custom">Custom</option>
            </select>
        </td>
        <td><input type="text" class="stakeholder-name"></td>
        <td>
            <button class="btn-delete-row" onclick="deleteRow(this)">
                <i class="fas fa-trash"></i>
            </button>
        </td>
    `;
}

function addKeywordRow() {
    const tbody = document.querySelector('#keywordsTable tbody');
    const row = tbody.insertRow();
    row.innerHTML = `
        <td>
            <select class="keyword-name">
                <option value="Relevant Event">Relevant Event</option>
                <option value="Relevant Matter">Relevant Matter</option>
                <option value="Section 278">Section 278</option>
                <option value="Delay">Delay</option>
                <option value="Risk">Risk</option>
                <option value="Change">Change</option>
                <option value="Variation">Variation</option>
                <option value="Custom">Custom</option>
            </select>
        </td>
        <td><input type="text" class="keyword-variations" placeholder="e.g., Section 278, Highways Agreement, Section 106"></td>
        <td>
            <button class="btn-delete-row" onclick="deleteRow(this)">
                <i class="fas fa-trash"></i>
            </button>
        </td>
    `;
}

function addCaseKeywordRow() {
    const tbody = document.querySelector('#caseKeywordsTable tbody');
    const row = tbody.insertRow();
    row.innerHTML = `
        <td>
            <select class="keyword-name">
                <option value="Relevant Event">Relevant Event</option>
                <option value="Relevant Matter">Relevant Matter</option>
                <option value="Section 278">Section 278</option>
                <option value="Delay">Delay</option>
                <option value="Risk">Risk</option>
                <option value="Change">Change</option>
                <option value="Variation">Variation</option>
                <option value="Custom">Custom</option>
            </select>
        </td>
        <td><input type="text" class="keyword-variations" placeholder="e.g., Section 278, Highways Agreement, Section 106"></td>
        <td>
            <button class="btn-delete-row" onclick="deleteRow(this)">
                <i class="fas fa-trash"></i>
            </button>
        </td>
    `;
}

function addLegalTeamRow() {
    const tbody = document.querySelector('#legalTeamTable tbody');
    const row = tbody.insertRow();
    row.innerHTML = `
        <td><input type="text" class="team-role" placeholder="e.g., Partner, Counsel, Associate"></td>
        <td><input type="text" class="team-name" placeholder="Enter name or organisation"></td>
        <td>
            <button class="btn-delete-row" onclick="deleteRow(this)">
                <i class="fas fa-trash"></i>
            </button>
        </td>
    `;
}

function addHeadOfClaimRow() {
    const tbody = document.querySelector('#headsOfClaimTable tbody');
    const row = tbody.insertRow();
    row.innerHTML = `
        <td><input type="text" class="claim-head" placeholder="Enter head of claim"></td>
        <td>
            <select class="claim-status">
                <option value="Discovery">Discovery</option>
                <option value="Merit Established">Merit Established</option>
                <option value="Collating Evidence">Collating Evidence</option>
                <option value="Bundling">Bundling</option>
                <option value="Complete">Complete</option>
                <option value="Custom">Custom</option>
            </select>
        </td>
        <td><input type="text" class="claim-actions" placeholder="e.g., Request PM notes"></td>
        <td>
            <button class="btn-delete-row" onclick="deleteRow(this)">
                <i class="fas fa-trash"></i>
            </button>
        </td>
    `;
}

function addDeadlineRow() {
    const tbody = document.querySelector('#deadlinesTable tbody');
    const row = tbody.insertRow();
    row.innerHTML = `
        <td><input type="text" class="deadline-task" placeholder="e.g., Respondent's evidence"></td>
        <td><input type="text" class="deadline-description" placeholder="Additional notes"></td>
        <td><input type="date" class="deadline-date"></td>
        <td>
            <button class="btn-delete-row" onclick="deleteRow(this)">
                <i class="fas fa-trash"></i>
            </button>
        </td>
    `;
}

function deleteRow(button) {
    button.closest('tr').remove();
}

function toggleCustomContract(select) {
    const customInput = document.getElementById('contractTypeCustom');
    if (select.value === 'Custom') {
        customInput.classList.add('visible');
    } else {
        customInput.classList.remove('visible');
    }
}

function toggleCustomField(select, customInputId) {
    const customInput = document.getElementById(customInputId);
    if (select.value === 'Custom') {
        customInput.classList.add('visible');
    } else {
        customInput.classList.remove('visible');
    }
}

// Template loading functions
function loadProjectTemplate(templateName) {
    const template = projectTemplates[templateName];
    if (!template) return;
    
    // Clear existing stakeholders and add template ones
    const stakeholdersTable = document.querySelector('#stakeholdersTable tbody');
    if (stakeholdersTable) {
        stakeholdersTable.innerHTML = '';
        template.stakeholders.forEach(stakeholder => {
            addStakeholderRow();
            const lastRow = stakeholdersTable.lastElementChild;
            lastRow.querySelector('.stakeholder-role').value = stakeholder.role;
            lastRow.querySelector('.stakeholder-name').value = stakeholder.name;
        });
    }
    
    // Load template keywords
    const keywordsTable = document.querySelector('#keywordsTable tbody');
    if (keywordsTable) {
        keywordsTable.innerHTML = '';
        template.keywords.forEach(keyword => {
            addKeywordRow();
            const lastRow = keywordsTable.lastElementChild;
            const selectElem = lastRow.querySelector('.keyword-name');
            const variationsElem = lastRow.querySelector('.keyword-variations');
            
            // Check if it's a predefined keyword
            const option = Array.from(selectElem.options).find(opt => opt.value === keyword.name);
            if (option) {
                selectElem.value = keyword.name;
            } else {
                selectElem.value = 'Custom';
            }
            variationsElem.value = keyword.variations;
        });
    }
    
    // Set contract type
    const contractType = document.getElementById('contractType');
    if (contractType && template.contractType) {
        contractType.value = template.contractType;
    }
    
    alert(`${template.name} template loaded successfully!`);
}

function loadCaseTemplate(resolutionRoute) {
    const template = caseTemplates[resolutionRoute];
    if (!template) return;
    
    // Load template deadlines
    const deadlinesTable = document.querySelector('#deadlinesTable tbody');
    if (deadlinesTable) {
        deadlinesTable.innerHTML = '';
        template.deadlines.forEach(deadline => {
            addDeadlineRow();
            const lastRow = deadlinesTable.lastElementChild;
            lastRow.querySelector('.deadline-task').value = deadline.task;
            lastRow.querySelector('.deadline-description').value = deadline.description;
        });
    }
    
    // Load template keywords
    const keywordsTable = document.querySelector('#caseKeywordsTable tbody');
    if (keywordsTable) {
        keywordsTable.innerHTML = '';
        template.keywords.forEach(keyword => {
            addCaseKeywordRow();
            const lastRow = keywordsTable.lastElementChild;
            const selectElem = lastRow.querySelector('.keyword-name');
            const variationsElem = lastRow.querySelector('.keyword-variations');
            
            const option = Array.from(selectElem.options).find(opt => opt.value === keyword.name);
            if (option) {
                selectElem.value = keyword.name;
            } else {
                selectElem.value = 'Custom';
            }
            variationsElem.value = keyword.variations;
        });
    }
}

// CSV Import functionality
function importStakeholdersCSV() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.csv';
    input.onchange = e => {
        const file = e.target.files[0];
        const reader = new FileReader();
        reader.onload = event => {
            parseCSV(event.target.result);
        };
        reader.readAsText(file);
    };
    input.click();
}

function parseCSV(csvData) {
    const lines = csvData.split('\n');
    const stakeholdersTable = document.querySelector('#stakeholdersTable tbody');
    
    if (!stakeholdersTable) return;
    
    stakeholdersTable.innerHTML = '';
    
    // Skip header row, process data rows
    for (let i = 1; i < lines.length; i++) {
        const line = lines[i].trim();
        if (!line) continue;
        
        const [role, name] = line.split(',').map(s => s.trim().replace(/^["']|["']$/g, ''));
        
        addStakeholderRow();
        const lastRow = stakeholdersTable.lastElementChild;
        const roleSelect = lastRow.querySelector('.stakeholder-role');
        
        // Try to match role
        const option = Array.from(roleSelect.options).find(opt => 
            opt.value.toLowerCase() === role.toLowerCase()
        );
        
        if (option) {
            roleSelect.value = option.value;
        } else {
            roleSelect.value = 'Custom';
        }
        
        lastRow.querySelector('.stakeholder-name').value = name || '';
    }
    
    alert(`Imported ${lines.length - 1} stakeholders from CSV`);
}
