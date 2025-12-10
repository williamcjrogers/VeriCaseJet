"""HTTP API client for VeriCase backend integration."""

import logging
from typing import Any, Optional
from contextlib import asynccontextmanager

import httpx

from .config import settings

logger = logging.getLogger(__name__)


class VeriCaseAPIError(Exception):
    """Custom exception for VeriCase API errors."""

    def __init__(self, status_code: int, message: str, details: Optional[dict] = None):
        self.status_code = status_code
        self.message = message
        self.details = details or {}
        super().__init__(f"API Error {status_code}: {message}")


class VeriCaseAPI:
    """Async HTTP client for VeriCase API interactions."""

    def __init__(self, base_url: Optional[str] = None, token: Optional[str] = None):
        self.base_url = (base_url or settings.api_base_url).rstrip("/")
        self._token = token or settings.jwt_token
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def headers(self) -> dict:
        """Get default headers for requests."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        elif settings.api_key:
            headers["X-API-Key"] = settings.api_key
        return headers

    @asynccontextmanager
    async def get_client(self):
        """Get or create an async HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=self.headers,
                timeout=httpx.Timeout(settings.request_timeout),
            )
        try:
            yield self._client
        except Exception:
            raise

    async def close(self):
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _handle_response(self, response: httpx.Response) -> Any:
        """Handle API response and raise appropriate errors."""
        if response.status_code >= 400:
            try:
                error_data = response.json()
                message = error_data.get("detail", str(error_data))
            except Exception:
                message = response.text or f"HTTP {response.status_code}"
            raise VeriCaseAPIError(response.status_code, message)

        if response.status_code == 204:
            return None

        try:
            return response.json()
        except Exception:
            return response.text

    async def get(
        self, endpoint: str, params: Optional[dict] = None
    ) -> Any:
        """Make a GET request to the API."""
        async with self.get_client() as client:
            response = await client.get(endpoint, params=params)
            return await self._handle_response(response)

    async def post(
        self, endpoint: str, data: Optional[dict] = None, params: Optional[dict] = None
    ) -> Any:
        """Make a POST request to the API."""
        async with self.get_client() as client:
            response = await client.post(endpoint, json=data, params=params)
            return await self._handle_response(response)

    async def put(
        self, endpoint: str, data: Optional[dict] = None
    ) -> Any:
        """Make a PUT request to the API."""
        async with self.get_client() as client:
            response = await client.put(endpoint, json=data)
            return await self._handle_response(response)

    async def patch(
        self, endpoint: str, data: Optional[dict] = None
    ) -> Any:
        """Make a PATCH request to the API."""
        async with self.get_client() as client:
            response = await client.patch(endpoint, json=data)
            return await self._handle_response(response)

    async def delete(self, endpoint: str) -> Any:
        """Make a DELETE request to the API."""
        async with self.get_client() as client:
            response = await client.delete(endpoint)
            return await self._handle_response(response)

    # Authentication methods
    async def login(self, username: str, password: str) -> dict:
        """Authenticate and get JWT token."""
        async with self.get_client() as client:
            response = await client.post(
                "/api/auth/login",
                data={"username": username, "password": password},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            result = await self._handle_response(response)
            if "access_token" in result:
                self._token = result["access_token"]
            return result

    async def get_current_user(self) -> dict:
        """Get current authenticated user info."""
        return await self.get("/api/users/me")

    # Health check
    async def health_check(self) -> dict:
        """Check API health status."""
        return await self.get("/api/health")


# Global API client instance
api_client = VeriCaseAPI()
