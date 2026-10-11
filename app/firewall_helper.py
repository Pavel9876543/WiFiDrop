from __future__ import annotations

import argparse
from pathlib import Path

from app.hotspot.windows import ensure_firewall_rules


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--marker", required=True)
    parser.add_argument("--access-only", action="store_true")
    parser.add_argument("--mdns", action="store_true")
    args = parser.parse_args()
    marker = Path(args.marker)
    try:
        ensure_firewall_rules(args.port, access_only=args.access_only, mdns=args.mdns)
    except Exception:
        marker.write_text("error", encoding="utf-8")
        return 1
    marker.write_text("ok", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
