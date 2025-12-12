/**
 * Production Health Widget
 * Real-time system health monitoring for VeriCase
 * Usage: Add to master-dashboard.html
 */

class ProductionHealthWidget {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        this.refreshInterval = 30000; // 30 seconds
        this.intervalId = null;
    }

    async init() {
        await this.load();
        this.startAutoRefresh();
    }

    async load() {
        try {
            const token = localStorage.getItem('token');
            if (!token) {
                this.renderError('Not authenticated');
                return;
            }

            const response = await fetch('/api/dashboard/system-health', {
                headers: {
                    'Authorization': `Bearer ${token}`
                }
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            const health = await response.json();
            this.render(health);

        } catch (error) {
            console.error('Error loading system health:', error);
            this.renderError(error.message);
        }
    }

    render(health) {
        const statusClass = health.status === 'healthy' ? 'success' :
                           health.status === 'warning' ? 'warning' : 'danger';

        this.container.innerHTML = `
            <div class="health-widget">
                <div class="health-header">
                    <h3>System Health</h3>
                    <span class="badge badge-${statusClass}">${health.status.toUpperCase()}</span>
                    <span class="last-updated">Updated: ${new Date(health.timestamp).toLocaleTimeString()}</span>
                </div>

                <div class="health-grid">
                    <!-- EKS Cluster -->
                    <div class="metric-card">
                        <div class="metric-icon">☸️</div>
                        <div class="metric-content">
                            <h4>EKS Cluster</h4>
                            <div class="metric-value">${health.eks.status || 'N/A'}</div>
                            <div class="metric-detail">
                                Nodes: ${health.eks.node_count || 0} |
                                Pods: ${health.eks.pod_count || 'N/A'}
                            </div>
                        </div>
                    </div>

                    <!-- RDS Database -->
                    <div class="metric-card">
                        <div class="metric-icon">🗄️</div>
                        <div class="metric-content">
                            <h4>Database</h4>
                            <div class="metric-value">${health.rds.cpu_percent || 0}% CPU</div>
                            <div class="metric-detail">
                                Connections: ${health.rds.connections || 0} |
                                Storage: ${health.rds.storage_used_percent || 0}% used
                            </div>
                            ${health.rds.cpu_percent > 80 ? '<div class="alert">⚠️ High CPU</div>' : ''}
                        </div>
                    </div>

                    <!-- S3 Storage -->
                    <div class="metric-card">
                        <div class="metric-icon">📦</div>
                        <div class="metric-content">
                            <h4>Storage</h4>
                            <div class="metric-value">${health.s3.size_gb || 0} GB</div>
                            <div class="metric-detail">
                                Objects: ${(health.s3.object_count || 0).toLocaleString()} |
                                Cost: $${health.s3.estimated_monthly_cost_usd || 0}/mo
                            </div>
                        </div>
                    </div>

                    <!-- Application Stats -->
                    <div class="metric-card">
                        <div class="metric-icon">📊</div>
                        <div class="metric-content">
                            <h4>Application</h4>
                            <div class="metric-value">${health.application.documents.total || 0} Docs</div>
                            <div class="metric-detail">
                                Processing: ${health.application.documents.processing || 0} |
                                Cases: ${health.application.cases.active || 0} active
                            </div>
                        </div>
                    </div>
                </div>

                ${health.errors && health.errors.count > 0 ? `
                    <div class="health-alerts">
                        <div class="alert alert-danger">
                            <strong>⚠️ ${health.errors.count} error(s) in last hour</strong>
                        </div>
                    </div>
                ` : ''}
            </div>
        `;
    }

    renderError(message) {
        this.container.innerHTML = `
            <div class="health-widget">
                <div class="alert alert-danger">
                    Failed to load system health: ${message}
                </div>
            </div>
        `;
    }

    startAutoRefresh() {
        if (this.intervalId) clearInterval(this.intervalId);
        this.intervalId = setInterval(() => this.load(), this.refreshInterval);
    }

    stop() {
        if (this.intervalId) clearInterval(this.intervalId);
    }
}

// Auto-initialize if container exists
document.addEventListener('DOMContentLoaded', () => {
    const container = document.getElementById('production-health');
    if (container) {
        window.productionHealth = new ProductionHealthWidget('production-health');
        window.productionHealth.init();
    }
});
