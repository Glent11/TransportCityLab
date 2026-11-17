"""check-bus.py — 9 проверок пары «продюсер → консьюмер» (ЛР4).

Сценарий: поднимает учебный брокер в отдельном процессе, гоняет события,
проверяет подпись/повтор/окно/доставку/recovery.md. Итог: «пройдено N из 9».

Запуск: python3 scripts/check-bus.py [--kit ПУТЬ] [--district d4-bank]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "bus"))

import sign as bussign  # noqa: E402
import producer  # noqa: E402
import consumer  # noqa: E402

TOPIC = "city.events.bank.fee.paid"
KEY = bytes.fromhex("11" * 32)
WRONG_KEY = bytes.fromhex("22" * 32)


def wait_broker(url: str, proc: subprocess.Popen, timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            urllib.request.urlopen(url + "/health", timeout=1)
            return True
        except OSError:
            time.sleep(0.2)
    return False


def fresh_event(data=None):
    event = producer.build_event("city.bank.fee.paid.v1",
                                 data or {"application_id": "2026-000123", "amount": 1500,
                                          "currency": "RUB", "payer": "user:ivanov"},
                                 "/d4-bank/api")
    return event


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kit", default=str(BASE))
    ap.add_argument("--district", default=None, help="репозиторий района: проверка 9 читает его recovery.md")
    args = ap.parse_args()
    kit = Path(args.kit)

    results: list[tuple[int, str, bool, str]] = []

    broker = subprocess.Popen([sys.executable, str(kit / "broker/local_broker.py")],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = "http://127.0.0.1:14167"
    if not wait_broker(url, broker):
        print("Брокер набора не поднялся — проверки невозможны")
        return 1

    workdir = Path(tempfile.mkdtemp(prefix="check-bus-"))
    consumer.BASE = workdir          # handle() пишет state.json в изолированную папку
    dedup = consumer.Dedup(workdir / "processed.jsonl")
    try:
        # 1. Конверт события валиден
        event = fresh_event()
        type_ok = bool(re.fullmatch(r"city\.[a-z0-9]+(\.[a-z0-9]+){2,3}\.v\d+",
                                    event["type"])) and event["time"].endswith("Z")
        envelope_ok = all(k in event for k in ("specversion", "id", "source", "type", "time", "data"))
        results.append((1, "конверт CloudEvents (поля, шаблон type, UTC)", envelope_ok and type_ok, ""))

        # 2. Собственная подпись сходится
        producer_broker = url
        event = fresh_event()
        sig = bussign.sign(event, KEY)
        results.append((2, "подпись собственного события", bussign.verify(event, KEY), ""))

        # 3. Подмена data → подпись не сходится
        event = fresh_event()
        bussign.sign(event, KEY)
        event["data"]["amount"] = 1
        results.append((3, "подмена data отвергается", not bussign.verify(event, KEY), ""))

        # 4. Чужой ключ → не сходится
        event = fresh_event()
        bussign.sign(event, WRONG_KEY)
        results.append((4, "подпись чужим ключом отвергается", not bussign.verify(event, KEY), ""))

        # 5. Повтор с тем же id → duplicate
        event = fresh_event()
        bussign.sign(event, KEY)
        r1 = consumer.process(event, url, KEY, TOPIC, "check", dedup)
        r2 = consumer.process(event, url, KEY, TOPIC, "check", dedup)
        results.append((5, "повтор события → reject duplicate", r1 == "accepted" and r2 == "duplicate", f"{r1}/{r2}"))

        # 6. Старое событие (10 минут) → stale
        event = fresh_event()
        event["time"] = "2026-10-13T05:07:31.415Z"
        bussign.sign(event, KEY)
        r = consumer.process(event, url, KEY, TOPIC, "check", dedup)
        results.append((6, "событие старше окна → reject stale", r == "stale", r))

        # 7. Брокер недоступен → очередь; подъём → доставлено ровно один раз
        event = fresh_event()
        bussign.sign(event, KEY)
        producer.SPOOL = workdir / "spool"
        producer.publish(TOPIC, event, "http://127.0.0.1:14999", KEY)   # левый порт: уйдёт в spool
        queued = len(list((workdir / "spool").glob("*.json"))) == 1
        broker.terminate(); broker.wait()
        broker = subprocess.Popen([sys.executable, str(kit / "broker/local_broker.py")],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wait_broker(url, broker)
        producer.SPOOL = workdir / "spool"
        producer.flush_spool(url, KEY)
        d2 = consumer.Dedup(workdir / "processed2.jsonl")
        r = consumer.process(event, url, KEY, TOPIC, "check2", d2)      # первый приём
        r_again = consumer.process(event, url, KEY, TOPIC, "check2", d2)  # аварийный повтор
        results.append((7, "очередь недоставленных: после подъёма брокера — ровно один раз",
                        queued and r == "accepted" and r_again == "duplicate", f"queue={queued} {r}/{r_again}"))

        # 8. «Падение» после приёма, до обработки → обработка один раз
        event = fresh_event({"application_id": "2026-000777", "amount": 100})
        bussign.sign(event, KEY)
        st_before = json.loads((workdir / "state.json").read_text()) if (workdir / "state.json").exists() else {}
        consumer._post(url, "/publish", {"topic": TOPIC, "event": event})
        d3 = consumer.Dedup(workdir / "processed3.jsonl")
        consumer.process(event, url, KEY, TOPIC, "check3", d3)  # ack после обработки
        consumer.process(event, url, KEY, TOPIC, "check3", d3)  # повтор от брокера
        st_after = json.loads((workdir / "state.json").read_text())
        once = st_before.get("2026-000777") != st_after.get("2026-000777") and d3.seen(event["id"])
        results.append((8, "обработка ровно один раз (журнал + ack после обработки)", once, ""))

        # 9. recovery.md у района
        repo = Path(args.district) if args.district else BASE.parent
        rm = repo / "docs" / "recovery.md"
        need = ["зависимости", "секреты", "порядок запуска", "проверка"]
        ok9 = rm.exists() and all(any(n in ln.lower() for ln in rm.read_text(encoding="utf-8").splitlines()) for n in need)
        if not rm.exists():
            hint = f"нет {rm}"
        else:
            hint = "разделы: " + (", ".join(n for n in need if any(n in ln.lower() for ln in rm.read_text(encoding="utf-8").splitlines())))
        results.append((9, "docs/recovery.md с четырьмя разделами", ok9, hint))
    finally:
        broker.terminate()

    passed = sum(1 for *_, ok, _ in [(r[0], r[1], r[2], r[3]) for r in results] if ok)
    for num, name, ok, hint in results:
        mark = "OK  " if ok else "FAIL"
        print(f"[{mark}] {num}. {name}" + (f"   ({hint})" if hint and not ok else ""))
    print(f"\nпройдено {passed} из 9")
    return 0 if passed == 9 else 1


if __name__ == "__main__":
    sys.exit(main())
