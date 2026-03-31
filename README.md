# AITree

**Project file map generator for AI-assisted development.**

Scans a directory and prints a clean, annotated tree that you can paste directly into any AI chat. Instead of uploading your entire codebase, share the map first — then only send the files the AI actually asks for.

```
webapp/
├── src/
│   ├── components/
│   │   ├── Header.jsx  [4KB]
│   │   └── Footer.jsx  [2KB]
│   ├── App.jsx  [8KB]
│   └── index.js  [1KB]
├── public/
│   └── index.html  [3KB]
└── package.json  [1KB]

# 2 directories, 6 files  (18KB total)
#
# File types:
#   .jsx          3   ███
#   .js           1   █
#   .html         1   █
#   .json         1   █
```

---

## Installation

**Via pip (recommended):**
```bash
pip install paracci-aitree
```

**One-liner (Linux / macOS):**
```bash
curl -fsSL https://raw.githubusercontent.com/paracci/aitree/main/install.sh | bash
```

**One-liner (Windows PowerShell):**
```powershell
irm https://raw.githubusercontent.com/paracci/aitree/main/install.ps1 | iex
```

**From source:**
```bash
git clone https://github.com/paracci/aitree.git
cd aitree
pip install .
```

**Optional dependencies** — install only what you need:

```bash
pip install "paracci-aitree[live]"    # --live mode  (watchdog)
pip install "paracci-aitree[tokens]"  # --tokens     (tiktoken)
pip install "paracci-aitree[git]"     # --git-changed (gitpython)
pip install "paracci-aitree[mcp]"     # MCP server   (mcp)
pip install "paracci-aitree[all]"     # everything + clipboard (pyperclip)
```

---

## Usage

```bash
aitree [path] [options]
```

`path` defaults to the current directory if omitted.

### Output modes

| Flag | Description |
|---|---|
| *(none)* | Print tree to stdout |
| `--save` | Save to `_aitree.txt` (or `_aitree.json` / `_aitree.md`) |
| `--copy` | Copy output to clipboard |
| `--live` | Watch for changes and auto-update the saved file |
| `--serve` | Launch the web UI in your browser |

### Output formats

| Flag | Description |
|---|---|
| `--format text` | Plain text with `#` comments *(default)* |
| `--format json` | Structured JSON with tree + stats + meta |
| `--format markdown` | Markdown with fenced code block + stats table |

### Filtering

| Flag | Description |
|---|---|
| `--depth N` | Limit tree depth (e.g. `--depth 2`) |
| `--include GLOB` | Show only matching files (repeatable) |
| `--exclude GLOB` | Hide matching files (repeatable) |
| `--no-gitignore` | Skip `.gitignore` / `.aitreeignore` parsing |
| `--git-changed` | Show only git-changed / untracked files |

### Extras

| Flag | Description |
|---|---|
| `--tokens` | Append estimated token count to output |
| `--version` | Show version and exit |

---

## Examples

```bash
aitree .                                    # current directory → stdout
aitree ~/projects/webapp                    # specific path → stdout
aitree . --save                             # save to _aitree.txt
aitree . --copy                             # copy to clipboard
aitree . --depth 2                          # top 2 levels only
aitree . --include "*.py"                   # Python files only
aitree . --include "*.py" --include "*.js"  # multiple patterns
aitree . --exclude "*.test.*"               # hide test files
aitree . --git-changed                      # only modified/untracked files
aitree . --format json --save               # save as _aitree.json
aitree . --format markdown --save           # save as _aitree.md
aitree . --tokens                           # append token count
aitree . --live                             # watch for changes
aitree . --live --depth 2 --git-changed     # live + depth + git filter
aitree . --serve                            # open web UI
aitree . --serve --port 8080                # web UI on a custom port
```

### AI workflow

```
1. aitree . --copy
2. Paste into your AI chat
3. Ask "Which files do you need?"
4. Send only those files
```

---

## Web UI

`--serve` launches a local web server and opens the tree in your browser.

- Interactive tree with collapse / expand
- Filter panel: depth, include, exclude, git-changed
- File content preview on click
- Live reload when the directory changes

```bash
aitree . --serve
aitree . --serve --port 8080
```

---

## MCP Server

AITree ships a [Model Context Protocol](https://modelcontextprotocol.io) server so AI assistants (Claude Desktop, etc.) can call it as a tool.

```bash
# Install MCP dependency
pip install "paracci-aitree[mcp]"

# Start the server
aitree-mcp
```

### Available tools

| Tool | Description |
|---|---|
| `aitree_get_tree` | Generate a file tree for a local path or GitHub URL |
| `aitree_get_stats` | Return structured JSON statistics for a path |
| `aitree_get_changed` | List git-changed / untracked files |
| `aitree_read_file` | Read the contents of a file inside the project |

`aitree_read_file` lets an AI assistant fetch any file it spotted in the tree — without leaving the conversation:

```
aitree_get_tree(path=".", format="text")
aitree_read_file(path=".", file="src/auth/login.py")
```

### Claude Desktop config (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "aitree": {
      "command": "aitree-mcp"
    }
  }
}
```

---

## GitHub URL support

Pass a GitHub repository URL instead of a local path:

```bash
aitree https://github.com/owner/repo
aitree https://github.com/owner/repo --depth 2
aitree https://github.com/owner/private-repo --token ghp_xxxx
```

Works entirely via the GitHub API — no cloning required.

---

## Custom ignore rules

Create `.aitreeignore` in your project root — same syntax as `.gitignore`:

```
# .aitreeignore
*.secret
config/local.json
private/
```

AITree reads `.aitreeignore` first, then `.gitignore`. Use `--no-gitignore` to skip both.

---

## What gets ignored by default

| Category | Examples |
|---|---|
| VCS & editors | `.git`, `.idea`, `.vscode`, `.svn` |
| Dependencies | `node_modules`, `.venv`, `venv`, `env` |
| Build output | `dist`, `build`, `target`, `out`, `bin` |
| Cache | `__pycache__`, `.pytest_cache`, `.mypy_cache` |
| Binary & temp | `.pyc`, `.class`, `.exe`, `.log`, `.tmp` |
| OS files | `.DS_Store`, `Thumbs.db` |

---

## Live mode

`--live` watches the directory with [watchdog](https://github.com/gorakhargosh/watchdog) and regenerates the output file whenever the structure actually changes. False positives (editor auto-saves, antivirus touches, etc.) are filtered out via content hashing and a 1-second debounce.

```
🟢  AITree LIVE — Watching: /home/user/projects/webapp  [depth=2, git-changed]
    Updates trigger only on real changes.
    Press Ctrl+C to stop.

[14:32:10] Updated — initial snapshot
[14:33:05] Updated — filesystem change  (3 false events skipped)
```

Combines with any filter flag: `--depth`, `--include`, `--exclude`, `--git-changed`.

---

## Platform support

| Platform | Tested |
|---|---|
| Linux | ✅ |
| macOS | ✅ |
| Windows | ✅ |
| WSL | ✅ |

Requires **Python 3.10+**.

---

## License

[MIT](LICENSE)