# data_collector

`data_collector` is the config-driven replacement path for `data_collecter`.
It records arbitrary ROS 2 topics into HDF5 without hardcoding which topics are
present in Python code.

Each configured topic declares at least:

- `topic`: ROS topic name.
- `type`: ROS message type, for example `sensor_msgs/msg/Image`.

Optional fields:

- `dataset`: HDF5 dataset or group path. Defaults to the config entry name.
- `writer`: explicit HDF5 writer adapter. Defaults from the message type.
- `required`: whether the topic must be available before a sample is recorded.

Every saved episode includes `sample_time_ns` and `sample_time` datasets at the
HDF5 root. These are the collector's Unix wall-clock sample times, stored as
nanoseconds and seconds.

Every saved episode also includes a collector metadata snapshot:

- Root attribute `data_schema_version`: version of the HDF5 layout written by
  this collector.
- `metadata/collector/config_json`: effective collection metadata as JSON,
  including data root, compression, collection rate, completeness policy, topic
  descriptors, static topic descriptors, and resolved writer adapters.

Stable metadata can be declared under `static_topics`. Static topics use the
same fields as `topics`, but default to `required: false` and are saved once per
episode from the latest received message. Use this for camera calibration topics
such as `/cam0/color/camera_info`. If a metadata topic can change during an
episode, keep it under `topics` instead.

Dynamic samples are streamed to HDF5 while recording. The capture loop enqueues
snapshots into a bounded primary-writer queue instead of keeping the full episode
in memory. Tune `writer_queue_size` and `writer_put_timeout_sec` for the storage
device; if the queue stays full, recording fails loudly because primary evidence
is no longer keeping up.

The streaming writer is split into three layers:

- `Sample`: the capture-boundary unit with `index`, `time_ns`, and topic messages.
- `Hdf5EpisodeWriter`: episode lifecycle, bounded queue, worker errors, flush
  cadence, static topics, and episode summary metadata.
- `MessageWriter` / `TopicMessageStream`: per-topic schema and encoding.

`flush_every_samples` and `flush_every_seconds` control how often the background
writer asks HDF5 to flush buffered primary writes. The collector does not fsync
inside the target-fps loop.

Known writer adapters:

- `image_compressed`: stores `sensor_msgs/msg/Image` as JPEG or PNG bytes.
- `image_raw`: stores `sensor_msgs/msg/Image` as an array.
- `camera_info`: stores `sensor_msgs/msg/CameraInfo` calibration fields.
- `compressed_image`: stores `sensor_msgs/msg/CompressedImage` payload bytes.
- `pointcloud_xyzrgb`: stores `sensor_msgs/msg/PointCloud2` as `x,y,z,r,g,b`.
- `joint_state`: stores `sensor_msgs/msg/JointState` fields in a group.
- `pose_stamped`: stores `geometry_msgs/msg/PoseStamped` as `x,y,z,qx,qy,qz,qw`.
- `serialized_cdr`: fallback for unsupported message types.

Run with:

```bash
ros2 run data_collector data_collector --ros-args --params-file src/data_collector/config/data_collector.yaml
```

Use a custom config:

```bash
ros2 run data_collector data_collector --ros-args --params-file /path/to/config.yaml
```

The collector uses SPACE on stdin to start and stop recording, so run it directly
from an interactive terminal. `ros2 launch` does not attach a usable stdin to the
node, which disables the SPACE hotkey.
