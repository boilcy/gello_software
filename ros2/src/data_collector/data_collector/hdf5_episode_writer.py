from __future__ import annotations

import os
import queue
import threading
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np

from .config import TopicConfig
from .hdf5_storage import Hdf5EpisodeStorage
from .message_writers import TopicMessageStream, resolve_message_writer

DATA_SCHEMA_VERSION = "1"
_STOP_WRITER = object()


@dataclass(frozen=True)
class Sample:
    index: int
    time_ns: int
    messages: dict[str, Any | None]


@dataclass(frozen=True)
class TopicWriteSummary:
    name: str
    topic: str
    dataset: str
    writer: str
    present_count: int
    missing_count: int
    present_indices: tuple[int, ...]
    missing_indices: tuple[int, ...]


@dataclass(frozen=True)
class EpisodeSummary:
    filename: str
    sample_count: int
    written_sample_count: int
    started_at_unix_ns: int
    finished_at_unix_ns: int
    topics: tuple[TopicWriteSummary, ...]


class Hdf5EpisodeWriter:
    def __init__(
        self,
        data_root: str,
        topics: tuple[TopicConfig, ...],
        static_topics: tuple[TopicConfig, ...] = (),
        compression: str | None = "gzip",
        collection_rate_hz: float | None = None,
        subscription_queue_size: int | None = None,
        require_complete_samples: bool | None = None,
        writer_queue_size: int = 8,
        writer_put_timeout_sec: float = 0.1,
        flush_every_samples: int = 30,
        flush_every_seconds: float = 1.0,
    ):
        self._data_root = data_root
        self._topics = topics
        self._static_topics = static_topics
        self._compression = compression
        self._collection_rate_hz = collection_rate_hz
        self._subscription_queue_size = subscription_queue_size
        self._require_complete_samples = require_complete_samples
        self._writer_queue_size = writer_queue_size
        self._writer_put_timeout_sec = writer_put_timeout_sec
        self._flush_every_samples = flush_every_samples
        self._flush_every_seconds = flush_every_seconds
        self._timestamp = time.strftime("%Y-%m-%d-%H-%M-%S", time.localtime())
        self._episode_index = 0
        self._sample_count = 0
        self._written_sample_count = 0
        self._sample_time_ns: list[int] = []
        self._present_indices: dict[str, list[int]] = {topic.name: [] for topic in topics}
        self._missing_indices: dict[str, list[int]] = {topic.name: [] for topic in topics}
        self._filename: str | None = None
        self._queue: queue.Queue[Sample | object] | None = None
        self._thread: threading.Thread | None = None
        self._worker_error: BaseException | None = None
        self._started_at_ns: int | None = None
        self._last_summary: EpisodeSummary | None = None

    @property
    def sample_count(self) -> int:
        return self._sample_count

    @property
    def last_summary(self) -> EpisodeSummary | None:
        return self._last_summary

    def start(self) -> str:
        self._ensure_started()
        assert self._filename is not None
        return self._filename

    def append(
        self,
        sample_or_snapshot: Sample | dict[str, Any | None],
        sample_time_ns: int | None = None,
    ) -> None:
        self._raise_worker_error()
        sample = self._coerce_sample(sample_or_snapshot, sample_time_ns)
        if sample.index != self._sample_count:
            raise ValueError(
                f"Sample index {sample.index} does not match next index {self._sample_count}."
            )
        self._validate_required_topics(sample.messages)
        self._ensure_started()

        assert self._queue is not None
        try:
            self._queue.put(sample, timeout=self._writer_put_timeout_sec)
        except queue.Full as exc:
            raise TimeoutError(
                "HDF5 writer queue is full. Primary data cannot be persisted fast enough "
                f"(queue_size={self._writer_queue_size}, sample_index={sample.index})."
            ) from exc

        self._sample_time_ns.append(sample.time_ns)
        self._sample_count = max(self._sample_count, sample.index + 1)

    def finish(self, static_snapshot: dict[str, Any | None] | None = None) -> str | None:
        return self.save(static_snapshot)

    def save(self, static_snapshot: dict[str, Any | None] | None = None) -> str | None:
        if not self._sample_count:
            if self._thread is not None:
                filename = self._filename
                self._finish_writer_thread()
                self._raise_worker_error()
                if filename and os.path.exists(filename):
                    os.remove(filename)
                self.clear()
            return None

        self._finish_writer_thread()
        self._raise_worker_error()
        assert self._filename is not None
        assert self._started_at_ns is not None
        filename = self._filename
        finished_at_ns = time.time_ns()

        storage = Hdf5EpisodeStorage(filename, compression=self._compression, mode="a")
        try:
            storage.hdf5_file.attrs["sample_count"] = self._written_sample_count
            for topic in self._topics:
                stream = self._open_topic_stream(storage, topic)
                stream.finalize(self._present_indices[topic.name], self._sample_time_ns)

            self._write_static_topics(storage, static_snapshot or {}, finished_at_ns)
            summary = self._build_summary(filename, self._started_at_ns, finished_at_ns)
            self._write_episode_summary(storage, summary)
            storage.flush()
        finally:
            storage.close()

        self._last_summary = summary
        self._episode_index += 1
        self.clear(keep_last_summary=True)
        return filename

    def clear(self, keep_last_summary: bool = False) -> None:
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("Cannot clear an active HDF5 writer.")
        last_summary = self._last_summary if keep_last_summary else None
        self._sample_count = 0
        self._written_sample_count = 0
        self._sample_time_ns.clear()
        self._present_indices = {topic.name: [] for topic in self._topics}
        self._missing_indices = {topic.name: [] for topic in self._topics}
        self._filename = None
        self._queue = None
        self._thread = None
        self._worker_error = None
        self._started_at_ns = None
        self._last_summary = last_summary

    def _coerce_sample(
        self,
        sample_or_snapshot: Sample | dict[str, Any | None],
        sample_time_ns: int | None,
    ) -> Sample:
        if isinstance(sample_or_snapshot, Sample):
            return sample_or_snapshot
        if sample_time_ns is None:
            raise ValueError("sample_time_ns is required when appending a snapshot.")
        return Sample(
            index=self._sample_count,
            time_ns=sample_time_ns,
            messages=sample_or_snapshot,
        )

    def _validate_required_topics(self, snapshot: dict[str, Any | None]) -> None:
        missing = [
            topic.name
            for topic in self._topics
            if topic.required and snapshot.get(topic.name) is None
        ]
        if missing:
            raise ValueError(
                "Required topic(s) missing from sample: " + ", ".join(sorted(missing))
            )

    def _ensure_started(self) -> None:
        if self._thread is not None:
            return

        filename = os.path.join(
            self._data_root,
            self._timestamp,
            f"episode{self._episode_index}.hdf5",
        )
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        self._filename = filename
        self._queue = queue.Queue(maxsize=self._writer_queue_size)
        self._started_at_ns = time.time_ns()
        self._thread = threading.Thread(
            target=self._write_samples_until_stopped,
            args=(filename, self._started_at_ns),
            name=f"data_collector_hdf5_episode_{self._episode_index}",
            daemon=False,
        )
        self._thread.start()

    def _finish_writer_thread(self) -> None:
        self._raise_worker_error()
        assert self._queue is not None
        assert self._thread is not None
        self._queue.put(_STOP_WRITER)
        self._thread.join()
        self._raise_worker_error()

    def _write_samples_until_stopped(self, filename: str, created_at_ns: int) -> None:
        storage = Hdf5EpisodeStorage(filename, compression=self._compression, mode="w")
        streams = {
            topic.name: self._open_topic_stream(storage, topic)
            for topic in self._topics
        }
        last_flush = time.monotonic()
        try:
            storage.hdf5_file.attrs["collector"] = "data_collector"
            storage.hdf5_file.attrs["data_schema_version"] = DATA_SCHEMA_VERSION
            storage.hdf5_file.attrs["sample_count"] = 0
            _write_collector_metadata(storage, self._build_metadata_payload(created_at_ns))

            while True:
                assert self._queue is not None
                item = self._queue.get()
                try:
                    if item is _STOP_WRITER:
                        storage.hdf5_file.attrs["sample_count"] = self._written_sample_count
                        storage.flush()
                        return
                    assert isinstance(item, Sample)
                    self._write_sample(storage, streams, item)
                    self._written_sample_count += 1
                    last_flush = self._flush_if_due(storage, last_flush)
                finally:
                    self._queue.task_done()
        except BaseException as exc:  # noqa: BLE001 - propagated to caller on append/finish.
            self._worker_error = exc
        finally:
            storage.close()

    def _write_sample(
        self,
        storage: Hdf5EpisodeStorage,
        streams: dict[str, TopicMessageStream],
        sample: Sample,
    ) -> None:
        _append_sample_time(storage, sample.time_ns)
        for topic in self._topics:
            message = sample.messages.get(topic.name)
            if message is None:
                self._missing_indices[topic.name].append(sample.index)
                continue
            streams[topic.name].append(sample.index, sample.time_ns, message)
            self._present_indices[topic.name].append(sample.index)

    def _flush_if_due(self, storage: Hdf5EpisodeStorage, last_flush: float) -> float:
        now = time.monotonic()
        sample_due = (
            self._flush_every_samples > 0
            and self._written_sample_count % self._flush_every_samples == 0
        )
        time_due = self._flush_every_seconds > 0 and now - last_flush >= self._flush_every_seconds
        if sample_due or time_due:
            storage.flush()
            return now
        return last_flush

    def _open_topic_stream(
        self,
        storage: Hdf5EpisodeStorage,
        topic: TopicConfig,
    ) -> TopicMessageStream:
        writer = resolve_message_writer(topic.type_name, topic.writer)
        return writer.open_stream(storage, topic)

    def _write_static_topics(
        self,
        storage: Hdf5EpisodeStorage,
        static_snapshot: dict[str, Any | None],
        sample_time_ns: int,
    ) -> None:
        for topic in self._static_topics:
            message = static_snapshot.get(topic.name)
            if message is None:
                if topic.required:
                    raise ValueError(
                        f"Required static topic '{topic.name}' ({topic.topic}) "
                        "has not received a message."
                    )
                continue

            stream = self._open_topic_stream(storage, topic)
            stream.append(0, sample_time_ns, message)
            stream.finalize([0], [sample_time_ns])
            target = storage.get(topic.dataset)
            target.attrs["static"] = True
            target.attrs["sample_count"] = 1

    def _raise_worker_error(self) -> None:
        if self._worker_error is not None:
            raise RuntimeError("HDF5 writer worker failed.") from self._worker_error

    def _build_metadata_payload(self, created_at_ns: int) -> dict[str, Any]:
        return {
            "collector": "data_collector",
            "data_schema_version": DATA_SCHEMA_VERSION,
            "created_at_unix_ns": created_at_ns,
            "created_at_utc": datetime.fromtimestamp(
                created_at_ns / 1_000_000_000,
                tz=UTC,
            ).isoformat(),
            "data_root": self._data_root,
            "hdf5_compression": self._compression,
            "collection_rate_hz": self._collection_rate_hz,
            "subscription_queue_size": self._subscription_queue_size,
            "require_complete_samples": self._require_complete_samples,
            "writer_queue_size": self._writer_queue_size,
            "writer_put_timeout_sec": self._writer_put_timeout_sec,
            "flush_every_samples": self._flush_every_samples,
            "flush_every_seconds": self._flush_every_seconds,
            "topics": [_topic_metadata(topic, static=False) for topic in self._topics],
            "static_topics": [
                _topic_metadata(topic, static=True) for topic in self._static_topics
            ],
        }

    def _build_summary(
        self,
        filename: str,
        started_at_ns: int,
        finished_at_ns: int,
    ) -> EpisodeSummary:
        return EpisodeSummary(
            filename=filename,
            sample_count=self._sample_count,
            written_sample_count=self._written_sample_count,
            started_at_unix_ns=started_at_ns,
            finished_at_unix_ns=finished_at_ns,
            topics=tuple(
                TopicWriteSummary(
                    name=topic.name,
                    topic=topic.topic,
                    dataset=topic.dataset,
                    writer=resolve_message_writer(topic.type_name, topic.writer).writer_id,
                    present_count=len(self._present_indices[topic.name]),
                    missing_count=len(self._missing_indices[topic.name]),
                    present_indices=tuple(self._present_indices[topic.name]),
                    missing_indices=tuple(self._missing_indices[topic.name]),
                )
                for topic in self._topics
            ),
        )

    def _write_episode_summary(
        self,
        storage: Hdf5EpisodeStorage,
        summary: EpisodeSummary,
    ) -> None:
        summary_payload = asdict(summary)
        storage.write_json("metadata/collector/episode_summary_json", summary_payload)


def _write_collector_metadata(storage: Hdf5EpisodeStorage, payload: dict[str, Any]) -> None:
    collector_group = storage.require_group("metadata/collector")
    collector_group.attrs["data_schema_version"] = payload["data_schema_version"]
    collector_group.attrs["created_at_unix_ns"] = payload["created_at_unix_ns"]
    collector_group.attrs["created_at_utc"] = payload["created_at_utc"]
    collector_group.attrs["hdf5_compression"] = payload["hdf5_compression"] or ""
    collector_group.attrs["writer_queue_size"] = payload["writer_queue_size"]
    collector_group.attrs["writer_put_timeout_sec"] = payload["writer_put_timeout_sec"]
    collector_group.attrs["flush_every_samples"] = payload["flush_every_samples"]
    collector_group.attrs["flush_every_seconds"] = payload["flush_every_seconds"]
    storage.write_json("metadata/collector/config_json", payload)


def _topic_metadata(topic: TopicConfig, static: bool) -> dict[str, Any]:
    writer = resolve_message_writer(topic.type_name, topic.writer)
    return {
        "name": topic.name,
        "topic": topic.topic,
        "type": topic.type_name,
        "dataset": topic.dataset,
        "writer": topic.writer,
        "resolved_writer": writer.writer_id,
        "required": topic.required,
        "static": static,
    }


def _append_sample_time(storage: Hdf5EpisodeStorage, sample_time_ns: int) -> None:
    ns_dataset = storage.append_array(
        "sample_time_ns",
        np.asarray(sample_time_ns, dtype=np.int64),
    )
    ns_dataset.attrs["clock"] = "unix_wall_time"
    ns_dataset.attrs["unit"] = "nanoseconds"

    sec_dataset = storage.append_array(
        "sample_time",
        np.asarray(sample_time_ns / 1_000_000_000.0, dtype=np.float64),
    )
    sec_dataset.attrs["clock"] = "unix_wall_time"
    sec_dataset.attrs["unit"] = "seconds"
