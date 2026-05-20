import time

import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node

from .config import load_collector_config
from .hdf5_episode_writer import Hdf5EpisodeWriter, Sample
from .keyboard import KeyboardInterface
from .topic_snapshot import DynamicTopicSnapshot


class DataCollectorNode(Node):
    def __init__(self):
        super().__init__(
            "data_collector",
            allow_undeclared_parameters=True,
            automatically_declare_parameters_from_overrides=True,
        )
        self.config = load_collector_config(self)
        self.snapshot = DynamicTopicSnapshot(
            self,
            self.config.topics,
            self.config.subscription_queue_size,
        )
        self.static_snapshot = DynamicTopicSnapshot(
            self,
            self.config.static_topics,
            self.config.subscription_queue_size,
        )

        for topic in self.config.topics:
            writer = topic.writer or "auto"
            self.get_logger().info(
                f"Collecting {topic.name}: {topic.topic} [{topic.type_name}] writer={writer}"
            )
        for topic in self.config.static_topics:
            writer = topic.writer or "auto"
            self.get_logger().info(
                f"Collecting static {topic.name}: "
                f"{topic.topic} [{topic.type_name}] writer={writer}"
            )


def main(args=None):
    rclpy.init(args=args)
    node = DataCollectorNode()
    executor = SingleThreadedExecutor()
    executor.add_node(node)

    interval_sec = 1.0 / node.config.collection_rate_hz
    episode_writer = Hdf5EpisodeWriter(
        data_root=node.config.data_root,
        topics=node.config.topics,
        static_topics=node.config.static_topics,
        compression=node.config.hdf5_compression,
        collection_rate_hz=node.config.collection_rate_hz,
        subscription_queue_size=node.config.subscription_queue_size,
        require_complete_samples=node.config.require_complete_samples,
        writer_queue_size=node.config.writer_queue_size,
        writer_put_timeout_sec=node.config.writer_put_timeout_sec,
        flush_every_samples=node.config.flush_every_samples,
        flush_every_seconds=node.config.flush_every_seconds,
    )
    recording = False
    interval_ns = int(1_000_000_000 / node.config.collection_rate_hz)
    last_sample_time_ns = time.time_ns()

    try:
        with KeyboardInterface() as keyboard:
            node.get_logger().info("Press SPACE to start/stop collection. Press Ctrl-C to exit.")
            if not keyboard.enabled:
                node.get_logger().warn("stdin is not a TTY; SPACE hotkey is disabled.")

            while rclpy.ok():
                executor.spin_once(timeout_sec=0.0)

                key = keyboard.get_key()
                if key == " ":
                    recording = _toggle_recording(node, episode_writer, recording)

                if not recording:
                    time.sleep(interval_sec)
                    continue

                now_ns = time.time_ns()
                if now_ns - last_sample_time_ns < interval_ns:
                    time.sleep(0.001)
                    continue
                last_sample_time_ns = now_ns

                snapshot = node.snapshot.read()
                missing = node.snapshot.missing_required(snapshot)
                if node.config.require_complete_samples and missing:
                    node.get_logger().info(
                        "Received incomplete data, skipping... Missing topics: "
                        + ", ".join(missing)
                    )
                    continue

                sample = Sample(
                    index=episode_writer.sample_count,
                    time_ns=now_ns,
                    messages=snapshot,
                )
                episode_writer.append(sample)
                node.get_logger().info(f"{episode_writer.sample_count}")

    except KeyboardInterrupt:
        if recording and episode_writer.sample_count:
            node.get_logger().info("Shutting down. Waiting for primary HDF5 writes...")
            static_snapshot = node.static_snapshot.read()
            filename = episode_writer.finish(static_snapshot)
            node.get_logger().info(f"Data saved to {filename}.")
        else:
            node.get_logger().info("Shutting down.")
    finally:
        executor.remove_node(node)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


def _toggle_recording(
    node: DataCollectorNode,
    episode_writer: Hdf5EpisodeWriter,
    recording: bool,
) -> bool:
    if recording:
        node.get_logger().info("Collection paused. Saving collected data to disk...")
        static_snapshot = node.static_snapshot.read()
        filename = episode_writer.finish(static_snapshot)
        if filename is None:
            node.get_logger().info("No collected data to save.")
        else:
            node.get_logger().info(f"Data saved to {filename}.")
            node.get_logger().info("Press SPACE to start a new collection.")
        return False

    node.get_logger().info("Collection started.")
    episode_writer.start()
    return True


if __name__ == "__main__":
    main()
