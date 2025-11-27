/**
 * VeriCase Navigation Shell
 * Injects consistent navigation into all pages
 */

(function() {
    'use strict';

    const NAV_ITEMS = [
        { section: 'HOME', items: [
            { id: 'home', label: 'Command Center', icon: 'fa-home', url: 'master-dashboard.html' },
        ]},
        { section: 'PROJECT', items: [
            { id: 'dashboard', label: 'Project Dashboard', icon: 'fa-th-large', url: 'dashboard.html' },
            { id: 'evidence', label: 'Evidence Repository', icon: 'fa-folder-open', url: 'evidence.html' },
            { id: 'correspondence', label: 'Correspondence', icon: 'fa-envelope-open-text', url: 'correspondence-enterprise.html' },
            { id: 'claims', label: 'Claims & Matters', icon: 'fa-balance-scale', url: 'contentious-matters.html' },
        ]},
        { section: 'TOOLS', items: [
            { id: 'upload', label: 'Upload PST', icon: 'fa-upload', url: 'pst-upload.html' },
            { id: 'wizard', label: 'Project Setup', icon: 'fa-magic', url: 'wizard.html' },
            { id: 'refinement', label: 'AI Refinement', icon: 'fa-robot', url: 'ai-refinement-wizard.html' },
            { id: 'research', label: 'Deep Research', icon: 'fa-microscope', url: 'deep-research.html', badge: 'NEW' },
        ]},
        { section: 'ADMIN', adminOnly: true, items: [
            { id: 'settings', label: 'Settings', icon: 'fa-cog', url: 'admin-settings.html' },
            { id: 'users', label: 'Users', icon: 'fa-users', url: 'admin-users.html' },
        ]}
    ];

    function getCurrentPage() {
        return window.location.pathname.split('/').pop().toLowerCase() || 'dashboard.html';
    }

    function getProjectId() {
        const urlParams = new URLSearchParams(window.location.search);
        return urlParams.get('projectId') || localStorage.getItem('vericase_current_project') || '';
    }

    function getUserRole() {
        try {
            const user = JSON.parse(localStorage.getItem('user') || '{}');
            return user.role || 'VIEWER';
        } catch {
            return 'VIEWER';
        }
    }

    function isAdmin() {
        return getUserRole() === 'ADMIN';
    }

    function buildNavUrl(url) {
        const projectId = getProjectId();
        // Don't add projectId to home page
        if (url === 'master-dashboard.html') {
            return url;
        }
        if (projectId) {
            const u = new URL(url, window.location.href);
            u.searchParams.set('projectId', projectId);
            return u.toString();
        }
        return url;
    }

    function renderSidebar() {
        const currentPage = getCurrentPage();
        const userIsAdmin = isAdmin();
        const hasProject = !!getProjectId();
        
        let navHtml = '';
        NAV_ITEMS.forEach(section => {
            // Skip admin section for non-admins
            if (section.adminOnly && !userIsAdmin) {
                return;
            }
            
            // Add visual indicator if project section but no project selected
            const needsProject = section.section === 'PROJECT';
            const sectionClass = needsProject && !hasProject ? 'nav-section needs-project' : 'nav-section';
            
            navHtml += `<div class="${sectionClass}">`;
            navHtml += `<div class="nav-section-title">${section.section}</div>`;
            
            section.items.forEach(item => {
                const isActive = currentPage.includes(item.url.replace('.html', ''));
                const itemDisabled = needsProject && !hasProject ? 'disabled' : '';
                navHtml += `
                    <a href="${buildNavUrl(item.url)}" class="nav-item ${isActive ? 'active' : ''} ${itemDisabled}" data-nav="${item.id}">
                        <i class="fas ${item.icon}"></i>
                        <span>${item.label}</span>
                        ${item.badge ? `<span class="nav-badge">${item.badge}</span>` : ''}
                    </a>
                `;
            });
            
            navHtml += `</div>`;
        });

        // Add project context indicator if project is selected
        const projectId = getProjectId();
        const projectContext = projectId ? `
            <div class="project-context">
                <div class="project-context-label">Current Project</div>
                <div class="project-context-name" id="currentProjectName">Loading...</div>
            </div>
        ` : '';

        return `
            <aside class="app-sidebar" id="appSidebar">
                <div class="sidebar-header">
                    <a href="master-dashboard.html" class="sidebar-logo">
                        <i class="fas fa-shield-alt"></i>
                        <span>VeriCase</span>
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

    function renderHeader(title = '', actions = '') {
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

    function injectShell(options = {}) {
        const { 
            title = document.title.replace('VeriCase - ', ''),
            headerActions = '',
            showProgress = false,
            projectId = null
        } = options;

        // Don't inject if already has shell
        if (document.querySelector('.app-shell')) return;

        // Wrap existing body content
        const existingContent = document.body.innerHTML;
        
        document.body.innerHTML = `
            <div class="app-shell">
                ${renderSidebar()}
                <main class="app-main">
                    ${renderHeader(title, headerActions)}
                    ${showProgress ? '<div id="progressTracker"></div>' : ''}
                    <div class="app-content">
                        ${existingContent}
                    </div>
                </main>
            </div>
            <div class="toast-container" id="toastContainer"></div>
        `;

        // Initialize progress tracker if needed
        if (showProgress && projectId && window.VericaseUI) {
            window.VericaseUI.Progress.render('progressTracker', projectId);
        }

        // Setup responsive sidebar toggle
        const mediaQuery = window.matchMedia('(max-width: 1024px)');
        const sidebar = document.getElementById('appSidebar');
        const toggle = document.getElementById('sidebarToggle');
        
        function handleMediaChange(e) {
            if (toggle) {
                toggle.style.display = e.matches ? 'flex' : 'none';
            }
        }
        
        mediaQuery.addListener(handleMediaChange);
        handleMediaChange(mediaQuery);
        
        if (toggle && sidebar) {
            toggle.addEventListener('click', () => {
                sidebar.classList.toggle('mobile-open');
            });
        }
    }

    // Export
    window.VericaseShell = {
        inject: injectShell,
        NAV_ITEMS,
        buildNavUrl,
        getProjectId
    };

})();

