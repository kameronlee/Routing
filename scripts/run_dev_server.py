"""Launch the FastAPI app with file-backed logs for local development."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import traceback

import uvicorn


def main() -> None:
    """Run the API server, redirecting logs when launched without a console."""

    root = Path(__file__).resolve().parents[1]
    stdout_log = root / "devserver.log"
    stderr_log = root / "devserver.err.log"

    with stdout_log.open("a", encoding="utf-8") as stdout, stderr_log.open(
        "a",
        encoding="utf-8",
    ) as stderr:
        sys.stdout = stdout
        sys.stderr = stderr
        try:
            uvicorn.run(
                "routing_backend.api:app",
                host=os.getenv("ROUTING_HOST", "127.0.0.1"),
                port=int(os.getenv("ROUTING_PORT", "8000")),
                log_level=os.getenv("ROUTING_LOG_LEVEL", "info"),
            )
        except Exception:
            traceback.print_exc(file=stderr)
            stderr.flush()
            raise


if __name__ == "__main__":
    main()
