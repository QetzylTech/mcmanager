from __future__ import annotations

from flask import Flask

import app.web.api.manager_content as manager_content


def _client():
    app = Flask(__name__)
    app.register_blueprint(manager_content.documentation_bp)
    app.register_blueprint(manager_content.manager_logs_bp)
    app.config["TESTING"] = True
    return app.test_client()


def test_documentation_listing_and_reading_are_rooted_and_sorted(tmp_path, monkeypatch):
    boundary = tmp_path.resolve()
    docs = boundary / "docs"
    (docs / "nested").mkdir(parents=True)
    (docs / "zebra.md").write_text("# Zebra Guide\ncontent", encoding="utf-8")
    (docs / "nested" / "alpha.md").write_text("Plain text", encoding="utf-8")
    (docs / "ignored.txt").write_text("not markdown", encoding="utf-8")
    (boundary / "outside.md").write_text("outside", encoding="utf-8")
    monkeypatch.setattr(manager_content, "_documentation_root", lambda: (docs, boundary))
    client = _client()

    listing = client.get("/api/documentation")

    assert listing.status_code == 200
    documents = listing.json["data"]["documents"]
    assert [document["path"] for document in documents] == [
        "nested/alpha.md",
        "zebra.md",
    ]
    assert [document["title"] for document in documents] == [
        "alpha",
        "Zebra Guide",
    ]
    read = client.get("/api/documentation/nested/alpha.md")
    assert read.status_code == 200
    assert read.json["data"]["document"]["content"] == "Plain text"
    assert client.get("/api/documentation/ignored.txt").status_code == 404

    unauthorized = manager_content._guarded_path(docs, boundary, "../outside.md")
    assert unauthorized is None


def test_manager_log_channel_listing_filters_hidden_files_and_downloads(tmp_path, monkeypatch):
    boundary = tmp_path.resolve()
    root = boundary / "data" / "logs"
    channel = root / "minecraft"
    channel.mkdir(parents=True)
    (channel / "server.log").write_text("ready\n", encoding="utf-8")
    (channel / ".private.log").write_text("secret\n", encoding="utf-8")
    (channel / "nested").mkdir()
    monkeypatch.setattr(manager_content, "_manager_logs_root", lambda: (root, boundary))
    client = _client()

    channels = client.get("/api/manager/logs")
    assert channels.status_code == 200
    assert channels.json["data"]["channels"] == ["minecraft"]

    listing = client.get("/api/manager/logs/minecraft")
    assert listing.status_code == 200
    assert [item["name"] for item in listing.json["data"]["files"]] == ["server.log"]
    download = client.get("/api/manager/logs/minecraft/server.log")
    assert download.status_code == 200
    assert download.data.replace(b"\r\n", b"\n") == b"ready\n"
    download.close()

    assert client.get("/api/manager/logs/unsupported").status_code == 400
    assert client.get("/api/manager/logs/minecraft/nested/server.log").status_code == 403
