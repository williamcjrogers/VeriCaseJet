// VeriCase Frontend Configuration
// This file handles API URL configuration for both local development and AWS deployment

(function() {
    'use strict';
    
    // Configuration object
    window.VeriCaseConfig = {
        // API URL Configuration
        getApiUrl: function() {
            // Check if we're running locally
            if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
                return window.location.protocol + '//localhost:8010';
            }
            
            // AWS App Runner deployment
            // The API is hosted on the same App Runner service, accessible via the same URL
            // App Runner handles both static files (UI) and API routes
            return window.location.origin;
        },
        
        // Get the base API endpoint
        get apiUrl() {
            return this.getApiUrl();
        },
        
        // Check if we're in development mode
        get isDevelopment() {
            return window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
        },
        
        // Check if we're in production (AWS)
        get isProduction() {
            return !this.isDevelopment;
        },
        
        // S3/Storage Configuration
        get storageEndpoint() {
            if (this.isDevelopment) {
                // Local MinIO endpoint
                return 'http://localhost:9002';
            }
            // AWS S3 - handled by the API backend
            return null; // API will use AWS SDK with proper credentials
        },
        
        // Feature flags
        features: {
            aiEnabled: true,  // Can be disabled if AI services are not configured
            debugMode: false, // Set to true for additional logging
        },
        
        // Helper function to make API calls with proper error handling
        async apiCall(endpoint, options = {}) {
            const url = this.apiUrl + endpoint;
            
            // Add default headers
            const headers = {
                'Content-Type': 'application/json',
                ...options.headers
            };
            
            // Add auth token if available
            const token = localStorage.getItem('token') || localStorage.getItem('jwt');
            if (token && !headers.Authorization) {
                headers.Authorization = `Bearer ${token}`;
            }
            
            try {
                const response = await fetch(url, {
                    ...options,
                    headers
                });
                
                if (!response.ok) {
                    // Log error details for debugging
                    if (this.features.debugMode) {
                        console.error(`API call failed: ${response.status} ${response.statusText}`);
                        console.error('URL:', url);
                        console.error('Response:', await response.text());
                    }
                    
                    // Handle specific error codes
                    if (response.status === 401) {
                        // Unauthorized - redirect to login
                        console.error('Authentication failed - redirecting to login');
                        // Don't redirect if we're already on login page
                        if (!window.location.pathname.includes('login')) {
                            localStorage.removeItem('token');
                            localStorage.removeItem('jwt');
                            window.location.href = '/index.html';
                        }
                    }
                    
                    throw new Error(`API call failed: ${response.status} ${response.statusText}`);
                }
                
                return response;
            } catch (error) {
                console.error('API call error:', error);
                throw error;
            }
        },
        
        // Initialize configuration
        init() {
            // Log configuration for debugging
            console.log('VeriCase Configuration:');
            console.log('- Environment:', this.isDevelopment ? 'Development' : 'Production');
            console.log('- API URL:', this.apiUrl);
            console.log('- Storage Endpoint:', this.storageEndpoint || 'AWS S3 (backend managed)');
            
            // Check if we're on AWS and need to use HTTPS
            if (this.isProduction && window.location.protocol === 'http:') {
                console.warn('Running on HTTP in production - consider using HTTPS');
            }
            
            // Set up global error handler for network issues
            window.addEventListener('unhandledrejection', event => {
                if (event.reason && event.reason.message && event.reason.message.includes('fetch')) {
                    console.error('Network error detected:', event.reason);
                    // Could show a user-friendly error message here
                }
            });
        }
    };
    
    // Initialize on load
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => VeriCaseConfig.init());
    } else {
        VeriCaseConfig.init();
    }
})();
