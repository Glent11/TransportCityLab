"""Сервис-заглушка района: /health, /api/v1/info и журнал в формате JSON Lines (Р4).

Только стандартная библиотека Python — ничего устанавливать не нужно.
Замените на настоящий сервис своего района (FastAPI, Flask, Go, ...),
но сохраните /health, X-Request-ID и формат журнала.
"""

import json
import os
import sys
import uuid
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DISTRICT = os.environ.get("DISTRICT", "unknown")
SERVICE = os.environ.get("SERVICE", "api")
PORT = int(os.environ.get("PORT", "8080"))


def log(level: str, event: str, outcome: str, msg: str, **fields: object) -> None:
    """Одна строка JSON в stdout: время UTC с миллисекундами (Р3) и обязательные поля Р4."""
    record = {
        "ts": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "district": DISTRICT,
        "service": SERVICE,
        "level": level,
        "event": event,
        "outcome": outcome,
        "msg": msg,
    }
    record.update({k: v for k, v in fields.items() if v is not None})
    print(json.dumps(record, ensure_ascii=False), file=sys.stdout, flush=True)


class Handler(BaseHTTPRequestHandler):
    server_version = "city"  # не раскрываем версию Python в заголовке Server
    sys_version = ""

    def _send(self, status: int, body: dict, content_type: str = "application/json") -> None:
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Request-ID", self.request_id)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802 (имя задано http.server)
        self.request_id = self.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        if self.path == "/health":
            # /health не пишет в журнал: чекер ходит сюда часто и засорил бы SOC
            self._send(200, {"status": "ok"})
            return
        if self.path == "/api/v1/info":
            self._send(200, {"district": DISTRICT, "service": SERVICE})
            log("INFO", "data.read", "success", "запрошена информация о сервисе",
                actor="anonymous", src_ip=self.client_address[0], request_id=self.request_id)
            return
        # Ошибка в формате RFC 9457 — без подробностей о внутреннем устройстве
        self._send(404, {"type": "about:blank", "title": "Not Found", "status": 404},
                   content_type="application/problem+json")
        log("INFO", "http.not_found", "failure", "неизвестный адрес",
            src_ip=self.client_address[0], request_id=self.request_id,
            details={"path": self.path[:200]})

    def log_message(self, format: str, *args: object) -> None:
        """Отключаем стандартный текстовый журнал http.server — у нас свой, в JSON."""


if __name__ == "__main__":
    log("INFO", "service.start", "success", f"сервис слушает порт {PORT}")
    try:
        ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        log("INFO", "service.stop", "success", "сервис остановлен")
