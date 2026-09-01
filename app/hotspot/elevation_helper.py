from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.hotspot.windows import configure_adapter, configure_and_start_hosted_network, stop_hosted_network


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="action", required=True)

    start = subparsers.add_parser("start")
    start.add_argument("--request", required=True)
    start.add_argument("--marker", required=True)

    stop = subparsers.add_parser("stop")
    stop.add_argument("--marker", required=True)

    args = parser.parse_args()
    marker = Path(args.marker)
    try:
        if args.action == "start":
            request_path = Path(args.request)
            request = json.loads(request_path.read_text(encoding="utf-8"))
            adapter = configure_and_start_hosted_network(request["ssid"], request["password"])
            configure_adapter(adapter.name, request["gateway_ip"])
            payload = {"ok": True, "adapter_name": adapter.name, "gateway_ip": request["gateway_ip"]}
        else:
            stop_hosted_network()
            payload = {"ok": True}
    except Exception as exc:
        payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    marker.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
