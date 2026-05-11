#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


class AdminPanelHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        if path in ("/", "/index.html"):
            self.path = "/admin.html"
        return super().do_GET()


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve OCR admin panel with admin page as default route.")
    parser.add_argument("--port", type=int, default=int(os.getenv("ADMIN_PANEL_PORT", "8091")))
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    handler = partial(AdminPanelHandler, directory=str(repo_root))
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)

    print(f"[admin-panel] serving {repo_root}")
    print(f"[admin-panel] url: http://127.0.0.1:{args.port}/")
    print(f"[admin-panel] direct: http://127.0.0.1:{args.port}/admin.html")
    server.serve_forever()


if __name__ == "__main__":
    main()

