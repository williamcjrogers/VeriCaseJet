#!/usr/bin/env python3
"""Test the enhanced authentication flows"""
import requests
import json
import time

API_URL = "http://localhost:8010"

def test_login_with_security():
    """Test the enhanced login endpoint with security features"""
    print("\n=== Testing Enhanced Login ===")
    
    # Test successful login
    response = requests.post(f"{API_URL}/api/auth/login-secure", json={
        "email": "test@vericase.com",
        "password": "password",
        "remember_me": True
    })
    
    if response.status_code == 200:
        data = response.json()
        print("✓ Login successful")
        print(f"  Token: {data['access_token'][:20]}...")
        print(f"  User: {data['user']['email']}")
        print(f"  Email Verified: {data['user'].get('email_verified', 'N/A')}")
        return data['access_token']
    else:
        print(f"✗ Login failed: {response.status_code}")
        print(f"  Error: {response.text}")
        return None

def test_password_strength():
    """Test password strength endpoint"""
    print("\n=== Testing Password Strength ===")
    
    passwords = [
        "weak",
        "Weak123",
        "Weak123!",
        "VeryStrongPassword123!"
    ]
    
    for password in passwords:
        response = requests.post(f"{API_URL}/api/auth/check-password-strength", 
                               json=password)
        if response.status_code == 200:
            data = response.json()
            print(f"✓ Password: {password}")
            print(f"  Strength: {data['strength']} (Score: {data['score']})")
            print(f"  Valid: {data['valid']}")
            if data['errors']:
                print(f"  Issues: {', '.join(data['errors'])}")
        else:
            print(f"✗ Failed to check password: {password}")

def test_sessions(token):
    """Test session management"""
    print("\n=== Testing Session Management ===")
    
    headers = {"Authorization": f"Bearer {token}"}
    
    # List sessions
    response = requests.get(f"{API_URL}/api/auth/sessions", headers=headers)
    if response.status_code == 200:
        data = response.json()
        print(f"✓ Found {len(data['sessions'])} active session(s)")
        for session in data['sessions']:
            print(f"  - Session {session['id'][:8]}...")
            print(f"    IP: {session['ip_address']}")
            print(f"    Created: {session['created_at']}")
    else:
        print(f"✗ Failed to list sessions: {response.status_code}")

def test_password_reset():
    """Test password reset flow"""
    print("\n=== Testing Password Reset ===")
    
    # Request reset
    response = requests.post(f"{API_URL}/api/auth/request-reset", json={
        "email": "test@vericase.com"
    })
    
    if response.status_code == 200:
        data = response.json()
        print("✓ Password reset requested")
        print(f"  Message: {data['message']}")
    else:
        print(f"✗ Failed to request reset: {response.status_code}")

def test_logout(token):
    """Test logout"""
    print("\n=== Testing Logout ===")
    
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.post(f"{API_URL}/api/auth/logout", headers=headers)
    
    if response.status_code == 200:
        print("✓ Logout successful")
        
        # Try to use token after logout
        response = requests.get(f"{API_URL}/api/auth/sessions", headers=headers)
        if response.status_code == 401:
            print("✓ Token correctly invalidated")
        else:
            print("✗ Token still valid after logout!")
    else:
        print(f"✗ Logout failed: {response.status_code}")

def test_rate_limiting():
    """Test rate limiting on login"""
    print("\n=== Testing Rate Limiting ===")
    
    # Try multiple failed logins
    for i in range(7):
        response = requests.post(f"{API_URL}/api/auth/login-secure", json={
            "email": "test@vericase.com",
            "password": "wrongpassword"
        })
        
        if response.status_code == 429:
            print(f"✓ Rate limited after {i} attempts")
            break
        elif response.status_code == 403:
            data = response.json()
            print(f"✓ Account locked: {data['detail']}")
            break
        else:
            print(f"  Attempt {i+1}: {response.status_code}")

def main():
    """Run all tests"""
    print("VeriCase Enhanced Authentication Test Suite")
    print("=" * 50)
    
    # Test login
    token = test_login_with_security()
    
    if token:
        # Test other features
        test_password_strength()
        test_sessions(token)
        test_password_reset()
        test_logout(token)
    
    # Test rate limiting (do this last as it might lock the account)
    test_rate_limiting()
    
    print("\n" + "=" * 50)
    print("Test suite complete!")

if __name__ == "__main__":
    main()
