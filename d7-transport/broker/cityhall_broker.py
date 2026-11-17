"""Учебный брокер шины событий — стандартная библиотека Python, без Docker.

Модель: темы (city.events.bank.fee.paid и т.п.), подписчики получают каждое
сообщение, пока не подтвердят обработку (POST /ack) — at-least-once.
Запуск:  python3 broker/local_broker.py            # 127.0.0.1:14167
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HOST, PORT = "127.0.0.1", 14168

_lock = threading.Lock()
_topics: dict[str, list[dict]] = {}   # тема -> [{"event", "enqueued", "acks": [sub, ...]}]
_seen: set[str] = set()               # id событий (защита брокера от дубликатов по id)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # тихий журнал
        pass

    def _reply(self, code: int, obj: dict):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/health":
            return self._reply(200, {"status": "ok"})
        if url.path == "/poll":
            sub = parse_qs(url.query).get("sub", ["anon"])[0]
            with _lock:
                out = []
                for topic, msgs in _topics.items():
                    for m in msgs:
                        if sub not in m["acks"]:
                            out.append({"topic": topic, "event": m["event"]})
            return self._reply(200, {"messages": out})
        self._reply(404, {"error": "not found"})

    def do_POST(self):
        url = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._reply(400, {"error": "bad json"})
        with _lock:
            if url.path == "/publish":
                topic, event = body.get("topic", ""), body.get("event", {})
                eid = event.get("id", "")
                if not topic or not eid:
                    return self._reply(400, {"error": "need topic and event.id"})
                if eid in _seen:
                    return self._reply(202, {"accepted": True, "duplicate": True, "id": eid})
                _seen.add(eid)
                _topics.setdefault(topic, []).append(
                    {"event": event, "enqueued": time.time(), "acks": []})
                return self._reply(202, {"accepted": True, "id": eid})
            if url.path == "/ack":
                topic, eid, sub = body.get("topic", ""), body.get("id", ""), body.get("sub", "anon")
                found = False
                for m in _topics.get(topic, []):
                    if m["event"].get("id") == eid:
                        found = True
                        if sub not in m["acks"]:
                            m["acks"].append(sub)
                return self._reply(200, {"acked": found})
        self._reply(404, {"error": "not found"})


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"учебный брокер: http://{HOST}:{PORT}  (GET /health /poll, POST /publish /ack)")
    server.serve_forever()


if __name__ == "__main__":
    main()
