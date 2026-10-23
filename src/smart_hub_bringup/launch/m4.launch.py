"""Launch sensor-backed parking and traffic with independent motion supervision."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    """Preserve M3 regression launch and require an external stop heartbeat."""
    return LaunchDescription([
        DeclareLaunchArgument('seed', default_value='17'),
        Node(package='smart_hub_sim', executable='scenario_runner', output='screen',
             parameters=[{'m3_mode': True, 'm4_mode': True,
                          'seed': ParameterValue(LaunchConfiguration('seed'), value_type=int)}]),
        Node(package='smart_hub_safety', executable='safety_supervisor', output='screen'),
        Node(package='smart_hub_control', executable='crossing_arbiter', output='screen'),
        Node(package='smart_hub_control', executable='route_planner', output='screen'),
        Node(package='smart_hub_control', executable='bus_manager', output='screen'),
        Node(package='smart_hub_control', executable='parking_manager', output='screen'),
        Node(package='smart_hub_control', executable='traffic_monitor', output='screen'),
        Node(package='smart_hub_bringup', executable='reset_coordinator', output='screen',
             parameters=[{'include_bus': True, 'include_m4': True}]),
    ])
