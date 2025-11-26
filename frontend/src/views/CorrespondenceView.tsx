import React, { useState, useEffect, useMemo } from 'react';
import { fetchEmails, Email } from '../api/correspondence';
import { EmailGrid } from '../components/EmailGrid';
import { DetailPanel } from '../components/DetailPanel';
import { StatsBar } from '../components/StatsBar';
import { Toolbar, ViewMode } from '../components/Toolbar';
import { AIChat } from '../components/AIChat';

export const CorrespondenceView: React.FC = () => {
    const [emails, setEmails] = useState<Email[]>([]);
    const [selectedEmail, setSelectedEmail] = useState<Email | null>(null);
    const [viewMode, setViewMode] = useState<ViewMode>('all');
    const [isAIChatOpen, setIsAIChatOpen] = useState(false);
    const [filterText, setFilterText] = useState('');

    useEffect(() => {
        const loadData = async () => {
            const urlParams = new URLSearchParams(window.location.search);
            let caseId = urlParams.get('caseId') || urlParams.get('case_id');
            let projectId = urlParams.get('projectId') || urlParams.get('project_id');

            if (!caseId && !projectId) {
                const profileType = localStorage.getItem('profileType') || 'project';
                if (profileType === 'project') {
                    projectId = localStorage.getItem('currentProjectId');
                } else {
                    caseId = localStorage.getItem('currentCaseId');
                }
            }

            try {
                const data = await fetchEmails({ projectId: projectId || undefined, caseId: caseId || undefined });
                setEmails(data);
            } catch (error: unknown) {
                console.error('Failed to load emails', error);
                if ((error as { response?: { status?: number } })?.response?.status === 401) {
                    window.location.href = '/login?redirect=' + encodeURIComponent(window.location.href);
                }
            }
        };
        void loadData();
    }, []);

    // Load Data function for refresh
    const loadData = async () => {
        const urlParams = new URLSearchParams(window.location.search);
        let caseId = urlParams.get('caseId') || urlParams.get('case_id');
        let projectId = urlParams.get('projectId') || urlParams.get('project_id');

        if (!caseId && !projectId) {
            const profileType = localStorage.getItem('profileType') || 'project';
            if (profileType === 'project') {
                projectId = localStorage.getItem('currentProjectId');
            } else {
                caseId = localStorage.getItem('currentCaseId');
            }
        }

        try {
            const data = await fetchEmails({ projectId: projectId || undefined, caseId: caseId || undefined });
            setEmails(data);
        } catch (error: unknown) {
            console.error('Failed to load emails', error);
            if ((error as { response?: { status?: number } })?.response?.status === 401) {
                window.location.href = '/login?redirect=' + encodeURIComponent(window.location.href);
            }
        }
    };

    // Filter Logic
    const filteredEmails = useMemo(() => {
        let result = emails;
        
        // Apply view mode filter
        if (viewMode === 'attachments') {
            result = result.filter(e => (e.attachments?.length || 0) > 0 || (e.meta?.attachments?.length || 0) > 0);
        } else if (viewMode === 'threads') {
            // Placeholder for thread logic
        }

        // Apply text filter (simplified, Grid handles most filtering but good for stats)
        if (filterText) {
             const lower = filterText.toLowerCase();
             result = result.filter(e => 
                 e.email_subject.toLowerCase().includes(lower) || 
                 e.email_from.toLowerCase().includes(lower) ||
                 e.email_to.toLowerCase().includes(lower)
             );
        }
        
        return result;
    }, [emails, viewMode, filterText]);

    const stats = useMemo(() => {
        const uniqueThreads = new Set(filteredEmails.map(e => e.email_subject.replace(/^(re:|fwd:)\s*/i, '').trim())).size;
        const withAttachments = filteredEmails.filter(e => (e.attachments?.length || 0) > 0 || (e.meta?.attachments?.length || 0) > 0).length;
        
        return {
            total: filteredEmails.length,
            uniqueThreads,
            withAttachments,
            selected: selectedEmail ? 1 : 0 // Simplified selected count
        };
    }, [filteredEmails, selectedEmail]);

    return (
        <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
            <div className="header" style={{ padding: '1rem', borderBottom: '1px solid #e2e8f0', background: 'white' }}>
                 <div className="logo" style={{ color: '#17B5A3', fontWeight: 'bold', fontSize: '1.25rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <span role="img" aria-label="email">📨</span> VeriCase Correspondence
                 </div>
            </div>

            <AIChat isOpen={isAIChatOpen} onClose={() => setIsAIChatOpen(false)} />
            
            <Toolbar 
                onToggleAI={() => setIsAIChatOpen(!isAIChatOpen)}
                onRefresh={loadData}
                viewMode={viewMode}
                onViewModeChange={setViewMode}
                onFilterChange={setFilterText}
            />
            
            <StatsBar 
                totalEmails={stats.total}
                uniqueThreads={stats.uniqueThreads}
                withAttachments={stats.withAttachments}
                selectedCount={stats.selected}
            />

            <div className="main-content" style={{ flex: 1, display: 'flex', position: 'relative', overflow: 'hidden' }}>
                <div className="grid-container" style={{ flex: 1 }}>
                    <EmailGrid 
                        rowData={filteredEmails} 
                        onRowClicked={setSelectedEmail}
                    />
                </div>
                
                {selectedEmail && (
                    <DetailPanel 
                        email={selectedEmail} 
                        onClose={() => setSelectedEmail(null)} 
                    />
                )}
            </div>
        </div>
    );
};
