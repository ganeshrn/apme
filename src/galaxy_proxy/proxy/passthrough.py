"""PyPI passthrough for non-collection packages."""

from __future__ import annotations

import httpx

DEFAULT_PYPI_URL = "https://pypi.org"


class PyPIPassthrough:
    """Forwards Simple API requests to an upstream PyPI server."""

    def __init__(self, pypi_url: str = DEFAULT_PYPI_URL, timeout: float = 15.0) -> None:
        """Initialise with upstream PyPI base URL."""
        self._client = httpx.AsyncClient(
            base_url=pypi_url.rstrip("/"),
            timeout=timeout,
            follow_redirects=True,
        )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def fetch_project_page(self, package_name: str) -> tuple[str, int]:
        """Fetch a project's Simple API page from upstream PyPI.

        Returns:
            Tuple of (html_content, status_code).
        """
        resp = await self._client.get(
            f"/simple/{package_name}/",
            headers={"Accept": "text/html"},
        )
        return resp.text, resp.status_code
