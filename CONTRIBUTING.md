# Contributing

Thanks for your interest in contributing to Markdown Tools!

## Setup

1. Clone the repository and install dependencies:

```bash
git clone https://github.com/alexandermeyer2026/markdown-tools.git
cd markdown-tools
poetry install
```

2. Set up your journal directory for testing:

```bash
export JOURNAL_DIR=/path/to/your/journal
```

## Running Tests

```bash
poetry run pytest
```

## Adding a New Tool

Tools live in `tools/` or in a module-specific subdirectory (e.g. `tools/journal_tools/`). Each tool should:

- Be self-contained and focused on a single task
- Accept its inputs via the CLI in `main.py`
- Have corresponding tests under `tests/`

## Submitting a Pull Request

1. Fork the repository and create a branch from `main`
2. Make your changes and ensure tests pass
3. Open a pull request with a clear description of what it does and why

## Code Style

- Follow standard Python conventions (PEP 8)
- Keep functions small and focused
- No comments unless the reason behind something is non-obvious
