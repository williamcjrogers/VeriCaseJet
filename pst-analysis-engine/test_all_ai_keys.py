#!/usr/bin/env python3
"""Quick test script for all AI API keys"""

import requests
import json

# Your VeriCase API endpoint
API_BASE = "http://18.130.216.34:8010"

def test_all_providers():
    """Test all AI providers"""
    
    # You'll need to get your auth token first
    print("Please login first to get your token:")
    print(f"1. Go to {API_BASE}/ui/login.html")
    print("2. Login and check browser dev tools -> Application -> Local Storage -> token")
    print("3. Enter the token below:")
    
    token = input("Enter your auth token: ").strip()
    
    if not token:
        print("No token provided. Exiting.")
        return
    
    headers = {"Authorization": f"Bearer {token}"}
    
    providers = ["openai", "anthropic", "gemini", "grok", "perplexity", "phi"]
    
    print("\n" + "="*50)
    print("TESTING ALL AI PROVIDERS")
    print("="*50)
    
    for provider in providers:
        print(f"\n🧪 Testing {provider.upper()}...")
        
        try:
            response = requests.post(
                f"{API_BASE}/api/ai-chat/models/test/{provider}",
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get("success"):
                    print(f"✅ {provider.upper()}: SUCCESS")
                    print(f"   Model: {result.get('model', 'Unknown')}")
                    print(f"   Response time: {result.get('response_time', 'Unknown')}ms")
                else:
                    print(f"❌ {provider.upper()}: FAILED")
                    print(f"   Error: {result.get('error', 'Unknown error')}")
            else:
                print(f"❌ {provider.upper()}: HTTP {response.status_code}")
                
        except requests.exceptions.Timeout:
            print(f"⏰ {provider.upper()}: TIMEOUT (>30s)")
        except Exception as e:
            print(f"💥 {provider.upper()}: ERROR - {str(e)}")
    
    print("\n" + "="*50)
    print("TEST COMPLETE")
    print("="*50)

if __name__ == "__main__":
    test_all_providers()