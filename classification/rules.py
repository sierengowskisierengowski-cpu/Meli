"""Rule loading for the classification engine."""
from __future__ import annotations

import yaml
import structlog
from pathlib import Path

log = structlog.get_logger()

_DEFAULT_RULES_FILE = Path(__file__).parent / "default_rules.yaml"


class RuleLoader:
    """Loads and caches classification rules from YAML files."""

    def __init__(self) -> None:
        self._rules: list[dict] = []
        self._loaded = False

    def get_rules(self) -> list[dict]:
        if not self._loaded:
            self.reload()
        return self._rules

    def reload(self) -> None:
        rules = []

        # Load default rules
        if _DEFAULT_RULES_FILE.exists():
            try:
                with open(_DEFAULT_RULES_FILE) as f:
                    data = yaml.safe_load(f)
                    rules.extend(data.get("rules", []))
                log.debug("Default classification rules loaded", count=len(rules))
            except Exception as e:
                log.error("Failed to load default rules", error=str(e))

        # Load user custom rules from DB
        try:
            rules.extend(self._load_db_rules())
        except Exception as e:
            log.debug("Could not load custom rules from DB", error=str(e))

        self._rules = [r for r in rules if r.get("conditions")]
        self._loaded = True

    def _load_db_rules(self) -> list[dict]:
        """Load user-defined rules stored in the database."""
        import json
        from meli.database import get_db
        from meli.database.models import AlertRule
        from sqlalchemy import select

        db_rules = []
        with get_db() as db:
            rows = db.execute(
                select(AlertRule).where(AlertRule.enabled == True)
            ).scalars().all()
            for row in rows:
                if row.conditions:
                    try:
                        conds = json.loads(row.conditions)
                        db_rules.append({
                            "name": row.name,
                            "severity": row.severity_threshold,
                            "priority": 99,
                            "conditions": conds,
                        })
                    except Exception:
                        pass
        return db_rules

    def invalidate(self) -> None:
        self._loaded = False
