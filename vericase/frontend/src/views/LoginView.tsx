import React, { useState } from 'react';
import { apiClient } from '../api/client';

export const LoginView: React.FC = () => {
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState('');
    const [isLoading, setIsLoading] = useState(false);

    const handleLogin = async (e: React.FormEvent) => {
        e.preventDefault();
        setError('');
        setIsLoading(true);

        try {
            const response = await apiClient.post('/auth/login', { email, password });
            
            if (response.data && response.data.access_token) {
                // Store token
                localStorage.setItem('token', response.data.access_token);
                localStorage.setItem('user', JSON.stringify(response.data.user));
                
                // Redirect to dashboard (Legacy) or Correspondence (React) depending on flow
                // Ideally, we move Dashboard to React next. For now, we bridge:
                const params = new URLSearchParams(window.location.search);
                const redirect = params.get('redirect');
                
                if (redirect) {
                    window.location.href = redirect;
                } else {
                    // Default to legacy dashboard for now until that's migrated
                    window.location.href = '/ui/dashboard.html';
                }
            }
        } catch (err: unknown) {
            console.error('Login failed', err);
            const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Login failed. Please check credentials.';
            setError(msg);
        } finally {
            setIsLoading(false);
        }
    };

    return (
        <div style={{ 
            height: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', 
            background: 'linear-gradient(135deg, #E8EEF2 0%, #E8EEF2 100%)',
            fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
        }}>
            <div style={{ 
                width: '100%', maxWidth: '400px', padding: '2.5rem', 
                background: 'white', borderRadius: '12px', 
                boxShadow: '0 10px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.1)' 
            }}>
                <div style={{ textAlign: 'center', marginBottom: '2rem' }}>
                    <h1 style={{ color: '#1F2937', fontSize: '1.75rem', fontWeight: '700', marginBottom: '0.5rem' }}>
                        <span style={{ color: '#17B5A3' }}>VeriCase</span> Analysis
                    </h1>
                    <p style={{ color: '#6B7280', fontSize: '0.875rem' }}>Sign in to your account</p>
                </div>

                {error && (
                    <div style={{ 
                        background: '#FEE2E2', border: '1px solid #FCA5A5', color: '#B91C1C', 
                        padding: '0.75rem', borderRadius: '6px', marginBottom: '1.5rem', fontSize: '0.875rem' 
                    }}>
                        {error}
                    </div>
                )}

                <form onSubmit={handleLogin}>
                    <div style={{ marginBottom: '1.25rem' }}>
                        <label htmlFor="email" style={{ display: 'block', fontSize: '0.875rem', fontWeight: '500', color: '#374151', marginBottom: '0.5rem' }}>Email Address</label>
                        <input 
                            id="email" type="email" required 
                            value={email} onChange={e => setEmail(e.target.value)}
                            style={{ 
                                width: '100%', padding: '0.75rem', borderRadius: '6px', border: '1px solid #D1D5DB',
                                fontSize: '0.875rem', outline: 'none', transition: 'border-color 0.2s'
                            }}
                            placeholder="you@example.com"
                        />
                    </div>

                    <div style={{ marginBottom: '1.5rem' }}>
                        <label htmlFor="password" style={{ display: 'block', fontSize: '0.875rem', fontWeight: '500', color: '#374151', marginBottom: '0.5rem' }}>Password</label>
                        <input 
                            id="password" type="password" required 
                            value={password} onChange={e => setPassword(e.target.value)}
                            style={{ 
                                width: '100%', padding: '0.75rem', borderRadius: '6px', border: '1px solid #D1D5DB',
                                fontSize: '0.875rem', outline: 'none', transition: 'border-color 0.2s'
                            }}
                            placeholder="••••••••"
                        />
                    </div>

                    <button 
                        type="submit" disabled={isLoading}
                        style={{ 
                            width: '100%', padding: '0.75rem', borderRadius: '6px', border: 'none',
                            background: '#17B5A3', color: 'white', fontSize: '0.875rem', fontWeight: '600',
                            cursor: isLoading ? 'not-allowed' : 'pointer', transition: 'background 0.2s',
                            opacity: isLoading ? 0.7 : 1
                        }}
                    >
                        {isLoading ? 'Signing in...' : 'Sign In'}
                    </button>
                </form>
            </div>
        </div>
    );
};

