// Contract Intelligence UI Component

class ContractIntelligenceUI {
    constructor() {
        this.apiBase = window.VeriCaseConfig ? window.VeriCaseConfig.apiUrl : window.location.origin;
    }

    async loadAnalysis(emailId) {
        try {
            const response = await fetch(`${this.apiBase}/contract-intelligence/analysis/${emailId}`, {
                headers: getAuthHeaders()
            });
            
            if (!response.ok) {
                if (response.status === 404) return null;
                throw new Error('Failed to load analysis');
            }
            
            return await response.json();
        } catch (error) {
            console.error('Error loading contract analysis:', error);
            return null;
        }
    }

    renderAnalysis(analysis, containerId) {
        const container = document.getElementById(containerId);
        if (!container) return;
        
        if (!analysis || Object.keys(analysis).length === 0) {
            container.innerHTML = '<div style="padding: 1rem; color: var(--text-muted); font-style: italic;">No contract analysis available for this email.</div>';
            return;
        }
        
        let html = '<div class="contract-analysis" style="padding: 1rem;">';
        
        // Risks
        if (analysis.risks && analysis.risks.length > 0) {
            html += '<div class="analysis-section risks" style="margin-bottom: 1.5rem;">';
            html += '<h4 style="margin-bottom: 0.5rem; color: var(--text-primary); font-size: 1rem;"><i class="fas fa-exclamation-triangle" style="color: #f59e0b; margin-right: 0.5rem;"></i> Risks Identified</h4>';
            html += '<ul style="list-style: none; padding: 0; margin: 0;">';
            analysis.risks.forEach(risk => {
                html += `<li style="background: #fffbeb; border: 1px solid #fcd34d; border-radius: 6px; padding: 0.75rem; margin-bottom: 0.5rem;">
                    <div style="font-weight: 600; color: #92400e; margin-bottom: 0.25rem;">Clause ${risk.clause}</div>
                    <div style="color: #b45309; margin-bottom: 0.5rem;">${risk.description}</div>
                    ${risk.mitigation ? `<div class="mitigation" style="font-size: 0.875rem; color: #78350f; background: rgba(255,255,255,0.5); padding: 0.5rem; border-radius: 4px;"><i class="fas fa-shield-alt" style="margin-right: 0.25rem;"></i> Mitigation: ${risk.mitigation}</div>` : ''}
                </li>`;
            });
            html += '</ul></div>';
        }
        
        // Entitlements
        if (analysis.entitlements && analysis.entitlements.length > 0) {
            html += '<div class="analysis-section entitlements" style="margin-bottom: 1.5rem;">';
            html += '<h4 style="margin-bottom: 0.5rem; color: var(--text-primary); font-size: 1rem;"><i class="fas fa-check-circle" style="color: #10b981; margin-right: 0.5rem;"></i> Potential Entitlements</h4>';
            html += '<ul style="list-style: none; padding: 0; margin: 0;">';
            analysis.entitlements.forEach(ent => {
                html += `<li style="background: #ecfdf5; border: 1px solid #6ee7b7; border-radius: 6px; padding: 0.75rem; margin-bottom: 0.5rem;">
                    <div style="font-weight: 600; color: #065f46; margin-bottom: 0.25rem;">${ent.type.replace('_', ' ').toUpperCase()} (Clause ${ent.clause})</div>
                    <div style="color: #047857;">${ent.description}</div>
                </li>`;
            });
            html += '</ul></div>';
        }
        
        // Matched Clauses
        if (analysis.matched_clauses && analysis.matched_clauses.length > 0) {
            html += '<div class="analysis-section clauses">';
            html += '<h4 style="margin-bottom: 0.5rem; color: var(--text-primary); font-size: 1rem;"><i class="fas fa-book" style="color: #3b82f6; margin-right: 0.5rem;"></i> Relevant Clauses</h4>';
            html += '<ul style="list-style: none; padding: 0; margin: 0;">';
            analysis.matched_clauses.forEach(clause => {
                const riskColor = clause.risk_level === 'high' || clause.risk_level === 'critical' ? '#ef4444' : 
                                 clause.risk_level === 'medium' ? '#f59e0b' : '#10b981';
                
                html += `<li style="background: #f3f4f6; border: 1px solid #e5e7eb; border-radius: 6px; padding: 0.75rem; margin-bottom: 0.5rem;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.25rem;">
                        <strong style="color: var(--text-primary);">${clause.clause_number} - ${clause.clause_title}</strong>
                        <span class="badge" style="background: ${riskColor}; color: white; padding: 2px 8px; border-radius: 999px; font-size: 0.75rem; text-transform: uppercase;">${clause.risk_level}</span>
                    </div>
                    <div class="text-muted small" style="color: var(--text-secondary); font-size: 0.875rem;">${clause.description}</div>
                </li>`;
            });
            html += '</ul></div>';
        }
        
        html += '</div>';
        container.innerHTML = html;
    }
}

window.contractIntelligence = new ContractIntelligenceUI();
