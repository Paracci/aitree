"""
AITree Web UI — HTTP server and API handlers.

Endpoints
---------
GET  /                    Single-page app (HTML)
GET  /static/<file>       Static assets (CSS, JS)
POST /api/tree            Generate tree output
     body: {path, depth, include, exclude, format, git_changed, no_gitignore, tokens}
GET  /api/file            Read a file
     query: root=<abs-path>&file=<rel-path>
GET  /api/poll            Live-reload polling — returns {hash, path, timestamp}
"""

from __future__ import annotations

import datetime
import hashlib
import json
import mimetypes
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from ..core import Config, generate_output, tree_snapshot


# ── Static files directory ────────────────────────────────────────────────────

_STATIC_DIR = Path(__file__).parent / "static"


# ── Shared live-reload state ──────────────────────────────────────────────────

_lock = threading.Lock()
_state: dict = {"hash": "", "path": ".", "timestamp": ""}


def _watcher(path: str, cfg: Config) -> None:
    """Background thread: recomputes tree snapshot hash every 2 s."""
    root = Path(path).resolve()
    while True:
        try:
            fresh = Config(
                depth=cfg.depth,
                include=list(cfg.include),
                exclude=list(cfg.exclude),
                no_gitignore=cfg.no_gitignore,
                git_changed=cfg.git_changed,
            )
            snap = tree_snapshot(root, fresh)
            h = hashlib.md5(snap.encode()).hexdigest()[:12]
            ts = datetime.datetime.now().isoformat(timespec="seconds")
            with _lock:
                _state["hash"] = h
                _state["timestamp"] = ts
        except Exception:
            pass
        time.sleep(2)


# ── Request handler ───────────────────────────────────────────────────────────

class _Handler(BaseHTTPRequestHandler):
    root_path: str = "."
    root_cfg: "Config | None" = None

    def log_message(self, fmt: str, *args) -> None:  # type: ignore[override]
        pass  # suppress default access log

    # ── response helpers ───────────────────────────────────────────────────────

    def _json(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _static_file(self, filename: str) -> None:
        """Serve a file from the static directory."""
        target = (_STATIC_DIR / filename).resolve()

        # Path-traversal protection
        try:
            target.relative_to(_STATIC_DIR.resolve())
        except ValueError:
            self.send_error(403)
            return

        if not target.is_file():
            self.send_error(404)
            return

        mime, _ = mimetypes.guess_type(str(target))
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ── routing ────────────────────────────────────────────────────────────────

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        qs     = parse_qs(parsed.query)
        route  = parsed.path

        if route == "/":
            self._static_file("index.html")
        elif route.startswith("/static/"):
            self._static_file(route[len("/static/"):])
        elif route == "/api/poll":
            with _lock:
                self._json(dict(_state))
        elif route == "/api/file":
            self._get_file(
                qs.get("root", [self.root_path])[0],
                qs.get("file", [""])[0],
            )
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        route = urlparse(self.path).path
        body  = self._read_body()
        if route == "/api/tree":
            self._post_tree(body)
        elif route == "/api/stats":
            body["format"] = "json"
            self._post_tree(body)
        else:
            self.send_error(404)

    # ── handlers ───────────────────────────────────────────────────────────────

    def _read_body(self) -> dict:
        n = int(self.headers.get("Content-Length", 0))
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n))
        except Exception:
            return {}

    def _make_cfg(self, body: dict) -> Config:
        return Config(
            depth         = body.get("depth") or None,
            include       = body.get("include") or [],
            exclude       = body.get("exclude") or [],
            no_gitignore  = bool(body.get("no_gitignore")),
            git_changed   = bool(body.get("git_changed")),
            output_format = body.get("format", "text"),
            tokens        = bool(body.get("tokens")),
        )

    def _post_tree(self, body: dict) -> None:
        path = body.get("path", self.root_path)
        cfg  = self._make_cfg(body)
        try:
            output = generate_output(path, cfg)
            # core.py returns "[ERROR] ..." strings for invalid states
            # (e.g. --git-changed on a non-git directory)
            if isinstance(output, str) and output.startswith("[ERROR]"):
                self._json({"output": None, "error": output[7:].strip()})
            else:
                self._json({"output": output, "error": None})
        except Exception as e:
            self._json({"output": None, "error": str(e)})

    def _get_file(self, root: str, file: str) -> None:
        if not file:
            self._json({"error": "file parameter required"}, 400)
            return

        # Normalize path separators
        file = file.replace("\\", "/").strip("/")
        root_p = Path(root).expanduser().resolve()

        # Heuristic: if the AI included the root directory name in the path, strip it.
        # Example: if root is "C:/Users/AITree" and file is "AITree/aitree/core.py"
        root_name = root_p.name
        if file.startswith(root_name + "/"):
            file = file[len(root_name)+1:]

        target = (root_p / file).resolve()

        # Path-traversal protection using relative_to
        try:
            target.relative_to(root_p)
        except ValueError:
            self._json({"error": f"Path traversal or invalid path: {file}"}, 403)
            return

        if not target.is_file():
            # Second attempt: try finding the file if the path was slightly off
            # (only for flat filename matches if it looks like just a name)
            if "/" not in file:
                matches = list(root_p.rglob(file))
                if matches and matches[0].is_file():
                    target = matches[0]
                else:
                    self._json({"error": f"File not found: {file}"}, 404)
                    return
            else:
                self._json({"error": f"File not found: {file}"}, 404)
                return

        try:
            content = target.read_text(encoding="utf-8", errors="replace")
            self._json({
                "content": content,
                "size":    target.stat().st_size,
                "file":    str(target.relative_to(root_p)),
                "error":   None,
            })
        except OSError as e:
            self._json({"error": str(e)}, 500)


# ── Public API ────────────────────────────────────────────────────────────────

def start_server(
    path: str,
    cfg: Config,
    host: str = "localhost",
    port: int = 8080,
) -> None:
    """
    Start the AITree web UI server.

    Opens a browser window at http://host:port and serves the interactive
    file tree explorer.  A background watcher thread keeps the live-reload
    indicator updated every 2 seconds.

    Press Ctrl+C to stop.
    """
    import webbrowser

    root = Path(path).resolve()

    # Pre-compute initial snapshot hash so the first poll response is non-empty
    try:
        fresh = Config(
            depth=cfg.depth,
            include=list(cfg.include),
            exclude=list(cfg.exclude),
            no_gitignore=cfg.no_gitignore,
            git_changed=cfg.git_changed,
        )
        snap = tree_snapshot(root, fresh)
        h    = hashlib.md5(snap.encode()).hexdigest()[:12]
        with _lock:
            _state["hash"]      = h
            _state["path"]      = str(root)
            _state["timestamp"] = datetime.datetime.now().isoformat(timespec="seconds")
    except Exception:
        with _lock:
            _state["path"] = str(root)

    # Start background watcher for live reload
    threading.Thread(target=_watcher, args=(str(root), cfg), daemon=True).start()

    # Build handler class with server-specific root path
    Handler = type("Handler", (_Handler,), {
        "root_path": str(root),
        "root_cfg":  cfg,
    })

    server = HTTPServer((host, port), Handler)
    url    = f"http://{host}:{port}"

    print(f"\n🌳  AITree Web UI")
    print(f"    Serving:  {root}")
    print(f"    Open:     {url}")
    print(f"    Ctrl+C to stop.\n")

    # Open browser in background after a short delay
    threading.Thread(
        target=lambda: (time.sleep(0.5), webbrowser.open(url)),
        daemon=True,
    ).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n🔴  AITree Web stopped.")
    finally:
        server.server_close()