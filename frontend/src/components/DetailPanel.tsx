import React from 'react';
import { Email } from '../api/correspondence';

interface DetailPanelProps {
    email: Email | null;
    onClose: () => void;
}

export const DetailPanel: React.FC<DetailPanelProps> = ({ email, onClose }) => {
    if (!email) return null;

    return (
        <div className="detail-panel" style={{
            position: 'absolute', right: 0, top: 0, bottom: 0, width: '500px', 
            background: 'white', borderLeft: '1px solid #e2e8f0', display: 'flex', flexDirection: 'column',
            zIndex: 100, boxShadow: '-2px 0 5px rgba(0,0,0,0.1)'
        }}>
            <div className="detail-header" style={{
                padding: '1rem 1.5rem', borderBottom: '1px solid #e2e8f0', 
                display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: '#f8fafc'
            }}>
                <h3>Email Details</h3>
                <button onClick={onClose} style={{ border: 'none', background: 'transparent', cursor: 'pointer', fontSize: '1.25rem' }}>
                   ✕
                </button>
            </div>
            <div className="detail-content" style={{ flex: 1, overflowY: 'auto', padding: '1.5rem' }}>
                <div className="email-header" style={{ marginBottom: '1.5rem' }}>
                    <h2 className="email-subject" style={{ fontSize: '1.25rem', fontWeight: 600, marginBottom: '1rem' }}>
                        {email.email_subject}
                    </h2>
                    <div className="email-meta" style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', fontSize: '0.875rem', color: '#64748b' }}>
                        <div className="email-meta-item" style={{ display: 'flex', gap: '0.5rem' }}>
                            <span style={{ fontWeight: 500, minWidth: '60px' }}>From:</span>
                            <span style={{ wordBreak: 'break-all' }}>{email.email_from}</span>
                        </div>
                        <div className="email-meta-item" style={{ display: 'flex', gap: '0.5rem' }}>
                            <span style={{ fontWeight: 500, minWidth: '60px' }}>To:</span>
                            <span style={{ wordBreak: 'break-all' }}>{email.email_to}</span>
                        </div>
                        <div className="email-meta-item" style={{ display: 'flex', gap: '0.5rem' }}>
                            <span style={{ fontWeight: 500, minWidth: '60px' }}>Date:</span>
                            <span>{new Date(email.email_date).toLocaleString()}</span>
                        </div>
                    </div>
                </div>
                
                <div className="email-body" style={{ background: '#f8fafc', borderRadius: '0.5rem', padding: '1rem', marginTop: '1rem', whiteSpace: 'pre-wrap' }}>
                    {email.body_text || (email.content && !email.content.includes('<html') ? email.content : 'HTML Content hidden in preview') || 'No content available'}
                </div>

                {/* Attachments from meta if available, or direct attachments field */}
                {(email.attachments?.length || email.meta?.attachments?.length) ? (
                    <div className="email-attachments" style={{ marginTop: '1.5rem' }}>
                        <div className="attachments-header" style={{ fontWeight: 600, marginBottom: '0.75rem' }}>
                            Attachments ({(email.attachments || email.meta?.attachments || []).length})
                        </div>
                        <div className="attachment-list" style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                            {(email.attachments || email.meta?.attachments || []).map((att: unknown, idx: number) => {
                                const attachment = att as { filename?: string };
                                return (
                                    <div key={idx} className="attachment-item" style={{ 
                                        display: 'flex', alignItems: 'center', gap: '0.75rem', padding: '0.75rem', 
                                        background: '#f8fafc', borderRadius: '0.5rem', cursor: 'pointer', border: '1px solid #e2e8f0'
                                    }}>
                                        <div className="attachment-icon" style={{ 
                                            width: '32px', height: '32px', display: 'flex', alignItems: 'center', justifyContent: 'center',
                                            background: '#17B5A3', color: 'white', borderRadius: '0.375rem'
                                        }}>📎</div>
                                        <div className="attachment-info">
                                            <div className="attachment-name" style={{ fontWeight: 500, fontSize: '0.875rem' }}>
                                                {attachment.filename || 'Unknown'}
                                            </div>
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                ) : null}
            </div>
        </div>
    );
};

