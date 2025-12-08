import React from 'react';

interface AIChatProps {
    isOpen: boolean;
    onClose: () => void;
}

export const AIChat: React.FC<AIChatProps> = ({ isOpen, onClose }) => {
    if (!isOpen) return null;

    return (
        <div id="aiChatContainer" style={{
            background: 'white', borderBottom: '2px solid #17B5A3', 
            boxShadow: '0 4px 12px rgba(0,0,0,0.08)', padding: '1.5rem 2rem'
        }}>
            <div style={{ maxWidth: '1400px', margin: '0 auto' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '1rem' }}>
                    <div style={{ 
                        width: '48px', height: '48px', background: 'linear-gradient(135deg, #17B5A3, #129B8B)', 
                        borderRadius: '12px', display: 'flex', alignItems: 'center', justifyContent: 'center', 
                        boxShadow: '0 4px 14px rgba(23, 181, 163, 0.39)' 
                    }}>
                        <span role="img" aria-label="brain" style={{ fontSize: '24px' }}>🧠</span>
                    </div>
                    <div style={{ flex: 1 }}>
                        <h3 style={{ color: '#1F2937', fontSize: '1.25rem', marginBottom: '0.25rem' }}>AI Research Assistant</h3>
                        <p style={{ color: '#64748b', fontSize: '0.875rem' }}>Ask questions about your evidence.</p>
                    </div>
                    <button onClick={onClose} style={{ background: 'transparent', border: 'none', color: '#64748b', cursor: 'pointer', fontSize: '1.5rem', padding: '0.5rem' }}>
                        ✕
                    </button>
                </div>
                
                <textarea 
                    placeholder="Ask a question about your evidence..." 
                    style={{ 
                        width: '100%', minHeight: '80px', padding: '1rem', border: '2px solid #E5E7EB', 
                        borderRadius: '12px', fontSize: '0.9375rem', fontFamily: 'inherit', resize: 'vertical' 
                    }}
                />
            </div>
        </div>
    );
};

