"""Консьюмер событий: приём → проверка подписи → окно времени → дедупликация
→ обработка (идемпотентная) → журнал processed.jsonl → ack брокеру.

Порядок операций — часть задания: менять его нельзя (см. Л2, закладка 2).
Использование:
    python3 bus/consumer.py --demo                 # слушает тему демо-события
    python3 bus/consumer.py --sub my-district --topics city.events.bank.fee.paid
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


def load_env() -> tuple[str, bytes]:
    broker = os.environ.get("BUS_BROKER", "http://127.0.0.1:14167")
    key = os.environ.get("BUS_KEY", "")
    envfile = BASE / ".env"
    if envfile.exists():
        for line in envfile.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                broker = broker if k.strip() != "BUS_BROKER" or os.environ.get("BUS_BROKER") else v.strip()
                key = key if k.strip() != "BUS_KEY" or os.environ.get("BUS_KEY") else v.strip()
    if not key:
        sys.exit("Нет BUS_KEY: задайте в .env (openssl rand -hex 32)")
    return broker, bytes.fromhex(key)


def log(event: str, outcome: str = "success", level: str = "INFO", **fields):
    rec = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
           "district": os.environ.get("DISTRICT", "unknown"), "service": "consumer",
           "level": level, "event": event, "outcome": outcome}
    rec.update(fields)
    print(json.dumps(rec, ensure_ascii=False))


class Dedup:
    """Журнал обработанных id (processed.jsonl): один id — одна обработка."""

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
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"id": eid, "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")}) + "\n")


def reject(event: dict, reason: str):
    log("event.rejected", outcome="failure", level="WARN", msg=f"событие отвергнуто: {reason}",
        details={"id": event.get("id"), "type": event.get("type"), "reason": reason})


def handle(event: dict):
    """ВАША ОБРАБОТКА. Должна быть идемпотентной: событие может прийти дважды
    (аварийный повтор), а дедупликация по id ловит только тот же id.

    Здесь: демо-обработка — записать факт в state.json (идемпотентно: перезапись
    по application_id, а не «прибавить»)."""
    state_path = BASE / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    data = event.get("data", {})
    key = data.get("application_id", event["id"])
    state[key] = {"type": event["type"], "data": data}   # «поставить», не «добавить»
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    log("data.change", msg=f"обработано (идемпотентно): {key}")


def process(event: dict, broker: str, key: bytes, topic: str, sub: str, dedup: Dedup) -> str:
    """Три проверки → обработка → журнал → ack. Возвращает: accepted/reject-причина."""
    if not bussign.verify(event, key):
        reject(event, "bad_signature")
        return "bad_signature"
    if not bussign.fresh(event):
        reject(event, "stale")
        return "stale"
    if dedup.seen(event["id"]):
        reject(event, "duplicate")
        return "duplicate"
    handle(event)                    # 1. обработка
    dedup.mark(event["id"])          # 2. журнал обработанных
    _post(broker, "/ack", {"topic": topic, "id": event["id"], "sub": sub})  # 3. ack
    log("event.consumed", msg="событие обработано", details={"id": event["id"]})
    return "accepted"


def _post(broker: str, path: str, payload: dict):
    req = urllib.request.Request(broker + path, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


def poll_once(broker: str, key: bytes, topics: list[str], sub: str, dedup: Dedup) -> int:
    url = broker + "/poll?sub=" + urllib.parse.quote(sub)
    with urllib.request.urlopen(url, timeout=5) as resp:
        messages = json.loads(resp.read())["messages"]
    n = 0
    for m in messages:
        if topics and m["topic"] not in topics:
            continue
        process(m["event"], broker, key, m["topic"], sub, dedup)
        n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sub", default=os.environ.get("DISTRICT", "consumer"))
    ap.add_argument("--topics", default="city.events.bank.fee.paid,city.events.grid.alarm.raised")
    ap.add_argument("--once", action="store_true", help="один проход и выход")
    ap.add_argument("--demo", action="store_true", help="слушать тему демо-события")
    args = ap.parse_args()
    broker, key = load_env()
    topics = ["city.events.bank.fee.paid"] if args.demo else [t.strip() for t in args.topics.split(",") if t.strip()]
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
