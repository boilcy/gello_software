from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare

from launch import LaunchDescription


def generate_launch_description():
    default_config_file = PathJoinSubstitution(
        [FindPackageShare("data_collector"), "config", "data_collector.yaml"]
    )
    config_file = LaunchConfiguration("config_file")

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "config_file",
                default_value=default_config_file,
                description="YAML file containing data_collector topic descriptors.",
            ),
            Node(
                package="data_collector",
                executable="data_collector",
                name="data_collector",
                output="screen",
                parameters=[config_file],
            ),
        ]
    )
