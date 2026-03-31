"""
AITree — core tree building logic.
"""

import datetime
import fnmatch
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

# ── Default ignore lists ──────────────────────────────────────────────────────

DEFAULT_IGNORE_DIRS: set[str] = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "env", ".env", "dist", "build", ".idea", ".vscode",
    ".next", ".nuxt", "coverage", ".pytest_cache", ".mypy_cache",
    "target", "out", "bin", "obj", ".gradle", ".mvn",
    ".svn", ".hg",
}

DEFAULT_IGNORE_FILES: set[str] = {
    "_aitree.txt", ".gitignore", ".aitreeignore", ".gitattributes",
    "Thumbs.db", ".DS_Store",
}

DEFAULT_IGNORE_EXTENSIONS: set[str] = {
    ".pyc", ".pyo", ".pyd", ".class", ".o", ".obj",
    ".exe", ".dll", ".so", ".dylib", ".a", ".lib",
    ".log", ".tmp", ".temp", ".cache",
}

OUTPUT_FILENAME = "_aitree.txt"


# ── Config ────────────────────────────────────────────────────────────────────

@dataclass
class Config:
    depth:        int | None  = None
    include:      list[str]   = field(default_factory=list)
    exclude:      list[str]   = field(default_factory=list)
    no_gitignore: bool        = False
    git_changed:  bool        = False   # show only git-changed files
    output_format: str        = "text"  # "text" | "json" | "markdown"
    tokens:       bool        = False   # show token count estimate

    _gitignore_patterns: list[str] = field(default_factory=list, repr=False)

    def load_gitignore(self, root: Path) -> None:
        if self.no_gitignore:
            return
        for name in (".aitreeignore", ".gitignore"):
            ig = root / name
            if ig.is_file():
                try:
                    for line in ig.read_text(encoding="utf-8", errors="replace").splitlines():
                        line = line.strip()
                        if line and not line.startswith("#"):
                            self._gitignore_patterns.append(line)
                except OSError:
                    pass

    def is_gitignored(self, path: Path, root: Path) -> bool:
        if not self._gitignore_patterns:
            return False
        try:
            rel = str(path.relative_to(root))
        except ValueError:
            return False
        name = path.name
        for pat in self._gitignore_patterns:
            if fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(rel, pat):
                return True
            if pat.endswith("/") and path.is_dir() and fnmatch.fnmatch(name, pat.rstrip("/")):
                return True
        return False

    def matches_include(self, path: Path) -> bool:
        if not self.include or path.is_dir():
            return True
        return any(fnmatch.fnmatch(path.name, p) for p in self.include)

    def matches_exclude(self, path: Path, root: Path) -> bool:
        if not self.exclude:
            return False
        try:
            rel = str(path.relative_to(root))
        except ValueError:
            rel = path.name
        return any(
            fnmatch.fnmatch(path.name, p) or fnmatch.fnmatch(rel, p)
            for p in self.exclude
        )




# ── Project config (.aitree.toml) ─────────────────────────────────────────────

def load_project_config(root: Path) -> dict:
    """
    Reads .aitree.toml in the project root and returns a dict.
    Returns empty dict if file does not exist — always safe to call.

    Priority: CLI arguments > .aitree.toml > defaults

    Uses stdlib tomllib in Python 3.11+.
    Minimal fallback parser is used in Python 3.10 if tomllib is missing
    (supports only string, int, bool and simple string list).

    Supported .aitree.toml format:
        depth   = 3
        exclude = ["*.test.*", "*.spec.*"]
        include = []
        format  = "text"
        tokens  = false

        [suggest]
        provider = "anthropic"
    """
    config_file = root / ".aitree.toml"
    if not config_file.exists():
        return {}

    # Python 3.11+ stdlib tomllib
    try:
        import tomllib
        with open(config_file, "rb") as f:
            return tomllib.load(f)
    except ImportError:
        pass

    # Optional tomli package (pip install tomli)
    try:
        import tomli as tomllib  # type: ignore
        with open(config_file, "rb") as f:
            return tomllib.load(f)
    except ImportError:
        pass

    # Fallback: minimal line-based parser
    return _simple_toml_parse(config_file)


def _simple_toml_parse(path: Path) -> dict:
    """
    Minimal TOML parser that works without tomllib/tomli.
    Supports: string, int, bool, single-line string list.
    Also processes [section] headers (creates nested dicts).
    """
    result: dict = {}
    current: dict = result
    section: str  = ""

    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        # [section] header
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            if section not in result:
                result[section] = {}
            current = result[section]
            continue

        if "=" not in line:
            continue

        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()

        # String list: ["a", "b", "c"]
        if val.startswith("["):
            inner = val.strip("[]")
            if inner.strip():
                items = [
                    i.strip().strip('"').strip("'")
                    for i in inner.split(",")
                    if i.strip()
                ]
                current[key] = items
            else:
                current[key] = []
        # Bool
        elif val.lower() == "true":
            current[key] = True
        elif val.lower() == "false":
            current[key] = False
        # Int
        elif val.lstrip("-").isdigit():
            current[key] = int(val)
        # String (with or without quotes)
        else:
            current[key] = val.strip('"').strip("'")

    return result


# ── Git helpers ───────────────────────────────────────────────────────────────

# Split original single try/except into two:
def get_changed_files(root: Path) -> set[Path] | None:
    try:
        import git  # type: ignore
    except ImportError:
        return None  # gitpython is not installed

    try:
        repo = git.Repo(root, search_parent_directories=True)
        changed: set[Path] = set()
        repo_root = Path(repo.working_tree_dir)

        for item in repo.index.diff(None):
            changed.add((repo_root / item.a_path).resolve())
        for item in repo.index.diff("HEAD"):
            changed.add((repo_root / item.a_path).resolve())
        for rel in repo.untracked_files:
            changed.add((repo_root / rel).resolve())

        return changed
    except Exception:
        return set()  # ← Not None, empty set! Not a git repo or error


# ── Token counter ─────────────────────────────────────────────────────────────

def count_tokens(text: str) -> int | None:
    """
    Estimate token count.
    Tries tiktoken (accurate) then falls back to a character-ratio heuristic (~4 chars/token).
    """
    try:
        import tiktoken  # type: ignore
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except ImportError:
        pass
    except Exception:
        pass  # tiktoken installed but encoding download failed — use fallback

    # Heuristic: ~4 characters per token (good enough for size estimates)
    return max(1, len(text) // 4)


def _token_label(n: int | None) -> str:
    if n is None:
        return ""
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M tokens"
    if n >= 1_000:
        return f"{n/1_000:.1f}K tokens"
    return f"{n} tokens"


# ── Filtering ─────────────────────────────────────────────────────────────────

def should_ignore(path: Path) -> bool:
    if path.is_dir() and path.name in DEFAULT_IGNORE_DIRS:
        return True
    if path.is_file() and path.name in DEFAULT_IGNORE_FILES:
        return True
    if path.is_file() and path.suffix.lower() in DEFAULT_IGNORE_EXTENSIONS:
        return True
    return False


def _any_parent_ignored(path: Path, root: Path) -> bool:
    try:
        for part in path.relative_to(root).parents:
            if part.name in DEFAULT_IGNORE_DIRS:
                return True
    except ValueError:
        pass
    return False


def _is_visible(path: Path, root: Path, cfg: Config,
                changed_files: set[Path] | None = None) -> bool:
    if should_ignore(path):
        return False
    if cfg.is_gitignored(path, root):
        return False
    if cfg.matches_exclude(path, root):
        return False
    if not cfg.matches_include(path):
        return False
    if cfg.git_changed and changed_files is not None and path.is_file():
        if path.resolve() not in changed_files:
            return False
    return True


# ── Tree rendering ────────────────────────────────────────────────────────────

def _human_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f}{unit}"
        size /= 1024
    return f"{size:.0f}TB"


def build_tree(
    root: Path,
    cfg: Config,
    tree_root: Path,
    changed_files: set[Path] | None = None,
    prefix: str = "",
    current_depth: int = 0,
) -> list[str]:
    lines: list[str] = []

    if cfg.depth is not None and current_depth >= cfg.depth:
        return lines

    if cfg.git_changed:
        changed_files = get_changed_files(root)
        if changed_files is None:
            return "[ERROR] --git-changed requires gitpython: pip install gitpython"
        # Continues silently if set() returns (not git repo = empty list)

    try:
        entries = sorted(root.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
        entries = [e for e in entries if _is_visible(e, tree_root, cfg, changed_files)]
    except PermissionError:
        return [f"{prefix}    [permission denied]"]

    for i, entry in enumerate(entries):
        is_last = i == len(entries) - 1
        connector = "└── " if is_last else "├── "
        extender  = "    " if is_last else "│   "

        if entry.is_dir():
            lines.append(f"{prefix}{connector}{entry.name}/")
            lines.extend(build_tree(entry, cfg, tree_root, changed_files, prefix + extender, current_depth + 1))
        else:
            size = _human_size(entry.stat().st_size)
            lines.append(f"{prefix}{connector}{entry.name}  [{size}]")

    return lines


# ── Stats helpers ─────────────────────────────────────────────────────────────

def collect_stats(root: Path, cfg: Config,
                  changed_files: set[Path] | None = None) -> dict:
    """Collect file/dir counts and extension breakdown."""
    ext_count: dict[str, int] = defaultdict(int)
    ext_size:  dict[str, int] = defaultdict(int)
    ext_tokens: dict[str, int] = defaultdict(int) 
    total_files = 0
    total_dirs  = 0
    total_size  = 0
    total_tokens = 0

    for p in root.rglob("*"):
        if _any_parent_ignored(p, root):
            continue
        if not _is_visible(p, root, cfg, changed_files):
            continue
        if p.is_dir():
            total_dirs += 1
        elif p.is_file():
            total_files += 1
            try:
                size = p.stat().st_size
                total_size += size
                ext = p.suffix.lower() or "(no ext)"
                ext_count[ext] += 1
                ext_size[ext]  += size
                
                if cfg.tokens:
                    try:
                        content = p.read_text(encoding="utf-8", errors="replace")
                        toks = count_tokens(content) or 0
                        total_tokens += toks
                        ext_tokens[ext] += toks
                    except Exception:
                        pass
            except OSError:
                continue

    return {
        "total_files": total_files,
        "total_dirs":  total_dirs,
        "total_size":  total_size,
        "total_tokens": total_tokens if cfg.tokens else None,
        "ext_count":   dict(sorted(ext_count.items(), key=lambda x: -x[1])),
        "ext_size":    dict(sorted(ext_size.items(),  key=lambda x: -x[1])),
        "ext_tokens":  dict(sorted(ext_tokens.items(), key=lambda x: -x[1])) if cfg.tokens else {},
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


# ── Output formats ────────────────────────────────────────────────────────────

def _build_header_meta(root: Path, cfg: Config) -> dict:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    meta: dict = {"generated": now, "root": str(root)}
    if cfg.depth      is not None: meta["depth"]   = cfg.depth
    if cfg.include:                 meta["include"] = cfg.include
    if cfg.exclude:                 meta["exclude"] = cfg.exclude
    if cfg.git_changed:             meta["git_changed"] = True
    return meta


def _format_text(root: Path, cfg: Config,
                 changed_files: set[Path] | None = None) -> str:
    meta = _build_header_meta(root, cfg)
    header = [
        "# AITree - Project File Map",
        f"# Generated: {meta['generated']}",
        f"# Root:      {meta['root']}",
    ]
    if cfg.depth      is not None: header.append(f"# Depth:     {cfg.depth}")
    if cfg.include:                 header.append(f"# Include:   {', '.join(cfg.include)}")
    if cfg.exclude:                 header.append(f"# Exclude:   {', '.join(cfg.exclude)}")
    if cfg.git_changed:             header.append("# Mode:      git-changed only")

    tree_lines = [f"{root.name}/"] + build_tree(root, cfg, root, changed_files)
    stats = collect_stats(root, cfg, changed_files)
    stat_lines = _stats_lines(stats)

    output = "\n".join(header + [""] + tree_lines + [""] + stat_lines)

    if cfg.tokens:
        n = count_tokens(output)
        output += f"\n# Estimated: {_token_label(n)}"

    return output


def _format_markdown(root: Path, cfg: Config,
                     changed_files: set[Path] | None = None) -> str:
    meta = _build_header_meta(root, cfg)
    parts = [
        f"# AITree — Project File Map",
        f"",
        f"**Generated:** {meta['generated']}  ",
        f"**Root:** `{meta['root']}`",
    ]
    if cfg.depth is not None:  parts.append(f"**Depth:** {cfg.depth}")
    if cfg.git_changed:        parts.append(f"**Mode:** git-changed only")
    parts += ["", "## Tree", "", "```"]

    tree_lines = [f"{root.name}/"] + build_tree(root, cfg, root, changed_files)
    parts += tree_lines + ["```", ""]

    stats = collect_stats(root, cfg, changed_files)
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


def _format_json(root: Path, cfg: Config,
                 changed_files: set[Path] | None = None) -> str:

    def _node(p: Path, depth: int = 0) -> dict:
        node: dict = {"name": p.name, "type": "directory" if p.is_dir() else "file"}
        if p.is_file():
            node["size"] = p.stat().st_size
            if cfg.tokens:
                try:
                    # For safety, only read small files for per-node tokens
                    # Large files could slow down tree building significantly
                    if node["size"] < 1_000_000: # 1MB limit
                        content = p.read_text(encoding="utf-8", errors="replace")
                        node["tokens"] = count_tokens(content)
                except Exception:
                    pass
        if p.is_dir():
            if cfg.depth is None or depth < cfg.depth:
                try:
                    children = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
                    children = [c for c in children if _is_visible(c, root, cfg, changed_files)]
                    node["children"] = [_node(c, depth + 1) for c in children]
                except PermissionError:
                    node["children"] = []
        return node

    meta = _build_header_meta(root, cfg)
    stats = collect_stats(root, cfg, changed_files)
    tree = _node(root)

    payload: dict = {
        "meta":  meta,
        "tree":  tree,
        "stats": stats,
    }

    output = json.dumps(payload, indent=2, ensure_ascii=False)

    if cfg.tokens:
        n = count_tokens(output)
        payload["meta"]["estimated_tokens"] = n
        output = json.dumps(payload, indent=2, ensure_ascii=False)

    return output


# ── Public entry ──────────────────────────────────────────────────────────────

def generate_output(path: str, cfg: Config | None = None) -> str:
    if cfg is None:
        cfg = Config()

    root = Path(path).resolve()
    if not root.exists():
        return f"[ERROR] Directory not found: {path}"
    if not root.is_dir():
        return f"[ERROR] Not a directory: {path}"

    cfg.load_gitignore(root)

    changed_files: set[Path] | None = None
    if cfg.git_changed:
        changed_files = get_changed_files(root)
        if changed_files is None:
            return "[ERROR] --git-changed requires a git repository and 'pip install gitpython'"

    if cfg.output_format == "json":
        return _format_json(root, cfg, changed_files)
    if cfg.output_format == "markdown":
        return _format_markdown(root, cfg, changed_files)
    return _format_text(root, cfg, changed_files)


# ── Live mode helpers ─────────────────────────────────────────────────────────

def file_hash(path: Path) -> str:
    try:
        return hashlib.md5(path.read_bytes()).hexdigest()
    except Exception:
        return ""


def tree_snapshot(root: Path, cfg: Config | None = None) -> str:
    if cfg is None:
        cfg = Config()
    changed_files = get_changed_files(root) if cfg.git_changed else None
    parts: list[str] = []
    for p in sorted(root.rglob("*")):
        if not _is_visible(p, root, cfg, changed_files) or _any_parent_ignored(p, root):
            continue
        try:
            rel = p.relative_to(root)
            parts.append(f"{rel}:{p.stat().st_size}" if p.is_file() else f"{rel}/")
        except Exception:
            pass
    return "|".join(parts)

# ── Diff ──────────────────────────────────────────────────────────────────────

@dataclass
class DiffResult:
    """Holds the differences between two trees."""
    added:   list
    removed: list
    grown:   list   # list[tuple[str, int, int]] — (path, old_size, new_size)
    shrunk:  list   # list[tuple[str, int, int]] — (path, old_size, new_size)

    @property
    def is_empty(self) -> bool:
        return not any([self.added, self.removed, self.grown, self.shrunk])

    @property
    def total_changes(self) -> int:
        return len(self.added) + len(self.removed) + len(self.grown) + len(self.shrunk)


def _scan_dir(root: Path, cfg: Config) -> dict:
    """
    Scan directory, return {relative_path: size} for visible files.
    cfg filters (include, exclude, depth) are applied.
    """
    cfg.load_gitignore(root)
    result: dict = {}

    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if _any_parent_ignored(p, root):
            continue
        if not _is_visible(p, root, cfg):
            continue
        try:
            rel = str(p.relative_to(root))
            result[rel] = p.stat().st_size
        except (ValueError, OSError):
            pass

    return result


def diff_trees(root_a: Path, root_b: Path, cfg: Config) -> DiffResult:
    """
    Calculate the difference between root_a (current) and root_b (reference/old).

    root_a = current state (current directory)
    root_b = comparison reference (old commit, another branch, another dir)
    """
    files_a = _scan_dir(root_a, cfg)
    files_b = _scan_dir(root_b, cfg)

    keys_a = set(files_a)
    keys_b = set(files_b)

    added   = sorted(keys_a - keys_b)
    removed = sorted(keys_b - keys_a)
    grown  = []
    shrunk = []

    for path in sorted(keys_a & keys_b):
        size_a = files_a[path]
        size_b = files_b[path]
        if size_a > size_b:
            grown.append((path, size_b, size_a))
        elif size_a < size_b:
            shrunk.append((path, size_b, size_a))

    return DiffResult(added=added, removed=removed, grown=grown, shrunk=shrunk)


def extract_git_ref(repo_root: Path, ref: str, target_dir: Path) -> bool:
    """
    Extract the Git ref (commit hash, branch, HEAD~1 etc.) into target_dir.
    Returns True if successful, False if git is unavailable or an error occurs.
    Uses subprocess + 'git archive' — no extra dependencies.
    """
    import subprocess
    import tarfile
    import io

    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "archive", "--format=tar", ref],
            capture_output=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False   # git CLI missing or timeout

    if result.returncode != 0:
        return False   # invalid ref or not a git repo

    try:
        with tarfile.open(fileobj=io.BytesIO(result.stdout)) as tar:
            tar.extractall(target_dir)
        return True
    except Exception:
        return False