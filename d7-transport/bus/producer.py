"""Продюсер событий района: конверт Р5 (CloudEvents) + подпись + доставка.

Публикует в брокер из .env (BUS_BROKER). Если брокер недоступен — копит события
в spool/ и шлёт при следующей попытке (очередь недоставленных).
Ключ HMAC — только из окружения/файла .env, в Git не попадает.

Использование:
    python3 bus/producer.py demo
    python3 bus/producer.py publish --type city.transport.delivery.failed.v1 \\
        --source /d7-transport/api --subject <ID_исходного_события> \\
        --data '{"event_id":"...","event_type":"city.bank.fee.paid.v1",...}'
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sign as bussign  # noqa: E402

SPOOL = Path(__file__).resolve().parent.parent / "spool"
SUB = "producer"


def load_env() -> tuple[str, bytes]:
    broker = os.environ.get("BUS_BROKER", "http://127.0.0.1:14167")
    key = os.environ.get("BUS_KEY", "")
    envfile = Path(__file__).resolve().parent.parent / ".env"
    if envfile.exists():
        for line in envfile.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                broker = broker if k.strip() != "BUS_BROKER" or os.environ.get("BUS_BROKER") else v.strip()
                key = key if k.strip() != "BUS_KEY" or os.environ.get("BUS_KEY") else v.strip()
    if not key:
        sys.exit("Нет BUS_KEY: задайте в .env (openssl rand -hex 32)")
    return broker, bytes.fromhex(key)


def build_event(etype: str, data: dict, source: str, subject: str | None = None) -> dict:
    """Создаёт конверт CloudEvents 1.0; subject добавляется, если передан."""
    event = {
        "specversion": "1.0",
        "id": str(uuid.uuid4()),
        "source": source,
        "type": etype,
        "time": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "datacontenttype": "application/json",
        "data": data,
    }
    if subject:
        event["subject"] = subject
    return event


def log(event: str, **fields):
    """Журнал Р4: одна строка — один JSON."""
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "district": os.environ.get("DISTRICT", "unknown"),
        "service": "producer",
        "level": "INFO",
        "event": event,
        "outcome": "success",
    }
    rec.update(fields)
    print(json.dumps(rec, ensure_ascii=False))


def _post(broker: str, path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        broker + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


def publish(topic: str, event: dict, broker: str, key: bytes) -> bool:
    bussign.sign(event, key)
    try:
        _post(broker, "/publish", {"topic": topic, "event": event})
        log(
            "event.published",
            msg="событие отправлено в шину",
            details={"id": event["id"], "type": event["type"]},
        )
        return True
    except OSError as exc:
        log(
            "service.error",
            level="ERROR",
            outcome="failure",
            msg="брокер недоступен, событие в очереди",
            details={"id": event["id"], "error": str(exc)},
        )
        SPOOL.mkdir(exist_ok=True)
        (SPOOL / f"{event['id']}.json").write_text(
            json.dumps({"topic": topic, "event": event}),
            encoding="utf-8",
        )
        return False


def flush_spool(broker: str, key: bytes) -> int:
    """Отправляет накопленные события. Возвращает число доставленных."""
    sent = 0
    for f in sorted(SPOOL.glob("*.json")):
        item = json.loads(f.read_text(encoding="utf-8"))
        if publish(item["topic"], item["event"], broker, key):
            f.unlink()
            sent += 1
    return sent


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("demo")

    p = sub.add_parser("publish")
    p.add_argument("--type", required=True, help="например city.transport.delivery.failed.v1")
    p.add_argument("--data", required=True, help="JSON полезной нагрузки")
    p.add_argument(
        "--source",
        default=f"/d{os.environ.get('DISTRICT_NUM', '7')}-{os.environ.get('DISTRICT', 'transport')}/api",
    )
    p.add_argument("--subject", help="ID недоставленного события для delivery.failed")

    args = ap.parse_args()
    broker, key = load_env()

    if args.cmd == "demo":
        failed_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

        event = build_event(
            "city.transport.delivery.failed.v1",
            {
                "event_id": failed_id,
                "event_type": "city.bank.fee.paid.v1",
                "source": "/d4-bank/api",
                "target": "/d3-cityhall/api",
                "reason": "timeout",
                "attempts": 5,
                "first_seen": now,
                "last_seen": now,
                "request_id": "demo-request-001",
            },
            "/d7-transport/api",
            subject=failed_id,
        )
        publish("city.events.transport.delivery.failed", event, broker, key)

    elif args.cmd == "publish":
        parts = args.type.split(".")
        if len(parts) < 5 or parts[0] != "city" or not parts[-1].startswith("v"):
            ap.error("Некорректный --type: ожидается city.<district>.<object>.<action>.vN")

        district = parts[1]
        event = build_event(args.type, json.loads(args.data), args.source, args.subject)
        topic = f"city.events.{district}.{'.'.join(parts[2:-1])}"
        publish(topic, event, broker, key)

    else:
        ap.print_help()
        return

    sent = flush_spool(broker, key)
    if sent:
        log("event.published", msg=f"из очереди недоставленных доставлено: {sent}")


if __name__ == "__main__":
    main()
