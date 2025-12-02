"""Phi-4 client for VeriCase AI integration"""

import httpx
import json
import logging
from typing import Dict, Any, Optional, AsyncGenerator
from .config import settings

logger = logging.getLogger(__name__)


class PhiClient:
    """Client for Phi-4 model running on EC2 via Ollama"""

    def __init__(self):
        self.endpoint = getattr(settings, "PHI_ENDPOINT", "http://localhost:11434")
        self.model = getattr(settings, "PHI_MODEL", "phi4:latest")
        self.enabled = getattr(settings, "PHI_ENABLED", False)

    async def is_available(self) -> bool:
        """Check if Phi-4 service is available"""
        if not self.enabled:
            return False

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.endpoint}/api/tags")
                if response.status_code == 200:
                    models = response.json().get("models", [])
                    return any(model["name"] == self.model for model in models)
        except Exception as e:
            logger.warning(f"Phi-4 availability check failed: {e}")
        return False

    async def chat(self, message: str, context: Optional[str] = None) -> str:
        """Send chat message to Phi-4"""
        if not await self.is_available():
            raise Exception("Phi-4 service not available")

        prompt = message
        if context:
            prompt = f"Context: {context}\n\nQuestion: {message}"

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.7, "top_p": 0.9, "max_tokens": 2000},
        }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.endpoint}/api/generate", json=payload
                )
                response.raise_for_status()
                result = response.json()
                return result.get("response", "No response generated")

        except Exception as e:
            logger.error(f"Phi-4 chat error: {e}")
            raise Exception(f"Phi-4 request failed: {str(e)}")

    async def analyze_document(
        self, content: str, analysis_type: str = "summary"
    ) -> Dict[str, Any]:
        """Analyze document content with Phi-4"""
        prompts = {
            "summary": "Provide a concise summary of this document, highlighting key points:",
            "entities": "Extract key entities (people, dates, amounts, locations) from this document:",
            "legal_analysis": "Analyze this document for legal implications, risks, and important clauses:",
            "timeline": "Extract chronological events and dates from this document:",
        }

        prompt = prompts.get(analysis_type, prompts["summary"])
        full_prompt = f"{prompt}\n\nDocument:\n{content[:4000]}"  # Limit content length

        response = await self.chat(full_prompt)

        return {
            "analysis_type": analysis_type,
            "model": "phi4",
            "response": response,
            "content_length": len(content),
        }

    async def stream_chat(
        self, message: str, context: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """Stream chat response from Phi-4"""
        if not await self.is_available():
            raise Exception("Phi-4 service not available")

        prompt = message
        if context:
            prompt = f"Context: {context}\n\nQuestion: {message}"

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": True,
            "options": {"temperature": 0.7, "top_p": 0.9, "max_tokens": 2000},
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST", f"{self.endpoint}/api/generate", json=payload
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line.strip():
                            try:
                                data = json.loads(line)
                                if "response" in data:
                                    yield data["response"]
                                if data.get("done", False):
                                    break
                            except json.JSONDecodeError:
                                continue

        except Exception as e:
            logger.error(f"Phi-4 streaming error: {e}")
            raise Exception(f"Phi-4 streaming failed: {str(e)}")


# Global instance
phi_client = PhiClient()
