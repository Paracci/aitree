"""
AITree — MCP server mode.

Exposes AITree's core functionality as MCP tools so AI assistants
(Claude, Cursor, etc.) can call them directly without a shell.

Entry point:
  aitree-mcp               start the MCP server (stdio transport)

Tools exposed:
  aitree_get_tree          generate a file-tree map for a local directory or GitHub URL
  aitree_read_file         read the contents of a file inside the project directory
  aitree_get_stats         return file/directory stats as structured data
  aitree_get_changed       list git-changed / untracked files
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:
    raise SystemExit(
        "[ERROR] MCP server mode requires the 'mcp' package.\n"
        "Install it with:  pip install 'aitree[mcp]'"
    ) from exc

from .core import (
    Config,
    collect_stats,
    generate_output,
    get_changed_files,
    _human_size,
)
from .github import is_github_url, generate_github_output
# ── Server setup ──────────────────────────────────────────────────────────────

mcp = FastMCP("aitree")


# ── Tool: get_tree ────────────────────────────────────────────────────────────

@mcp.tool()
def aitree_get_tree(
    path: Annotated[str, "Absolute or relative local path, or a GitHub URL (https://github.com/owner/repo)"],
    depth: Annotated[int | None, "Maximum depth to traverse (omit = unlimited)"] = None,
    include: Annotated[list[str] | None, "Glob patterns — show only matching files, e.g. ['*.py']"] = None,
    exclude: Annotated[list[str] | None, "Glob patterns — hide matching files, e.g. ['*.test.*']"] = None,
    format: Annotated[str, "Output format: 'text' (default), 'json', or 'markdown'"] = "text",
    git_changed: Annotated[bool, "Show only git-changed / untracked files (local only)"] = False,
    no_gitignore: Annotated[bool, "Skip .gitignore and .aitreeignore (local only)"] = False,
    tokens: Annotated[bool, "Append estimated token count"] = False,
    token: Annotated[str | None, "GitHub personal access token for private repos (or set GITHUB_TOKEN env var)"] = None,
) -> str:
    """
    Generate an annotated file-tree map for a local directory or a GitHub repository.

    Accepts either:
    - A local path  (absolute or relative)
    - A GitHub URL  (https://github.com/owner/repo  or  .../tree/branch/sub/path)

    Returns a text/json/markdown snapshot of the project structure,
    suitable for pasting into an AI chat or feeding into another tool.
    Respects .gitignore and .aitreeignore by default for local paths.
    For private GitHub repos, supply a personal access token via the
    `token` parameter or the GITHUB_TOKEN environment variable.
    """
    import os

    cfg = Config(
        depth=depth,
        include=include or [],
        exclude=exclude or [],
        no_gitignore=no_gitignore,
        git_changed=git_changed,
        output_format=format,
        tokens=tokens,
    )

    # ── GitHub URL ────────────────────────────────────────────────────────────
    if is_github_url(path):
        resolved_token = token or os.environ.get("GITHUB_TOKEN") or None
        return generate_github_output(path, cfg, resolved_token)

    # ── Local path ────────────────────────────────────────────────────────────
    root = Path(path).expanduser().resolve()
    if not root.exists():
        return f"[ERROR] Path not found: {path}"
    if not root.is_dir():
        return f"[ERROR] Not a directory: {path}"

    return generate_output(str(root), cfg)


# ── Tool: read_file ──────────────────────────────────────────────────────────

@mcp.tool()
def aitree_read_file(
    path: Annotated[str, "Absolute or relative path of the project root directory"],
    file: Annotated[str, "Relative path of the file to read (as seen in aitree_get_tree output)"],
    encoding: Annotated[str, "File encoding (default: utf-8)"] = "utf-8",
) -> str:
    """
    Reads the content of a file in the project directory.

    Typical usage:
      1. Get project tree with aitree_get_tree
      2. Read interested files using aitree_read_file
      This allows reading only the necessary files instead of sending the entire codebase.

    Security: path traversal access outside the root path is blocked.
    """
    root   = Path(path).expanduser().resolve()
    target = (root / file).resolve()

    # ── Security checks ───────────────────────────────────────────────────────
    if not str(target).startswith(str(root)):
        return json.dumps({"error": "Path traversal detected — file must be inside path"})
    if not root.exists():
        return json.dumps({"error": f"Root path not found: {path}"})
    if not target.exists():
        return json.dumps({"error": f"File not found: {file}"})
    if not target.is_file():
        return json.dumps({"error": f"Not a file: {file}"})

    # ── Read file ─────────────────────────────────────────────────────────────
    try:
        content = target.read_text(encoding=encoding, errors="replace")
    except OSError as exc:
        return json.dumps({"error": str(exc)})

    stat = target.stat()
    return json.dumps({
        "file":     file,
        "size":     stat.st_size,
        "size_human": _human_size(stat.st_size),
        "encoding": encoding,
        "content":  content,
    }, ensure_ascii=False, indent=2)


# ── Tool: get_stats ───────────────────────────────────────────────────────────

@mcp.tool()
def aitree_get_stats(
    path: Annotated[str, "Absolute or relative path to the directory"],
    depth: Annotated[int | None, "Maximum depth to consider (omit = unlimited)"] = None,
    include: Annotated[list[str] | None, "Glob patterns — count only matching files"] = None,
    exclude: Annotated[list[str] | None, "Glob patterns — exclude from count"] = None,
    no_gitignore: Annotated[bool, "Skip .gitignore and .aitreeignore"] = False,
) -> str:
    """
    Return file/directory statistics as JSON.

    Includes total file count, directory count, total size, and a
    breakdown of file types (extension → count + size), sorted by frequency.
    Useful for understanding the shape of a codebase at a glance.
    """
    root = Path(path).expanduser().resolve()
    if not root.exists():
        return json.dumps({"error": f"Path not found: {path}"})
    if not root.is_dir():
        return json.dumps({"error": f"Not a directory: {path}"})

    cfg = Config(
        depth=depth,
        include=include or [],
        exclude=exclude or [],
        no_gitignore=no_gitignore,
    )
    cfg.load_gitignore(root)

    stats = collect_stats(root, cfg)

    # Enrich with human-readable sizes
    result = {
        "path":        str(root),
        "directories": stats["total_dirs"],
        "files":       stats["total_files"],
        "total_size":  _human_size(stats["total_size"]),
        "total_bytes": stats["total_size"],
        "file_types":  [
            {
                "extension": ext,
                "count":     count,
                "size":      _human_size(stats["ext_size"].get(ext, 0)),
            }
            for ext, count in list(stats["ext_count"].items())[:20]
        ],
    }

    return json.dumps(result, indent=2, ensure_ascii=False)


# ── Tool: get_changed ─────────────────────────────────────────────────────────

@mcp.tool()
def aitree_get_changed(
    path: Annotated[str, "Absolute or relative path to the git repository root or any subdirectory"],
) -> str:
    """
    List git-changed and untracked files in a repository.

    Returns a JSON array of relative file paths that are staged, unstaged,
    or untracked. Requires gitpython ('pip install aitree[git]').
    """
    root = Path(path).expanduser().resolve()
    if not root.exists():
        return json.dumps({"error": f"Path not found: {path}"})

    changed = get_changed_files(root)
    if changed is None:
        return json.dumps({
            "error": (
                "Not a git repository, or gitpython is not installed. "
                "Install with:  pip install 'aitree[git]'"
            )
        })

    try:
        import git  # type: ignore
        repo = git.Repo(root, search_parent_directories=True)
        repo_root = Path(repo.working_tree_dir)
        relative = sorted(
            str(p.relative_to(repo_root))
            for p in changed
            if p.exists()
        )
    except Exception:
        relative = sorted(str(p) for p in changed if p.exists())

    return json.dumps({
        "repository": str(root),
        "changed_files": relative,
        "count": len(relative),
    }, indent=2, ensure_ascii=False)




# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    """Start the AITree MCP server (stdio transport)."""
    mcp.run()


if __name__ == "__main__":
    main()