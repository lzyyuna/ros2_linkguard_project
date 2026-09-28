from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    config = os.path.join(
        get_package_share_directory('linkguard_bringup'),
        'config',
        'demo.yaml',
    )
    reliability = LaunchConfiguration('command_qos_reliability')
    qos_override = {'command_qos_reliability': reliability}
    return LaunchDescription([
        DeclareLaunchArgument(
            'command_qos_reliability',
            default_value='reliable',
            description='reliable or best_effort for command packet topics',
        ),
        Node(
            package='linkguard_bringup',
            executable='robot_sim',
            parameters=[config, qos_override],
            output='screen',
        ),
        Node(
            package='linkguard_bringup',
            executable='link_emulator',
            parameters=[config, qos_override],
            output='screen',
        ),
        Node(
            package='linkguard_bringup',
            executable='mission_server',
            parameters=[config, qos_override],
            output='screen',
        ),
        Node(
            package='linkguard_bringup',
            executable='network_monitor',
            output='screen',
        ),
    ])
