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
            width: 120,
            sortable: false,
            cellRenderer: (params: ICellRendererParams<Email>) => {
                const attachments = params.value || params.data?.meta?.attachments || [];
                if (!attachments || attachments.length === 0) return '-';
                return (
                    <span className="badge badge-blue" style={{ 
                        background:'#e0f2fe', color:'#0369a1', padding:'2px 8px', borderRadius:'12px', fontSize:'12px' 
                    }}>
                        {attachments.length} files
                    </span>
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
