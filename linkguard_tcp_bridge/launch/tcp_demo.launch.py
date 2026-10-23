import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    bringup_launch = os.path.join(
        get_package_share_directory('linkguard_bringup'), 'launch', 'demo.launch.py'
    )

    return LaunchDescription([
        DeclareLaunchArgument('server_ip', description='Windows upper-computer IPv4 address'),
        DeclareLaunchArgument('server_port', default_value='19001'),
        DeclareLaunchArgument('robot_id', default_value='robot01'),
        IncludeLaunchDescription(PythonLaunchDescriptionSource(bringup_launch)),
        Node(
            package='linkguard_tcp_bridge',
            executable='linkguard_tcp_bridge_node',
            name='linkguard_tcp_bridge',
            output='screen',
            parameters=[{
                'server_ip': ParameterValue(
                    LaunchConfiguration('server_ip'), value_type=str
                ),
                'server_port': ParameterValue(
                    LaunchConfiguration('server_port'), value_type=int
                ),
                'robot_id': ParameterValue(
                    LaunchConfiguration('robot_id'), value_type=str
                ),
            }],
        ),
    ])
