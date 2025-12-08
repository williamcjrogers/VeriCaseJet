import React, { useMemo } from 'react';
import { AgGridReact } from 'ag-grid-react';
import { ColDef, ICellRendererParams, ValueGetterParams } from 'ag-grid-community';
import { Email } from '../api/correspondence';
import 'ag-grid-enterprise';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const wrapStyle: any = { whiteSpace: 'normal', lineHeight: '1.4', paddingTop: '8px', paddingBottom: '8px' };
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const boldStyle: any = { fontWeight: '500' };

const decodeHtml = (text: string) => text.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');

const extractField = (content: string, field: string): string => {
    const match = content.match(new RegExp(`<b>${field}:<\\/b>\\s*([^<\\n]+)|${field}:\\s*([^<\\n]+)`, 'i'));
    return match ? decodeHtml((match[1] || match[2]).trim()) : '-';
};

// Helper function to check if an attachment is an embedded/inline image (should be excluded from list)
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const isEmbeddedImage = (att: any): boolean => {
    // Trust is_inline or is_embedded flag from backend
    if (att.is_inline === true || att.is_embedded === true) return true;
    
    const filename = (att.filename || att.name || '').toLowerCase();
    const contentType = (att.content_type || att.contentType || '').toLowerCase();
    const fileSize = att.file_size || att.size || 0;
    
    // Common tracking/spacer images
    const trackingFiles = ['blank.gif', 'spacer.gif', 'pixel.gif', '1x1.gif', 'oledata.mso'];
    if (trackingFiles.includes(filename)) return true;
    
    // CID prefixed files (content-id inline images)
    if (filename.startsWith('cid:') || filename.startsWith('cid_')) return true;
    
    // Pattern: image001.png, image002.jpg, etc (Outlook inline)
    if (/^image\d{3}\.(png|jpg|jpeg|gif|bmp)$/.test(filename)) return true;
    
    // Pattern: img_001.png, img001.jpg, etc
    if (/^img_?\d+\.(png|jpg|jpeg|gif|bmp)$/.test(filename)) return true;
    
    // Small embedded images (signatures, logos, icons)
    if (contentType.includes('image')) {
        // Very small images are likely embedded icons/logos
        if (fileSize && fileSize < 20000) return true;
        
        // Check for signature/logo keywords
        const excludedKeywords = ['signature', 'logo', 'banner', 'header', 'footer', 'badge', 'icon'];
        if (excludedKeywords.some(kw => filename.includes(kw))) return true;
    }
    
    return false;
};

// Helper to filter out embedded images from attachment list
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const getRealAttachments = (attachments: any[]): any[] => {
    if (!attachments || !Array.isArray(attachments)) return [];
    return attachments.filter(att => !isEmbeddedImage(att));
};

// Helper to format file size in human-readable format
const formatFileSize = (bytes: number): string => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
};

const sideBarConfig = {
    toolPanels: [
        { id: 'columns', labelDefault: 'Columns', labelKey: 'columns', iconKey: 'columns', toolPanel: 'agColumnsToolPanel' },
        { id: 'filters', labelDefault: 'Filters', labelKey: 'filters', iconKey: 'filter', toolPanel: 'agFiltersToolPanel' }
    ]
};

interface EmailGridProps {
    rowData: Email[];
    onRowClicked: (email: Email) => void;
}

export const EmailGrid: React.FC<EmailGridProps> = ({ rowData, onRowClicked }) => {
    
    const containerStyle = useMemo(() => ({ width: '100%', height: '100%' }), []);

    const columnDefs = useMemo<ColDef<Email>[]>(() => [
        {
            headerName: '',
            field: 'id', // using id as placeholder for selection
            width: 50,
            checkboxSelection: true,
            headerCheckboxSelection: true,
            pinned: 'left',
            valueGetter: () => undefined, // Hide value
            sortable: false,
            filter: false
        },
        {
            headerName: 'Date/Time',
            field: 'email_date',
            width: 180,
            sort: 'desc',
            cellRenderer: (params: ICellRendererParams<Email>) => {
                if (!params.value) return '-';
                const date = new Date(params.value);
                return (
                    <div style={{ display: 'flex', flexDirection: 'column' }}>
                        <span style={{ fontWeight: 500 }}>{date.toLocaleDateString()}</span>
                        <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{date.toLocaleTimeString()}</span>
                    </div>
                );
            },
            filter: 'agDateColumnFilter',
            filterParams: {
                comparator: (filterDate: Date, cellValue: string) => {
                    const cellDate = new Date(cellValue);
                    if (cellDate < filterDate) return -1;
                    if (cellDate > filterDate) return 1;
                    return 0;
                }
            }
        },
        {
            headerName: 'From',
            field: 'email_from',
            width: 200,
            wrapText: true,
            autoHeight: true,
            cellStyle: wrapStyle,
            filter: 'agSetColumnFilter',
        },
        {
            headerName: 'To',
            field: 'email_to',
            width: 200,
            wrapText: true,
            autoHeight: true,
            valueGetter: (params: ValueGetterParams<Email>) => {
                if (params.data?.email_to) return params.data.email_to;
                const content = params.data?.meta?.content || params.data?.content || '';
                return (content.includes('<html') || content.includes('To:')) ? extractField(content, 'To') : '-';
            },
            filter: 'agTextColumnFilter'
        },
        {
            headerName: 'CC',
            field: 'email_cc',
            width: 150,
            wrapText: true,
            autoHeight: true,
            valueGetter: (params: ValueGetterParams<Email>) => {
                if (params.data?.email_cc) return params.data.email_cc;
                const content = params.data?.meta?.content || params.data?.content || '';
                return (content.includes('<html') || content.includes('CC:')) ? extractField(content, 'CC') : '-';
            },
            filter: 'agTextColumnFilter'
        },
        {
             headerName: 'Subject',
             field: 'email_subject',
             width: 300,
             wrapText: true,
             autoHeight: true,
             cellStyle: boldStyle,
             filter: 'agTextColumnFilter'
        },
        {
            headerName: 'Attachments',
            field: 'attachments',
            width: 250,
            wrapText: true,
            autoHeight: true,
            sortable: false,
            filter: 'agTextColumnFilter',
            valueGetter: (params: ValueGetterParams<Email>) => {
                // Get attachments from various possible sources
                const rawAttachments = params.data?.attachments || params.data?.meta?.attachments || [];
                const realAttachments = getRealAttachments(rawAttachments);
                
                // Return filenames as comma-separated string for filtering
                if (realAttachments.length === 0) return '';
                return realAttachments.map((att: { filename?: string; name?: string }) => att.filename || att.name || 'Attachment').join(', ');
            },
            cellRenderer: (params: ICellRendererParams<Email>) => {
                // Get attachments from various possible sources
                const rawAttachments = params.data?.attachments || params.data?.meta?.attachments || [];
                const realAttachments = getRealAttachments(rawAttachments);
                
                if (realAttachments.length === 0) return <span style={{ color: '#94a3b8' }}>—</span>;
                
                // Display each attachment filename
                return (
                    <div style={{ 
                        display: 'flex', 
                        flexDirection: 'column', 
                        gap: '2px',
                        padding: '4px 0'
                    }}>
                        {realAttachments.map((att: { filename?: string; name?: string; id?: string; file_size?: number; size?: number }, index: number) => {
                            const filename = att.filename || att.name || 'Attachment';
                            const fileSize = att.file_size || att.size;
                            const sizeStr = fileSize ? ` (${formatFileSize(fileSize)})` : '';
                            
                            return (
                                <div 
                                    key={att.id || index}
                                    style={{
                                        display: 'flex',
                                        alignItems: 'center',
                                        gap: '6px',
                                        fontSize: '0.8rem',
                                        color: '#0369a1',
                                        padding: '2px 6px',
                                        background: '#e0f2fe',
                                        borderRadius: '4px',
                                        maxWidth: '100%',
                                        overflow: 'hidden'
                                    }}
                                    title={filename + sizeStr}
                                >
                                    <span style={{ fontSize: '0.7rem' }}>📎</span>
                                    <span style={{ 
                                        overflow: 'hidden', 
                                        textOverflow: 'ellipsis', 
                                        whiteSpace: 'nowrap',
                                        flex: 1
                                    }}>
                                        {filename}
                                    </span>
                                </div>
                            );
                        })}
                    </div>
                );
            }
        }
    ], []);

    const defaultColDef = useMemo(() => ({
        sortable: true,
        filter: true,
        resizable: true,
        floatingFilter: true,
    }), []);

    return (
        <div style={containerStyle} className="ag-theme-quartz">
            <AgGridReact<Email>
                rowData={rowData}
                columnDefs={columnDefs}
                defaultColDef={defaultColDef}
                rowSelection="multiple"
                pagination={true}
                paginationPageSize={20}
                onRowClicked={(e) => e.data && onRowClicked(e.data)}
                enableRangeSelection={true}
                sideBar={sideBarConfig}
            />
        </div>
    );
};
