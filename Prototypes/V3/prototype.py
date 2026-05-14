from __future__ import annotations

import os
from pathlib import Path
from typing import Final

from flask import Flask, abort, redirect, request, send_from_directory

ROOT: Final[Path] = Path(__file__).resolve().parent
STATIC_DIR: Final[Path] = ROOT / "static"

# Serve these HTML files directly from Prototypes/V2/
ALLOWED_PAGES: Final[set[str]] = {
    "index.html",
    "manager_worlds.html",
    "setup.html",
    "manager_settings.html",
    "user_management.html",
    "maintenance_retention.html",
    "instructions_documentation.html",
    "system_logs.html",
    "audit_history.html",
    "offsite_sync.html",
    "manager_maintenance.html",
    "world_templates.html",
    "world_main.html",
    "world_backup_restore.html",
    "world_logs.html",
    "file_manager.html",
    "world_maintenance_retention.html",
    "world_setup.html",
    "world_properties.html",
}

app = Flask(__name__, static_folder=str(STATIC_DIR))


@app.get("/")
def home() -> object:
    return redirect("/index.html", code=302)


@app.get("/static/<path:filename>")
def static_files(filename: str) -> object:
    # Flask already handles this, but we keep it explicit for clarity.
    return send_from_directory(str(STATIC_DIR), filename)


def load_html_text(page: str) -> str:
    file_path = ROOT / page
    return file_path.read_text(encoding="utf-8")


@app.get("/<path:page>")
def pages(page: str) -> object:
    # Only serve explicitly listed prototype pages.
    # Prevents path traversal / accidental file serving.
    if page not in ALLOWED_PAGES:
        abort(404)

    # Minimal server-side personalization for world context:
    # manager links go to world pages like: world_main.html?world=Example%20World
    # We replace placeholder "Example World" occurrences in world_* pages.
    world = request.args.get("world")
    if world and page.startswith("world_"):
        html = load_html_text(page)
        html = html.replace("Example World", world)
        return app.response_class(html, mimetype="text/html")

    return send_from_directory(str(ROOT), page)


if __name__ == "__main__":
    # Non-interactive, safe defaults for local prototype testing.
    host = os.environ.get("MCWEB_HOST", "127.0.0.1")
    port = int(os.environ.get("MCWEB_PORT", "8002"))
    app.run(host=host, port=port, debug=False)
