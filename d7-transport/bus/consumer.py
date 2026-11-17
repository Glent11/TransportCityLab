"""Консьюмер событий района 7: проверка подписи и времени,
дедупликация, идемпотентная обработка, журнал и ack брокеру.

Порядок операций сохранён: verify -> fresh -> dedup -> handle -> mark -> ack.
Использование:
    python3 bus/consumer.py
    python3 bus/consumer.py --sub transport-soc --topics city.events.transport.delivery.failed
    python3 bus/consumer.py --once --sub transport-soc --topics city.events.transport.delivery.failed
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sign as bussign  # noqa: E402

BASE = Path(__file__).resolve().parent.parent
PROCESSED = BASE / "processed.jsonl"
TRANSPORT_TOPIC = "city.events.transport.delivery.failed"


def load_env() -> tuple[str, bytes]:
    broker = os.environ.get("BUS_BROKER", "http://127.0.0.1:14167")
    key = os.environ.get("BUS_KEY", "")
    envfile = BASE / ".env"
    if envfile.exists():
        for line in envfile.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip()
                if k == "BUS_BROKER" and not os.environ.get("BUS_BROKER"):
                    broker = v
                elif k == "BUS_KEY" and not os.environ.get("BUS_KEY"):
                    key = v
    if not key:
        sys.exit("Нет BUS_KEY: задайте его в .env")
    try:
        return broker, bytes.fromhex(key)
    except ValueError:
        sys.exit("BUS_KEY должен быть hex-строкой")


def log(event: str, outcome: str = "success", level: str = "INFO", **fields):
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "district": os.environ.get("DISTRICT", "d7-transport"),
        "service": "consumer",
        "level": level,
        "event": event,
        "outcome": outcome,
    }
    rec.update(fields)
    print(json.dumps(rec, ensure_ascii=False), flush=True)


class Dedup:
    """Журнал обработанных envelope id: один id — одна обработка."""

    def __init__(self, path: Path = PROCESSED):
        self.path = path
        self.ids = set()
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self.ids.add(json.loads(line)["id"])

    def seen(self, eid: str) -> bool:
        return eid in self.ids

    def mark(self, eid: str):
        self.ids.add(eid)
        record = {
            "id": eid,
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")


def reject(event: dict, reason: str):
    log(
        "event.rejected",
        outcome="failure",
        level="WARN",
        msg=f"событие отвергнуто: {reason}",
        details={"id": event.get("id"), "type": event.get("type"), "reason": reason},
    )


def handle(event: dict):
    """Идемпотентно сохраняет факт обработки, не выводя payload в журнал.

    Путь вычисляется при каждом вызове через BASE: тестовый стенд может
    перенаправить BASE во временную папку. Для delivery.failed ключ состояния
    — пара (event_id, target). Для прочих типов — application_id или envelope id.
    """
    state_path = BASE / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    data = event.get("data", {})
    etype = event.get("type", "")

    if etype == "city.transport.delivery.failed.v1":
        event_id = data.get("event_id", event["id"])
        target = data.get("target", "unknown")
        state_key = f"delivery.failed:{event_id}:{target}"
        state[state_key] = {
            "type": etype,
            "event_id": event_id,
            "target": target,
            "reason": data.get("reason"),
            "attempts": data.get("attempts"),
            "subject": event.get("subject"),
        }
    else:
        # Универсальная идемпотентная заглушка для учебных событий других районов.
        state_key = str(data.get("application_id", event["id"]))
        state[state_key] = {"type": etype, "data": data}

    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    log("data.change", msg="событие сохранено идемпотентно", details={"key": state_key, "type": etype})


def process(event: dict, broker: str, key: bytes, topic: str, sub: str, dedup: Dedup) -> str:
    """Проверки -> обработка -> журнал -> ack. Возвращает accepted/причину отказа."""
    if not bussign.verify(event, key):
        reject(event, "bad_signature")
        return "bad_signature"
    if not bussign.fresh(event):
        reject(event, "stale")
        return "stale"
    if dedup.seen(event["id"]):
        reject(event, "duplicate")
        return "duplicate"

    handle(event)  # 1. обработка
    dedup.mark(event["id"])  # 2. журнал обработанных
    _post(broker, "/ack", {"topic": topic, "id": event["id"], "sub": sub})  # 3. ack
    log("event.consumed", msg="событие обработано", details={"id": event["id"], "type": event.get("type")})
    return "accepted"


def _post(broker: str, path: str, payload: dict):
    req = urllib.request.Request(
        broker + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else {}


def poll_once(broker: str, key: bytes, topics: list[str], sub: str, dedup: Dedup) -> int:
    url = broker + "/poll?sub=" + urllib.parse.quote(sub)
    with urllib.request.urlopen(url, timeout=5) as resp:
        messages = json.loads(resp.read())["messages"]
    count = 0
    for message in messages:
        if topics and message["topic"] not in topics:
            continue
        process(message["event"], broker, key, message["topic"], sub, dedup)
        count += 1
    return count


def main():
    ap = argparse.ArgumentParser(description="Консьюмер событий района 7 — Транспорт")
    ap.add_argument("--sub", default=os.environ.get("DISTRICT", "d7-transport-consumer"))
    ap.add_argument("--topics", default=TRANSPORT_TOPIC)
    ap.add_argument("--once", action="store_true", help="один проход и выход")
    ap.add_argument("--demo", action="store_true", help="слушать транспортную демо-тему")
    args = ap.parse_args()

    broker, key = load_env()
    topics = [TRANSPORT_TOPIC] if args.demo else [
        topic.strip() for topic in args.topics.split(",") if topic.strip()
    ]
    dedup = Dedup()

    while True:
        try:
            poll_once(broker, key, topics, args.sub, dedup)
        except OSError as exc:
            log("service.error", outcome="failure", level="ERROR", msg=f"брокер недоступен: {exc}")
        if args.once:
            return
        time.sleep(3)


if __name__ == "__main__":
    main()
