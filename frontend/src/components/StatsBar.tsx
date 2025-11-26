import React from 'react';

interface StatsBarProps {
    totalEmails: number;
    uniqueThreads: number;
    withAttachments: number;
    selectedCount: number;
}

export const StatsBar: React.FC<StatsBarProps> = ({ totalEmails, uniqueThreads, withAttachments, selectedCount }) => {
    return (
        <div className="stats-bar" style={{
            background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
            color: 'white',
            padding: '1rem 1.5rem',
            display: 'flex',
            alignItems: 'center',
            gap: '3rem',
            overflowX: 'auto'
        }}>
            <StatItem label="Total Emails" value={totalEmails} />
            <StatItem label="Unique Threads" value={uniqueThreads} />
            <StatItem label="With Attachments" value={withAttachments} />
            <StatItem label="Selected" value={selectedCount} />
        </div>
    );
};

const StatItem: React.FC<{ label: string; value: number | string }> = ({ label, value }) => (
    <div className="stat-item" style={{ display: 'flex', flexDirection: 'column', minWidth: 'max-content' }}>
        <span className="stat-label" style={{ fontSize: '0.75rem', opacity: 0.9, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            {label}
        </span>
        <span className="stat-value" style={{ fontSize: '1.5rem', fontWeight: 700 }}>
            {value}
        </span>
    </div>
);

