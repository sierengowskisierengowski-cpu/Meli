# Honeypot Integration Guide

This guide covers connecting each supported honeypot type to Meli.

## Event Format

### Canonical Meli Format

Send JSON with this structure for the cleanest parsing:

```json
{
  "timestamp": "2024-01-15T12:00:00Z",
  "network": {
    "source_ip": "1.2.3.4",
    "source_port": 54321,
    "destination_port": 22,
    "protocol": "tcp",
    "transport": "ssh"
  },
  "honeypot": {
    "type": "cowrie",
    "name": "my-vps-cowrie"
  },
  "action": {
    "type": "login_attempt",
    "details": {
      "username": "root",
      "password": "toor"
    }
  },
  "session": {
    "session_id": "abc123def456"
  }
}
```

Action types: `connection`, `login_attempt`, `successful_auth`, `command`,
`file_download`, `file_upload`, `port_forward`, `session_close`, `web_request`,
`smtp_probe`, `unknown`.

---

## Cowrie (SSH/Telnet Honeypot)

Cowrie natively outputs JSON in a format Meli understands.

### Via MQTT (recommended)

Install Cowrie's MQTT output plugin:

```bash
pip install paho-mqtt  # inside Cowrie's venv
```

In `etc/cowrie.cfg`:
```ini
[output_mqtt]
enabled = true
host = 127.0.0.1
port = 1883
topic = meli/events/ingest
qos = 1
# No auth needed for local Mosquitto
```

Restart Cowrie:
```bash
systemctl restart cowrie
# or
bin/cowrie restart
```

### Via log file forwarding

Use `mosquitto_pub` to forward from the JSON log:

```bash
# One-liner forwarder (add to crontab or systemd timer)
tail -n 0 -F /opt/cowrie/var/log/cowrie/cowrie.json | \
  mosquitto_pub -h 127.0.0.1 -t meli/events/ingest -l
```

Or use the `cowrie_to_meli.py` helper in `meli/scripts/`:
```bash
python3 meli/scripts/cowrie_to_meli.py --log /opt/cowrie/var/log/cowrie/cowrie.json
```

---

## Heralding (Multi-Service Credential Capture)

Heralding supports JSON log output.

In `heralding.yml`:
```yaml
output_plugins:
  - type: json_log
    filename: /var/log/heralding/heralding.json
```

Forward events:
```bash
tail -n 0 -F /var/log/heralding/heralding.json | \
  mosquitto_pub -h 127.0.0.1 -t meli/events/ingest -l
```

Or add a custom output plugin that POSTs directly (see `scripts/heralding_webhook.py`).

---

## Dionaea (Malware Capture)

Dionaea logs to SQLite by default. Use the bridge script:

```bash
python3 meli/scripts/dionaea_bridge.py \
  --db /opt/dionaea/var/dionaea/logsql.sqlite \
  --meli-url http://127.0.0.1:17654/api/v1/events/ingest \
  --token YOUR_INGEST_TOKEN
```

Or configure Dionaea's HPFEED output plugin to publish to your Mosquitto instance.

---

## HTTP Honeypots (Snare/Tanner, nginx)

### Snare/Tanner

Snare → Tanner can be configured to POST to Meli directly via a custom reporter:

```python
# In tanner/reporter/meli_reporter.py
import requests
requests.post("http://127.0.0.1:17654/api/v1/events/ingest",
              headers={"Authorization": "Bearer TOKEN"},
              json=event_data)
```

### Custom nginx honeypot

Log in JSON format and forward:

```nginx
log_format meli_json escape=json '{'
  '"timestamp":"$time_iso8601",'
  '"remote_addr":"$remote_addr",'
  '"method":"$request_method",'
  '"path":"$request_uri",'
  '"status":$status,'
  '"user_agent":"$http_user_agent"'
  '}';

access_log /var/log/nginx/meli.json meli_json;
```

Then:
```bash
tail -n 0 -F /var/log/nginx/meli.json | \
  mosquitto_pub -h 127.0.0.1 -t meli/events/ingest -l
```

---

## Remote Honeypots (Different Server)

If your honeypot runs on a different machine:

1. Expose the Meli HTTP ingest endpoint (change `http_ingest.host` to `0.0.0.0`)
2. Use a firewall rule to restrict access to trusted IPs only
3. Send events with Bearer token authentication

Or set up MQTT federation:
```bash
# On the honeypot server, bridge its local Mosquitto to your Meli server
# In /etc/mosquitto/conf.d/meli_bridge.conf:
connection meli-bridge
address MELI_SERVER_IP:1883
topic meli/events/ingest out 1
```

---

## Testing the Connection

```bash
# Test HTTP ingest
curl -X POST http://127.0.0.1:17654/api/v1/events/ingest \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "network": {"source_ip": "203.0.113.1", "destination_port": 22},
    "honeypot": {"type": "cowrie"},
    "action": {"type": "login_attempt",
                "details": {"username": "root", "password": "qwerty"}},
    "timestamp": "'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'"
  }'

# Test MQTT
mosquitto_pub -h 127.0.0.1 -t meli/events/ingest -m '{
  "src_ip": "203.0.113.1",
  "eventid": "cowrie.login.failed",
  "username": "admin",
  "password": "admin123",
  "timestamp": "2024-01-15T12:00:00Z"
}'
```

Events should appear in Meli's Live Feed within seconds.
