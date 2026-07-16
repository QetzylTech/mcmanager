from __future__ import annotations

import argparse
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parent
TEMPLATES_DIR = ROOT / "templates"
FRAGMENTS_DIR = TEMPLATES_DIR / "fragments"
STATIC_DIR = ROOT / "static"


class PrototypeHandler(BaseHTTPRequestHandler):
    server_version = "MCPrototype/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        route = parsed.path

        if route == "/":
            self.serve_file(TEMPLATES_DIR / "app_shell.html")
            return
        if route == "/setup":
            self.serve_file(TEMPLATES_DIR / "setup.html")
            return
        if route.startswith("/fragments/"):
            relative = route.removeprefix("/fragments/")
            self.serve_safe(FRAGMENTS_DIR, relative)
            return
        if route.startswith("/static/"):
            relative = route.removeprefix("/static/")
            self.serve_safe(STATIC_DIR, relative)
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Page not found")

    def log_message(self, fmt: str, *args: object) -> None:
        print(
            "%s - - [%s] %s"
            % (self.address_string(), self.log_date_time_string(), fmt % args)
        )

    def serve_safe(self, base_dir: Path, relative: str) -> None:
        relative_path = Path(unquote(relative))
        candidate = (base_dir / relative_path).resolve()
        try:
            candidate.relative_to(base_dir.resolve())
        except ValueError:
            self.send_error(HTTPStatus.FORBIDDEN, "Forbidden path")
            return
        self.serve_file(candidate)

    def serve_file(self, file_path: Path) -> None:
        if not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return

        ctype, _ = mimetypes.guess_type(str(file_path))
        if not ctype:
            ctype = "application/octet-stream"

        data = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Serve the local UI prototype on localhost."
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to.")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    server = ThreadingHTTPServer((args.host, args.port), PrototypeHandler)
    url = f"http://{args.host}:{args.port}/"
    print(f"Serving prototype at {url}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down prototype server...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
