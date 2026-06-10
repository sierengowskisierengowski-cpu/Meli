#!/usr/bin/env python3
"""
cowrie_to_meli.py — Forward Cowrie JSON log to Meli ingest.
Watches the Cowrie JSON log file and publishes new events to Meli.

Usage:
    python3 cowrie_to_meli.py --log /opt/cowrie/var/log/cowrie/cowrie.json
    python3 cowrie_to_meli.py --log /opt/cowrie/var/log/cowrie/cowrie.json \
        --mode http --url http://127.0.0.1:17654/api/v1/events/ingest \
        --token YOUR_TOKEN
"""
import sys
import json
import time
import argparse
import subprocess


def tail_file(path):
    """Generator that yields new lines as they are appended."""
    import os
    with open(path, "r") as f:
        f.seek(0, os.SEEK_END)
        while True:
            line = f.readline()
            if not line:
                time.sleep(0.1)
                continue
            yield line.strip()


def publish_mqtt(event: dict, host: str, port: int, topic: str) -> None:
    import paho.mqtt.publish as publish
    publish.single(topic=topic, payload=json.dumps(event), hostname=host, port=port, qos=1)


def publish_http(event: dict, url: str, token: str) -> None:
    import requests
    requests.post(url, json=event, headers={"Authorization": f"Bearer {token}"}, timeout=5)


def main():
    parser = argparse.ArgumentParser(description="Forward Cowrie JSON log to Meli")
    parser.add_argument("--log", required=True, help="Path to cowrie.json log file")
    parser.add_argument("--mode", default="mqtt", choices=["mqtt", "http"])
    parser.add_argument("--host", default="127.0.0.1", help="MQTT broker host")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--topic", default="meli/events/ingest")
    parser.add_argument("--url", default="http://127.0.0.1:17654/api/v1/events/ingest")
    parser.add_argument("--token", default="", help="Meli ingest token")
    args = parser.parse_args()

    print(f"[cowrie_to_meli] Watching {args.log} (mode={args.mode})")
    count = 0
    for line in tail_file(args.log):
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            if args.mode == "mqtt":
                publish_mqtt(event, args.host, args.port, args.topic)
            else:
                publish_http(event, args.url, args.token)
            count += 1
            if count % 100 == 0:
                print(f"[cowrie_to_meli] Forwarded {count} events")
        except Exception as e:
            print(f"[cowrie_to_meli] Error: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
