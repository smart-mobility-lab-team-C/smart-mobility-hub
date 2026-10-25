"""Bring up the single-owner simulator, perception, prediction and M2–M4 control."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    """Use observed camera queue and traffic with one publisher per state topic."""
    return LaunchDescription([
        DeclareLaunchArgument('seed', default_value='17'),
        Node(package='smart_hub_sim', executable='scenario_runner', output='screen',
             parameters=[{'m3_mode': True, 'm4_mode': True, 'm6_mode': True,
                          'publish_queue': False,
                          'seed': ParameterValue(LaunchConfiguration('seed'),
                                                 value_type=int)}]),
        Node(package='smart_hub_perception', executable='passenger_detector',
             output='screen'),
        Node(package='smart_hub_prediction', executable='demand_predictor',
             output='screen'),
        Node(package='smart_hub_safety', executable='safety_supervisor',
             output='screen'),
        Node(package='smart_hub_control', executable='crossing_arbiter',
             output='screen'),
        Node(package='smart_hub_control', executable='route_planner',
             output='screen'),
        Node(package='smart_hub_control', executable='robot_manager',
             output='screen'),
        Node(package='smart_hub_control', executable='bus_manager',
             output='screen'),
        Node(package='smart_hub_control', executable='parking_manager',
             output='screen'),
        Node(package='smart_hub_control', executable='traffic_monitor',
             output='screen'),
        Node(package='smart_hub_bringup', executable='dashboard_marker_publisher',
             output='screen'),
    ])
