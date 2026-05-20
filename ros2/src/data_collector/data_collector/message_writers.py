from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import cv2
import numpy as np
import sensor_msgs_py.point_cloud2 as pc2
from geometry_msgs.msg import PoseStamped
from rclpy.serialization import serialize_message
from sensor_msgs.msg import CameraInfo, CompressedImage, Image, JointState, PointCloud2
from std_msgs.msg import Float32MultiArray, String

from .config import TopicConfig
from .hdf5_storage import Hdf5EpisodeStorage, split_hdf5_path


class Hdf5MessageWriter(ABC):
    writer_id: str

    def write(
        self,
        hdf5_file: Any,
        topic: TopicConfig,
        messages: list[Any],
        compression: str | None,
    ) -> None:
        """Compatibility batch API backed by the streaming topic API."""
        storage = Hdf5EpisodeStorage(hdf5_file, compression=compression)
        stream = self.open_stream(storage, topic)
        sample_times = list(range(len(messages)))
        for sample_index, message in enumerate(messages):
            stream.append(sample_index, sample_index, message)
        stream.finalize(list(range(len(messages))), sample_times)

    @abstractmethod
    def open_stream(
        self,
        storage: Hdf5EpisodeStorage,
        topic: TopicConfig,
    ) -> TopicMessageStream:
        """Open one topic stream inside an episode storage target."""


class TopicMessageStream(ABC):
    def __init__(self, storage: Hdf5EpisodeStorage, topic: TopicConfig, writer_id: str):
        self.storage = storage
        self.topic = topic
        self.writer_id = writer_id

    @abstractmethod
    def append(self, sample_index: int, sample_time_ns: int, message: Any) -> None:
        """Append one present topic message."""

    def finalize(self, present_indices: list[int], sample_time_ns: list[int]) -> None:
        target = self._target()
        if target is None:
            return
        target.attrs["sample_count"] = len(present_indices)
        if not present_indices or len(present_indices) == len(sample_time_ns):
            return

        target.attrs["partial_samples"] = True
        if hasattr(target, "create_dataset"):
            index_owner = target
            index_name = "sample_index"
            time_name = "sample_time_ns"
        else:
            parent_path, dataset_name = split_hdf5_path(self.topic.dataset)
            index_owner = self.storage.get(parent_path) if parent_path else self.storage.hdf5_file
            index_name = f"{dataset_name}_sample_index"
            time_name = f"{dataset_name}_sample_time_ns"

        indices = np.asarray(present_indices, dtype=np.int64)
        times = np.asarray([sample_time_ns[index] for index in present_indices], dtype=np.int64)
        index_owner.create_dataset(index_name, data=indices, compression=self.storage.compression)
        time_dataset = index_owner.create_dataset(
            time_name,
            data=times,
            compression=self.storage.compression,
        )
        time_dataset.attrs["clock"] = "unix_wall_time"
        time_dataset.attrs["unit"] = "nanoseconds"

    def _set_common_attrs(self, path: str | None = None) -> Any:
        target = self.storage.get(path or self.topic.dataset)
        target.attrs["topic"] = self.topic.topic
        target.attrs["type"] = self.topic.type_name
        target.attrs["writer"] = self.writer_id
        return target

    def _target(self) -> Any | None:
        try:
            return self.storage.get(self.topic.dataset)
        except KeyError:
            return None


class ImageCompressedWriter(Hdf5MessageWriter):
    writer_id = "image_compressed"

    def open_stream(
        self,
        storage: Hdf5EpisodeStorage,
        topic: TopicConfig,
    ) -> TopicMessageStream:
        return ImageCompressedStream(storage, topic, self.writer_id)


class ImageRawWriter(Hdf5MessageWriter):
    writer_id = "image_raw"

    def open_stream(
        self,
        storage: Hdf5EpisodeStorage,
        topic: TopicConfig,
    ) -> TopicMessageStream:
        return ImageRawStream(storage, topic, self.writer_id)


class CompressedImageWriter(Hdf5MessageWriter):
    writer_id = "compressed_image"

    def open_stream(
        self,
        storage: Hdf5EpisodeStorage,
        topic: TopicConfig,
    ) -> TopicMessageStream:
        return CompressedImageStream(storage, topic, self.writer_id)


class PointCloudXyzRgbWriter(Hdf5MessageWriter):
    writer_id = "pointcloud_xyzrgb"

    def __init__(self, num_points: int = 2048):
        self._num_points = num_points

    def open_stream(
        self,
        storage: Hdf5EpisodeStorage,
        topic: TopicConfig,
    ) -> TopicMessageStream:
        return PointCloudXyzRgbStream(storage, topic, self.writer_id, self._num_points)


class CameraInfoWriter(Hdf5MessageWriter):
    writer_id = "camera_info"

    def open_stream(
        self,
        storage: Hdf5EpisodeStorage,
        topic: TopicConfig,
    ) -> TopicMessageStream:
        return CameraInfoStream(storage, topic, self.writer_id)


class PoseStampedWriter(Hdf5MessageWriter):
    writer_id = "pose_stamped"

    def open_stream(
        self,
        storage: Hdf5EpisodeStorage,
        topic: TopicConfig,
    ) -> TopicMessageStream:
        return PoseStampedStream(storage, topic, self.writer_id)


class JointStateWriter(Hdf5MessageWriter):
    writer_id = "joint_state"

    def open_stream(
        self,
        storage: Hdf5EpisodeStorage,
        topic: TopicConfig,
    ) -> TopicMessageStream:
        return JointStateStream(storage, topic, self.writer_id)


class StringWriter(Hdf5MessageWriter):
    writer_id = "string"

    def open_stream(
        self,
        storage: Hdf5EpisodeStorage,
        topic: TopicConfig,
    ) -> TopicMessageStream:
        return StringStream(storage, topic, self.writer_id)


class Float32MultiArrayWriter(Hdf5MessageWriter):
    writer_id = "float32_multi_array"

    def open_stream(
        self,
        storage: Hdf5EpisodeStorage,
        topic: TopicConfig,
    ) -> TopicMessageStream:
        return Float32MultiArrayStream(storage, topic, self.writer_id)


class SerializedCdrWriter(Hdf5MessageWriter):
    writer_id = "serialized_cdr"

    def open_stream(
        self,
        storage: Hdf5EpisodeStorage,
        topic: TopicConfig,
    ) -> TopicMessageStream:
        return SerializedCdrStream(storage, topic, self.writer_id)


class ImageCompressedStream(TopicMessageStream):
    def append(self, sample_index: int, sample_time_ns: int, message: Image) -> None:
        payload, image_format = _encode_image_message(message)
        dataset = self.storage.append_bytes(self.topic.dataset, payload)
        self._set_common_attrs()
        self.storage.append_csv_attr(self.topic.dataset, "format", image_format)
        dataset.attrs["source_encoding"] = message.encoding


class ImageRawStream(TopicMessageStream):
    def append(self, sample_index: int, sample_time_ns: int, message: Image) -> None:
        dataset = self.storage.append_array(self.topic.dataset, _image_to_array(message))
        self._set_common_attrs()
        dataset.attrs["source_encoding"] = message.encoding


class CompressedImageStream(TopicMessageStream):
    def append(self, sample_index: int, sample_time_ns: int, message: CompressedImage) -> None:
        dataset = self.storage.append_bytes(self.topic.dataset, bytes(message.data))
        self._set_common_attrs()
        dataset.attrs["format"] = message.format


class PointCloudXyzRgbStream(TopicMessageStream):
    def __init__(
        self,
        storage: Hdf5EpisodeStorage,
        topic: TopicConfig,
        writer_id: str,
        num_points: int,
    ):
        super().__init__(storage, topic, writer_id)
        self._num_points = num_points

    def append(self, sample_index: int, sample_time_ns: int, message: PointCloud2) -> None:
        dataset = self.storage.append_array(
            self.topic.dataset,
            _pointcloud_to_array(message, self._num_points),
        )
        self._set_common_attrs()
        dataset.attrs["columns"] = "x,y,z,r,g,b"
        dataset.attrs["point_fields"] = ",".join(sorted(_pointcloud_field_names(message)))


class CameraInfoStream(TopicMessageStream):
    def append(self, sample_index: int, sample_time_ns: int, message: CameraInfo) -> None:
        group = self.storage.require_group(self.topic.dataset)
        group.attrs["topic"] = self.topic.topic
        group.attrs["type"] = self.topic.type_name
        group.attrs["writer"] = self.writer_id

        _append_header_stream(self.storage, self.topic.dataset, message)
        _append_numeric_stream(self.storage, f"{self.topic.dataset}/height", message.height)
        _append_numeric_stream(self.storage, f"{self.topic.dataset}/width", message.width)
        _append_numeric_stream(self.storage, f"{self.topic.dataset}/d", message.d)
        _append_numeric_stream(self.storage, f"{self.topic.dataset}/k", message.k)
        _append_numeric_stream(self.storage, f"{self.topic.dataset}/r", message.r)
        _append_numeric_stream(self.storage, f"{self.topic.dataset}/p", message.p)
        _append_numeric_stream(self.storage, f"{self.topic.dataset}/binning_x", message.binning_x)
        _append_numeric_stream(self.storage, f"{self.topic.dataset}/binning_y", message.binning_y)
        self.storage.append_bytes(
            f"{self.topic.dataset}/distortion_model",
            message.distortion_model.encode("utf-8"),
        )

        roi_path = f"{self.topic.dataset}/roi"
        self.storage.require_group(roi_path)
        _append_numeric_stream(self.storage, f"{roi_path}/x_offset", message.roi.x_offset)
        _append_numeric_stream(self.storage, f"{roi_path}/y_offset", message.roi.y_offset)
        _append_numeric_stream(self.storage, f"{roi_path}/height", message.roi.height)
        _append_numeric_stream(self.storage, f"{roi_path}/width", message.roi.width)
        self.storage.append_array(
            f"{roi_path}/do_rectify",
            np.asarray(message.roi.do_rectify, dtype=np.bool_),
        )


class PoseStampedStream(TopicMessageStream):
    def append(self, sample_index: int, sample_time_ns: int, message: PoseStamped) -> None:
        dataset = self.storage.append_array(self.topic.dataset, _pose_stamped_to_array(message))
        self._set_common_attrs()
        dataset.attrs["columns"] = "x,y,z,qx,qy,qz,qw"


class JointStateStream(TopicMessageStream):
    def append(self, sample_index: int, sample_time_ns: int, message: JointState) -> None:
        group = self.storage.require_group(self.topic.dataset)
        group.attrs["topic"] = self.topic.topic
        group.attrs["type"] = self.topic.type_name
        group.attrs["writer"] = self.writer_id
        _append_numeric_stream(self.storage, f"{self.topic.dataset}/position", message.position)
        _append_numeric_stream(self.storage, f"{self.topic.dataset}/velocity", message.velocity)
        _append_numeric_stream(self.storage, f"{self.topic.dataset}/effort", message.effort)
        self.storage.append_bytes(
            f"{self.topic.dataset}/name",
            "\n".join(message.name).encode("utf-8"),
        )


class StringStream(TopicMessageStream):
    def append(self, sample_index: int, sample_time_ns: int, message: String) -> None:
        dataset = self.storage.append_bytes(self.topic.dataset, message.data.encode("utf-8"))
        self._set_common_attrs()
        dataset.attrs["encoding"] = "utf-8"


class Float32MultiArrayStream(TopicMessageStream):
    def append(self, sample_index: int, sample_time_ns: int, message: Float32MultiArray) -> None:
        self.storage.append_array(
            self.topic.dataset,
            np.asarray(message.data, dtype=np.float64),
        )
        self._set_common_attrs()


class SerializedCdrStream(TopicMessageStream):
    def append(self, sample_index: int, sample_time_ns: int, message: Any) -> None:
        self.storage.append_bytes(self.topic.dataset, bytes(serialize_message(message)))
        self._set_common_attrs()


WRITERS: dict[str, Hdf5MessageWriter] = {
    ImageCompressedWriter.writer_id: ImageCompressedWriter(),
    ImageRawWriter.writer_id: ImageRawWriter(),
    CameraInfoWriter.writer_id: CameraInfoWriter(),
    CompressedImageWriter.writer_id: CompressedImageWriter(),
    PointCloudXyzRgbWriter.writer_id: PointCloudXyzRgbWriter(),
    PoseStampedWriter.writer_id: PoseStampedWriter(),
    JointStateWriter.writer_id: JointStateWriter(),
    StringWriter.writer_id: StringWriter(),
    Float32MultiArrayWriter.writer_id: Float32MultiArrayWriter(),
    SerializedCdrWriter.writer_id: SerializedCdrWriter(),
}

DEFAULT_WRITERS_BY_TYPE = {
    "sensor_msgs/msg/Image": ImageCompressedWriter.writer_id,
    "sensor_msgs/msg/CameraInfo": CameraInfoWriter.writer_id,
    "sensor_msgs/msg/CompressedImage": CompressedImageWriter.writer_id,
    "sensor_msgs/msg/PointCloud2": PointCloudXyzRgbWriter.writer_id,
    "sensor_msgs/msg/JointState": JointStateWriter.writer_id,
    "geometry_msgs/msg/PoseStamped": PoseStampedWriter.writer_id,
    "std_msgs/msg/String": StringWriter.writer_id,
    "std_msgs/msg/Float32MultiArray": Float32MultiArrayWriter.writer_id,
}


def resolve_message_writer(type_name: str, writer_id: str | None) -> Hdf5MessageWriter:
    resolved_id = (
        writer_id or DEFAULT_WRITERS_BY_TYPE.get(type_name) or SerializedCdrWriter.writer_id
    )
    try:
        return WRITERS[resolved_id]
    except KeyError as exc:
        known = ", ".join(sorted(WRITERS))
        raise ValueError(
            f"Unknown writer '{resolved_id}' for {type_name}. Known writers: {known}"
        ) from exc


def _append_header_stream(storage: Hdf5EpisodeStorage, group_path: str, message: Any) -> None:
    stamp_ns = (message.header.stamp.sec * 1_000_000_000) + message.header.stamp.nanosec
    stamp_ns_dataset = storage.append_array(
        f"{group_path}/header_stamp_ns",
        np.asarray(stamp_ns, dtype=np.int64),
    )
    stamp_ns_dataset.attrs["unit"] = "nanoseconds"

    stamp_dataset = storage.append_array(
        f"{group_path}/header_stamp",
        np.asarray(stamp_ns / 1_000_000_000.0, dtype=np.float64),
    )
    stamp_dataset.attrs["unit"] = "seconds"
    storage.append_bytes(f"{group_path}/frame_id", message.header.frame_id.encode("utf-8"))


def _append_numeric_stream(storage: Hdf5EpisodeStorage, path: str, value: Any) -> Any:
    return storage.append_array(path, np.asarray(value, dtype=np.float64))


def _image_to_array(message: Image) -> np.ndarray:
    dtype = np.uint16 if message.encoding in {"16UC1", "mono16"} else np.uint8
    channels = 3 if message.encoding in {"rgb8", "bgr8"} else 1
    itemsize = np.dtype(dtype).itemsize
    row_width = message.step // itemsize
    array = np.frombuffer(message.data, dtype=dtype).reshape(message.height, row_width)

    if channels == 1:
        return array[:, : message.width].copy()

    pixel_width = message.width * channels
    image = array[:, :pixel_width].reshape(message.height, message.width, channels)
    if message.encoding == "bgr8":
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    return image.copy()


def _encode_image_message(message: Image) -> tuple[bytes, str]:
    image = _image_to_array(message)
    if image.dtype == np.uint8 and image.ndim == 3:
        encode_ext = ".jpg"
    else:
        encode_ext = ".png"

    ok, encoded = cv2.imencode(encode_ext, image)
    if not ok:
        raise ValueError(f"Failed to encode Image message with encoding '{message.encoding}'.")
    return encoded.tobytes(), encode_ext.lstrip(".")


def _pointcloud_to_array(message: PointCloud2, num_points: int) -> np.ndarray:
    fields = _pointcloud_field_names(message)
    missing_position_fields = {"x", "y", "z"} - fields
    if missing_position_fields:
        missing = ", ".join(sorted(missing_position_fields))
        available = ", ".join(sorted(fields)) or "<none>"
        raise ValueError(
            f"PointCloud2 message is missing required field(s): {missing}. "
            f"Available fields: {available}."
        )

    color_fields = _pointcloud_color_fields(fields)
    requested_fields = ["x", "y", "z", *color_fields]
    cloud = pc2.read_points(message, field_names=requested_fields, skip_nans=True)
    point_count = len(cloud)
    if point_count == 0:
        return np.zeros((num_points, 6), dtype=np.float32)

    if point_count > num_points:
        indices = np.random.choice(point_count, num_points, replace=False)
        cloud = cloud[indices]
        point_count = num_points

    points = np.empty((point_count, 6), dtype=np.float32)
    points[:, 0] = cloud["x"]
    points[:, 1] = cloud["y"]
    points[:, 2] = cloud["z"]

    if color_fields in (["rgb"], ["rgba"]):
        packed_color = cloud[color_fields[0]]
        if np.issubdtype(packed_color.dtype, np.floating):
            packed = np.ascontiguousarray(packed_color, dtype=np.float32).view(np.uint32)
        else:
            packed = np.asarray(packed_color, dtype=np.uint32)

        points[:, 3] = (packed >> 16) & 0xFF
        points[:, 4] = (packed >> 8) & 0xFF
        points[:, 5] = packed & 0xFF
    elif color_fields == ["r", "g", "b"]:
        points[:, 3] = cloud["r"]
        points[:, 4] = cloud["g"]
        points[:, 5] = cloud["b"]
    else:
        points[:, 3:] = 0

    if point_count < num_points:
        padding = np.zeros((num_points - point_count, 6), dtype=np.float32)
        points = np.vstack([points, padding])

    return points


def _pointcloud_field_names(message: PointCloud2) -> set[str]:
    return {field.name for field in message.fields}


def _pointcloud_color_fields(fields: set[str]) -> list[str]:
    if "rgb" in fields:
        return ["rgb"]
    if "rgba" in fields:
        return ["rgba"]
    if {"r", "g", "b"}.issubset(fields):
        return ["r", "g", "b"]
    return []


def _pose_stamped_to_array(message: PoseStamped) -> np.ndarray:
    pose = message.pose
    return np.array(
        [
            pose.position.x,
            pose.position.y,
            pose.position.z,
            pose.orientation.x,
            pose.orientation.y,
            pose.orientation.z,
            pose.orientation.w,
        ],
        dtype=np.float64,
    )
