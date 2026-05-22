# Contributing to Meli

Meli is a personal project by Joseph Sierengowski. Pull requests for bug fixes, new parsers, and enrichment services are welcome.

**Repository:** [github.com/sierengowskisierengowski-cpu/Meli](https://github.com/sierengowskisierengowski-cpu/Meli)

## Development Setup

```bash
git clone https://github.com/sierengowskisierengowski-cpu/Meli
cd Meli

# System dependencies (GTK4, PyGObject, Mosquitto)
sudo ./install.sh --phase 1

# Python dev environment
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -e .

# Run tests
python -m pytest tests/ -v

# Launch the GUI
python -m meli

# Launch the ingest daemon only
python -m meli --daemon ingest

# Launch Atrium kiosk mode
python -m meli --kiosk

# Debug mode (verbose logging)
python -m meli --debug
```

## Adding a Honeypot Parser

1. Create `meli/ingest/parsers/yourparser.py`
2. Implement a class with a `parse(raw: dict) -> dict | None` method
3. Return a dict with these keys (any subset):
   ```python
   {
       "honeypot_service": str,      # Required
       "timestamp": datetime,        # Required
       "source_ip": str,             # Required
       "source_port": int | None,
       "destination_port": int | None,
       "protocol": str,
       "transport": str,
       "session_id": str | None,
       "action_type": str,
       "username": str | None,
       "password": str | None,
       "command": str | None,
       "payload_hash": str | None,
   }
   ```
4. Register in `meli/ingest/parsers/__init__.py`
5. Add tests in `tests/test_parsers.py`

## Adding an Enrichment Service

1. Create `meli/enrichment/yourservice.py`
2. Implement `query_yourservice(ip: str) -> dict | None`
3. Use `get_cached()` / `set_cached()` from `meli.enrichment.cache`
4. Read API key from `get_config().get("enrichment", "services", "yourservice", "api_key")`
5. Add the service to `enrich_ip()` in `meli/enrichment/__init__.py`
6. Add config defaults in `meli/config.py` under `DEFAULTS["enrichment"]["services"]`
7. Add settings UI in `meli/ui/views/settings.py` under `_build_enrichment_apis()`

## Adding a Notification Channel

1. Create `meli/alerts/notifiers/yournotifier.py`
2. Implement `notify(rule_name, summary, severity) -> None`
3. Import in `meli/alerts/notifiers/__init__.py`
4. Register in `meli/alerts/engine.py` in `_send_notifications()`
5. Add settings UI in `meli/ui/views/settings.py` under `_build_alerts_and_notifications()`

## Code Style

- Python 3.12+, type hints everywhere
- `structlog` for logging (no `print()`)
- SQLAlchemy 2.x style (no legacy `session.query()`)
- GTK4/libadwaita only (no deprecated GTK3 widgets)
- All DB operations in background threads + `GLib.idle_add()` for UI updates
- PEP 8, max line length 120

## Testing

```bash
# All tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=meli --cov-report=term-missing

# Specific test file
pytest tests/test_parsers.py -v

# Skip slow tests
pytest tests/ -m "not slow"
```

## Filing Issues

Please include:
- Your Linux distribution and version
- GTK4 / libadwaita version (`gtk4-demo --version`)
- Python version (`python3 --version`)
- Honeypot type and version
- Relevant log lines from `journalctl --user -u meli-ingest -n 50`
- Steps to reproduce
