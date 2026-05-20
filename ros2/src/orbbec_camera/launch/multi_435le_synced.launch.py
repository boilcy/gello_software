import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, GroupAction, TimerAction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    # Include launch files
    package_dir = get_package_share_directory("orbbec_camera")
    launch_file_dir = os.path.join(package_dir, "launch")
    config_file_dir = os.path.join(package_dir, "config")
    config_file_path = os.path.join(config_file_dir, "camera_params.yaml")
    secondary_config_file_path = os.path.join(config_file_dir, "camera_secondary_params.yaml")

    args = [
        DeclareLaunchArgument("primary_camera_name", default_value="cam0"),
        DeclareLaunchArgument("secondary_camera_name", default_value="cam1"),
        DeclareLaunchArgument("primary_serial_number", default_value="CP4N651006F"),
        DeclareLaunchArgument("secondary_serial_number", default_value="CP4E463000BA"),
        DeclareLaunchArgument("primary_config_file_path", default_value=config_file_path),
        DeclareLaunchArgument("secondary_config_file_path", default_value=secondary_config_file_path),
        DeclareLaunchArgument("primary_log_file_name", default_value="camera_00.log"),
        DeclareLaunchArgument("secondary_log_file_name", default_value="camera_01.log"),
        DeclareLaunchArgument("log_level", default_value="none"),
    ]

    launch1_include = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(launch_file_dir, "gemini435_le.launch.py")
        ),
        launch_arguments={
            "camera_name": LaunchConfiguration("primary_camera_name"),
            "sync_mode": "primary",
            "serial_number": LaunchConfiguration("primary_serial_number"),
            "config_file_path": LaunchConfiguration("primary_config_file_path"),
            "trigger_out_enabled": "true",
            "log_level": LaunchConfiguration("log_level"),
            "log_file_name": LaunchConfiguration("primary_log_file_name"),
        }.items(),
    )

    launch2_include = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(launch_file_dir, "gemini435_le.launch.py")
        ),
        launch_arguments={
            "camera_name": LaunchConfiguration("secondary_camera_name"),
            "sync_mode": "secondary_synced",
            "serial_number": LaunchConfiguration("secondary_serial_number"),
            "config_file_path": LaunchConfiguration("secondary_config_file_path"),
            "trigger_out_enabled": "false",
            "log_level": LaunchConfiguration("log_level"),
            "log_file_name": LaunchConfiguration("secondary_log_file_name"),
        }.items(),
    )

    # Launch description
    ld = LaunchDescription(
        [
            *args,
            TimerAction(period=0.0, actions=[GroupAction([launch2_include])]),
            TimerAction(period=2.0, actions=[GroupAction([launch1_include])]),
            # The primary camera should be launched at last
        ]
    )

    return ld
