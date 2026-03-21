"""CLI entry point for galaxy-proxy (argparse, no external deps)."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path


def _setup_logging(verbose: int) -> None:
    level = logging.WARNING
    if verbose == 1:
        level = logging.INFO
    elif verbose >= 2:
        level = logging.DEBUG
    logging.basicConfig(
        level=level,
        format="%(levelname)s: %(message)s",
    )


def _parse_galaxy_server(raw: str) -> GalaxyServer:  # noqa: F821
    """Parse a ``--galaxy-server`` value into a :class:`GalaxyServer`.

    Format: ``URL[,token=TOK][,name=LABEL]``

    Args:
        raw: Raw server string from CLI or env var.

    Returns:
        Parsed GalaxyServer instance.
    """
    from galaxy_proxy.galaxy_client import GalaxyServer

    parts = [p.strip() for p in raw.split(",")]
    url = parts[0]
    token: str | None = None
    name: str | None = None
    for part in parts[1:]:
        if part.startswith("token="):
            token = part[len("token=") :]
        elif part.startswith("name="):
            name = part[len("name=") :]
    return GalaxyServer(url=url, token=token, name=name)


def main(argv: list[str] | None = None) -> None:
    """Galaxy proxy entry point."""
    parser = argparse.ArgumentParser(
        prog="galaxy-proxy",
        description="PEP 503 proxy: serve Galaxy collections as Python wheels.",
    )
    parser.add_argument("--port", "-p", type=int, default=8765, help="Port to bind to (default: 8765).")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to (default: 0.0.0.0).")
    parser.add_argument(
        "--galaxy-url",
        default=os.environ.get("GALAXY_URL", "https://galaxy.ansible.com"),
        help="Default Galaxy server URL (env: GALAXY_URL).",
    )
    parser.add_argument(
        "--galaxy-token",
        default=os.environ.get("GALAXY_TOKEN"),
        help="Auth token (env: GALAXY_TOKEN).",
    )
    parser.add_argument(
        "--galaxy-server",
        dest="galaxy_servers",
        action="append",
        default=[],
        help="Upstream Galaxy server: URL[,token=TOK][,name=LABEL]. Repeatable.",
    )
    parser.add_argument("--pypi-url", default="https://pypi.org", help="Upstream PyPI URL for passthrough.")
    parser.add_argument("--cache-dir", type=Path, default=None, help="Wheel cache directory.")
    parser.add_argument("--metadata-ttl", type=int, default=600, help="Metadata cache TTL in seconds.")
    parser.add_argument("--no-passthrough", action="store_true", help="Disable PyPI passthrough.")
    parser.add_argument("-v", "--verbose", action="count", default=0, help="Increase logging verbosity.")

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    import uvicorn

    from galaxy_proxy.galaxy_client import GalaxyServer
    from galaxy_proxy.proxy.server import create_app

    parsed_servers: list[GalaxyServer] | None = None
    if args.galaxy_servers:
        parsed_servers = [_parse_galaxy_server(s) for s in args.galaxy_servers]

    app = create_app(
        galaxy_url=args.galaxy_url,
        galaxy_token=args.galaxy_token,
        pypi_url=args.pypi_url,
        cache_dir=args.cache_dir,
        metadata_ttl=float(args.metadata_ttl),
        enable_passthrough=not args.no_passthrough,
        galaxy_servers=parsed_servers,
    )

    host, port = args.host, args.port
    sys.stderr.write(f"Starting Galaxy Proxy on {host}:{port}\n")
    if parsed_servers:
        for i, srv in enumerate(parsed_servers, 1):
            auth = " (authenticated)" if srv.token else ""
            sys.stderr.write(f"  Galaxy [{i}]: {srv.label()}{auth}\n")
    else:
        sys.stderr.write(f"Galaxy: {args.galaxy_url}\n")
    sys.stderr.write(f"PyPI passthrough: {'disabled' if args.no_passthrough else args.pypi_url}\n")
    sys.stderr.write(f"Cache: {args.cache_dir or '~/.cache/galaxy-proxy'}\n")
    sys.stderr.flush()

    uvicorn.run(app, host=host, port=port, log_level="info" if args.verbose else "warning")


if __name__ == "__main__":
    main()
