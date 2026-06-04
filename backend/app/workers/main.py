"""Worker entry — arq plus a no-op health server for hosts that need an open port."""

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from arq import run_worker

from app.workers.config import WorkerSettings

HEALTH_PORT = 7860


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')

    def log_message(self, *_: object) -> None:
        return


def _serve_health(port: int = HEALTH_PORT) -> None:
    HTTPServer(("0.0.0.0", port), _HealthHandler).serve_forever()


def main() -> None:
    threading.Thread(target=_serve_health, daemon=True).start()
    run_worker(WorkerSettings)  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
