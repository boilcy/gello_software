from copy import deepcopy
from threading import Lock
from typing import Any

from rosidl_runtime_py.utilities import get_message

from .config import TopicConfig


class DynamicTopicSnapshot:
    def __init__(self, node, topics: tuple[TopicConfig, ...], queue_size: int):
        self._node = node
        self._topics = topics
        self._latest: dict[str, Any | None] = {topic.name: None for topic in topics}
        self._locks = {topic.name: Lock() for topic in topics}
        self._subscriptions = []

        for topic_config in topics:
            msg_type = get_message(topic_config.type_name)
            subscription = node.create_subscription(
                msg_type,
                topic_config.topic,
                self._make_callback(topic_config.name),
                queue_size,
            )
            self._subscriptions.append(subscription)

    def read(self) -> dict[str, Any | None]:
        snapshot = {}
        for name in self._latest:
            with self._locks[name]:
                message = self._latest[name]
                snapshot[name] = deepcopy(message) if message is not None else None
        return snapshot

    def missing_required(self, snapshot: dict[str, Any | None]) -> list[str]:
        return [
            topic.name
            for topic in self._topics
            if topic.required and snapshot.get(topic.name) is None
        ]

    def _make_callback(self, name: str):
        def callback(message):
            with self._locks[name]:
                self._latest[name] = message

        return callback
