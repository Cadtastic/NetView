# netview

A plugin-based LAN monitor with a local web UI, built with Clean Architecture
(domain, application, infrastructure, presentation, plus a public plugin SDK).

## Development

```bash
uv sync
uv run pytest -q
uv run ruff check .
uv run mypy
uv run lint-imports
```
