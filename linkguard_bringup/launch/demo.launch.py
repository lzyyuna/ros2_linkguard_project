from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    config = os.path.join(
        get_package_share_directory('linkguard_bringup'),
        'config',
        'demo.yaml',
    )
    reliability = LaunchConfiguration('command_qos_reliability')
    depth = LaunchConfiguration('command_qos_depth')
    random_seed = LaunchConfiguration('random_seed')
    qos_override = {
        'command_qos_reliability': reliability,
        'command_qos_depth': ParameterValue(depth, value_type=int),
    }
    return LaunchDescription([
        DeclareLaunchArgument(
            'command_qos_reliability',
            default_value='reliable',
            description='reliable or best_effort for command packet topics',
        ),
        DeclareLaunchArgument(
            'command_qos_depth',
            default_value='10',
            description='KEEP_LAST depth for command packet topics',
        ),
        DeclareLaunchArgument(
            'random_seed',
            default_value='7',
            description='Deterministic random seed for the link emulator',
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
            parameters=[
                config,
                qos_override,
                {'random_seed': ParameterValue(random_seed, value_type=int)},
            ],
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
            output='log',
        ),
    ])
