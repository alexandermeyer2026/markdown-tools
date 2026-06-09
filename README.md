# Markdown Tools

## What is this?

markdown-tools is a modular command-line toolkit for working with data stored
in plain markdown files.

Markdown is human-readable, version-controllable, and supported everywhere.
This project provides tools that operate directly on `.md` files — so your data
stays accessible and portable, independent of any specific application.

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

Tools are designed to work independently:

| Command | Description |
|---|---|
| `journal <date>` | Open a journal file in Vim (`today`, `yesterday`, `tomorrow`, or `YYYY-MM-DD`) |
| `journal timeline <file>` | Visual timeline of a day's tasks |
| `journal catch-up` | Step through past journal files with unresolved tasks |
| `journal planner` | Interactive planner for scheduling tasks |
| `journal update` | Dashboard overview of open and upcoming tasks |
| `journal time-machine <file>` | Browse and restore previous versions of a file |
| `journal sync` | Push and pull files to a self-hosted server |

## Project Structure

```
markdown-tools/
├── main.py                 # Main entry point and CLI
├── config/                 # YAML configuration (task patterns, etc.)
├── models/                 # Data models
├── parser/                 # Markdown parsing utilities
├── os_utils/               # File system utilities
├── tools/                  # Tool implementations
│   └── journal_tools/      # Journal tools (timeline, catch-up, planner, update)
└── webapp/                 # Optional self-hosted web interface
    ├── backend/            # FastAPI backend
    ├── frontend/           # React frontend
    └── nginx/              # Nginx reverse proxy config
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

Your data should be accessible and long-lived, independent of any application. Every tool you need, working with files you control, in a format that works everywhere.
