import React, { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { AgGridReact } from 'ag-grid-react';
import { ColDef, GridReadyEvent, RowClickedEvent, ValueGetterParams, ICellRendererParams } from 'ag-grid-community';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-alpine.css';

import {
    listEvidence,
    listCollections,
    getEvidenceDetail,
    getEvidenceStats,
    toggleEvidenceStar,
    uploadEvidence,
    EvidenceItemSummary,
    EvidenceItem,
    EvidenceCollection,
    EvidenceStats,
    EvidenceListFilters,
    formatFileSize,
    getFileIcon,
    getEvidenceTypeLabel
} from '../api/evidence';

// ============================================================================
// STYLES
// ============================================================================

const styles = {
    container: {
        height: '100vh',
        display: 'flex',
        flexDirection: 'column' as const,
        overflow: 'hidden',
        fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, sans-serif",
        background: '#f8fafc'
    },
    header: {
        padding: '0.75rem 1.5rem',
        borderBottom: '1px solid #e2e8f0',
        background: 'white',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between'
    },
    logo: {
        color: '#17B5A3',
        fontWeight: 700,
        fontSize: '1.25rem',
        display: 'flex',
        alignItems: 'center',
        gap: '0.5rem'
    },
    toolbar: {
        padding: '0.75rem 1.5rem',
        background: 'white',
        borderBottom: '1px solid #e2e8f0',
        display: 'flex',
        alignItems: 'center',
        gap: '1rem',
        flexWrap: 'wrap' as const
    },
    searchInput: {
        padding: '0.5rem 1rem',
        border: '1px solid #e2e8f0',
        borderRadius: '0.5rem',
        width: '300px',
        fontSize: '0.875rem',
        outline: 'none'
    },
    filterSelect: {
        padding: '0.5rem 1rem',
        border: '1px solid #e2e8f0',
        borderRadius: '0.5rem',
        fontSize: '0.875rem',
        background: 'white',
        cursor: 'pointer'
    },
    button: {
        padding: '0.5rem 1rem',
        border: 'none',
        borderRadius: '0.5rem',
        fontSize: '0.875rem',
        cursor: 'pointer',
        display: 'flex',
        alignItems: 'center',
        gap: '0.5rem',
        transition: 'all 0.2s'
    },
    primaryButton: {
        background: '#17B5A3',
        color: 'white'
    },
    secondaryButton: {
        background: '#f1f5f9',
        color: '#475569'
    },
    statsBar: {
        padding: '0.5rem 1.5rem',
        background: '#f1f5f9',
        display: 'flex',
        gap: '2rem',
        fontSize: '0.75rem',
        color: '#64748b'
    },
    statItem: {
        display: 'flex',
        alignItems: 'center',
        gap: '0.25rem'
    },
    statValue: {
        fontWeight: 600,
        color: '#1e293b'
    },
    mainContent: {
        flex: 1,
        display: 'flex',
        position: 'relative' as const,
        overflow: 'hidden'
    },
    sidebar: {
        width: '240px',
        background: 'white',
        borderRight: '1px solid #e2e8f0',
        display: 'flex',
        flexDirection: 'column' as const,
        overflow: 'hidden'
    },
    sidebarHeader: {
        padding: '1rem',
        fontWeight: 600,
        fontSize: '0.875rem',
        color: '#1e293b',
        borderBottom: '1px solid #e2e8f0'
    },
    collectionList: {
        flex: 1,
        overflow: 'auto',
        padding: '0.5rem'
    },
    collectionItem: {
        padding: '0.5rem 0.75rem',
        borderRadius: '0.375rem',
        cursor: 'pointer',
        display: 'flex',
        alignItems: 'center',
        gap: '0.5rem',
        fontSize: '0.875rem',
        color: '#475569',
        transition: 'all 0.15s'
    },
    collectionItemActive: {
        background: '#e0f2fe',
        color: '#0369a1'
    },
    gridContainer: {
        flex: 1,
        display: 'flex',
        flexDirection: 'column' as const,
        overflow: 'hidden'
    },
    detailPanel: {
        width: '400px',
        background: 'white',
        borderLeft: '1px solid #e2e8f0',
        display: 'flex',
        flexDirection: 'column' as const,
        overflow: 'hidden'
    },
    detailHeader: {
        padding: '1rem',
        borderBottom: '1px solid #e2e8f0',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between'
    },
    detailBody: {
        flex: 1,
        overflow: 'auto',
        padding: '1rem'
    },
    detailSection: {
        marginBottom: '1.5rem'
    },
    detailLabel: {
        fontSize: '0.75rem',
        color: '#64748b',
        marginBottom: '0.25rem',
        textTransform: 'uppercase' as const,
        letterSpacing: '0.05em'
    },
    detailValue: {
        fontSize: '0.875rem',
        color: '#1e293b'
    },
    tagList: {
        display: 'flex',
        flexWrap: 'wrap' as const,
        gap: '0.5rem'
    },
    tag: {
        padding: '0.25rem 0.5rem',
        background: '#e2e8f0',
        borderRadius: '0.25rem',
        fontSize: '0.75rem',
        color: '#475569'
    },
    dropzone: {
        border: '2px dashed #cbd5e1',
        borderRadius: '0.5rem',
        padding: '2rem',
        textAlign: 'center' as const,
        cursor: 'pointer',
        transition: 'all 0.2s',
        background: '#f8fafc'
    },
    dropzoneActive: {
        borderColor: '#17B5A3',
        background: '#f0fdfa'
    }
};

// ============================================================================
// COMPONENTS
// ============================================================================

// File type icon cell renderer
const FileTypeCellRenderer: React.FC<ICellRendererParams> = (params) => {
    const fileType = params.value || 'file';
    const iconClass = getFileIcon(fileType);
    return (
        <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <i className={`fas fa-${iconClass}`} style={{ color: '#64748b' }} />
            <span style={{ textTransform: 'uppercase', fontSize: '0.75rem', color: '#94a3b8' }}>
                {fileType}
            </span>
        </span>
    );
};

// Star cell renderer
const StarCellRenderer: React.FC<ICellRendererParams<EvidenceItemSummary>> = (params) => {
    const isStarred = params.data?.is_starred;
    return (
        <span 
            style={{ cursor: 'pointer', color: isStarred ? '#f59e0b' : '#cbd5e1' }}
            title={isStarred ? 'Starred' : 'Not starred'}
        >
            ★
        </span>
    );
};

// Evidence type badge renderer
const TypeBadgeCellRenderer: React.FC<ICellRendererParams> = (params) => {
    if (!params.value) return null;
    const label = getEvidenceTypeLabel(params.value);
    const colors: Record<string, { bg: string; text: string }> = {
        contract: { bg: '#dbeafe', text: '#1e40af' },
        variation: { bg: '#fef3c7', text: '#92400e' },
        drawing: { bg: '#e0e7ff', text: '#3730a3' },
        invoice: { bg: '#dcfce7', text: '#166534' },
        notice: { bg: '#fee2e2', text: '#991b1b' },
        photo: { bg: '#f3e8ff', text: '#6b21a8' },
        default: { bg: '#f1f5f9', text: '#475569' }
    };
    const color = colors[params.value] || colors.default;
    return (
        <span style={{
            padding: '0.125rem 0.5rem',
            borderRadius: '0.25rem',
            fontSize: '0.75rem',
            fontWeight: 500,
            background: color.bg,
            color: color.text
        }}>
            {label}
        </span>
    );
};

// Correspondence indicator renderer
const CorrespondenceCellRenderer: React.FC<ICellRendererParams<EvidenceItemSummary>> = (params) => {
    const count = params.data?.correspondence_count || 0;
    if (count === 0) return <span style={{ color: '#cbd5e1' }}>—</span>;
    return (
        <span style={{ 
            display: 'flex', 
            alignItems: 'center', 
            gap: '0.25rem',
            color: '#0369a1'
        }}>
            <i className="fas fa-envelope" style={{ fontSize: '0.75rem' }} />
            <span>{count}</span>
        </span>
    );
};

// ============================================================================
// MAIN COMPONENT
// ============================================================================

export const EvidenceView: React.FC = () => {
    // State
    const [evidence, setEvidence] = useState<EvidenceItemSummary[]>([]);
    const [collections, setCollections] = useState<EvidenceCollection[]>([]);
    const [stats, setStats] = useState<EvidenceStats | null>(null);
    const [selectedEvidence, setSelectedEvidence] = useState<EvidenceItem | null>(null);
    const [selectedCollectionId, setSelectedCollectionId] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const [uploading, setUploading] = useState(false);
    const [uploadProgress, setUploadProgress] = useState(0);
    
    // Filters
    const [searchText, setSearchText] = useState('');
    const [typeFilter, setTypeFilter] = useState('');
    const [statusFilter, setStatusFilter] = useState('');
    const [showUnassigned, setShowUnassigned] = useState(false);
    const [showStarred, setShowStarred] = useState(false);
    
    const gridRef = useRef<AgGridReact>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);

    // Load data
    const loadData = useCallback(async () => {
        setLoading(true);
        try {
            const urlParams = new URLSearchParams(window.location.search);
            const caseId = urlParams.get('caseId') || urlParams.get('case_id') || undefined;
            const projectId = urlParams.get('projectId') || urlParams.get('project_id') || undefined;

            const filters: EvidenceListFilters = {
                page: 1,
                page_size: 500,
                search: searchText || undefined,
                evidence_type: typeFilter || undefined,
                processing_status: statusFilter || undefined,
                is_starred: showStarred || undefined,
                unassigned: showUnassigned || undefined,
                collection_id: selectedCollectionId || undefined,
                case_id: caseId,
                project_id: projectId
            };

            const [evidenceData, collectionsData, statsData] = await Promise.all([
                listEvidence(filters),
                listCollections(true, caseId, projectId),
                getEvidenceStats(caseId, projectId)
            ]);

            setEvidence(evidenceData.items);
            setCollections(collectionsData);
            setStats(statsData);
        } catch (error) {
            console.error('Failed to load evidence:', error);
        } finally {
            setLoading(false);
        }
    }, [searchText, typeFilter, statusFilter, showUnassigned, showStarred, selectedCollectionId]);

    useEffect(() => {
        loadData();
    }, [loadData]);

    // Handle row click
    const handleRowClick = async (event: RowClickedEvent<EvidenceItemSummary>) => {
        if (event.data?.id) {
            try {
                const detail = await getEvidenceDetail(event.data.id);
                setSelectedEvidence(detail);
            } catch (error) {
                console.error('Failed to load evidence detail:', error);
            }
        }
    };

    // Handle star toggle
    const handleStarToggle = async (evidenceId: string) => {
        try {
            await toggleEvidenceStar(evidenceId);
            loadData();
        } catch (error) {
            console.error('Failed to toggle star:', error);
        }
    };

    // Handle file upload
    const handleFileUpload = async (files: FileList | null) => {
        if (!files || files.length === 0) return;

        setUploading(true);
        setUploadProgress(0);

        try {
            for (let i = 0; i < files.length; i++) {
                const file = files[i];
                await uploadEvidence(file, {
                    onProgress: (percent) => {
                        setUploadProgress(Math.round((i / files.length) * 100 + percent / files.length));
                    }
                });
            }
            loadData();
        } catch (error) {
            console.error('Upload failed:', error);
        } finally {
            setUploading(false);
            setUploadProgress(0);
        }
    };

    // Handle drag and drop
    const handleDrop = (e: React.DragEvent) => {
        e.preventDefault();
        handleFileUpload(e.dataTransfer.files);
    };

    // Grid columns
    const columnDefs = useMemo<ColDef<EvidenceItemSummary>[]>(() => [
        {
            field: 'is_starred',
            headerName: '',
            width: 40,
            cellRenderer: StarCellRenderer,
            sortable: true,
            onCellClicked: (params) => {
                if (params.data?.id) {
                    handleStarToggle(params.data.id);
                }
            }
        },
        {
            field: 'file_type',
            headerName: 'Type',
            width: 80,
            cellRenderer: FileTypeCellRenderer,
            sortable: true,
            filter: true
        },
        {
            field: 'filename',
            headerName: 'Filename',
            flex: 2,
            sortable: true,
            filter: true
        },
        {
            field: 'title',
            headerName: 'Title',
            flex: 1,
            sortable: true,
            filter: true
        },
        {
            field: 'evidence_type',
            headerName: 'Evidence Type',
            width: 140,
            cellRenderer: TypeBadgeCellRenderer,
            sortable: true,
            filter: true
        },
        {
            field: 'document_date',
            headerName: 'Date',
            width: 110,
            sortable: true,
            filter: true,
            valueGetter: (params: ValueGetterParams<EvidenceItemSummary>) => {
                if (!params.data?.document_date) return '';
                return new Date(params.data.document_date).toLocaleDateString();
            }
        },
        {
            field: 'file_size',
            headerName: 'Size',
            width: 90,
            sortable: true,
            valueGetter: (params: ValueGetterParams<EvidenceItemSummary>) => {
                return params.data?.file_size ? formatFileSize(params.data.file_size) : '';
            }
        },
        {
            field: 'correspondence_count',
            headerName: 'Links',
            width: 70,
            cellRenderer: CorrespondenceCellRenderer,
            sortable: true
        },
        {
            field: 'processing_status',
            headerName: 'Status',
            width: 100,
            sortable: true,
            filter: true,
            cellStyle: (params) => {
                const status = params.value;
                if (status === 'ready') return { color: '#16a34a' };
                if (status === 'processing') return { color: '#ca8a04' };
                if (status === 'failed') return { color: '#dc2626' };
                return { color: '#64748b' };
            }
        },
        {
            field: 'created_at',
            headerName: 'Uploaded',
            width: 110,
            sortable: true,
            valueGetter: (params: ValueGetterParams<EvidenceItemSummary>) => {
                if (!params.data?.created_at) return '';
                return new Date(params.data.created_at).toLocaleDateString();
            }
        }
    ], []);

    const defaultColDef = useMemo<ColDef>(() => ({
        resizable: true,
        sortable: true
    }), []);

    const onGridReady = (params: GridReadyEvent) => {
        params.api.sizeColumnsToFit();
    };

    return (
        <div style={styles.container}>
            {/* Header */}
            <div style={styles.header}>
                <div style={styles.logo}>
                    <span>📁</span> VeriCase Evidence Repository
                </div>
                <div style={{ display: 'flex', gap: '0.5rem' }}>
                    <button
                        style={{ ...styles.button, ...styles.secondaryButton }}
                        onClick={() => window.location.href = '/ui/correspondence-enterprise.html'}
                    >
                        📨 Correspondence
                    </button>
                    <button
                        style={{ ...styles.button, ...styles.secondaryButton }}
                        onClick={() => window.location.href = '/ui/dashboard.html'}
                    >
                        🏠 Dashboard
                    </button>
                </div>
            </div>

            {/* Toolbar */}
            <div style={styles.toolbar}>
                <input
                    type="text"
                    placeholder="Search evidence..."
                    style={styles.searchInput}
                    value={searchText}
                    onChange={(e) => setSearchText(e.target.value)}
                />
                
                <select
                    style={styles.filterSelect}
                    value={typeFilter}
                    onChange={(e) => setTypeFilter(e.target.value)}
                >
                    <option value="">All Types</option>
                    <option value="contract">Contracts</option>
                    <option value="variation">Variations</option>
                    <option value="drawing">Drawings</option>
                    <option value="invoice">Invoices</option>
                    <option value="notice">Notices</option>
                    <option value="meeting_minutes">Meeting Minutes</option>
                    <option value="photo">Photos</option>
                    <option value="letter">Letters</option>
                </select>

                <select
                    style={styles.filterSelect}
                    value={statusFilter}
                    onChange={(e) => setStatusFilter(e.target.value)}
                >
                    <option value="">All Status</option>
                    <option value="ready">Ready</option>
                    <option value="processing">Processing</option>
                    <option value="pending">Pending</option>
                    <option value="failed">Failed</option>
                </select>

                <label style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', cursor: 'pointer', fontSize: '0.875rem' }}>
                    <input
                        type="checkbox"
                        checked={showUnassigned}
                        onChange={(e) => setShowUnassigned(e.target.checked)}
                    />
                    Unassigned only
                </label>

                <label style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', cursor: 'pointer', fontSize: '0.875rem' }}>
                    <input
                        type="checkbox"
                        checked={showStarred}
                        onChange={(e) => setShowStarred(e.target.checked)}
                    />
                    Starred only
                </label>

                <div style={{ flex: 1 }} />

                <input
                    type="file"
                    ref={fileInputRef}
                    multiple
                    style={{ display: 'none' }}
                    onChange={(e) => handleFileUpload(e.target.files)}
                />
                <button
                    style={{ ...styles.button, ...styles.primaryButton }}
                    onClick={() => fileInputRef.current?.click()}
                    disabled={uploading}
                >
                    {uploading ? `Uploading ${uploadProgress}%` : '⬆ Upload Evidence'}
                </button>

                <button
                    style={{ ...styles.button, ...styles.secondaryButton }}
                    onClick={loadData}
                >
                    🔄 Refresh
                </button>
            </div>

            {/* Stats Bar */}
            <div style={styles.statsBar}>
                <div style={styles.statItem}>
                    <span style={styles.statValue}>{stats?.total || 0}</span> Total Items
                </div>
                <div style={styles.statItem}>
                    <span style={styles.statValue}>{stats?.unassigned || 0}</span> Unassigned
                </div>
                <div style={styles.statItem}>
                    <span style={styles.statValue}>{stats?.with_correspondence || 0}</span> With Links
                </div>
                <div style={styles.statItem}>
                    <span style={styles.statValue}>{stats?.recent_uploads || 0}</span> Recent (7d)
                </div>
                {stats?.by_status && Object.entries(stats.by_status).map(([status, count]) => (
                    <div key={status} style={styles.statItem}>
                        <span style={styles.statValue}>{count}</span> {status}
                    </div>
                ))}
            </div>

            {/* Main Content */}
            <div style={styles.mainContent}>
                {/* Collections Sidebar */}
                <div style={styles.sidebar}>
                    <div style={styles.sidebarHeader}>Collections</div>
                    <div style={styles.collectionList}>
                        <div
                            style={{
                                ...styles.collectionItem,
                                ...(selectedCollectionId === null ? styles.collectionItemActive : {})
                            }}
                            onClick={() => setSelectedCollectionId(null)}
                        >
                            📁 All Evidence
                        </div>
                        {collections.map((collection) => (
                            <div
                                key={collection.id}
                                style={{
                                    ...styles.collectionItem,
                                    ...(selectedCollectionId === collection.id ? styles.collectionItemActive : {}),
                                    paddingLeft: collection.is_system ? '0.75rem' : '1.5rem'
                                }}
                                onClick={() => setSelectedCollectionId(collection.id)}
                            >
                                <span style={{ color: collection.color || '#64748b' }}>
                                    {collection.icon ? `${collection.icon} ` : '📂 '}
                                </span>
                                {collection.name}
                                <span style={{ marginLeft: 'auto', fontSize: '0.75rem', color: '#94a3b8' }}>
                                    {collection.item_count}
                                </span>
                            </div>
                        ))}
                    </div>
                </div>

                {/* Grid */}
                <div style={styles.gridContainer}>
                    <div
                        className="ag-theme-alpine"
                        style={{ flex: 1, width: '100%' }}
                        onDragOver={(e) => e.preventDefault()}
                        onDrop={handleDrop}
                    >
                        <AgGridReact
                            ref={gridRef}
                            rowData={evidence}
                            columnDefs={columnDefs}
                            defaultColDef={defaultColDef}
                            onGridReady={onGridReady}
                            onRowClicked={handleRowClick}
                            rowSelection="single"
                            animateRows={true}
                            enableCellTextSelection={true}
                            suppressCellFocus={true}
                            overlayLoadingTemplate={loading ? '<span>Loading evidence...</span>' : undefined}
                            overlayNoRowsTemplate="<span>No evidence found. Drop files here to upload.</span>"
                        />
                    </div>
                </div>

                {/* Detail Panel */}
                {selectedEvidence && (
                    <div style={styles.detailPanel}>
                        <div style={styles.detailHeader}>
                            <span style={{ fontWeight: 600 }}>Evidence Details</span>
                            <button
                                style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '1.25rem' }}
                                onClick={() => setSelectedEvidence(null)}
                            >
                                ✕
                            </button>
                        </div>
                        <div style={styles.detailBody}>
                            <div style={styles.detailSection}>
                                <div style={styles.detailLabel}>Filename</div>
                                <div style={styles.detailValue}>{selectedEvidence.filename}</div>
                            </div>

                            {selectedEvidence.title && (
                                <div style={styles.detailSection}>
                                    <div style={styles.detailLabel}>Title</div>
                                    <div style={styles.detailValue}>{selectedEvidence.title}</div>
                                </div>
                            )}

                            <div style={styles.detailSection}>
                                <div style={styles.detailLabel}>Type</div>
                                <div style={styles.detailValue}>
                                    {selectedEvidence.evidence_type ? getEvidenceTypeLabel(selectedEvidence.evidence_type) : 'Not classified'}
                                </div>
                            </div>

                            {selectedEvidence.document_date && (
                                <div style={styles.detailSection}>
                                    <div style={styles.detailLabel}>Document Date</div>
                                    <div style={styles.detailValue}>
                                        {new Date(selectedEvidence.document_date).toLocaleDateString()}
                                    </div>
                                </div>
                            )}

                            <div style={styles.detailSection}>
                                <div style={styles.detailLabel}>Size</div>
                                <div style={styles.detailValue}>
                                    {selectedEvidence.file_size ? formatFileSize(selectedEvidence.file_size) : 'Unknown'}
                                </div>
                            </div>

                            {selectedEvidence.author && (
                                <div style={styles.detailSection}>
                                    <div style={styles.detailLabel}>Author</div>
                                    <div style={styles.detailValue}>{selectedEvidence.author}</div>
                                </div>
                            )}

                            {selectedEvidence.description && (
                                <div style={styles.detailSection}>
                                    <div style={styles.detailLabel}>Description</div>
                                    <div style={styles.detailValue}>{selectedEvidence.description}</div>
                                </div>
                            )}

                            {/* Tags */}
                            {(selectedEvidence.auto_tags?.length > 0 || selectedEvidence.manual_tags?.length > 0) && (
                                <div style={styles.detailSection}>
                                    <div style={styles.detailLabel}>Tags</div>
                                    <div style={styles.tagList}>
                                        {selectedEvidence.manual_tags?.map((tag, i) => (
                                            <span key={`manual-${i}`} style={{ ...styles.tag, background: '#dbeafe' }}>
                                                {tag}
                                            </span>
                                        ))}
                                        {selectedEvidence.auto_tags?.map((tag, i) => (
                                            <span key={`auto-${i}`} style={styles.tag}>
                                                {tag}
                                            </span>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {/* Extracted References */}
                            {selectedEvidence.extracted_references && selectedEvidence.extracted_references.length > 0 && (
                                <div style={styles.detailSection}>
                                    <div style={styles.detailLabel}>References Found</div>
                                    <div style={styles.tagList}>
                                        {selectedEvidence.extracted_references.map((ref, i) => (
                                            <span key={i} style={{ ...styles.tag, background: '#fef3c7' }}>
                                                {ref.reference}
                                            </span>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {/* Correspondence Links */}
                            {selectedEvidence.correspondence_links && selectedEvidence.correspondence_links.length > 0 && (
                                <div style={styles.detailSection}>
                                    <div style={styles.detailLabel}>
                                        Linked Correspondence ({selectedEvidence.correspondence_links.length})
                                    </div>
                                    {selectedEvidence.correspondence_links.map((link) => (
                                        <div 
                                            key={link.id} 
                                            style={{ 
                                                padding: '0.5rem',
                                                background: '#f8fafc',
                                                borderRadius: '0.25rem',
                                                marginBottom: '0.5rem',
                                                fontSize: '0.8125rem'
                                            }}
                                        >
                                            {link.email ? (
                                                <>
                                                    <div style={{ fontWeight: 500 }}>{link.email.subject}</div>
                                                    <div style={{ color: '#64748b', fontSize: '0.75rem' }}>
                                                        {link.email.sender_email} • {link.email.date_sent ? new Date(link.email.date_sent).toLocaleDateString() : ''}
                                                    </div>
                                                </>
                                            ) : link.external_correspondence ? (
                                                <>
                                                    <div style={{ fontWeight: 500 }}>{link.external_correspondence.subject || link.external_correspondence.reference}</div>
                                                    <div style={{ color: '#64748b', fontSize: '0.75rem' }}>
                                                        {link.external_correspondence.type} • {link.external_correspondence.date || ''}
                                                    </div>
                                                </>
                                            ) : null}
                                            <div style={{ color: '#94a3b8', fontSize: '0.6875rem', marginTop: '0.25rem' }}>
                                                {link.link_type} • {link.link_confidence ? `${link.link_confidence}% confidence` : 'Manual link'}
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}

                            {/* Download Button */}
                            {selectedEvidence.download_url && (
                                <div style={{ marginTop: '1rem' }}>
                                    <a
                                        href={selectedEvidence.download_url}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        style={{
                                            ...styles.button,
                                            ...styles.primaryButton,
                                            textDecoration: 'none',
                                            display: 'inline-flex',
                                            width: '100%',
                                            justifyContent: 'center'
                                        }}
                                    >
                                        ⬇ Download File
                                    </a>
                                </div>
                            )}
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};

export default EvidenceView;

