from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, GroupAction, TimerAction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    # Include launch files
    package_dir = get_package_share_directory('orbbec_camera')
    launch_file_dir = os.path.join(package_dir, 'launch')

    args = [
        DeclareLaunchArgument('primary_camera_name', default_value='camera_01'),
        DeclareLaunchArgument('secondary_camera_name', default_value='camera_02'),
        DeclareLaunchArgument('primary_serial_number', default_value=''),
        DeclareLaunchArgument('secondary_serial_number', default_value=''),
        DeclareLaunchArgument('primary_log_file_name', default_value='camera_01.log'),
        DeclareLaunchArgument('secondary_log_file_name', default_value='camera_02.log'),
        DeclareLaunchArgument('log_level', default_value='none'),
    ]

    launch1_include = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(launch_file_dir, 'gemini435_le.launch.py')
        ),
        launch_arguments={
            'camera_name': LaunchConfiguration('primary_camera_name'),
            'sync_mode': 'standalone',
            'serial_number': LaunchConfiguration('primary_serial_number'),
            'log_level': LaunchConfiguration('log_level'),
            'log_file_name': LaunchConfiguration('primary_log_file_name'),
        }.items()
    )

    launch2_include = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(launch_file_dir, 'gemini435_le.launch.py')
        ),
        launch_arguments={
            'camera_name': LaunchConfiguration('secondary_camera_name'),
            'sync_mode': 'standalone',
            'serial_number': LaunchConfiguration('secondary_serial_number'),
            'log_level': LaunchConfiguration('log_level'),
            'log_file_name': LaunchConfiguration('secondary_log_file_name'),
        }.items()
    )

    # If you need more cameras, just add more launch_include here, and change the usb_port and device_num

    # Launch description
    ld = LaunchDescription([
            *args,
            TimerAction(period=0.0, actions=[GroupAction([launch2_include])]),
            TimerAction(period=2.0, actions=[GroupAction([launch1_include])]),
    ])

    return ld
