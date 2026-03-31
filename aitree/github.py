"""
AITree — GitHub URL support.

Fetches a repository's file tree via the GitHub API (no cloning needed).
Works with public repos out of the box; private repos need a token.

Supported URL formats:
  https://github.com/owner/repo
  https://github.com/owner/repo/tree/branch
  https://github.com/owner/repo/tree/branch/sub/path
"""

from __future__ import annotations

import json
import re
import urllib.request
import urllib.error
from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Iterator
import fnmatch
import datetime

from .core import Config, _human_size, _token_label, count_tokens


# ── URL parsing ───────────────────────────────────────────────────────────────

@dataclass
class GithubRef:
    owner:   str
    repo:    str
    branch:  str | None  # None → use default branch
    subpath: str         # "" → repo root


_GITHUB_RE = re.compile(
    r"^(?:https?://)?github\.com"
    r"/(?P<owner>[^/]+)"
    r"/(?P<repo>[^/]+)"
    r"(?:/tree/(?P<branch>[^/]+)(?P<subpath>(?:/[^?#]*)?))?",
    re.IGNORECASE,
)


def parse_github_url(url: str) -> GithubRef | None:
    m = _GITHUB_RE.match(url.rstrip("/"))
    if not m:
        return None
    subpath = (m.group("subpath") or "").strip("/")
    return GithubRef(
        owner=m.group("owner"),
        repo=m.group("repo"),
        branch=m.group("branch"),
        subpath=subpath,
    )


def is_github_url(path: str) -> bool:
    return bool(parse_github_url(path))


# ── GitHub API helpers ────────────────────────────────────────────────────────

def _api_get(url: str, token: str | None = None) -> dict | list:
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "aitree/3.0")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            msg = json.loads(body).get("message", body)
        except Exception:
            msg = body
        raise RuntimeError(f"GitHub API error {e.code}: {msg}") from e


def _get_default_branch(owner: str, repo: str, token: str | None) -> str:
    data = _api_get(f"https://api.github.com/repos/{owner}/{repo}", token)
    return data.get("default_branch", "main")  # type: ignore


def _fetch_git_tree(owner: str, repo: str, branch: str, token: str | None) -> list[dict]:
    """Return flat list of all tree entries (type=blob/tree, path, size)."""
    url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
    data = _api_get(url, token)
    if data.get("truncated"):  # type: ignore
        # Very large repos — warn but continue with what we have
        import sys
        print("[WARNING] Repository tree was truncated by GitHub API (>100k files).", file=sys.stderr)
    return data.get("tree", [])  # type: ignore


# ── Tree node ─────────────────────────────────────────────────────────────────

@dataclass
class _Node:
    name:     str
    is_dir:   bool
    size:     int = 0
    children: list["_Node"] = None  # type: ignore

    def __post_init__(self):
        if self.children is None:
            self.children = []


def _build_node_tree(entries: list[dict], subpath: str) -> _Node:
    """Turn the flat GitHub API list into a nested _Node tree."""
    root_name = subpath.split("/")[-1] if subpath else "(root)"
    root = _Node(name=root_name, is_dir=True)
    nodes: dict[str, _Node] = {"": root}

    # Normalise — strip the subpath prefix
    prefix = subpath + "/" if subpath else ""

    for entry in entries:
        raw_path: str = entry.get("path", "")
        if prefix and not raw_path.startswith(prefix):
            continue
        rel_path = raw_path[len(prefix):]
        if not rel_path:
            continue

        parts = rel_path.split("/")
        is_blob = entry.get("type") == "blob"

        # Ensure all parent directories exist
        for depth in range(len(parts) - (0 if not is_blob else 1)):
            dir_key = "/".join(parts[:depth + 1])
            if dir_key not in nodes:
                dir_node = _Node(name=parts[depth], is_dir=True)
                parent_key = "/".join(parts[:depth]) if depth > 0 else ""
                nodes[parent_key].children.append(dir_node)
                nodes[dir_key] = dir_node

        if is_blob:
            file_node = _Node(
                name=parts[-1],
                is_dir=False,
                size=entry.get("size", 0),
            )
            parent_key = "/".join(parts[:-1])
            nodes[parent_key].children.append(file_node)

    # Sort: dirs first, then files, both alphabetical
    def _sort(node: _Node) -> None:
        node.children.sort(key=lambda n: (not n.is_dir, n.name.lower()))
        for child in node.children:
            if child.is_dir:
                _sort(child)

    _sort(root)
    return root


# ── Config-aware filtering ────────────────────────────────────────────────────

_DEFAULT_IGNORE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "env", ".env", "dist", "build", ".idea", ".vscode",
    ".next", ".nuxt", "coverage", ".pytest_cache", ".mypy_cache",
    "target", "out", "bin", "obj", ".gradle", ".mvn", ".svn", ".hg",
}

_DEFAULT_IGNORE_EXT = {
    ".pyc", ".pyo", ".pyd", ".class", ".o", ".obj",
    ".exe", ".dll", ".so", ".dylib", ".a", ".lib",
    ".log", ".tmp", ".temp", ".cache",
}


def _should_hide(node: _Node, rel: str, cfg: Config) -> bool:
    if node.is_dir and node.name in _DEFAULT_IGNORE_DIRS:
        return True
    if not node.is_dir:
        suffix = PurePosixPath(node.name).suffix.lower()
        if suffix in _DEFAULT_IGNORE_EXT:
            return True
        if cfg.include and not any(fnmatch.fnmatch(node.name, p) for p in cfg.include):
            return True
    if cfg.exclude and any(
        fnmatch.fnmatch(node.name, p) or fnmatch.fnmatch(rel, p)
        for p in cfg.exclude
    ):
        return True
    return False


# ── Rendering ─────────────────────────────────────────────────────────────────

def _render_lines(
    node: _Node,
    cfg: Config,
    rel_prefix: str = "",
    line_prefix: str = "",
    depth: int = 0,
) -> list[str]:
    lines: list[str] = []
    if cfg.depth is not None and depth >= cfg.depth:
        return lines

    visible = [
        c for c in node.children
        if not _should_hide(c, f"{rel_prefix}/{c.name}".lstrip("/"), cfg)
    ]

    for i, child in enumerate(visible):
        is_last = i == len(visible) - 1
        connector = "└── " if is_last else "├── "
        extender  = "    " if is_last else "│   "
        rel = f"{rel_prefix}/{child.name}".lstrip("/")

        if child.is_dir:
            lines.append(f"{line_prefix}{connector}{child.name}/")
            lines.extend(_render_lines(child, cfg, rel, line_prefix + extender, depth + 1))
        else:
            size_str = _human_size(child.size) if child.size else "—"
            lines.append(f"{line_prefix}{connector}{child.name}  [{size_str}]")

    return lines


def _collect_stats(node: _Node, cfg: Config, rel_prefix: str = "") -> dict:
    ext_count: dict[str, int] = defaultdict(int)
    ext_size:  dict[str, int] = defaultdict(int)
    total_files = 0
    total_dirs  = 0
    total_size  = 0

    def _walk(n: _Node, rel: str) -> None:
        nonlocal total_files, total_dirs, total_size
        for child in n.children:
            child_rel = f"{rel}/{child.name}".lstrip("/")
            if _should_hide(child, child_rel, cfg):
                continue
            if child.is_dir:
                total_dirs += 1
                _walk(child, child_rel)
            else:
                total_files += 1
                total_size  += child.size
                ext = PurePosixPath(child.name).suffix.lower() or "(no ext)"
                ext_count[ext] += 1
                ext_size[ext]  += child.size

    _walk(node, rel_prefix)
    return {
        "total_files": total_files,
        "total_dirs":  total_dirs,
        "total_size":  total_size,
        "ext_count":   dict(sorted(ext_count.items(), key=lambda x: -x[1])),
        "ext_size":    dict(sorted(ext_size.items(),  key=lambda x: -x[1])),
    }


def _stats_lines(stats: dict) -> list[str]:
    lines = [
        f"# {stats['total_dirs']} directories, {stats['total_files']} files"
        f"  ({_human_size(stats['total_size'])} total)",
    ]
    if stats["ext_count"]:
        lines.append("#")
        lines.append("# File types:")
        for ext, count in list(stats["ext_count"].items())[:10]:
            bar = "█" * min(count, 20)
            lines.append(f"#   {ext:<12} {count:>4}   {bar}")
    return lines


# ── Output format builders ────────────────────────────────────────────────────

def _format_text(ref: GithubRef, node: _Node, cfg: Config, url: str) -> str:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    header = [
        "# AITree - Project File Map",
        f"# Generated: {now}",
        f"# Source:    {url}",
        f"# Repo:      {ref.owner}/{ref.repo}  (branch: {ref.branch})",
    ]
    if cfg.depth is not None: header.append(f"# Depth:     {cfg.depth}")
    if cfg.include:            header.append(f"# Include:   {', '.join(cfg.include)}")
    if cfg.exclude:            header.append(f"# Exclude:   {', '.join(cfg.exclude)}")

    tree_lines = [f"{node.name}/"] + _render_lines(node, cfg)
    stats      = _collect_stats(node, cfg)
    stat_lines = _stats_lines(stats)

    output = "\n".join(header + [""] + tree_lines + [""] + stat_lines)

    if cfg.tokens:
        n = count_tokens(output)
        output += f"\n# Estimated: {_token_label(n)}"

    return output


def _format_markdown(ref: GithubRef, node: _Node, cfg: Config, url: str) -> str:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    parts = [
        "# AITree — Project File Map",
        "",
        f"**Generated:** {now}  ",
        f"**Source:** [{ref.owner}/{ref.repo}]({url})  ",
        f"**Branch:** `{ref.branch}`",
    ]
    if cfg.depth is not None: parts.append(f"**Depth:** {cfg.depth}")
    parts += ["", "## Tree", "", "```"]
    parts += [f"{node.name}/"] + _render_lines(node, cfg)
    parts += ["```", ""]

    stats = _collect_stats(node, cfg)
    parts += [
        "## Stats",
        "",
        f"- **Directories:** {stats['total_dirs']}",
        f"- **Files:** {stats['total_files']}",
        f"- **Total size:** {_human_size(stats['total_size'])}",
    ]
    if stats["ext_count"]:
        parts += ["", "### File types", "", "| Extension | Count |", "|---|---|"]
        for ext, count in list(stats["ext_count"].items())[:10]:
            parts.append(f"| `{ext}` | {count} |")

    output = "\n".join(parts)
    if cfg.tokens:
        n = count_tokens(output)
        parts += ["", f"**Estimated tokens:** {_token_label(n)}"]
        output = "\n".join(parts)
    return output


def _format_json(ref: GithubRef, node: _Node, cfg: Config, url: str) -> str:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stats = _collect_stats(node, cfg)

    def _node_dict(n: _Node, depth: int = 0) -> dict:
        d: dict = {"name": n.name, "type": "directory" if n.is_dir else "file"}
        if not n.is_dir:
            d["size"] = n.size
        if n.is_dir:
            if cfg.depth is None or depth < cfg.depth:
                d["children"] = [
                    _node_dict(c, depth + 1)
                    for c in n.children
                    if not _should_hide(c, c.name, cfg)
                ]
        return d

    payload: dict = {
        "meta": {
            "generated": now,
            "source":    url,
            "owner":     ref.owner,
            "repo":      ref.repo,
            "branch":    ref.branch,
            "subpath":   ref.subpath or None,
        },
        "tree":  _node_dict(node),
        "stats": stats,
    }

    output = json.dumps(payload, indent=2, ensure_ascii=False)
    if cfg.tokens:
        n = count_tokens(output)
        payload["meta"]["estimated_tokens"] = n
        output = json.dumps(payload, indent=2, ensure_ascii=False)
    return output


# ── Public entry ──────────────────────────────────────────────────────────────

def generate_github_output(url: str, cfg: Config | None = None, token: str | None = None) -> str:
    """
    Main entry point for GitHub URL mode.

    Fetches the repo tree via GitHub API and returns formatted output
    identical in structure to generate_output() for local paths.
    """
    if cfg is None:
        cfg = Config()

    ref = parse_github_url(url)
    if ref is None:
        return f"[ERROR] Could not parse GitHub URL: {url}"

    # Resolve default branch if not specified in URL
    try:
        if ref.branch is None:
            ref.branch = _get_default_branch(ref.owner, ref.repo, token)

        entries = _fetch_git_tree(ref.owner, ref.repo, ref.branch, token)
    except RuntimeError as exc:
        return f"[ERROR] {exc}"

    node = _build_node_tree(entries, ref.subpath)

    if cfg.output_format == "json":
        return _format_json(ref, node, cfg, url)
    if cfg.output_format == "markdown":
        return _format_markdown(ref, node, cfg, url)
    return _format_text(ref, node, cfg, url)
