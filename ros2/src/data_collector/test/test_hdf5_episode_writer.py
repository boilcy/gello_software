import json
import os

import h5py
import numpy as np
from sensor_msgs.msg import CameraInfo, JointState
from std_msgs.msg import String

from data_collector.config import TopicConfig
from data_collector.hdf5_episode_writer import Hdf5EpisodeWriter, Sample


def test_episode_writer_records_sample_time_and_static_camera_info(tmp_path) -> None:
    joint_topic = TopicConfig(
        name="joint_state",
        topic="/joint_states",
        type_name="sensor_msgs/msg/JointState",
        dataset="robot/joint_state",
    )
    camera_topic = TopicConfig(
        name="cam0_color_camera_info",
        topic="/cam0/color/camera_info",
        type_name="sensor_msgs/msg/CameraInfo",
        dataset="metadata/cam0/color/camera_info",
        writer="camera_info",
    )
    writer = Hdf5EpisodeWriter(
        data_root=str(tmp_path),
        topics=(joint_topic,),
        static_topics=(camera_topic,),
        compression=None,
        collection_rate_hz=30.0,
        subscription_queue_size=1,
        require_complete_samples=True,
    )

    joint_state = JointState()
    joint_state.name = ["joint1", "joint2"]
    joint_state.position = [1.0, 2.0]
    joint_state.velocity = [0.1, 0.2]
    joint_state.effort = [0.0, 0.0]

    camera_info = CameraInfo()
    camera_info.header.stamp.sec = 123
    camera_info.header.stamp.nanosec = 456
    camera_info.header.frame_id = "cam0_color_optical_frame"
    camera_info.height = 480
    camera_info.width = 640
    camera_info.distortion_model = "plumb_bob"
    camera_info.d = [0.1, 0.2, 0.3, 0.4, 0.5]
    camera_info.k = [1.0, 0.0, 320.0, 0.0, 1.0, 240.0, 0.0, 0.0, 1.0]
    camera_info.r = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
    camera_info.p = [1.0, 0.0, 320.0, 0.0, 0.0, 1.0, 240.0, 0.0, 0.0, 0.0, 1.0, 0.0]

    writer.append({"joint_state": joint_state}, sample_time_ns=1_779_185_375_958_419_192)
    filename = writer.save({"cam0_color_camera_info": camera_info})

    with h5py.File(filename, "r") as hdf5_file:
        assert hdf5_file.attrs["data_schema_version"] == "1"
        assert hdf5_file["sample_time_ns"][:].tolist() == [1_779_185_375_958_419_192]
        np.testing.assert_allclose(
            hdf5_file["sample_time"][:],
            np.array([1_779_185_375.958419192], dtype=np.float64),
        )

        collector_metadata = hdf5_file["metadata/collector"]
        assert collector_metadata.attrs["data_schema_version"] == "1"
        assert collector_metadata.attrs["hdf5_compression"] == ""
        config_json = collector_metadata["config_json"][()].decode("utf-8")
        config = json.loads(config_json)
        assert config["collection_rate_hz"] == 30.0
        assert config["subscription_queue_size"] == 1
        assert config["require_complete_samples"] is True
        assert config["topics"] == [
            {
                "dataset": "robot/joint_state",
                "name": "joint_state",
                "required": True,
                "resolved_writer": "joint_state",
                "static": False,
                "topic": "/joint_states",
                "type": "sensor_msgs/msg/JointState",
                "writer": None,
            }
        ]
        assert config["static_topics"] == [
            {
                "dataset": "metadata/cam0/color/camera_info",
                "name": "cam0_color_camera_info",
                "required": True,
                "resolved_writer": "camera_info",
                "static": True,
                "topic": "/cam0/color/camera_info",
                "type": "sensor_msgs/msg/CameraInfo",
                "writer": "camera_info",
            }
        ]

        camera_group = hdf5_file["metadata/cam0/color/camera_info"]
        assert camera_group.attrs["static"]
        assert camera_group.attrs["sample_count"] == 1
        assert camera_group["height"][:].tolist() == [480.0]
        assert camera_group["width"][:].tolist() == [640.0]
        np.testing.assert_allclose(camera_group["k"][0], np.asarray(camera_info.k))
        assert camera_group["header_stamp_ns"][:].tolist() == [123_000_000_456]
        assert camera_group["frame_id"][0].rstrip(b"\0") == b"cam0_color_optical_frame"


def test_episode_writer_skips_missing_optional_static_topic(tmp_path) -> None:
    joint_topic = TopicConfig(
        name="joint_state",
        topic="/joint_states",
        type_name="sensor_msgs/msg/JointState",
        dataset="robot/joint_state",
    )
    camera_topic = TopicConfig(
        name="cam0_color_camera_info",
        topic="/cam0/color/camera_info",
        type_name="sensor_msgs/msg/CameraInfo",
        dataset="metadata/cam0/color/camera_info",
        writer="camera_info",
        required=False,
    )
    writer = Hdf5EpisodeWriter(
        data_root=str(tmp_path),
        topics=(joint_topic,),
        static_topics=(camera_topic,),
        compression=None,
    )

    joint_state = JointState()
    writer.append({"joint_state": joint_state}, sample_time_ns=1)
    filename = writer.save({})

    with h5py.File(filename, "r") as hdf5_file:
        assert "sample_time_ns" in hdf5_file
        assert "metadata/collector" in hdf5_file
        assert "metadata/cam0" not in hdf5_file


def test_episode_writer_skips_missing_optional_dynamic_topic(tmp_path) -> None:
    joint_topic = TopicConfig(
        name="joint_state",
        topic="/joint_states",
        type_name="sensor_msgs/msg/JointState",
        dataset="robot/joint_state",
    )
    tactile_topic = TopicConfig(
        name="left_hand_matrix_touch",
        topic="/cb_left_hand_matrix_touch",
        type_name="std_msgs/msg/String",
        dataset="obs/hand/left/tactile/matrix_json",
        writer="string",
        required=False,
    )
    writer = Hdf5EpisodeWriter(
        data_root=str(tmp_path),
        topics=(joint_topic, tactile_topic),
        compression=None,
    )

    writer.append({"joint_state": JointState(), "left_hand_matrix_touch": None}, 1)
    filename = writer.save()

    with h5py.File(filename, "r") as hdf5_file:
        assert "robot/joint_state" in hdf5_file
        assert "obs" not in hdf5_file


def test_episode_writer_records_partial_optional_dynamic_topic_indices(tmp_path) -> None:
    joint_topic = TopicConfig(
        name="joint_state",
        topic="/joint_states",
        type_name="sensor_msgs/msg/JointState",
        dataset="robot/joint_state",
    )
    tactile_topic = TopicConfig(
        name="left_hand_matrix_touch",
        topic="/cb_left_hand_matrix_touch",
        type_name="std_msgs/msg/String",
        dataset="obs/hand/left/tactile/matrix_json",
        writer="string",
        required=False,
    )
    writer = Hdf5EpisodeWriter(
        data_root=str(tmp_path),
        topics=(joint_topic, tactile_topic),
        compression=None,
    )

    tactile = String()
    tactile.data = '{"thumb_matrix": []}'
    writer.append({"joint_state": JointState(), "left_hand_matrix_touch": None}, 10)
    writer.append({"joint_state": JointState(), "left_hand_matrix_touch": tactile}, 20)
    filename = writer.save()

    with h5py.File(filename, "r") as hdf5_file:
        dataset = hdf5_file["obs/hand/left/tactile/matrix_json"]
        assert dataset.attrs["partial_samples"]
        assert dataset.attrs["sample_count"] == 1
        assert dataset[0].rstrip(b"\0") == tactile.data.encode("utf-8")
        assert hdf5_file["obs/hand/left/tactile/matrix_json_sample_index"][:].tolist() == [1]
        assert hdf5_file["obs/hand/left/tactile/matrix_json_sample_time_ns"][:].tolist() == [20]


def test_episode_writer_accepts_sample_and_writes_summary(tmp_path) -> None:
    status_topic = TopicConfig(
        name="status",
        topic="/status",
        type_name="std_msgs/msg/String",
        dataset="metadata/status",
        writer="string",
        required=False,
    )
    writer = Hdf5EpisodeWriter(
        data_root=str(tmp_path),
        topics=(status_topic,),
        compression=None,
        flush_every_samples=1,
        flush_every_seconds=0.0,
    )

    message = String()
    message.data = "ready"
    writer.append(Sample(index=0, time_ns=100, messages={"status": message}))
    writer.append(Sample(index=1, time_ns=200, messages={"status": None}))
    filename = writer.finish()

    with h5py.File(filename, "r") as hdf5_file:
        assert hdf5_file.attrs["sample_count"] == 2
        assert hdf5_file["sample_time_ns"][:].tolist() == [100, 200]
        assert hdf5_file["metadata/status"][0].rstrip(b"\0") == b"ready"
        assert hdf5_file["metadata/status"].attrs["partial_samples"]
        assert hdf5_file["metadata/status_sample_index"][:].tolist() == [0]
        assert hdf5_file["metadata/status_sample_time_ns"][:].tolist() == [100]

        summary_json = hdf5_file["metadata/collector/episode_summary_json"][()].decode("utf-8")
        summary = json.loads(summary_json)
        assert summary["sample_count"] == 2
        assert summary["written_sample_count"] == 2
        assert summary["topics"][0]["present_indices"] == [0]
        assert summary["topics"][0]["missing_indices"] == [1]


def test_episode_writer_finish_after_start_without_samples_stops_worker(tmp_path) -> None:
    status_topic = TopicConfig(
        name="status",
        topic="/status",
        type_name="std_msgs/msg/String",
        dataset="metadata/status",
        writer="string",
        required=False,
    )
    writer = Hdf5EpisodeWriter(
        data_root=str(tmp_path),
        topics=(status_topic,),
        compression=None,
    )

    started_filename = writer.start()

    assert writer.finish() is None
    assert not os.path.exists(started_filename)
