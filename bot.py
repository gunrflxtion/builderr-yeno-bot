#!/usr/bin/env python3
"""YeNo volume bot server: POST /decide (stdlib only, no dependencies).

Serves the tuned Strategy from strategy.py (House Bot v1 + headroom /
min-gap / regime-filter changes; see strategy.py PARAMS and TEST_RESULTS.md).
Contract: returns exactly {"action":"HOLD"} | {"action":"BUY",
"outcome":"YES"|"NO","maxCashUsd":<=5} | {"action":"SELL"} within 200 ms.
The evaluator owns cash, fills, fees, volume and scoring; this server
only decides. No network access, no keys, no state is persisted.

Run:  python3 bot.py [port]          (default 8080, 127.0.0.1)
Test: python3 kit/yeno-smoke-test.py --url http://127.0.0.1:8080/decide
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from strategy import Strategy

BOT = Strategy()  # tuned PARAMS


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/decide":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            response = BOT.decide(json.loads(self.rfile.read(length)))
            body = json.dumps(response, separators=(",", ":")).encode()
        except Exception:
            self.send_error(400)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: Any) -> None:
        return


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
