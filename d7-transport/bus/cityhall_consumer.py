"""Отдельный consumer тестового узла района 3 — Мэрия."""
import os
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import consumer as transport_consumer

PARTNER_DIR = BASE / "partner" / "cityhall"
PARTNER_DIR.mkdir(parents=True, exist_ok=True)

# Отдельное хранилище состояния и обработанных ID
PROJECT_DIR = transport_consumer.BASE
transport_consumer.BASE = PARTNER_DIR

def main():
    transport_consumer.BASE = PROJECT_DIR
    broker, key = transport_consumer.load_env()
    transport_consumer.BASE = PARTNER_DIR
    topic = "city.events.transport.delivery.failed"
    sub = "d3-cityhall-consumer"
    dedup = transport_consumer.Dedup(
        path=PARTNER_DIR / "processed.jsonl"
    )

    print("Consumer района 3 — Мэрия запущен")
    print(f"Брокер: {broker}")
    print(f"Тема: {topic}")

    while True:
        try:
            count = transport_consumer.poll_once(
                broker, key, [topic], sub, dedup
            )
            if count:
                print(f"Получено сообщений: {count}", flush=True)
        except OSError as exc:
            transport_consumer.log(
                "service.error",
                outcome="failure",
                level="ERROR",
                msg=f"Ошибка подключения к брокеру Мэрии: {exc}"
            )
        time.sleep(2)

if __name__ == "__main__":
    main()
