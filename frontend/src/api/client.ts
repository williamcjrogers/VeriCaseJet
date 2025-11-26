import axios from 'axios';

// API Configuration
// In development, we use relative path which is proxied by Vite to localhost:8010
// In production, we use the current origin
const API_BASE_URL = '/api'; 

// Create Axios Instance
export const apiClient = axios.create({
    baseURL: API_BASE_URL,
    withCredentials: true, // For cookies
    headers: {
        'Content-Type': 'application/json',
    },
});

// CSRF Token Management
function getCsrfToken(): string {
    let token = sessionStorage.getItem('csrf-token');
    if (!token) {
        // Generate a cryptographically secure random token (64 hex characters = 32 bytes)
        const array = new Uint8Array(32);
        window.crypto.getRandomValues(array);
        token = Array.from(array)
            .map(b => b.toString(16).padStart(2, '0'))
            .join('');
        sessionStorage.setItem('csrf-token', token);
    }
    return token;
}

// Request Interceptor: Add Auth & CSRF Headers
apiClient.interceptors.request.use((config) => {
    // Add CSRF Token
    const csrfToken = getCsrfToken();
    if (csrfToken) {
        config.headers['X-CSRF-Token'] = csrfToken;
    }

    // Add Authorization Token from LocalStorage
    const token = localStorage.getItem('token') || localStorage.getItem('jwt');
    if (token) {
        config.headers['Authorization'] = `Bearer ${token}`;
    }

    return config;
}, (error) => {
    return Promise.reject(error);
});

// Response Interceptor: Error Handling
apiClient.interceptors.response.use((response) => {
    return response;
}, (error) => {
    if (error.response && error.response.status === 401) {
        console.warn('Unauthorized - redirecting to login');
        // Handle redirect or auth state update here
    }
    return Promise.reject(error);
});

