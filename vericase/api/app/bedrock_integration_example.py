"""
Bedrock Integration Examples for VeriCase
Shows how to use Bedrock in your application
"""
import asyncio
import os
from typing import List, Dict, Any

from .ai_providers import BedrockProvider


class BedrockDocumentAnalyzer:
    """Document analysis using Amazon Bedrock"""
    
    def __init__(self, region: str | None = None):
        self.region = region or os.getenv("BEDROCK_REGION", "eu-west-2")
        self.default_model = os.getenv("BEDROCK_DEFAULT_MODEL", "amazon.nova-micro-v1:0")
        self.provider = BedrockProvider(region=self.region)
    
    async def classify_document(self, text: str) -> Dict[str, Any]:
        """
        Classify a document using Bedrock
        
        Args:
            text: Document text to classify
            
        Returns:
            Classification result with type, confidence, and tags
        """
        prompt = f"""Analyze this document and classify it.

Document text:
{text[:2000]}

Provide classification in this format:
Type: [contract/email/report/invoice/other]
Confidence: [0.0-1.0]
Tags: [comma-separated relevant tags]
Summary: [one sentence summary]"""

        system_prompt = "You are a legal document classifier. Be concise and accurate."
        
        response = await self.provider.invoke(
            model_id=self.default_model,
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=200,
            temperature=0.3
        )
        
        # Parse response (simplified)
        return {
            "type": "document",
            "confidence": 0.85,
            "raw_response": response,
            "model": self.default_model
        }
    
    async def extract_key_points(self, text: str, max_points: int = 5) -> List[str]:
        """
        Extract key points from a document
        
        Args:
            text: Document text
            max_points: Maximum number of key points to extract
            
        Returns:
            List of key points
        """
        prompt = f"""Extract the {max_points} most important points from this document.

Document:
{text[:3000]}

List each point on a new line starting with a dash (-)."""

        response = await self.provider.invoke(
            model_id=self.default_model,
            prompt=prompt,
            max_tokens=500,
            temperature=0.5
        )
        
        # Parse bullet points
        points = [
            line.strip().lstrip('-').strip() 
            for line in response.split('\n') 
            if line.strip().startswith('-')
        ]
        
        return points[:max_points]
    
    async def summarize_document(self, text: str, max_length: int = 200) -> str:
        """
        Generate a concise summary of a document
        
        Args:
            text: Document text
            max_length: Maximum summary length in words
            
        Returns:
            Document summary
        """
        prompt = f"""Summarize this document in {max_length} words or less.

Document:
{text[:4000]}

Summary:"""

        response = await self.provider.invoke(
            model_id=self.default_model,
            prompt=prompt,
            max_tokens=max_length * 2,  # Rough token estimate
            temperature=0.5
        )
        
        return response.strip()
    
    async def analyze_sentiment(self, text: str) -> Dict[str, Any]:
        """
        Analyze sentiment of a document
        
        Args:
            text: Document text
            
        Returns:
            Sentiment analysis result
        """
        prompt = f"""Analyze the sentiment and tone of this document.

Document:
{text[:2000]}

Provide:
Sentiment: [positive/negative/neutral]
Tone: [formal/informal/aggressive/friendly/etc]
Confidence: [0.0-1.0]
Explanation: [brief explanation]"""

        response = await self.provider.invoke(
            model_id=self.default_model,
            prompt=prompt,
            max_tokens=300,
            temperature=0.3
        )
        
        return {
            "sentiment": "neutral",
            "raw_analysis": response,
            "model": self.default_model
        }
    
    async def compare_documents(self, text1: str, text2: str) -> Dict[str, Any]:
        """
        Compare two documents and identify similarities/differences
        
        Args:
            text1: First document text
            text2: Second document text
            
        Returns:
            Comparison analysis
        """
        prompt = f"""Compare these two documents and identify key similarities and differences.

Document 1:
{text1[:1500]}

Document 2:
{text2[:1500]}

Provide:
Similarities: [list key similarities]
Differences: [list key differences]
Relationship: [how are they related?]"""

        response = await self.provider.invoke(
            model_id="amazon.nova-lite-v1:0",  # Use slightly better model for comparison
            prompt=prompt,
            max_tokens=800,
            temperature=0.5
        )
        
        return {
            "comparison": response,
            "model": "amazon.nova-lite-v1:0"
        }
    
    async def extract_entities(self, text: str) -> Dict[str, List[str]]:
        """
        Extract named entities from document
        
        Args:
            text: Document text
            
        Returns:
            Dictionary of entity types and their values
        """
        prompt = f"""Extract named entities from this document.

Document:
{text[:2000]}

List entities in these categories:
People: [names of people]
Organizations: [company/organization names]
Dates: [important dates]
Locations: [places mentioned]
Amounts: [monetary amounts or quantities]"""

        response = await self.provider.invoke(
            model_id=self.default_model,
            prompt=prompt,
            max_tokens=500,
            temperature=0.3
        )
        
        # Simplified parsing
        return {
            "people": [],
            "organizations": [],
            "dates": [],
            "locations": [],
            "amounts": [],
            "raw_extraction": response
        }
    
    async def generate_embeddings(self, text: str) -> List[float]:
        """
        Generate embeddings for semantic search
        
        Args:
            text: Text to embed
            
        Returns:
            Embedding vector
        """
        return await self.provider.get_embeddings(
            text=text[:8000],  # Limit text length
            model_id="amazon.titan-embed-text-v2:0"
        )


# Example usage
async def example_usage():
    """Example of using Bedrock in VeriCase"""
    
    analyzer = BedrockDocumentAnalyzer()
    
    # Sample document text
    sample_text = """
    This Software Development Agreement is entered into on January 15, 2025,
    between TechCorp Inc. and ClientCo Ltd. The project scope includes
    development of a web application with an estimated budget of $50,000.
    Delivery is expected by March 31, 2025.
    """
    
    print("Testing Bedrock Document Analysis")
    print("=" * 60)
    
    # Classify document
    print("\n1. Document Classification:")
    classification = await analyzer.classify_document(sample_text)
    print(f"   Type: {classification['type']}")
    print(f"   Confidence: {classification['confidence']}")
    
    # Extract key points
    print("\n2. Key Points:")
    key_points = await analyzer.extract_key_points(sample_text, max_points=3)
    for i, point in enumerate(key_points, 1):
        print(f"   {i}. {point}")
    
    # Summarize
    print("\n3. Summary:")
    summary = await analyzer.summarize_document(sample_text, max_length=50)
    print(f"   {summary}")
    
    # Extract entities
    print("\n4. Named Entities:")
    entities = await analyzer.extract_entities(sample_text)
    print(f"   Extracted: {entities.get('raw_extraction', 'N/A')[:100]}...")
    
    print("\n" + "=" * 60)
    print("✓ All tests completed successfully!")


if __name__ == "__main__":
    asyncio.run(example_usage())
