#!/usr/bin/env python3
"""
VeriCase API Key Validator
Checks all configured API keys and secrets for validity.
"""

import os
import requests
import boto3
from dotenv import load_dotenv
import sys

# Load environment variables
load_dotenv()


def check_openai():
    """Check OpenAI API key"""
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return "❌ OPENAI_API_KEY not set"

    try:
        response = requests.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
        )
        return (
            "✅ OpenAI key valid"
            if response.status_code == 200
            else f"❌ OpenAI key invalid ({response.status_code})"
        )
    except Exception as e:
        return f"❌ OpenAI check failed: {str(e)}"


def check_anthropic():
    """Check Anthropic/Claude API key"""
    key = os.getenv("CLAUDE_API_KEY")
    if not key:
        return "❌ CLAUDE_API_KEY not set"

    try:
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-3-haiku-20240307",
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "test"}],
            },
            timeout=10,
        )
        return (
            "✅ Claude key valid"
            if response.status_code in [200, 400]
            else f"❌ Claude key invalid ({response.status_code})"
        )
    except Exception as e:
        return f"❌ Claude check failed: {str(e)}"


def check_gemini():
    """Check Google Gemini API key"""
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return "❌ GEMINI_API_KEY not set"

    try:
        response = requests.get(
            f"https://generativelanguage.googleapis.com/v1beta/models?key={key}",
            timeout=10,
        )
        return (
            "✅ Gemini key valid"
            if response.status_code == 200
            else f"❌ Gemini key invalid ({response.status_code})"
        )
    except Exception as e:
        return f"❌ Gemini check failed: {str(e)}"


def check_xai():
    """Check xAI/Grok API key"""
    key = os.getenv("XAI_API_KEY") or os.getenv("GROK_API_KEY")
    if not key:
        return "❌ XAI_API_KEY/GROK_API_KEY not set"

    try:
        response = requests.get(
            "https://api.x.ai/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
        )
        return (
            "✅ xAI key valid"
            if response.status_code == 200
            else f"❌ xAI key invalid ({response.status_code})"
        )
    except Exception as e:
        return f"❌ xAI check failed: {str(e)}"


def check_perplexity():
    """Check Perplexity API key"""
    key = os.getenv("PERPLEXITY_API_KEY")
    if not key:
        return "❌ PERPLEXITY_API_KEY not set"

    try:
        response = requests.post(
            "https://api.perplexity.ai/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "llama-3.1-sonar-small-128k-online",
                "messages": [{"role": "user", "content": "test"}],
                "max_tokens": 1,
            },
            timeout=10,
        )
        return (
            "✅ Perplexity key valid"
            if response.status_code in [200, 400]
            else f"❌ Perplexity key invalid ({response.status_code})"
        )
    except Exception as e:
        return f"❌ Perplexity check failed: {str(e)}"


def check_aws_bedrock():
    """Check AWS Bedrock access"""
    if not os.getenv("BEDROCK_ENABLED", "").lower() == "true":
        return "⚠️  Bedrock disabled"

    try:
        client = boto3.client(
            "bedrock", region_name=os.getenv("AWS_REGION", "eu-west-2")
        )
        client.list_foundation_models()
        return "✅ AWS Bedrock accessible"
    except Exception as e:
        return f"❌ AWS Bedrock failed: {str(e)}"


def check_jwt_secret():
    """Check JWT secret strength"""
    secret = os.getenv("JWT_SECRET")
    if not secret:
        return "❌ JWT_SECRET not set"
    if len(secret) < 32:
        return "⚠️  JWT_SECRET too short (< 32 chars)"
    if secret == "REPLACE_WITH_SECURE_64_CHAR_SECRET__openssl_rand_-base64_48":
        return "❌ JWT_SECRET is default template value"
    return "✅ JWT_SECRET configured"


def main():
    """Run all API key checks"""
    print("🔐 VeriCase API Key Validator")
    print("=" * 40)

    checks = [
        ("OpenAI", check_openai),
        ("Anthropic/Claude", check_anthropic),
        ("Google Gemini", check_gemini),
        ("xAI/Grok", check_xai),
        ("Perplexity", check_perplexity),
        ("AWS Bedrock", check_aws_bedrock),
        ("JWT Secret", check_jwt_secret),
    ]

    results = []
    for name, check_func in checks:
        print(f"Checking {name}...")
        result = check_func()
        results.append((name, result))
        print(f"  {result}")

    print("\n" + "=" * 40)
    print("📊 SUMMARY:")

    valid_count = sum(1 for _, result in results if result.startswith("✅"))
    total_count = len(results)

    for name, result in results:
        print(f"  {result}")

    print(f"\n✅ {valid_count}/{total_count} services configured correctly")

    if valid_count < total_count:
        print("\n⚠️  Some API keys need attention. Check your .env file.")
        sys.exit(1)
    else:
        print("\n🎉 All API keys are valid!")


if __name__ == "__main__":
    main()
