from launch import LaunchDescription
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    config = os.path.join(
        get_package_share_directory('linkguard_bringup'),
        'config',
        'demo.yaml',
    )
    return LaunchDescription([
        Node(package='linkguard_bringup', executable='robot_sim', parameters=[config], output='screen'),
        Node(package='linkguard_bringup', executable='link_emulator', parameters=[config], output='screen'),
        Node(package='linkguard_bringup', executable='mission_server', parameters=[config], output='screen'),
        Node(package='linkguard_bringup', executable='network_monitor', output='screen'),
    ])
