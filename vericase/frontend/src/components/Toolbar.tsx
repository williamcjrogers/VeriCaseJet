import React from 'react';

export type ViewMode = 'all' | 'threads' | 'attachments';

interface ToolbarProps {
    onToggleAI: () => void;
    onRefresh: () => void;
    viewMode: ViewMode;
    onViewModeChange: (mode: ViewMode) => void;
    onFilterChange: (text: string) => void;
}

export const Toolbar: React.FC<ToolbarProps> = ({ onToggleAI, onRefresh, viewMode, onViewModeChange, onFilterChange }) => {
    return (
        <div className="toolbar" style={{
            background: 'white', padding: '1rem 1.5rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            borderBottom: '1px solid #e2e8f0', flexWrap: 'wrap', gap: '1rem'
        }}>
            <div className="toolbar-left" style={{ display: 'flex', alignItems: 'center', gap: '1rem', flex: 1 }}>
                <button className="btn btn-primary" onClick={onToggleAI} style={{
                    display: 'inline-flex', alignItems: 'center', gap: '0.5rem', padding: '0.5rem 1rem', borderRadius: '0.5rem',
                    background: '#17B5A3', color: 'white', border: 'none', cursor: 'pointer'
                }}>
                    <span role="img" aria-label="brain">🧠</span> AI Assistant
                </button>
                <div className="search-box" style={{
                    display: 'flex', alignItems: 'center', background: '#E8EEF2', border: '1px solid #e2e8f0',
                    borderRadius: '0.5rem', padding: '0.5rem 1rem', minWidth: '300px', flex: 1, maxWidth: '500px'
                }}>
                    <span role="img" aria-label="search" style={{ color: '#64748b', marginRight: '0.5rem' }}>🔍</span>
                    <input 
                        type="text" 
                        placeholder="Quick search emails..." 
                        onChange={(e) => onFilterChange(e.target.value)}
                        style={{ border: 'none', background: 'none', outline: 'none', width: '100%', fontSize: '0.875rem' }}
                    />
                </div>
                <button className="btn" onClick={onRefresh} style={{
                    padding: '0.5rem 1rem', borderRadius: '0.5rem', border: '1px solid #e2e8f0', background: 'white', cursor: 'pointer'
                }}>
                   Refresh
                </button>
            </div>
            <div className="toolbar-right" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <div className="btn-group" style={{ display: 'flex', borderRadius: '0.5rem', overflow: 'hidden', border: '1px solid #e2e8f0' }}>
                    {(['all', 'threads', 'attachments'] as const).map((mode) => (
                        <button 
                            key={mode}
                            onClick={() => onViewModeChange(mode)}
                            className={`btn ${viewMode === mode ? 'active' : ''}`}
                            style={{
                                borderRadius: 0, border: 'none', borderRight: '1px solid #e2e8f0', padding: '0.5rem 1rem', cursor: 'pointer',
                                background: viewMode === mode ? '#17B5A3' : 'white',
                                color: viewMode === mode ? 'white' : '#1F2937'
                            }}
                        >
                            {mode.charAt(0).toUpperCase() + mode.slice(1)}
                        </button>
                    ))}
                </div>
            </div>
        </div>
    );
};

