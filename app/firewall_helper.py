from __future__ import annotations

import argparse
from pathlib import Path

from app.hotspot.windows import ensure_firewall_rules


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--marker", required=True)
    args = parser.parse_args()
    marker = Path(args.marker)
    try:
        ensure_firewall_rules(args.port)
    except Exception:
        marker.write_text("error", encoding="utf-8")
        return 1
    marker.write_text("ok", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
