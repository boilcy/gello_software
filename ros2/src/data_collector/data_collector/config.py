from dataclasses import dataclass
from typing import Any

from rclpy.node import Node


@dataclass(frozen=True)
class TopicConfig:
    name: str
    topic: str
    type_name: str
    dataset: str
    writer: str | None = None
    required: bool = True


@dataclass(frozen=True)
class CollectorConfig:
    collection_rate_hz: float
    subscription_queue_size: int
    data_root: str
    require_complete_samples: bool
    hdf5_compression: str | None
    writer_queue_size: int
    writer_put_timeout_sec: float
    flush_every_samples: int
    flush_every_seconds: float
    topics: tuple[TopicConfig, ...]
    static_topics: tuple[TopicConfig, ...]


def load_collector_config(node: Node) -> CollectorConfig:
    collection_rate_hz = _get_positive_float(node, "collection_rate_hz", 30.0)
    subscription_queue_size = _get_positive_int(node, "subscription_queue_size", 1)
    data_root = _get_required_string(node, "data_root", "data")
    require_complete_samples = _get_bool(node, "require_complete_samples", True)
    hdf5_compression = _get_optional_string(node, "hdf5_compression", "gzip")
    writer_queue_size = _get_positive_int(node, "writer_queue_size", 8)
    writer_put_timeout_sec = _get_positive_float(node, "writer_put_timeout_sec", 0.1)
    flush_every_samples = _get_non_negative_int(node, "flush_every_samples", 30)
    flush_every_seconds = _get_non_negative_float(node, "flush_every_seconds", 1.0)

    topics = _load_topic_configs(node, "topics", default_required=True)
    static_topics = _load_topic_configs(node, "static_topics", default_required=False)
    if not topics:
        raise ValueError("No topics configured. Add entries under ros__parameters.topics.")

    return CollectorConfig(
        collection_rate_hz=collection_rate_hz,
        subscription_queue_size=subscription_queue_size,
        data_root=data_root,
        require_complete_samples=require_complete_samples,
        hdf5_compression=hdf5_compression,
        writer_queue_size=writer_queue_size,
        writer_put_timeout_sec=writer_put_timeout_sec,
        flush_every_samples=flush_every_samples,
        flush_every_seconds=flush_every_seconds,
        topics=tuple(topics),
        static_topics=tuple(static_topics),
    )


def _load_topic_configs(
    node: Node,
    prefix: str,
    default_required: bool,
) -> list[TopicConfig]:
    raw_params = node.get_parameters_by_prefix(prefix)
    grouped: dict[str, dict[str, Any]] = {}

    for suffix, parameter in raw_params.items():
        name, _, field = suffix.partition(".")
        if not name or not field:
            continue
        grouped.setdefault(name, {})[field] = parameter.value

    topics = []
    for name in sorted(grouped):
        fields = grouped[name]
        topic = _clean_string(fields.get("topic"))
        type_name = _clean_string(fields.get("type"))
        if not topic or not type_name:
            raise ValueError(f"Topic entry '{name}' must define non-empty topic and type fields.")

        dataset = _clean_string(fields.get("dataset")) or name
        writer = _clean_string(fields.get("writer")) or None
        required = _coerce_bool(fields.get("required"), default_required)
        topics.append(
            TopicConfig(
                name=name,
                topic=topic,
                type_name=type_name,
                dataset=dataset,
                writer=writer,
                required=required,
            )
        )

    return topics


def _get_required_string(node: Node, name: str, default: str) -> str:
    value = _clean_string(_get_or_declare(node, name, default))
    if not value:
        raise ValueError(f"ROS parameter '{name}' must be a non-empty string.")
    return value


def _get_optional_string(node: Node, name: str, default: str | None) -> str | None:
    value = _clean_string(_get_or_declare(node, name, default or ""))
    return value or None


def _get_positive_float(node: Node, name: str, default: float) -> float:
    value = float(_get_or_declare(node, name, default))
    if value <= 0.0:
        raise ValueError(f"ROS parameter '{name}' must be positive.")
    return value


def _get_positive_int(node: Node, name: str, default: int) -> int:
    value = int(_get_or_declare(node, name, default))
    if value <= 0:
        raise ValueError(f"ROS parameter '{name}' must be positive.")
    return value


def _get_non_negative_float(node: Node, name: str, default: float) -> float:
    value = float(_get_or_declare(node, name, default))
    if value < 0.0:
        raise ValueError(f"ROS parameter '{name}' must be non-negative.")
    return value


def _get_non_negative_int(node: Node, name: str, default: int) -> int:
    value = int(_get_or_declare(node, name, default))
    if value < 0:
        raise ValueError(f"ROS parameter '{name}' must be non-negative.")
    return value


def _get_bool(node: Node, name: str, default: bool) -> bool:
    return _coerce_bool(_get_or_declare(node, name, default), default)


def _get_or_declare(node: Node, name: str, default: Any) -> Any:
    if not node.has_parameter(name):
        node.declare_parameter(name, default)
    return node.get_parameter(name).value


def _clean_string(value: Any) -> str:
    return str(value or "").strip()


def _coerce_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    return bool(value)
