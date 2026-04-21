"""GitHub SCM provider — Phase 1 of ADR-050.

Uses the GitHub REST API v3 for branch creation, file push (via the
Git Trees/Commits API for atomic multi-file commits), and PR creation.
Supports both ``github.com`` and GitHub Enterprise Server via a
configurable ``api_base_url``.
"""

from __future__ import annotations

import base64
import logging
import os
import ssl
from urllib.parse import urlparse

import httpx

from apme_gateway.scm.base import PullRequestResult

logger = logging.getLogger(__name__)


def _custom_ca_bundle() -> str:
    """Return the configured custom CA bundle path, if any.

    Returns:
        Absolute CA bundle path when configured, else an empty string.
    """
    for key in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        candidate = os.environ.get(key, "").strip()
        if candidate:
            return candidate
    return ""


def _http_verify() -> ssl.SSLContext | bool:
    """Return TLS verification settings for outbound HTTPS.

    The gateway may run behind a corporate TLS intercept or use an internal CA.
    In that case ``up.sh`` injects one or more standard CA environment variables
    into the container. ``httpx`` is given the resolved bundle path explicitly so
    SCM API calls trust both the platform store and the custom corporate root.

    Returns:
        SSL context with system roots plus the configured custom bundle, else
        ``True`` for the default platform trust store.
    """
    custom_bundle = _custom_ca_bundle()
    if not custom_bundle:
        return True

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.verify_mode = ssl.CERT_REQUIRED
    context.check_hostname = True
    context.load_default_certs(ssl.Purpose.SERVER_AUTH)
    context.load_verify_locations(cafile=custom_bundle)
    return context


def _parse_owner_repo(repo_url: str) -> tuple[str, str]:
    """Extract ``(owner, repo)`` from an HTTPS clone URL.

    Args:
        repo_url: HTTPS URL like ``https://github.com/owner/repo.git``.

    Returns:
        Tuple of (owner, repo) with ``.git`` suffix stripped.

    Raises:
        ValueError: If the URL cannot be parsed.
    """
    parsed = urlparse(repo_url)
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(parts) < 2:
        msg = f"Cannot extract owner/repo from URL: {repo_url}"
        raise ValueError(msg)
    owner = parts[0]
    repo = parts[1].removesuffix(".git")
    return owner, repo


class GitHubProvider:
    """GitHub REST API v3 implementation of :class:`ScmProvider`."""

    def __init__(self, api_base_url: str = "https://api.github.com") -> None:
        """Store the API base URL for subsequent requests.

        Args:
            api_base_url: Base URL for the GitHub API.
        """
        self._api = api_base_url.rstrip("/")

    def _headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    @staticmethod
    def _client(*, timeout: float) -> httpx.AsyncClient:
        """Build an HTTP client with the configured CA bundle.

        Args:
            timeout: Request timeout in seconds.

        Returns:
            Configured ``httpx.AsyncClient`` instance.
        """
        return httpx.AsyncClient(timeout=timeout, verify=_http_verify())

    async def create_branch(
        self,
        repo_url: str,
        base_branch: str,
        new_branch: str,
        token: str,
    ) -> None:
        """Create a Git ref for *new_branch* from the HEAD of *base_branch*.

        Args:
            repo_url: HTTPS clone URL.
            base_branch: Source branch.
            new_branch: New branch name.
            token: GitHub PAT or app installation token.
        """
        owner, repo = _parse_owner_repo(repo_url)
        async with self._client(timeout=30) as client:
            ref_resp = await client.get(
                f"{self._api}/repos/{owner}/{repo}/git/ref/heads/{base_branch}",
                headers=self._headers(token),
            )
            ref_resp.raise_for_status()
            sha = ref_resp.json()["object"]["sha"]

            create_resp = await client.post(
                f"{self._api}/repos/{owner}/{repo}/git/refs",
                headers=self._headers(token),
                json={"ref": f"refs/heads/{new_branch}", "sha": sha},
            )
            create_resp.raise_for_status()
        logger.info("Created branch %s from %s@%s on %s/%s", new_branch, base_branch, sha[:8], owner, repo)

    async def push_files(
        self,
        repo_url: str,
        branch: str,
        files: dict[str, bytes],
        commit_message: str,
        token: str,
    ) -> str:
        """Push files atomically via the Git Trees + Commits API.

        Args:
            repo_url: HTTPS clone URL.
            branch: Target branch.
            files: Mapping of path → content.
            commit_message: Commit message.
            token: GitHub PAT.

        Returns:
            SHA of the new commit.
        """
        owner, repo = _parse_owner_repo(repo_url)
        async with self._client(timeout=60) as client:
            headers = self._headers(token)

            ref_resp = await client.get(
                f"{self._api}/repos/{owner}/{repo}/git/ref/heads/{branch}",
                headers=headers,
            )
            ref_resp.raise_for_status()
            commit_sha_head = ref_resp.json()["object"]["sha"]

            commit_detail = await client.get(
                f"{self._api}/repos/{owner}/{repo}/git/commits/{commit_sha_head}",
                headers=headers,
            )
            commit_detail.raise_for_status()
            base_tree_sha = commit_detail.json()["tree"]["sha"]

            tree_items = []
            for path, content in files.items():
                if _is_text(content):
                    blob_json = {"content": content.decode("utf-8"), "encoding": "utf-8"}
                else:
                    blob_json = {"content": base64.b64encode(content).decode(), "encoding": "base64"}

                blob_resp = await client.post(
                    f"{self._api}/repos/{owner}/{repo}/git/blobs",
                    headers=headers,
                    json=blob_json,
                )
                blob_resp.raise_for_status()
                tree_items.append(
                    {
                        "path": path,
                        "mode": "100644",
                        "type": "blob",
                        "sha": blob_resp.json()["sha"],
                    }
                )

            tree_resp = await client.post(
                f"{self._api}/repos/{owner}/{repo}/git/trees",
                headers=headers,
                json={"base_tree": base_tree_sha, "tree": tree_items},
            )
            tree_resp.raise_for_status()
            tree_sha = tree_resp.json()["sha"]

            commit_resp = await client.post(
                f"{self._api}/repos/{owner}/{repo}/git/commits",
                headers=headers,
                json={
                    "message": commit_message,
                    "tree": tree_sha,
                    "parents": [commit_sha_head],
                },
            )
            commit_resp.raise_for_status()
            commit_sha: str = commit_resp.json()["sha"]

            update_resp = await client.patch(
                f"{self._api}/repos/{owner}/{repo}/git/refs/heads/{branch}",
                headers=headers,
                json={"sha": commit_sha},
            )
            update_resp.raise_for_status()

        logger.info("Pushed %d files to %s/%s@%s (%s)", len(files), owner, repo, branch, commit_sha[:8])
        return commit_sha

    async def create_pull_request(
        self,
        repo_url: str,
        base_branch: str,
        head_branch: str,
        title: str,
        body: str,
        token: str,
    ) -> PullRequestResult:
        """Create a pull request via the GitHub Pulls API.

        Args:
            repo_url: HTTPS clone URL.
            base_branch: Target branch.
            head_branch: Source branch.
            title: PR title.
            body: PR body.
            token: GitHub PAT.

        Returns:
            PullRequestResult with the URL.
        """
        owner, repo = _parse_owner_repo(repo_url)
        async with self._client(timeout=30) as client:
            resp = await client.post(
                f"{self._api}/repos/{owner}/{repo}/pulls",
                headers=self._headers(token),
                json={
                    "title": title,
                    "body": body,
                    "head": head_branch,
                    "base": base_branch,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        pr_url = data["html_url"]
        logger.info("Created PR %s on %s/%s", pr_url, owner, repo)
        return PullRequestResult(pr_url=pr_url, branch_name=head_branch, provider="github")


def _is_text(data: bytes) -> bool:
    """Heuristic: treat content as text if it decodes as UTF-8 without errors.

    Args:
        data: Raw bytes to check.

    Returns:
        True if the data is valid UTF-8 text.
    """
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True
