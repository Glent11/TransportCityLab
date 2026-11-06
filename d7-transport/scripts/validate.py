
import json
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path


# JSON Schema события city.transport.delivery.failed.v1
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "specversion",
        "id",
        "source",
        "type",
        "time",
        "datacontenttype",
        "data",
    ],
    "properties": {
        "specversion": {"const": "1.0"},
        "id": {"type": "string", "format": "uuid"},
        "source": {"type": "string", "minLength": 1},
        "type": {"const": "city.transport.delivery.failed.v1"},
        "time": {"type": "string", "format": "date-time"},
        "subject": {"type": "string", "minLength": 1},
        "datacontenttype": {"const": "application/json"},
        "data": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "event_id",
                "event_type",
                "source",
                "target",
                "reason",
                "attempts",
                "first_seen",
                "last_seen",
            ],
            "properties": {
                "event_id": {"type": "string", "format": "uuid"},
                "event_type": {
                    "type": "string",
                    "pattern": r"^city\.[a-z0-9-]+\.[a-z0-9-]+\.[a-z0-9-]+\.v[1-9][0-9]*$",
                },
                "source": {"type": "string", "minLength": 1},
                "target": {"type": "string", "minLength": 1},
                "reason": {
                    "type": "string",
                    "enum": [
                        "timeout",
                        "connection_refused",
                        "tls_error",
                        "unauthorized",
                        "schema_invalid",
                        "payload_too_large",
                        "rejected_by_target",
                    ],
                },
                "attempts": {"type": "integer", "minimum": 1},
                "first_seen": {"type": "string", "format": "date-time"},
                "last_seen": {"type": "string", "format": "date-time"},
                "request_id": {"type": "string", "minLength": 1},
            },
        },
    },
}


UUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)

TIME_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
)


def check_type(value, expected):
    """Проверяет тип значения с учётом особенностей Python."""
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "string":
        return isinstance(value, str)
    return True


def validate_value(value, schema, path, errors):
    """Рекурсивно проверяет значение по части JSON Schema."""

    expected = schema.get("type")

    if expected and not check_type(value, expected):
        errors.append(f"{path}: ожидается тип {expected}")
        return

    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: значение должно быть {schema['const']!r}")

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: недопустимое значение {value!r}")

    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: строка слишком короткая")

        if "pattern" in schema and not re.fullmatch(schema["pattern"], value):
            errors.append(f"{path}: неверный формат строки")

        if schema.get("format") == "uuid":
            if not UUID_PATTERN.fullmatch(value):
                errors.append(f"{path}: некорректный UUID")
            else:
                try:
                    uuid.UUID(value)
                except ValueError:
                    errors.append(f"{path}: некорректный UUID")

        if schema.get("format") == "date-time":
            if not TIME_PATTERN.fullmatch(value):
                errors.append(f"{path}: ожидается UTC-время с миллисекундами и Z")
            else:
                try:
                    datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
                except ValueError:
                    errors.append(f"{path}: некорректная дата или время")

    if isinstance(value, int) and not isinstance(value, bool):
        if value < schema.get("minimum", value):
            errors.append(f"{path}: значение меньше допустимого минимума")

    if isinstance(value, dict):
        required = schema.get("required", [])
        properties = schema.get("properties", {})

        for field in required:
            if field not in value:
                errors.append(f"{path}.{field}: отсутствует обязательное поле")

        if schema.get("additionalProperties") is False:
            for field in value:
                if field not in properties:
                    errors.append(f"{path}.{field}: неизвестное поле")

        for field, field_schema in properties.items():
            if field in value:
                validate_value(
                    value[field],
                    field_schema,
                    f"{path}.{field}",
                    errors,
                )


def main():
    if len(sys.argv) != 2:
        print("Использование: python3 scripts/validate.py <файл.json>")
        sys.exit(2)

    event_path = Path(sys.argv[1])

    try:
        with event_path.open("r", encoding="utf-8") as file:
            event = json.load(file)
    except FileNotFoundError:
        print(f"Ошибка: файл не найден: {event_path}")
        sys.exit(2)
    except json.JSONDecodeError as error:
        print(f"Ошибка JSON: {error}")
        sys.exit(1)

    errors = []
    validate_value(event, SCHEMA, "$", errors)

    if errors:
        print("Событие НЕ прошло проверку:")
        for error in errors:
            print(f"- {error}")
        sys.exit(1)

    print("Событие успешно прошло проверку!")
    print(f"Тип события: {event['type']}")
    print(f"ID события: {event['id']}")


if __name__ == "__main__":
    main()
