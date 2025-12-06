"""
Test Amazon Bedrock Setup
Run this to verify your Bedrock configuration is working
"""
import asyncio
import os
import sys
from pathlib import Path

# Add api directory to path
sys.path.insert(0, str(Path(__file__).parent / "api"))

from dotenv import load_dotenv

# Load environment variables
load_dotenv()


async def test_bedrock():
    """Test Bedrock connection and available models"""
    print("=" * 60)
    print("Amazon Bedrock Setup Test")
    print("=" * 60)
    
    # Check environment
    region = os.getenv("AWS_REGION", "eu-west-2")
    access_key = os.getenv("AWS_ACCESS_KEY_ID", "")
    has_credentials = bool(access_key)
    
    print(f"\n✓ AWS Region: {region}")
    print(f"✓ Credentials: {'Explicit keys' if has_credentials else 'IAM Role/Default chain'}")
    
    # Import Bedrock provider
    try:
        from app.ai_providers import BedrockProvider, bedrock_available
        print("✓ Bedrock provider imported successfully")
    except ImportError as e:
        print(f"✗ Failed to import Bedrock provider: {e}")
        print("\nInstall boto3: pip install boto3")
        return False
    
    # Check if Bedrock is available
    if not bedrock_available():
        print("\n✗ Bedrock not available - check AWS credentials")
        print("\nSetup options:")
        print("1. Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in .env")
        print("2. Configure AWS CLI: aws configure")
        print("3. Use IAM role (for EC2/ECS/Lambda)")
        return False
    
    print("✓ AWS credentials found")
    
    # Initialize provider
    try:
        provider = BedrockProvider(region=region)
        print(f"✓ Bedrock provider initialized")
    except Exception as e:
        print(f"✗ Failed to initialize provider: {e}")
        return False
    
    # List available models
    print("\n" + "=" * 60)
    print("Available Bedrock Models")
    print("=" * 60)
    
    models = provider.get_available_models()
    for model_id, info in models.items():
        print(f"\n{info['name']}")
        print(f"  ID: {model_id}")
        print(f"  Type: {info['type']}")
        print(f"  Provider: {info['provider_family']}")
    
    # Test connection
    print("\n" + "=" * 60)
    print("Testing Connection")
    print("=" * 60)
    
    try:
        result = await provider.test_connection()
        
        if result["success"]:
            print(f"\n✓ Connection successful!")
            print(f"  Model: {result['model']}")
            print(f"  Response: {result['response']}")
            print(f"  Region: {result['region']}")
            return True
        else:
            print(f"\n✗ Connection failed: {result.get('error', 'Unknown error')}")
            return False
            
    except Exception as e:
        print(f"\n✗ Connection test failed: {e}")
        return False


async def test_simple_query():
    """Test a simple AI query"""
    print("\n" + "=" * 60)
    print("Testing Simple Query")
    print("=" * 60)
    
    from app.ai_providers import BedrockProvider
    
    region = os.getenv("AWS_REGION", "eu-west-2")
    provider = BedrockProvider(region=region)
    
    try:
        response = await provider.invoke(
            model_id="amazon.nova-micro-v1:0",
            prompt="What is the capital of France? Answer in one word.",
            max_tokens=50,
            temperature=0
        )
        
        print(f"\nPrompt: What is the capital of France?")
        print(f"Response: {response}")
        print("\n✓ Query successful!")
        return True
        
    except Exception as e:
        print(f"\n✗ Query failed: {e}")
        return False


async def main():
    """Run all tests"""
    success = await test_bedrock()
    
    if success:
        await test_simple_query()
        
        print("\n" + "=" * 60)
        print("Setup Complete! ✓")
        print("=" * 60)
        print("\nNext steps:")
        print("1. Update BEDROCK_DEFAULT_MODEL in .env if needed")
        print("2. Enable AI features in your application")
        print("3. Start using Bedrock models in your code")
    else:
        print("\n" + "=" * 60)
        print("Setup Failed")
        print("=" * 60)
        print("\nTroubleshooting:")
        print("1. Verify AWS credentials are configured")
        print("2. Check IAM permissions for Bedrock access")
        print("3. Ensure boto3 is installed: pip install boto3")
        print("4. Verify region has Bedrock enabled")


if __name__ == "__main__":
    asyncio.run(main())
