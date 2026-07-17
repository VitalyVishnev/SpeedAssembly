"""Shared file protocol helpers for isolated worker processes.

Layer: infrastructure.

This module owns atomic request/result/error file exchange and worker command
resolution. It must not know conversion, proxy, fracture, or FBX semantics.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
import tempfile
from array import array
from base64 import b64decode, b64encode
from dataclasses import fields, is_dataclass
from enum import Enum
from functools import lru_cache
from importlib import import_module
from pathlib import Path
from typing import Any


_TYPE_KEY = "__xml_to_usda_worker_payload_type__"
_CLASS_KEY = "__xml_to_usda_worker_payload_class__"
WORKER_TOKEN_ENV = "XML_TO_USDA_WORKER_TOKEN"
_WORKER_PAYLOAD_MODULES = (
    "xml_to_usda.models",
    "xml_to_usda.runtime_paths",
    "xml_to_usda.conversion_worker_subprocess",
    "xml_to_usda.proxy_mesh_service",
    "xml_to_usda.proxy_mesh_worker_subprocess",
    "xml_to_usda.fracture_collision",
    "xml_to_usda.fracture_export_service",
    "xml_to_usda.fracture_preview_service",
    "xml_to_usda.fracture_service",
    "xml_to_usda.fracture_worker_subprocess",
    "xml_to_usda.part_preview_service",
    "xml_to_usda.part_preview_worker_subprocess",
    "xml_to_usda.wind_preview_service",
    "xml_to_usda.wind_external_skeleton",
    "xml_to_usda.wind_preview_worker_subprocess",
    "xml_to_usda.wind_viewport_scene",
    "xml_to_usda.viewport_scene",
)
_ALLOWED_CLASS_CACHE: dict[str, tuple[object, type]] = {}


def write_worker_payload_atomic(path: str | Path, payload: object) -> None:
    target_path = Path(path)
    temp_path = target_path.with_name(f"{target_path.name}.tmp")
    try:
        temp_path.write_text(
            json.dumps(_encode_worker_value(payload), separators=(",", ":")),
            encoding="utf-8",
        )
        temp_path.replace(target_path)
    except Exception:
        cleanup_file(temp_path)
        cleanup_file(target_path)
        raise


def read_worker_payload(path: str | Path) -> Any:
    return _decode_worker_value(json.loads(Path(path).read_text(encoding="utf-8")))


def new_worker_token() -> str:
    return secrets.token_urlsafe(32)


def worker_env(token: str) -> dict[str, str]:
    env = os.environ.copy()
    env[WORKER_TOKEN_ENV] = token
    env["PYTHONFAULTHANDLER"] = "1"
    return env


def validate_worker_token(request_token: str) -> None:
    expected = os.environ.get(WORKER_TOKEN_ENV)
    if not expected:
        raise RuntimeError("Worker request origin token is missing from environment.")
    if not request_token:
        raise RuntimeError("Worker request origin token is missing from request payload.")
    if not secrets.compare_digest(request_token, expected):
        raise RuntimeError("Worker request origin token mismatch.")


def write_json_atomic(path: str | Path, payload: dict[str, object]) -> None:
    target_path = Path(path)
    temp_path = target_path.with_name(f"{target_path.name}.tmp")
    try:
        temp_path.write_text(json.dumps(payload), encoding="utf-8")
        temp_path.replace(target_path)
    except Exception:
        cleanup_file(temp_path)
        cleanup_file(target_path)
        raise


def read_json_payload(path: str | Path) -> dict[str, object]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("Worker JSON payload must be an object.")
    return payload


def write_error_payload(path: str | Path, *, message: str, formatted_traceback: str) -> None:
    write_json_atomic(
        path,
        {
            "message": message,
            "traceback": formatted_traceback,
        },
    )


def read_error_payload(path: str | Path) -> tuple[str, str] | None:
    error_path = Path(path)
    if not error_path.exists():
        return None
    payload = read_json_payload(error_path)
    return str(payload.get("message", "")), str(payload.get("traceback", ""))


def create_temp_path(prefix: str, suffix: str) -> Path:
    file_descriptor, raw_path = tempfile.mkstemp(prefix=prefix, suffix=suffix)
    os.close(file_descriptor)
    path = Path(raw_path)
    cleanup_file(path)
    return path


def cleanup_file(path: str | Path) -> None:
    try:
        Path(path).unlink(missing_ok=True)
    except Exception:
        pass


def resolve_worker_command(command: str, request_path: str | Path) -> list[str]:
    request = str(request_path)
    if bool(getattr(sys, "frozen", False)):
        return [sys.executable, command, "--request", request]
    return [sys.executable, "-m", "xml_to_usda", command, "--request", request]


def _encode_worker_value(value: object) -> object:
    if isinstance(value, Enum):
        return {
            _TYPE_KEY: "enum",
            _CLASS_KEY: _allowed_worker_class_key(type(value)),
            "value": value.value,
        }
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, array):
        return {
            _TYPE_KEY: "array",
            "typecode": value.typecode,
            "data": b64encode(value.tobytes()).decode("ascii"),
        }
    if isinstance(value, bytes):
        return {_TYPE_KEY: "bytes", "data": b64encode(value).decode("ascii")}
    if isinstance(value, Path):
        return {_TYPE_KEY: "path", "value": str(value)}
    packed_fields = _packed_model_value_fields(value)
    if packed_fields is not None:
        components = array("d")
        for item in value:
            components.extend(tuple(getattr(item, name) for name in packed_fields))
        return {
            _TYPE_KEY: "model_value_tuple",
            _CLASS_KEY: _allowed_worker_class_key(type(value[0])),
            "width": len(packed_fields),
            "data": b64encode(components.tobytes()).decode("ascii"),
        }
    if isinstance(value, tuple) and value and all(type(item) is int for item in value):
        components = array("q", value)
        return {
            _TYPE_KEY: "numeric_tuple",
            "typecode": components.typecode,
            "data": b64encode(components.tobytes()).decode("ascii"),
        }
    if isinstance(value, tuple) and value and all(type(item) is float for item in value):
        components = array("d", value)
        return {
            _TYPE_KEY: "numeric_tuple",
            "typecode": components.typecode,
            "data": b64encode(components.tobytes()).decode("ascii"),
        }
    if isinstance(value, tuple):
        return {_TYPE_KEY: "tuple", "items": [_encode_worker_value(item) for item in value]}
    if isinstance(value, list):
        return [_encode_worker_value(item) for item in value]
    if isinstance(value, dict):
        return {
            _TYPE_KEY: "dict",
            "items": [
                [_encode_worker_value(key), _encode_worker_value(item)]
                for key, item in value.items()
            ],
        }
    if is_dataclass(value):
        return {
            _TYPE_KEY: "object",
            _CLASS_KEY: _allowed_worker_class_key(type(value)),
            "fields": {
                field_name: _encode_worker_value(getattr(value, field_name))
                for field_name in _dataclass_field_names(type(value))
            },
        }
    slot_names = _slot_names(type(value))
    if slot_names:
        return {
            _TYPE_KEY: "object",
            _CLASS_KEY: _allowed_worker_class_key(type(value)),
            "fields": {name: _encode_worker_value(getattr(value, name)) for name in slot_names},
        }
    raise TypeError(f"Unsupported worker payload type: {type(value).__module__}.{type(value).__qualname__}.")


def _decode_worker_value(value: object) -> object:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, list):
        return [_decode_worker_value(item) for item in value]
    if not isinstance(value, dict):
        raise TypeError(f"Invalid worker payload value type: {type(value).__name__}.")
    payload_type = value.get(_TYPE_KEY)
    if payload_type is None:
        return {key: _decode_worker_value(item) for key, item in value.items()}
    if payload_type == "array":
        decoded = array(str(value["typecode"]))
        decoded.frombytes(b64decode(str(value["data"]).encode("ascii")))
        return decoded
    if payload_type == "bytes":
        return b64decode(str(value["data"]).encode("ascii"))
    if payload_type == "path":
        return Path(str(value["value"]))
    if payload_type == "tuple":
        items = value.get("items")
        if not isinstance(items, list):
            raise TypeError("Worker tuple payload must contain an item list.")
        return tuple(_decode_worker_value(item) for item in items)
    if payload_type == "vector3_tuple":
        cls = _allowed_worker_class(str(value[_CLASS_KEY]))
        components = array("d")
        components.frombytes(b64decode(str(value["data"]).encode("ascii")))
        if len(components) % 3:
            raise TypeError("Worker Vector3 tuple payload has an invalid component count.")
        return tuple(cls(*components[index : index + 3]) for index in range(0, len(components), 3))
    if payload_type == "model_value_tuple":
        cls = _allowed_worker_class(str(value[_CLASS_KEY]))
        width = int(value["width"])
        components = array("d")
        components.frombytes(b64decode(str(value["data"]).encode("ascii")))
        if width <= 0 or len(components) % width:
            raise TypeError("Worker model-value tuple payload has an invalid component count.")
        return tuple(cls(*components[index : index + width]) for index in range(0, len(components), width))
    if payload_type == "numeric_tuple":
        typecode = str(value["typecode"])
        if typecode not in {"q", "d"}:
            raise TypeError(f"Worker numeric tuple payload has unsupported typecode {typecode!r}.")
        components = array(typecode)
        components.frombytes(b64decode(str(value["data"]).encode("ascii")))
        return tuple(components)
    if payload_type == "dict":
        items = value.get("items")
        if not isinstance(items, list):
            raise TypeError("Worker dict payload must contain an item list.")
        return {_decode_worker_value(key): _decode_worker_value(item) for key, item in items}
    if payload_type == "enum":
        cls = _allowed_worker_class(str(value[_CLASS_KEY]))
        if not issubclass(cls, Enum):
            raise TypeError("Worker enum payload class is not an Enum.")
        return cls(value["value"])
    if payload_type == "object":
        cls = _allowed_worker_class(str(value[_CLASS_KEY]))
        raw_fields = value.get("fields")
        if not isinstance(raw_fields, dict):
            raise TypeError("Worker object payload must contain a field object.")
        return cls(**{name: _decode_worker_value(item) for name, item in raw_fields.items()})
    raise TypeError(f"Unsupported worker payload marker: {payload_type}.")


def _packed_model_value_fields(value: object) -> tuple[str, ...] | None:
    if not isinstance(value, tuple) or not value:
        return None
    cls = type(value[0])
    fields_by_name = {
        "Vector2": ("x", "y"),
        "Vector3": ("x", "y", "z"),
        "Color4": ("r", "g", "b", "a"),
        "Quaternion": ("real", "i", "j", "k"),
    }
    field_names = fields_by_name.get(cls.__qualname__) if cls.__module__ == "xml_to_usda.models" else None
    if field_names is None or not all(type(item) is cls for item in value):
        return None
    return field_names


@lru_cache(maxsize=None)
def _allowed_worker_class_key(cls: type) -> str:
    key = f"{cls.__module__}.{cls.__qualname__}"
    if cls.__module__ not in _WORKER_PAYLOAD_MODULES or not _is_allowed_worker_payload_class(cls):
        raise TypeError(f"Unsupported worker payload class: {key}.")
    return key


def _allowed_worker_class(key: str) -> type:
    module_name, _, qualname = key.rpartition(".")
    if module_name not in _WORKER_PAYLOAD_MODULES or not qualname:
        raise TypeError(f"Unsupported worker payload class: {key}.")
    cached = _ALLOWED_CLASS_CACHE.get(key)
    current_module = sys.modules.get(module_name)
    if cached is not None and current_module is cached[0]:
        return cached[1]
    obj: object = import_module(module_name)
    module = obj
    for part in qualname.split("."):
        obj = getattr(obj, part)
    if not isinstance(obj, type) or obj.__module__ != module_name or not _is_allowed_worker_payload_class(obj):
        raise TypeError(f"Unsupported worker payload class: {key}.")
    _ALLOWED_CLASS_CACHE[key] = (module, obj)
    return obj


@lru_cache(maxsize=None)
def _is_allowed_worker_payload_class(cls: type) -> bool:
    return is_dataclass(cls) or issubclass(cls, Enum) or bool(_slot_names(cls))


@lru_cache(maxsize=None)
def _dataclass_field_names(cls: type) -> tuple[str, ...]:
    return tuple(field.name for field in fields(cls))


@lru_cache(maxsize=None)
def _slot_names(cls: type) -> tuple[str, ...]:
    names: list[str] = []
    for owner in reversed(cls.__mro__):
        slots = getattr(owner, "__slots__", ())
        if isinstance(slots, str):
            slots = (slots,)
        names.extend(name for name in slots if name not in {"__dict__", "__weakref__"})
    return tuple(names)
