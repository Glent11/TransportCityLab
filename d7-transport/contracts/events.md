# События района 7 — Транспорт

Формат конверта — CloudEvents 1.0 (соглашение P5 «Архитектуры города»).
Тип события: `city.<код района>.<объект>.<действие>.vN`. Время — UTC по P3, RFC 3339 с миллисекундами и `Z`.
В `data` и `subject` — только идентификаторы, не ФИО и не секреты.
Транспорт не владеет `data`-схемами событий других районов: `data` принадлежит району-источнику, а конверт, реестр, валидация и версионирование — Транспорту. Схемы утверждаются архитектурным советом (P5a, P7).

## Публикуем
| Тип (`type`)                                                                                | Когда                                                                                                                                           | Кто получатель                 | Поля `data` (пример)                                                                                        |
| ------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------ | ----------------------------------------------------------------------------------------------------------- |
| `city.transport.delivery.failed.v1`                                                         | Событие не удалось доставить подписчику после исчерпания попыток или сразу при жёстком отказе (неверный формат, отказ в доступе у получателя)   | Городской SOC                  | `event_id`, `event_type`, `source`, `target`, `reason`, `attempts`, `first_seen`, `last_seen`, `request_id` |
| `city.transport.event.rejected.v1` *(предложение в каталог, внести на архитектурный совет)* | Входящее событие отклонено до попадания в брокер: не прошло валидацию по JSON Schema, нет подписи (с недели 5), повтор по `id`, нет прав на тип | Район-источник и Городской SOC | `event_id`, `event_type`, `source`, `reason`, `received_at`, `request_id`                                   |

Пример `city.transport.delivery.failed.v1`:
```json
{
  "specversion": "1.0",
  "id": "5c2a9f7e-1b3d-4e6a-9f80-2d4c6b8e0a11",
  "source": "/d7-transport/api",
  "type": "city.transport.delivery.failed.v1",
  "time": "2026-10-13T05:07:31.415Z",
  "subject": "b3f1c0de-2a44-4c1e-9d5f-6a7e8b9c0d11",
  "datacontenttype": "application/json",
  "data": {
    "event_id": "b3f1c0de-2a44-4c1e-9d5f-6a7e8b9c0d11",
    "event_type": "city.bank.fee.paid.v1",
    "source": "/d4-bank/api",
    "target": "/d3-cityhall/api",
    "reason": "timeout",
    "attempts": 5,
    "first_seen": "2026-10-13T05:02:11.002Z",
    "last_seen": "2026-10-13T05:07:31.400Z",
    "request_id": "7f3c9a2e"
  }
}
```

Правила публикации:
- `subject` у `delivery.failed` — `id` недоставленного события, чтобы SOC мог связать запись с исходным событием.
- `reason` — из закрытого словаря: `timeout`, `connection_refused`, `tls_error`, `unauthorized`, `schema_invalid`, `payload_too_large`, `rejected_by_target`. Расширение словаря — через совет.
- `attempts` — целое, сколько попыток доставки сделано.
- `first_seen` / `last_seen` — UTC, RFC 3339 с миллисекундами (P3).
- `request_id` — из `X-Request-ID` исходного запроса на публикацию, если он был.
- Событие публикуется не чаще одного раза на пару `(event_id, target)` за интервал, заданный настройкой DLQ; повторы подавляются по `id` (с недели 5).

Пример `city.transport.event.rejected.v1` :
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://city.lab/contracts/schemas/city.transport.event.rejected.v1.schema.json",
  "title": "city.transport.event.rejected.v1",
  "description": "Схема для уведомления Транспорта об отклонении входящего события.",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "specversion",
    "id",
    "source",
    "type",
    "time",
    "datacontenttype",
    "data"
  ],
  "properties": {
    "specversion": {
      "const": "1.0",
      "description": "Версия CloudEvents."
    },
    "id": {
      "type": "string",
      "format": "uuid",
      "pattern": "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$",
      "description": "Уникальный UUID уведомления об отклонении"
    },
    "source": {
      "const": "/d7-transport/api",
      "description": "Источник уведомления — API Транспорта."
    },
    "type": {
      "const": "city.transport.event.rejected.v1"
    },
    "time": {
      "type": "string",
      "format": "date-time",
      "pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}\\.\\d{3}Z$",
      "description": "Время публикации уведомления в UTC, RFC 3339 с миллисекундами и Z."
    },
    "subject": {
      "type": "string",
      "minLength": 1,
      "description": "ID отклонённого события, если он извлечён и пригоден для использования; соответствует data.event_id."
    },
    "datacontenttype": {
      "const": "application/json"
    },
    "data": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "reason",
        "received_at"
      ],
      "properties": {
        "event_id": {
          "type": "string",
          "format": "uuid",
          "pattern": "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$",
          "description": "UUID отклонённого события, если присутствует и корректен."
        },
        "event_type": {
          "type": "string",
          "pattern": "^city\\.[a-z0-9-]+\\.[a-z0-9-]+\\.[a-z0-9-]+\\.v[1-9][0-9]*$",
          "description": "Заявленный тип отклонённого события, если удалось извлечь."
        },
        "source": {
          "type": "string",
          "minLength": 1,
          "description": "Заявленный источником исходного события source; не является подтверждением подлинности."
        },
        "reason": {
          "type": "string",
          "enum": [
            "schema_invalid",
            "unauthorized",
            "duplicate",
            "signature_invalid",
            "replay"
          ],
          "description": "Предлагаемый закрытый словарь причин."
        },
        "received_at": {
          "type": "string",
          "format": "date-time",
          "pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}\\.\\d{3}Z$",
          "description": "Время получения входящего события Транспортом, UTC, RFC 3339 с миллисекундами и Z."
        },
        "request_id": {
          "type": "string",
          "minLength": 1,
          "description": "Значение X-Request-ID исходного запроса на публикацию."
        }
      }
    }
  }
}
```

Правила публикации:
- Внешние обязательные поля: `specversion`, `id`, `source`, `type`, `time`, `datacontenttype`, `data`.
- `data.reason` и `data.received_at` обязательны; `event_id`, `event_type`, `source`, `request_id` необязательны, потому что исходное сообщение может быть некорректным.
- `subject` необязателен: он может отсутствовать, если корректный ID исходного события не удалось извлечь.
- `reason` и его закрытый словарь являются предложением до решения архитектурного совета.
- Схема ограничивает дополнительные поля через `additionalProperties: false`; это строгое правило, которое нужно сверить с общей политикой эволюции контрактов.
- Проверка `format` зависит от настроек JSON Schema-валидатора; для UUID также указан шаблон, а для времён — шаблон UTC с миллисекундами и `Z`.
a7e2912 (docs(api): дополнить спецификацию схем событий района 7)
## Потребляем

Транспорт принимает **все** события каталога P5, валидирует их по JSON Schema и маршрутизирует подписчикам. `data`-схемы событий других районов Транспорт не пишет — он их получает через `events.md` районов и утверждает на совете.

| Тип (`type`)                          | От кого              | Что делаем при получении                                                                                                                 | Что делаем с неверным / повторным событием                                              |
| ------------------------------------- | -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| `city.cityhall.fee.requested.v1`      | Мэрия (d3)           | Валидируем конверт и `data` по схеме, проверяем права источника на тип, маршрутизируем в Банк (d4), сохраняем статус в `db`, журналируем | `event.rejected` в журнал, событие в DLQ, публикуем `delivery.failed` при сбое маршрута |
| `city.bank.fee.paid.v1`               | Банк (d4)            | То же: маршрут в Мэрию (d3), статус в `db`, журнал                                                                                       | То же                                                                                   |
| `city.hospital.certificate.issued.v1` | Больница (d5)        | Маршрут в Мэрию (d3), статус в `db`, журнал                                                                                              | То же; `data` с PII не логируем в `details`                                             |
| `city.hospital.stats.published.v1`    | Больница (d5)        | Маршрут в Мэрию (d3), статус в `db`, журнал                                                                                              | То же                                                                                   |
| `city.grid.alarm.raised.v1`           | Энергосеть (d6)      | Маршрут в SOC (d8), статус в `db`, журнал; тег `high_priority` для SLA                                                                   | То же                                                                                   |
| `city.grid.outage.planned.v1`         | Энергосеть (d6)      | Маршрут в Мэрию (d3), статус в `db`, журнал                                                                                              | То же                                                                                   |
| `city.passport.user.created.v1`       | Паспортный стол (d2) | Fan-out всем районам-подписчикам по реестру подписок, статус по каждому получателю, журнал                                               | То же                                                                                   |
| `city.passport.user.disabled.v1`      | Паспортный стол (d2) | Fan-out всем районам с высоким приоритетом (районы прекращают сессии), статус, журнал                                                    | То же                                                                                   |
| `city.gateway.block.added.v1`         | Шлюз (d1)            | Маршрут в SOC (d8), статус, журнал                                                                                                       | То же                                                                                   |
| `city.soc.incident.opened.v1`         | SOC (d8)             | Маршрут в затронутый район по `subject` или `data.district`, статус, журнал                                                              | То же                                                                                   |

Общие правила обработки:
- **Валидация.** Конверт проверяется на обязательные поля P5 (`specversion`, `id`, `source`, `type`, `time`, `data`) и на соответствие JSON Schema из `schema-registry`. Не прошло — `event.rejected` в журнал, событие в DLQ, публикуем `delivery.failed` с `reason=schema_invalid`, если событие успело попасть в брокер.
- **Права источника.** Источник может публиковать только типы, разрешённые ему в каталоге. Нарушение — `event.rejected` с `reason=unauthorized`, в SOC.
- **Идемпотентность.** Повтор по `id` (с недели 5 — и по подписи) отбрасывается: `event.rejected` с `reason=duplicate`, исходное событие не дублируется получателям.
- **Подпись и anti-replay (с недели 5).** Нет подписи или подпись не сходится — `event.rejected` с `reason=signature_invalid`; повторно использованный nonce/окно времени — `reason=replay`.
- **Ошибка доставки.** Исчерпаны попытки или получатель ответил 4xx/5xx — событие в DLQ, публикуем `delivery.failed` с `target` и `reason`.
- **Журнал.** Каждое принятое, отклонённое и недоставленное событие пишется в JSON Lines по P4 с полями `ts`, `district=transport`, `service=api`, `level`, `event`, `outcome`, `request_id`, `details`. В `details` не попадают `data`-payload’ы событий Больницы и Паспортного стола (PII).
- **Ответ источнику.** На `POST /api/v1/events` источник получает `202 Accepted` с `id` события и ссылкой на статус; окончательная доставка — асинхронно, через `GET /api/v1/events/{id}/status`.

## Открытые вопросы к архитектурному совету
- Утвердить `city.transport.event.rejected.v1`.
- Зафиксировать, что `data`-схема события принадлежит району-источнику, а конверт, реестр и валидация — Транспорту.
- Согласовать закрытый словарь `reason` для `delivery.failed` и `event.rejected`; расширение — только через совет.
- Согласовать, что fan-out событий `city.passport.user.created.v1` и `city.passport.user.disabled.v1` выполняется по реестру подписок, который ведёт Транспорт, а не по жёстко прописанному списку получателей.
a7e2912 (docs(api): дополнить спецификацию схем событий района 7)
