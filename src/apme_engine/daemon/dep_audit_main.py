"""Run the Python Dependency Auditor gRPC server."""

import asyncio
import os
import sys
import traceback

from apme_engine.daemon.dep_audit_server import serve


async def _run(listen: str) -> None:
    server = await serve(listen)
    sys.stderr.write(f"Dep audit validator listening on {listen}\n")
    sys.stderr.flush()
    await server.wait_for_termination()


def main() -> None:
    """Entry point: run dep audit validator gRPC server until interrupted.

    Uses APME_DEP_AUDIT_VALIDATOR_LISTEN for bind address. Exits with code 1 on failure.
    """
    from apme_engine.log_bridge import install_handler

    install_handler()

    listen = os.environ.get("APME_DEP_AUDIT_VALIDATOR_LISTEN", "0.0.0.0:50059")
    try:
        asyncio.run(_run(listen))
    except Exception as e:
        sys.stderr.write(f"Dep audit validator failed: {e}\n")
        traceback.print_exc(file=sys.stderr)
        sys.stderr.flush()
        sys.exit(1)


if __name__ == "__main__":
    main()
