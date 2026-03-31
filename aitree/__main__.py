"""
AITree — CLI entry point.

Usage:
  aitree [path|url]                  Print tree to stdout
  aitree [path|url] --save           Save to _aitree.txt
  aitree [path|url] --copy           Copy to clipboard
  aitree [path|url] --live           Watch for changes (requires: pip install watchdog)
  aitree [path|url] --depth 2        Limit tree depth
  aitree [path|url] --include "*.py" Show only matching files
  aitree [path|url] --exclude "*.md" Hide matching files
  aitree [path|url] --no-gitignore   Skip .gitignore / .aitreeignore
  aitree [path|url] --git-changed    Show only git-changed files
  aitree [path|url] --format json    Output as JSON
  aitree [path|url] --format markdown Output as Markdown
  aitree [path|url] --tokens         Show estimated token count

GitHub URL examples:
  aitree https://github.com/owner/repo
  aitree https://github.com/owner/repo/tree/main/src
  aitree https://github.com/owner/repo --depth 2 --include "*.py"
  aitree https://github.com/owner/repo --token ghp_xxxx   (private repos)
"""

import os
import sys
import time
import datetime
import threading
import argparse
from pathlib import Path

from .core import Config, generate_output, tree_snapshot, file_hash, OUTPUT_FILENAME, load_project_config, diff_trees, extract_git_ref, DiffResult
from .github import is_github_url, generate_github_output

# ── Clipboard ─────────────────────────────────────────────────────────────────

def _copy_to_clipboard(text: str) -> bool:
    try:
        import pyperclip  # type: ignore
        pyperclip.copy(text)
        return True
    except ImportError:
        pass

    import subprocess
    for cmd, inp in [
        (["pbcopy"],                            text.encode()),
        (["xclip", "-selection", "clipboard"],  text.encode()),
        (["xsel", "--clipboard", "--input"],     text.encode()),
        (["clip"],                              text.encode("utf-16")),
    ]:
        try:
            subprocess.run(cmd, input=inp, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
    return False


# ── Output extension ──────────────────────────────────────────────────────────

def _output_ext(cfg: Config) -> str:
    return {"json": ".json", "markdown": ".md"}.get(cfg.output_format, ".txt")


def _output_filename(cfg: Config) -> str:
    base = OUTPUT_FILENAME.replace(".txt", "")
    return base + _output_ext(cfg)


# ── GitHub token resolution ───────────────────────────────────────────────────

def _resolve_token(args_token: str | None) -> str | None:
    """CLI --token flag takes precedence, then GITHUB_TOKEN env var."""
    return args_token or os.environ.get("GITHUB_TOKEN") or None


# ── Modes ─────────────────────────────────────────────────────────────────────

def mode_print(path: str, cfg: Config, token: str | None = None) -> None:
    if is_github_url(path):
        print(generate_github_output(path, cfg, token))
    else:
        print(generate_output(path, cfg))


def mode_save(path: str, cfg: Config, token: str | None = None) -> None:
    if is_github_url(path):
        output = generate_github_output(path, cfg, token)
        # Save next to cwd for GitHub URLs
        out_file = Path.cwd() / _output_filename(cfg)
    else:
        root = Path(path).resolve()
        output = generate_output(path, cfg)
        out_file = root / _output_filename(cfg)

    print(output)
    out_file.write_text(output, encoding="utf-8")
    print(f"\n✔  Saved → {out_file}")


def mode_copy(path: str, cfg: Config, token: str | None = None) -> None:
    if is_github_url(path):
        output = generate_github_output(path, cfg, token)
    else:
        output = generate_output(path, cfg)

    print(output)
    if _copy_to_clipboard(output):
        print("\n✔  Copied to clipboard")
    else:
        print(
            "\n✘  Could not copy to clipboard.\n"
            "   Install pyperclip for cross-platform support:  pip install pyperclip"
        )


def mode_serve(path: str, cfg: Config, host: str = "localhost", port: int = 8080) -> None:
    """
    Launch the AITree Web UI — an interactive browser-based tree explorer.

    Opens http://host:port in the default browser and serves:
      - An interactive, collapsible file tree
      - File content preview (click any file)
      - Project statistics
      - Live reload (tree refreshes automatically on filesystem changes)

    Uses only stdlib (http.server) — no extra dependencies required.
    """
    try:
        from .web import start_server
    except ImportError as e:
        print(f"[ERROR] Could not load web module: {e}", file=sys.stderr)
        sys.exit(1)
    start_server(path, cfg, host=host, port=port)


def mode_diff(path: str, ref: str, cfg: Config) -> None:
    """
    Compare the current directory with a git ref or another directory.

    ref examples:
      HEAD~1          previous commit
      main            another branch
      abc1234         commit hash
      ./other-dir     another local directory
    """
    import tempfile
    from .core import _human_size

    root = Path(path).resolve()
    if not root.exists():
        print(f"[ERROR] Path not found: {path}", file=sys.stderr)
        sys.exit(1)

    # ── Resolve reference: directory or git ref? ─────────────────────────────
    ref_path = Path(ref).resolve()

    if ref_path.exists() and ref_path.is_dir():
        # Direct directory comparison
        result = diff_trees(root, ref_path, cfg)
        ref_label = str(ref_path)
        _print_diff(result, ref_label, cfg)
        return

    # Git ref — extract to temporary directory
    print(f"📦  Extracting git ref '{ref}'…")
    with tempfile.TemporaryDirectory(prefix="aitree_diff_") as tmpdir:
        tmp_path = Path(tmpdir)
        ok = extract_git_ref(root, ref, tmp_path)

        if not ok:
            print(
                f"[ERROR] Could not resolve '{ref}'.\n"
                f"  • If git ref: ensure it is a valid commit/branch/tag\n"
                f"  • If directory: path must exist\n"
                f"  • Is Git installed? Check with 'git --version'",
                file=sys.stderr,
            )
            sys.exit(1)

        result = diff_trees(root, tmp_path, cfg)

    _print_diff(result, ref, cfg)


def _print_diff(result: DiffResult, ref_label: str, cfg: Config) -> None:
    """Show DiffResult as colorful terminal output."""
    from .core import _human_size

    # ANSI color codes — degrades gracefully if terminal doesn't support them
    GREEN  = "\033[32m"
    RED    = "\033[31m"
    YELLOW = "\033[33m"
    BLUE   = "\033[34m"
    RESET  = "\033[0m"
    BOLD   = "\033[1m"

    # Enable ANSI support on Windows
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleMode(
                ctypes.windll.kernel32.GetStdHandle(-11), 7
            )
        except Exception:
            GREEN = RED = YELLOW = BLUE = RESET = BOLD = ""

    divider = "─" * 52
    print(f"\n{BOLD}Diff vs {ref_label}{RESET}")
    print(divider)

    if result.is_empty:
        print("  No differences found.")
        print(divider)
        return

    if result.added:
        print(f"\n  {GREEN}+ Added ({len(result.added)}){RESET}")
        for f in result.added:
            print(f"    {GREEN}+{RESET} {f}")

    if result.removed:
        print(f"\n  {RED}− Removed ({len(result.removed)}){RESET}")
        for f in result.removed:
            print(f"    {RED}−{RESET} {f}")

    if result.grown:
        print(f"\n  {YELLOW}↑ Grown ({len(result.grown)}){RESET}")
        for f, old_sz, new_sz in result.grown:
            delta = new_sz - old_sz
            print(f"    {YELLOW}↑{RESET} {f}  "
                  f"{_human_size(old_sz)} → {_human_size(new_sz)}  "
                  f"({YELLOW}+{_human_size(delta)}{RESET})")

    if result.shrunk:
        print(f"\n  {BLUE}↓ Shrunk ({len(result.shrunk)}){RESET}")
        for f, old_sz, new_sz in result.shrunk:
            delta = old_sz - new_sz
            print(f"    {BLUE}↓{RESET} {f}  "
                  f"{_human_size(old_sz)} → {_human_size(new_sz)}  "
                  f"({BLUE}−{_human_size(delta)}{RESET})")

    print(f"\n{divider}")
    parts = []
    if result.added:   parts.append(f"{GREEN}+{len(result.added)} added{RESET}")
    if result.removed: parts.append(f"{RED}−{len(result.removed)} removed{RESET}")
    if result.grown:   parts.append(f"{YELLOW}↑{len(result.grown)} grown{RESET}")
    if result.shrunk:  parts.append(f"{BLUE}↓{len(result.shrunk)} shrunk{RESET}")
    print("  " + "  ".join(parts))
    print()


def mode_stats(path: str, cfg: Config) -> None:
    """Return only statistics instead of a tree."""
    from .core import collect_stats, _human_size

    root = Path(path).resolve()
    if not root.exists():
        print(f"[ERROR] Path not found: {path}", file=sys.stderr)
        sys.exit(1)
    if not root.is_dir():
        print(f"[ERROR] Not a directory: {path}", file=sys.stderr)
        sys.exit(1)

    cfg.load_gitignore(root)
    stats = collect_stats(root, cfg)

    # ── JSON output ───────────────────────────────────────────────────────────
    if cfg.output_format == "json":
        import json
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
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    # ── Text output ───────────────────────────────────────────────────────────
    divider = "─" * 44
    print(f"\n{root}")
    print(divider)
    print(f"  {'Directories':<14} {stats['total_dirs']:>6}")
    print(f"  {'Files':<14} {stats['total_files']:>6}")
    print(f"  {'Total size':<14} {_human_size(stats['total_size']):>6}")

    if stats["ext_count"]:
        print(f"\n  {'Extension':<14} {'Count':>5}  {'Size':>7}  Distribution")
        print(f"  {divider}")
        max_count = max(stats["ext_count"].values())
        for ext, count in list(stats["ext_count"].items())[:15]:
            bar_len  = round(count / max_count * 18)
            bar      = "█" * bar_len
            size_str = _human_size(stats["ext_size"].get(ext, 0))
            print(f"  {ext:<14} {count:>5}  {size_str:>7}  {bar}")

    print()



def mode_live(path: str, cfg: Config, token: str | None = None) -> None:
    if is_github_url(path):
        print("[ERROR] --live mode is not supported for GitHub URLs.")
        print("        Use a local path with --live, or omit --live for GitHub URLs.")
        sys.exit(1)

    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        print("[ERROR] Live mode requires the 'watchdog' package.")
        print("Install it with:  pip install watchdog")
        sys.exit(1)

    root     = Path(path).resolve()
    out_file = root / _output_filename(cfg)

    state: dict = {
        "last_event_time": 0.0,
        "pending":         False,
        "last_snapshot":   "",
        "file_hashes":     {},
        "skipped":         0,
    }

    def refresh(reason: str, force: bool = False) -> None:
        new_snapshot = tree_snapshot(root, cfg)
        if not force and new_snapshot == state["last_snapshot"]:
            state["skipped"] += 1
            return
        state["last_snapshot"] = new_snapshot
        output = generate_output(path, cfg)
        out_file.write_text(output, encoding="utf-8")
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        skip_note = f"  ({state['skipped']} false events skipped)" if state["skipped"] else ""
        print(f"[{ts}] Updated — {reason}{skip_note}")
        state["skipped"] = 0

    class Handler(FileSystemEventHandler):
        def dispatch(self, event):
            src = str(event.src_path)
            if out_file.name in src:
                return
            src_path = Path(src)
            from .core import should_ignore, DEFAULT_IGNORE_DIRS
            if should_ignore(src_path):
                return
            if any(part in DEFAULT_IGNORE_DIRS for part in src_path.parts):
                return
            if event.event_type == "modified" and src_path.is_file():
                new_hash = file_hash(src_path)
                if new_hash == state["file_hashes"].get(src):
                    state["skipped"] += 1
                    return
                state["file_hashes"][src] = new_hash
            state["last_event_time"] = time.time()
            state["pending"] = True

        def on_any_event(self, event):
            pass

    def flush_loop() -> None:
        debounce = 1.0
        while True:
            time.sleep(0.2)
            if state["pending"] and (time.time() - state["last_event_time"]) >= debounce:
                state["pending"] = False
                refresh("filesystem change")

    state["last_snapshot"] = tree_snapshot(root, cfg)
    for p in root.rglob("*"):
        if p.is_file():
            state["file_hashes"][str(p)] = file_hash(p)

    out_file.write_text(generate_output(path, cfg), encoding="utf-8")
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] Updated — initial snapshot")

    threading.Thread(target=flush_loop, daemon=True).start()

    observer = Observer()
    observer.schedule(Handler(), str(root), recursive=True)
    observer.start()

    active = []
    if cfg.depth is not None:       active.append(f"depth={cfg.depth}")
    if cfg.git_changed:             active.append("git-changed")
    if cfg.output_format != "text": active.append(f"format={cfg.output_format}")
    if cfg.include:                 active.append(f"include={','.join(cfg.include)}")
    if cfg.exclude:                 active.append(f"exclude={','.join(cfg.exclude)}")
    active_str = f"  [{', '.join(active)}]" if active else ""

    print(f"\n🟢  AITree LIVE — Watching: {root}{active_str}")
    print(f"    Updates trigger only on real changes.")
    print(f"    Press Ctrl+C to stop.\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        print("\n🔴  AITree stopped.")
    observer.join()


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="aitree",
        description="AITree — project file map generator for AI-assisted development",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  aitree .                              print tree of current directory
  aitree . --save                       save to _aitree.txt
  aitree . --copy                       copy output to clipboard
  aitree . --depth 2                    show only top 2 levels
  aitree . --include "*.py"             show only Python files
  aitree . --exclude "*.test.*"         hide test files
  aitree . --git-changed                show only modified/untracked files
  aitree . --format json                output as JSON
  aitree . --format markdown --save     save as _aitree.md
  aitree . --tokens                     append estimated token count
  aitree . --serve                             launch interactive web UI
  aitree . --serve --port 3000                 web UI on port 3000

  aitree . --live                       watch for changes

  aitree . --diff HEAD~1                        compare with previous commit
  aitree . --diff main                          compare with another branch
  aitree . --diff ./other-dir                   compare with another directory
  aitree . --diff HEAD~1 --include "*.py"       diff only Python files

  aitree . --stats                              show project statistics
  aitree . --stats --format json                stats as JSON
  aitree . --stats --include "*.py"             stats for Python files only

  aitree https://github.com/owner/repo               scan a GitHub repo
  aitree https://github.com/owner/repo/tree/main/src subpath only
  aitree https://github.com/owner/repo --depth 2     limit depth
  aitree https://github.com/owner/repo --copy        copy to clipboard
  aitree https://github.com/owner/repo --token TOKEN private repo
        """,
    )

    parser.add_argument("path", nargs="?", default=".",
        help="Directory to scan, or a GitHub URL (default: current directory)")

    # Output modes — mutually exclusive.
    out_group = parser.add_mutually_exclusive_group()
    out_group.add_argument("--save",  action="store_true",
        help="Save output to file")
    out_group.add_argument("--copy",  action="store_true",
        help="Copy output to clipboard")
    out_group.add_argument("--live",  action="store_true",
        help="Watch for changes and auto-update (local only)")

    # Format
    parser.add_argument("--format", choices=["text", "json", "markdown"], default="text",
        metavar="FMT", help="Output format: text (default), json, markdown")

    # Filtering
    parser.add_argument("--depth", type=int, metavar="N",
        help="Limit tree depth (e.g. --depth 2)")
    parser.add_argument("--include", action="append", metavar="GLOB", default=[],
        help="Show only files matching GLOB (repeatable)")
    parser.add_argument("--exclude", action="append", metavar="GLOB", default=[],
        help="Hide files matching GLOB (repeatable)")
    parser.add_argument("--no-gitignore", action="store_true",
        help="Skip .gitignore and .aitreeignore (local only)")
    parser.add_argument("--git-changed", action="store_true",
        help="Show only git-changed/untracked files (local only, requires gitpython)")

    # GitHub
    parser.add_argument("--token", metavar="TOKEN",
        help="GitHub personal access token for private repos (or set GITHUB_TOKEN env var)")

    # Extra
    parser.add_argument("--diff", metavar="REF",
        help="Compare tree against a git ref (HEAD~1, branch, hash) or another directory")
    parser.add_argument("--stats", action="store_true",
        help="Show project statistics instead of tree (--format json for JSON output)")
    parser.add_argument("--tokens", action="store_true",
        help="Append estimated token count (requires tiktoken)")

    # Web UI
    parser.add_argument("--serve", action="store_true",
        help="Launch the interactive web UI in the browser (local paths only)")
    parser.add_argument("--port", type=int, default=8080, metavar="PORT",
        help="Port for the web UI server (default: 8080)")
    parser.add_argument("--host", default="localhost", metavar="HOST",
        help="Host for the web UI server (default: localhost)")

    parser.add_argument("--version", action="version", version="AITree 3.1.0")

    args = parser.parse_args()

    # ── Load .aitree.toml (skip for GitHub URLs) ──────────────────────────────
    project_cfg: dict = {}
    if not is_github_url(args.path):
        project_cfg = load_project_config(Path(args.path).resolve())

    # Use CLI argument if provided, else from config, else default.
    # Rule: CLI > .aitree.toml > argparse default
    def _cfg(cli_val, key, default=None):
        if cli_val is not None and cli_val is not False and cli_val != []:
            return cli_val
        return project_cfg.get(key, default)

    cfg = Config(
        depth         = args.depth        if args.depth is not None
                        else project_cfg.get("depth"),
        include       = args.include      or project_cfg.get("include", []),
        exclude       = args.exclude      or project_cfg.get("exclude", []),
        no_gitignore  = args.no_gitignore or project_cfg.get("no_gitignore", False),
        git_changed   = args.git_changed  or project_cfg.get("git_changed", False),
        output_format = args.format       if args.format != "text"
                        else project_cfg.get("format", "text"),
        tokens        = args.tokens       or project_cfg.get("tokens", False),
    )

    token = _resolve_token(args.token)

    if args.serve:
        if is_github_url(args.path):
            print("[ERROR] --serve does not support GitHub URLs (local paths only).", file=sys.stderr)
            sys.exit(1)
        mode_serve(args.path, cfg, host=args.host, port=args.port)
    elif args.live:
        mode_live(args.path, cfg, token)
    elif args.diff:
        mode_diff(args.path, args.diff, cfg)
    elif args.stats:
        mode_stats(args.path, cfg)
    elif args.save:
        mode_save(args.path, cfg, token)
    elif args.copy:
        mode_copy(args.path, cfg, token)
    else:
        mode_print(args.path, cfg, token)


if __name__ == "__main__":
    main()