
        // ============================================
        // CONFIGURATION
        // ============================================

        const apiUrl = window.VeriCaseConfig ? window.VeriCaseConfig.apiUrl : window.location.origin;

        let gridApi = null;
        let selectedEvidence = null;
        let currentPreviewData = null;
        let projectId = null;
        let caseId = null;
        let currentCategory = 'documents';
        let allEvidenceItems = [];

        // Evidence type configuration
        const typeConfig = {
            contract: { label: 'Contract', icon: 'fa-file-contract', color: '#1e40af' },
            variation: { label: 'Variation', icon: 'fa-exchange-alt', color: '#92400e' },
            drawing: { label: 'Drawing', icon: 'fa-drafting-compass', color: '#3730a3' },
            specification: { label: 'Specification', icon: 'fa-clipboard-list', color: '#166534' },
            programme: { label: 'Programme', icon: 'fa-calendar-alt', color: '#0f766e' },
            invoice: { label: 'Invoice', icon: 'fa-file-invoice-dollar', color: '#166534' },
            payment_certificate: { label: 'Payment Certificate', icon: 'fa-certificate', color: '#0f766e' },
            meeting_minutes: { label: 'Meeting Minutes', icon: 'fa-users', color: '#1e40af' },
            site_instruction: { label: 'Site Instruction', icon: 'fa-hard-hat', color: '#92400e' },
            rfi: { label: 'RFI', icon: 'fa-question-circle', color: '#6b21a8' },
            notice: { label: 'Notice', icon: 'fa-exclamation-triangle', color: '#991b1b' },
            letter: { label: 'Letter', icon: 'fa-envelope', color: '#475569' },
            email_attachment: { label: 'Email Attachment', icon: 'fa-paperclip', color: '#0369a1' },
            photo: { label: 'Photo', icon: 'fa-camera', color: '#6b21a8' },
            expert_report: { label: 'Expert Report', icon: 'fa-user-tie', color: '#1e40af' },
            pdf: { label: 'PDF', icon: 'fa-file-pdf', color: '#dc2626' },
            word_document: { label: 'Word Doc', icon: 'fa-file-word', color: '#2563eb' },
            spreadsheet: { label: 'Spreadsheet', icon: 'fa-file-excel', color: '#16a34a' },
            image: { label: 'Image', icon: 'fa-image', color: '#8b5cf6' },
            other: { label: 'Other', icon: 'fa-file', color: '#64748b' }
        };

        // ============================================
        // UTILITY FUNCTIONS
        // ============================================

        function getFileIcon(mimeType, evidenceType) {
            if (evidenceType && typeConfig[evidenceType]) {
                return typeConfig[evidenceType].icon;
            }
            if (mimeType) {
                if (mimeType.startsWith('image/')) return 'fa-image';
                if (mimeType === 'application/pdf') return 'fa-file-pdf';
                if (mimeType.includes('word')) return 'fa-file-word';
                if (mimeType.includes('excel') || mimeType.includes('spreadsheet')) return 'fa-file-excel';
                if (mimeType.includes('powerpoint') || mimeType.includes('presentation')) return 'fa-file-powerpoint';
                if (mimeType.startsWith('text/')) return 'fa-file-alt';
                if (mimeType.startsWith('audio/')) return 'fa-file-audio';
                if (mimeType.startsWith('video/')) return 'fa-file-video';
            }
            return 'fa-file';
        }

        function getFileIconClass(mimeType) {
            if (!mimeType) return '';
            if (mimeType === 'application/pdf') return 'pdf';
            if (mimeType.includes('word')) return 'word';
            if (mimeType.includes('excel') || mimeType.includes('spreadsheet')) return 'excel';
            if (mimeType.startsWith('image/')) return 'image';
            if (mimeType.includes('outlook') || mimeType === 'message/rfc822') return 'email';
            return '';
        }

        function formatFileSize(bytes) {
            if (!bytes) return '—';
            const k = 1024;
            const sizes = ['B', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
        }

        function formatDate(dateStr) {
            if (!dateStr) return '—';
            try {
                const d = new Date(dateStr);
                return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
            } catch {
                return dateStr;
            }
        }

        function isImageFile(mimeType, filename) {
            if (mimeType?.startsWith('image/')) return true;
            const imageExts = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.bmp', '.tiff', '.tif'];
            return imageExts.some(ext => filename?.toLowerCase().endsWith(ext));
        }

        function getFileTypeInfo(mimeType, filename) {
            const ext = filename?.split('.').pop()?.toLowerCase() || '';
            if (mimeType === 'application/pdf' || ext === 'pdf') return { label: 'PDF', class: 'pdf' };
            if (mimeType?.includes('word') || ['doc', 'docx'].includes(ext)) return { label: 'Word', class: 'word' };
            if (mimeType?.includes('excel') || mimeType?.includes('spreadsheet') || ['xls', 'xlsx', 'csv'].includes(ext)) return { label: 'Excel', class: 'excel' };
            if (mimeType?.includes('powerpoint') || mimeType?.includes('presentation') || ['ppt', 'pptx'].includes(ext)) return { label: 'PPT', class: 'ppt' };
            if (mimeType?.startsWith('text/') || ['txt', 'log', 'md'].includes(ext)) return { label: 'Text', class: 'text' };
            if (mimeType?.startsWith('image/')) return { label: 'Image', class: 'image' };
            return { label: ext.toUpperCase() || 'File', class: '' };
        }

        function escapeHtml(text) {
            if (!text) return '';
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        // ============================================
        // GRID SETUP
        // ============================================

        function initGrid() {
            const gridOptions = {
                columnDefs: [
                    {
                        field: 'thumbnail',
                        headerName: '',
                        width: 60,
                        sortable: false,
                        filter: false,
                        cellRenderer: params => {
                            const icon = getFileIcon(params.data.mime_type, params.data.evidence_type);
                            const iconClass = getFileIconClass(params.data.mime_type);
                            if (params.data.mime_type?.startsWith('image/') && params.data.download_url) {
                                return `<img src="${params.data.download_url}" class="grid-thumbnail" alt="" loading="lazy">`;
                            }
                            return `<div class="grid-file-icon ${iconClass}"><i class="fas ${icon}"></i></div>`;
                        }
                    },
                    {
                        field: 'filename',
                        headerName: 'Name',
                        flex: 2,
                        minWidth: 200,
                        cellRenderer: params => {
                            const typeInfo = getFileTypeInfo(params.data.mime_type, params.data.filename);
                            return `
                                <div class="file-info">
                                    <span class="file-name">${escapeHtml(params.data.title || params.data.filename)}</span>
                                    <span class="file-meta">${typeInfo.label} • ${formatFileSize(params.data.file_size)}</span>
                                </div>
                            `;
                        }
                    },
                    {
                        field: 'document_date',
                        headerName: 'Date',
                        width: 120,
                        valueFormatter: params => formatDate(params.value)
                    },
                    {
                        field: 'processing_status',
                        headerName: 'Status',
                        width: 120,
                        cellRenderer: params => {
                            const status = params.value || 'pending';
                            return `<span class="status-badge status-${status}">${status}</span>`;
                        }
                    },
                    {
                        field: 'evidence_type',
                        headerName: 'AI Classification',
                        width: 140,
                        cellRenderer: params => {
                            const type = params.value;
                            if (!type || type === 'other') return '<span style="color: var(--text-muted);">—</span>';
                            const config = typeConfig[type] || { label: type, color: '#64748b' };
                            return `<span style="color: ${config.color}; font-weight: 500;"><i class="fas ${config.icon || 'fa-file'}"></i> ${config.label}</span>`;
                        }
                    },
                    {
                        field: 'classification_confidence',
                        headerName: 'AI Confidence',
                        width: 120,
                        cellRenderer: params => {
                            const confidence = params.value;
                            if (!confidence) return '<span style="color: var(--text-muted);">—</span>';
                            const color = confidence >= 80 ? '#16a34a' : confidence >= 60 ? '#d97706' : '#dc2626';
                            return `<span style="color: ${color}; font-weight: 500;">${confidence}%</span>`;
                        }
                    },
                    {
                        field: 'extracted_parties',
                        headerName: 'Extracted Parties',
                        width: 160,
                        cellRenderer: params => {
                            const parties = params.value;
                            if (!parties || parties.length === 0) return '<span style="color: var(--text-muted);">—</span>';
                            const display = parties.slice(0, 2).join(', ');
                            const extra = parties.length > 2 ? ` +${parties.length - 2}` : '';
                            return `<span style="color: var(--vericase-teal); font-size: 0.75rem;">${display}${extra}</span>`;
                        }
                    },
                    {
                        field: 'extracted_amounts',
                        headerName: 'Key Amounts',
                        width: 120,
                        cellRenderer: params => {
                            const amounts = params.value;
                            if (!amounts || amounts.length === 0) return '<span style="color: var(--text-muted);">—</span>';
                            const display = amounts[0];
                            const extra = amounts.length > 1 ? ` +${amounts.length - 1}` : '';
                            return `<span style="color: #16a34a; font-weight: 500; font-size: 0.75rem;">${display}${extra}</span>`;
                        }
                    },
                    {
                        field: 'correspondence_count',
                        headerName: 'Links',
                        width: 80,
                        cellRenderer: params => {
                            const count = params.value || 0;
                            if (count > 0) {
                                return `<span style="color: var(--vericase-teal);"><i class="fas fa-link"></i> ${count}</span>`;
                            }
                            return `<span style="color: var(--text-muted);">—</span>`;
                        }
                    },
                    {
                        field: 'is_starred',
                        headerName: '',
                        width: 50,
                        sortable: false,
                        filter: false,
                        cellRenderer: params => {
                            const starred = params.value;
                            return `<button class="star-btn ${starred ? 'starred' : ''}" onclick="event.stopPropagation(); toggleStar('${params.data.id}')">
                                <i class="fas fa-star"></i>
                            </button>`;
                        }
                    }
                ],
                defaultColDef: {
                    sortable: true,
                    filter: true,
                    resizable: true
                },
                rowSelection: 'single',
                animateRows: true,
                rowHeight: 56,
                headerHeight: 44,
                onRowClicked: params => showDetail(params.data),
                onGridReady: params => {
                    loadAllData();
                }
            };

            const gridDiv = document.getElementById('evidenceGrid');
            // Use createGrid API (v31+) instead of deprecated new Grid()
            gridApi = agGrid.createGrid(gridDiv, gridOptions);
        }

        // ============================================
        // DATA LOADING (with prefetch support)
        // ============================================

        // Check for prefetched data from master dashboard
        function getPrefetchedData() {
            try {
                const cached = sessionStorage.getItem('vericase_evidence_prefetch');
                if (cached) {
                    const data = JSON.parse(cached);
                    // Only use if cached within last 5 minutes
                    const MAX_AGE = 5 * 60 * 1000;
                    if (Date.now() - data.timestamp < MAX_AGE) {
                        console.log('[Evidence] Using prefetched data from dashboard');
                        return data;
                    }
                    // Clear stale cache
                    sessionStorage.removeItem('vericase_evidence_prefetch');
                }
            } catch (e) {
                console.warn('[Evidence] Prefetch cache read failed:', e);
            }
            return null;
        }

        async function loadAllData() {
            const prefetched = getPrefetchedData();

            if (prefetched) {
                // Use prefetched data - instant render!
                console.log('[Evidence] Rendering from prefetched cache...');
                const startTime = performance.now();

                allEvidenceItems = prefetched.items || [];

                // Render grid immediately
                document.querySelector('.grid-wrapper').innerHTML = '<div id="evidenceGrid" class="ag-theme-alpine ag-theme-vericase" style="height: 100%;"></div>';
                initGrid();
                updateCategoryCounts();
                applyFilters();

                // Render collections and stats
                if (prefetched.collections) {
                    renderCollections(prefetched.collections);
                }
                if (prefetched.stats) {
                    renderStats(prefetched.stats);
                }

                const duration = (performance.now() - startTime).toFixed(0);
                VericaseUI.Toast.success(`Loaded ${allEvidenceItems.length} items instantly (cached) in ${duration}ms`);

                // Clear used cache
                sessionStorage.removeItem('vericase_evidence_prefetch');

                // Background refresh to get fresh data
                setTimeout(() => refreshDataInBackground(), 1000);
            } else {
                // Normal loading with skeletons
                VericaseUI.Loading.showSkeleton('.grid-wrapper');

                await Promise.all([
                    loadEvidence(),
                    loadCollections(),
                    loadStats()
                ]);
            }
        }

        // Silent background refresh
        async function refreshDataInBackground() {
            try {
                console.log('[Evidence] Background refresh starting...');
                const params = new URLSearchParams();
                params.append('page', '1');
                params.append('page_size', '10000');
                params.append('include_email_info', 'true');
                if (projectId) params.append('project_id', projectId);

                const response = await fetch(`${apiUrl}/api/evidence/items?${params.toString()}`);
                if (response.ok) {
                    const data = await response.json();
                    const newItems = data.items || [];

                    // Only update if there's a difference
                    const currentLength = allEvidenceItems ? allEvidenceItems.length : 0;
                    if (newItems.length !== currentLength) {
                        allEvidenceItems = newItems;
                        updateCategoryCounts();
                        applyFilters();
                        console.log('[Evidence] Background refresh complete - data updated');
                    } else {
                        console.log('[Evidence] Background refresh complete - no changes');
                    }
                }
            } catch (e) {
                console.warn('[Evidence] Background refresh failed:', e);
            }
        }

        async function loadEvidence() {
            try {
                const params = new URLSearchParams();
                params.append('page', '1');
                params.append('page_size', '10000');  // Load ALL evidence items
                params.append('include_email_info', 'true');

                // Include project_id if we have one
                if (projectId) params.append('project_id', projectId);

                const activeCollection = document.querySelector('.collection-item.active');
                const collectionId = activeCollection?.dataset.id;
                if (collectionId) params.append('collection_id', collectionId);

                const response = await fetch(`${apiUrl}/api/evidence/items?${params.toString()}`);

                if (response.ok) {
                    const data = await response.json();
                    allEvidenceItems = data.items || [];

                    // Restore grid
                    document.querySelector('.grid-wrapper').innerHTML = '<div id="evidenceGrid" class="ag-theme-alpine ag-theme-vericase" style="height: 100%;"></div>';
                    initGrid();

                    updateCategoryCounts();
                    applyFilters();

                    VericaseUI.Toast.success(`Loaded ${allEvidenceItems.length} evidence items`);
                } else {
                    throw new Error('Failed to load evidence');
                }
            } catch (error) {
                console.error('Error loading evidence:', error);
                VericaseUI.Toast.error('Failed to load evidence');
                allEvidenceItems = [];
                if (gridApi) gridApi.setGridOption('rowData', []);
            }
        }

        function updateCategoryCounts() {
            let docCount = 0;
            let imgCount = 0;

            // Defensive check - ensure allEvidenceItems is an array
            if (!allEvidenceItems || !Array.isArray(allEvidenceItems)) {
                allEvidenceItems = [];
            }

            allEvidenceItems.forEach(item => {
                if (isImageFile(item.mime_type, item.filename)) {
                    imgCount++;
                } else {
                    docCount++;
                }
            });

            document.getElementById('docCount').textContent = docCount.toLocaleString();
            document.getElementById('imgCount').textContent = imgCount.toLocaleString();
            document.getElementById('allCount').textContent = allEvidenceItems.length.toLocaleString();
        }

        function applyFilters() {
            if (!gridApi) return;

            let filtered = [...allEvidenceItems];

            // Category filter
            if (currentCategory === 'documents') {
                filtered = filtered.filter(item => !isImageFile(item.mime_type, item.filename));
            } else if (currentCategory === 'images') {
                filtered = filtered.filter(item => isImageFile(item.mime_type, item.filename));
            }

            // Search filter
            const search = document.getElementById('searchInput').value.toLowerCase().trim();
            if (search) {
                filtered = filtered.filter(item => {
                    const filename = (item.filename || '').toLowerCase();
                    const title = (item.title || '').toLowerCase();
                    const subject = (item.source_email_subject || '').toLowerCase();
                    const from = (item.source_email_from || '').toLowerCase();
                    return filename.includes(search) || title.includes(search) ||
                        subject.includes(search) || from.includes(search);
                });
            }

            // File type filter
            const fileType = document.getElementById('fileTypeFilter').value;
            if (fileType) {
                filtered = filtered.filter(item => {
                    const typeInfo = getFileTypeInfo(item.mime_type, item.filename);
                    const label = typeInfo.label.toLowerCase();
                    switch (fileType) {
                        case 'pdf': return label === 'pdf';
                        case 'word': return label === 'word';
                        case 'excel': return label === 'excel' || item.mime_type?.includes('spreadsheet');
                        case 'powerpoint': return label === 'ppt';
                        case 'text': return label === 'text' || item.mime_type?.startsWith('text/');
                        case 'image': return isImageFile(item.mime_type, item.filename);
                        case 'other': return !['pdf', 'word', 'excel', 'ppt', 'text', 'image'].includes(label.toLowerCase());
                        default: return true;
                    }
                });
            }

            // Status filter
            const status = document.getElementById('statusFilter').value;
            if (status) {
                filtered = filtered.filter(item => item.processing_status === status);
            }

            // Unassigned filter
            if (document.getElementById('unassignedFilter').checked) {
                filtered = filtered.filter(item => !item.case_id && !item.project_id);
            }

            // Starred filter
            if (document.getElementById('starredFilter').checked) {
                filtered = filtered.filter(item => item.is_starred);
            }

            gridApi.setGridOption('rowData', filtered);
        }

        // Render collections data (can be called with fetched or prefetched data)
        function renderCollections(collections) {
            const list = document.getElementById('collectionList');
            const collectionArray = Array.isArray(collections) ? collections : (collections.collections || []);

            let html = `
                <div class="collection-item active" data-id="">
                    <i class="fas fa-folder"></i>
                    All Evidence
                </div>
            `;

            collectionArray.forEach(c => {
                const icon = c.is_system ? 'fa-folder-open' : 'fa-folder';
                html += `
                    <div class="collection-item" data-id="${c.id}">
                        <i class="fas ${icon}"></i>
                        ${escapeHtml(c.name)}
                        <span class="collection-count">${c.item_count || 0}</span>
                    </div>
                `;
            });

            list.innerHTML = html;

            // Re-attach click handlers
            list.querySelectorAll('.collection-item').forEach(item => {
                item.addEventListener('click', () => {
                    list.querySelectorAll('.collection-item').forEach(i => i.classList.remove('active'));
                    item.classList.add('active');
                    loadEvidence();
                });
            });
        }

        async function loadCollections() {
            try {
                const response = await fetch(`${apiUrl}/api/evidence/collections?include_system=true`);
                if (response.ok) {
                    const collections = await response.json();
                    renderCollections(collections);
                }
            } catch (error) {
                console.error('Error loading collections:', error);
            }
        }

        // Render stats data (can be called with fetched or prefetched data)
        function renderStats(stats) {
            document.getElementById('totalCount').textContent = (stats.total || 0).toLocaleString();
            document.getElementById('unassignedCount').textContent = (stats.unassigned || 0).toLocaleString();
            document.getElementById('linkedCount').textContent = (stats.with_correspondence || 0).toLocaleString();
            document.getElementById('recentCount').textContent = (stats.recent_uploads || 0).toLocaleString();
        }

        async function loadStats() {
            try {
                const response = await fetch(`${apiUrl}/api/evidence/stats`);
                if (response.ok) {
                    const stats = await response.json();
                    renderStats(stats);
                }
            } catch (error) {
                console.error('Error loading stats:', error);
            }
        }

        // ============================================
        // DETAIL PANEL
        // ============================================

        async function showDetail(evidence) {
            if (!evidence) return;

            const panel = document.getElementById('detailPanel');
            panel.classList.add('open');

            // Show loading state
            document.getElementById('previewSection').innerHTML = `
                <div class="preview-placeholder">
                    <div class="loading" style="width: 32px; height: 32px; border-width: 3px;"></div>
                    <span>Loading preview...</span>
                </div>
            `;

            try {
                const [detailRes, previewRes, metadataRes] = await Promise.all([
                    fetch(`${apiUrl}/api/evidence/items/${evidence.id}`),
                    fetch(`${apiUrl}/api/evidence/items/${evidence.id}/preview`),
                    fetch(`${apiUrl}/api/evidence/items/${evidence.id}/metadata`)
                ]);

                if (detailRes.ok) {
                    const detail = await detailRes.json();
                    const preview = previewRes.ok ? await previewRes.json() : null;
                    const metadata = metadataRes.ok ? await metadataRes.json() : null;

                    selectedEvidence = detail;
                    currentPreviewData = preview;

                    renderPreview(preview, detail);
                    renderMetadata(detail, metadata?.metadata);
                }
            } catch (error) {
                console.error('Error loading detail:', error);
                VericaseUI.Toast.error('Failed to load evidence details');
            }
        }

        function renderPreview(preview, detail) {
            const section = document.getElementById('previewSection');

            if (!preview) {
                section.innerHTML = `
                    <div class="preview-placeholder">
                        <i class="fas ${getFileIcon(detail.mime_type, detail.evidence_type)}"></i>
                        <span>Preview not available</span>
                    </div>
                `;
                return;
            }

            let html = '';

            switch (preview.preview_type) {
                case 'image':
                    html = `
                        <img src="${preview.preview_url}" alt="${detail.filename}">
                        <button class="preview-expand-btn" onclick="openFullPreview()">
                            <i class="fas fa-expand"></i> Expand
                        </button>
                    `;
                    break;

                case 'pdf':
                    html = `
                        <iframe src="${preview.preview_url}#toolbar=0"></iframe>
                        <button class="preview-expand-btn" onclick="openFullPreview()">
                            <i class="fas fa-expand"></i> Expand
                        </button>
                    `;
                    break;

                case 'text':
                case 'office':
                    const content = preview.preview_content || 'No content available';
                    const contentStr = typeof content === 'string' ? content : JSON.stringify(content, null, 2);
                    const truncated = contentStr.length > 1000 ? contentStr.substring(0, 1000) + '\n...' : contentStr;
                    html = `
                        <pre style="color: var(--gray-400); font-size: 0.75rem; padding: 16px; margin: 0; overflow: auto; max-height: 100%;">${escapeHtml(truncated)}</pre>
                        <button class="preview-expand-btn" onclick="openFullPreview()">
                            <i class="fas fa-expand"></i> Full Text
                        </button>
                    `;
                    break;

                default:
                    html = `
                        <div class="preview-placeholder">
                            <i class="fas ${getFileIcon(detail.mime_type, detail.evidence_type)}"></i>
                            <span>${detail.filename}</span>
                        </div>
                    `;
            }

            section.innerHTML = html;
        }

        function renderMetadata(detail, extractedMeta) {
            const content = document.getElementById('metadataContent');
            const meta = extractedMeta || detail.extracted_metadata || {};

            let html = '';

            // Basic Info
            html += `
                <div class="detail-section">
                    <div class="detail-section-header">
                        <i class="fas fa-info-circle"></i>
                        <h4>Basic Information</h4>
                    </div>
                    <div class="detail-item" style="margin-bottom: 12px;">
                        <div class="detail-label">Filename</div>
                        <div class="detail-value" style="word-break: break-all;">${escapeHtml(detail.filename)}</div>
                    </div>
                    ${detail.title && detail.title !== detail.filename ? `
                        <div class="detail-item" style="margin-bottom: 12px;">
                            <div class="detail-label">Title</div>
                            <div class="detail-value">${escapeHtml(detail.title)}</div>
                        </div>
                    ` : ''}
                    <div class="detail-grid">
                        <div class="detail-item">
                            <div class="detail-label">Type</div>
                            <div class="detail-value">${typeConfig[detail.evidence_type]?.label || detail.evidence_type || 'Unknown'}</div>
                        </div>
                        <div class="detail-item">
                            <div class="detail-label">Size</div>
                            <div class="detail-value">${formatFileSize(detail.file_size)}</div>
                        </div>
                        <div class="detail-item">
                            <div class="detail-label">Status</div>
                            <div class="detail-value">
                                <span class="status-badge status-${detail.processing_status || 'pending'}">${detail.processing_status || 'pending'}</span>
                            </div>
                        </div>
                        ${detail.document_date ? `
                            <div class="detail-item">
                                <div class="detail-label">Document Date</div>
                                <div class="detail-value">${formatDate(detail.document_date)}</div>
                            </div>
                        ` : ''}
                    </div>
                </div>
            `;

            // Document Properties
            if (meta.author || meta.created_date || meta.page_count) {
                html += `
                    <div class="detail-section">
                        <div class="detail-section-header">
                            <i class="fas fa-file-alt"></i>
                            <h4>Document Properties</h4>
                        </div>
                        <div class="detail-grid">
                            ${meta.author || detail.author ? `
                                <div class="detail-item">
                                    <div class="detail-label">Author</div>
                                    <div class="detail-value">${escapeHtml(meta.author || detail.author)}</div>
                                </div>
                            ` : ''}
                            ${meta.page_count || detail.page_count ? `
                                <div class="detail-item">
                                    <div class="detail-label">Pages</div>
                                    <div class="detail-value">${meta.page_count || detail.page_count}</div>
                                </div>
                            ` : ''}
                            ${meta.created_date ? `
                                <div class="detail-item">
                                    <div class="detail-label">Created</div>
                                    <div class="detail-value">${formatDate(meta.created_date)}</div>
                                </div>
                            ` : ''}
                            ${meta.modified_date ? `
                                <div class="detail-item">
                                    <div class="detail-label">Modified</div>
                                    <div class="detail-value">${formatDate(meta.modified_date)}</div>
                                </div>
                            ` : ''}
                        </div>
                    </div>
                `;
            }

            // Image EXIF
            if (meta.width || meta.camera_make || meta.date_taken) {
                html += `
                    <div class="detail-section">
                        <div class="detail-section-header">
                            <i class="fas fa-camera"></i>
                            <h4>Image Information</h4>
                        </div>
                        <div class="detail-grid">
                            ${meta.width && meta.height ? `
                                <div class="detail-item">
                                    <div class="detail-label">Dimensions</div>
                                    <div class="detail-value">${meta.width} × ${meta.height} px</div>
                                </div>
                            ` : ''}
                            ${meta.camera_make ? `
                                <div class="detail-item">
                                    <div class="detail-label">Camera</div>
                                    <div class="detail-value">${escapeHtml(meta.camera_make)} ${escapeHtml(meta.camera_model || '')}</div>
                                </div>
                            ` : ''}
                            ${meta.date_taken ? `
                                <div class="detail-item">
                                    <div class="detail-label">Date Taken</div>
                                    <div class="detail-value">${formatDate(meta.date_taken)}</div>
                                </div>
                            ` : ''}
                        </div>
                        ${meta.gps_latitude && meta.gps_longitude ? `
                            <div class="detail-item" style="margin-top: 12px;">
                                <div class="detail-label">Location</div>
                                <a href="https://www.google.com/maps?q=${meta.gps_latitude},${meta.gps_longitude}" target="_blank" class="gps-map-link">
                                    <i class="fas fa-map-marker-alt"></i>
                                    ${meta.gps_latitude.toFixed(6)}, ${meta.gps_longitude.toFixed(6)}
                                    <i class="fas fa-external-link-alt" style="font-size: 0.6rem;"></i>
                                </a>
                            </div>
                        ` : ''}
                    </div>
                `;
            }

            // Tags
            if ((detail.auto_tags?.length > 0 || detail.manual_tags?.length > 0)) {
                html += `
                    <div class="detail-section">
                        <div class="detail-section-header">
                            <i class="fas fa-tags"></i>
                            <h4>Tags</h4>
                        </div>
                        <div class="tag-list">
                            ${(detail.manual_tags || []).map(t => `<span class="tag tag-teal">${escapeHtml(t)}</span>`).join('')}
                            ${(detail.auto_tags || []).map(t => `<span class="tag">${escapeHtml(t)}</span>`).join('')}
                        </div>
                    </div>
                `;
            }

            // Linked Correspondence
            if (detail.correspondence_links?.length > 0) {
                html += `
                    <div class="detail-section">
                        <div class="detail-section-header">
                            <i class="fas fa-envelope"></i>
                            <h4>Linked Correspondence (${detail.correspondence_links.length})</h4>
                        </div>
                        ${detail.correspondence_links.map(link => `
                            <div class="link-card">
                                ${link.email ? `
                                    <div class="link-card-title">${escapeHtml(link.email.subject || 'No subject')}</div>
                                    <div class="link-card-meta">${escapeHtml(link.email.sender || '')} • ${formatDate(link.email.date)}</div>
                                ` : ''}
                                <div class="link-card-meta">${link.link_type} • ${link.link_confidence ? link.link_confidence + '% confidence' : 'Manual link'}</div>
                            </div>
                        `).join('')}
                    </div>
                `;
            }

            // Forensic Data
            if (detail.file_hash) {
                html += `
                    <div class="detail-section">
                        <div class="detail-section-header">
                            <i class="fas fa-fingerprint"></i>
                            <h4>Forensic Data</h4>
                        </div>
                        <div class="detail-item">
                            <div class="detail-label">SHA-256 Hash</div>
                            <div class="detail-value" style="font-family: var(--font-mono); font-size: 0.625rem; word-break: break-all;">${detail.file_hash}</div>
                        </div>
                        <div class="detail-item" style="margin-top: 8px;">
                            <div class="detail-label">Uploaded</div>
                            <div class="detail-value">${formatDate(detail.created_at)}</div>
                        </div>
                    </div>
                `;
            }

            content.innerHTML = html;
        }

        function hideDetail() {
            document.getElementById('detailPanel').classList.remove('open');
            selectedEvidence = null;
            currentPreviewData = null;
        }

        // ============================================
        // ACTIONS
        // ============================================

        async function toggleStar(evidenceId) {
            try {
                const response = await fetch(`${apiUrl}/api/evidence/items/${evidenceId}/star`, {
                    method: 'POST'
                });

                if (response.ok) {
                    const result = await response.json();
                    // Update local data
                    const item = allEvidenceItems.find(i => i.id === evidenceId);
                    if (item) {
                        item.is_starred = result.is_starred;
                        applyFilters();
                    }
                    VericaseUI.Toast.success(result.is_starred ? 'Added to starred' : 'Removed from starred');
                }
            } catch (error) {
                console.error('Error toggling star:', error);
                VericaseUI.Toast.error('Failed to update star status');
            }
        }

        function downloadCurrentFile() {
            if (currentPreviewData?.download_url) {
                window.open(currentPreviewData.download_url, '_blank');
            } else if (selectedEvidence?.download_url) {
                window.open(selectedEvidence.download_url, '_blank');
            }
        }

        async function openFullPreview() {
            if (!selectedEvidence || !currentPreviewData) return;

            const modal = document.getElementById('previewModal');
            const content = document.getElementById('previewModalContent');
            const title = document.getElementById('previewModalTitle');

            title.textContent = selectedEvidence.filename;

            let html = '';

            switch (currentPreviewData.preview_type) {
                case 'image':
                    html = `<img src="${currentPreviewData.preview_url}" alt="${selectedEvidence.filename}">`;
                    break;

                case 'pdf':
                    html = `<iframe src="${currentPreviewData.preview_url}"></iframe>`;
                    break;

                case 'text':
                case 'office':
                    try {
                        const response = await fetch(`${apiUrl}/api/evidence/items/${selectedEvidence.id}/text-content?max_length=100000`);
                        if (response.ok) {
                            const data = await response.json();
                            html = `<pre>${escapeHtml(data.text)}</pre>`;
                        } else {
                            html = `<pre>${escapeHtml(currentPreviewData.preview_content || 'Could not load text content')}</pre>`;
                        }
                    } catch {
                        html = `<pre>${escapeHtml(currentPreviewData.preview_content || 'Could not load text content')}</pre>`;
                    }
                    break;

                default:
                    html = `
                        <div style="text-align: center; color: var(--gray-400);">
                            <i class="fas ${getFileIcon(selectedEvidence.mime_type, selectedEvidence.evidence_type)}" style="font-size: 4rem; margin-bottom: 1rem;"></i>
                            <p>Preview not available for this file type</p>
                            <p style="font-size: 0.875rem; margin-top: 0.5rem;">${escapeHtml(selectedEvidence.filename)}</p>
                            <button class="btn btn-vericase" style="margin-top: 1rem;" onclick="downloadCurrentFile()">
                                <i class="fas fa-download"></i> Download File
                            </button>
                        </div>
                    `;
            }

            content.innerHTML = html;
            modal.classList.add('active');
        }

        function closePreviewModal() {
            document.getElementById('previewModal').classList.remove('active');
        }

        async function extractMetadata() {
            if (!selectedEvidence) return;

            const btn = document.getElementById('extractMetadataBtn');
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';

            try {
                const response = await fetch(`${apiUrl}/api/evidence/items/${selectedEvidence.id}/extract-metadata`, {
                    method: 'POST'
                });

                if (response.ok) {
                    await showDetail(selectedEvidence);
                    VericaseUI.Toast.success('Metadata extracted successfully');
                } else {
                    VericaseUI.Toast.error('Failed to extract metadata');
                }
            } catch (error) {
                console.error('Error extracting metadata:', error);
                VericaseUI.Toast.error('Failed to extract metadata');
            } finally {
                btn.disabled = false;
                btn.innerHTML = '<i class="fas fa-magic"></i>';
            }
        }

        async function handleFileUpload(event) {
            const files = event.target.files;
            if (!files || files.length === 0) return;

            const uploadBtn = document.getElementById('uploadBtn');
            uploadBtn.disabled = true;
            uploadBtn.classList.add('loading');

            const toast = VericaseUI.Toast.info(`Uploading ${files.length} file(s)...`, { duration: 0 });

            try {
                let successCount = 0;
                for (const file of files) {
                    const formData = new FormData();
                    formData.append('file', file);
                    if (projectId) formData.append('project_id', projectId);
                    if (caseId) formData.append('case_id', caseId);

                    const response = await fetch(`${apiUrl}/api/evidence/upload/direct`, {
                        method: 'POST',
                        body: formData
                    });

                    if (response.ok) successCount++;
                }

                VericaseUI.Toast.dismiss(toast);
                VericaseUI.Toast.success(`Successfully uploaded ${successCount} file(s)`);

                loadEvidence();
                loadStats();
            } catch (error) {
                console.error('Upload error:', error);
                VericaseUI.Toast.dismiss(toast);
                VericaseUI.Toast.error('Upload failed. Please try again.');
            } finally {
                uploadBtn.disabled = false;
                uploadBtn.classList.remove('loading');
                document.getElementById('fileInput').value = '';
            }
        }

        // ============================================
        // EVENT LISTENERS
        // ============================================

        document.addEventListener('DOMContentLoaded', () => {
            // Inject navigation shell
            VericaseShell.inject({
                title: 'Evidence Repository',
                headerActions: ''
            });

            // Get project context
            projectId = VericaseShell.getProjectId();

            // Initialize grid
            initGrid();

            // Category tabs
            document.querySelectorAll('.category-tab').forEach(tab => {
                tab.addEventListener('click', () => {
                    document.querySelectorAll('.category-tab').forEach(t => t.classList.remove('active'));
                    tab.classList.add('active');
                    currentCategory = tab.dataset.category;
                    applyFilters();
                });
            });

            // Search with debounce
            let searchTimeout;
            document.getElementById('searchInput').addEventListener('input', () => {
                clearTimeout(searchTimeout);
                searchTimeout = setTimeout(applyFilters, 300);
            });

            // Filters
            document.getElementById('fileTypeFilter').addEventListener('change', applyFilters);
            document.getElementById('statusFilter').addEventListener('change', applyFilters);

            // Checkbox pills
            document.getElementById('unassignedFilter').addEventListener('change', (e) => {
                document.getElementById('unassignedPill').classList.toggle('active', e.target.checked);
                applyFilters();
            });

            document.getElementById('starredFilter').addEventListener('change', (e) => {
                document.getElementById('starredPill').classList.toggle('active', e.target.checked);
                applyFilters();
            });

            // Upload
            document.getElementById('uploadBtn').addEventListener('click', () => {
                document.getElementById('fileInput').click();
            });
            document.getElementById('fileInput').addEventListener('change', handleFileUpload);

            // Refresh
            document.getElementById('refreshBtn').addEventListener('click', () => {
                VericaseUI.Toast.info('Refreshing...');
                loadAllData();
            });
            // Detail panel
            document.getElementById('closeDetailBtn').addEventListener('click', hideDetail);
            document.getElementById('downloadBtn').addEventListener('click', downloadCurrentFile);
            document.getElementById('previewFullBtn').addEventListener('click', openFullPreview);
            document.getElementById('extractMetadataBtn').addEventListener('click', extractMetadata);

            // Preview modal
            document.getElementById('closePreviewModal').addEventListener('click', closePreviewModal);
            document.getElementById('modalDownloadBtn').addEventListener('click', downloadCurrentFile);
            document.getElementById('previewModal').addEventListener('click', (e) => {
                if (e.target === document.getElementById('previewModal')) {
                    closePreviewModal();
                }
            });

            // Escape key to close panels
            document.addEventListener('keydown', (e) => {
                if (e.key === 'Escape') {
                    hideDetail();
                    closePreviewModal();
                }
            });
            // Remove preload class after initial render
            requestAnimationFrame(() => {
                document.body.classList.remove('preload');
            });
        });
    
}
