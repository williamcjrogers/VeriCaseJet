#!/usr/bin/env python3
"""Test Bedrock connection"""
import boto3
import json

def test_bedrock():
    try:
        bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')
        
        # Test Claude 3 Haiku
        response = bedrock.invoke_model(
            modelId='anthropic.claude-3-haiku-20240307-v1:0',
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 100,
                "messages": [{"role": "user", "content": "Hello, are you working?"}]
            })
        )
        
        result = json.loads(response['body'].read())
        print("✅ Bedrock Claude 3 Haiku: WORKING")
        print(f"Response: {result['content'][0]['text']}")
        return True
        
    except Exception as e:
        print(f"❌ Bedrock test failed: {e}")
        return False

if __name__ == "__main__":
    test_bedrock()