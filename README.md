# Markdown Tools

A modular toolset for editing and managing knowledge and tasks in markdown files. Instead of relying on heavy-weight project management software, this project provides a collection of independent tools that work with plain markdown files, the universal format that works everywhere.

## Philosophy

Markdown is the lingua franca of knowledge management. It's human-readable, version-controllable, and compatible with virtually every tool and platform. By building tools that operate on markdown files, you create solutions that are:

- **Cross-software compatible**: Import/export to Notion, Obsidian, GitHub, and countless other platforms are possible
- **Future-proof**: Your data isn't locked into proprietary formats
- **Modular**: Each tool solves a specific problem independently
- **Extensible**: Anyone can contribute new tools that work with the same markdown files

## Why Markdown Tools?

Traditional project management software often comes with:

- Vendor lock-in
- Complex interfaces that get in the way
- Limited customization
- High costs
- Data silos

Markdown Tools takes a different approach: your data lives in markdown files that you control, and tools are built around your workflow, not the other way around.

## Installation

### Requirements

- Python 3.10+
- [Poetry](https://python-poetry.org/) for dependency management

### Setup

1. Clone the repository:

```bash
git clone https://github.com/alexandermeyer2026/markdown-tools.git
cd markdown-tools
```

2. Install dependencies with Poetry:

```bash
poetry install
```

3. Run commands via Poetry:

```bash
poetry run python3 main.py journal today
```

## Quick Start

The project provides a command-line interface for various tools:

```bash
poetry run python3 main.py journal today
poetry run python3 main.py journal timeline [file]
poetry run python3 main.py journal catch-up
poetry run python3 main.py journal planner
poetry run python3 main.py journal update
```

Set the journal directory via the `JOURNAL_DIR` environment variable:

```bash
export JOURNAL_DIR=/path/to/your/journal
```

For easier use, add the following to your `.zshrc` or `.bashrc`:

```bash
JOURNAL_DIR="$HOME/path/to/your/journal"

md-tools() {
    poetry run --directory ~/path/to/markdown-tools \
    python3 ~/path/to/markdown-tools/main.py "$@"
}

journal() {
    JOURNAL_DIR="$JOURNAL_DIR" md-tools journal "$@"
}
```

## Available Tools

All tools operate on the `journal` command and are designed to work independently:

| Command | Description |
|---|---|
| `journal <date>` | Open a journal file for a specific date in Vim |
| `journal today` | Open today's journal file |
| `journal timeline [file]` | Visual timeline of tasks across journal files |
| `journal catch-up` | Step through past journal files with unresolved tasks |
| `journal planner` | Interactive planner for scheduling tasks |
| `journal update` | Dashboard overview of open and upcoming tasks |

## Project Structure

```
markdown-tools/
├── main.py                 # Main entry point and CLI
├── config/                 # YAML configuration (task patterns, etc.)
├── models/                 # Data models
├── parser/                 # Markdown parsing utilities
├── os_utils/               # File system utilities
└── tools/                  # Tool implementations
    └── journal_tools/      # Journal tools (timeline, catch-up, planner, update)
```

## Contributing

This project thrives on community contributions. The modular architecture means you can:

- Build new tools that solve your specific problems
- Share tools that others might find useful
- Improve existing tools
- Create import/export integrations with other platforms

Everyone's workflow is different, and everyone's contributions make the ecosystem richer.

### Areas for Contribution

- New tools for specific use cases
- Import/export integrations (Notion, Obsidian, etc.)
- Documentation and examples
- Tests and code quality improvements
- Bug fixes and feature enhancements

## License

MIT – see [LICENSE](LICENSE) for details.

## Vision

Knowledge and task management shouldn't be constrained by software limitations. Every tool you need, working with files you control, in formats that will outlast any software vendor.
