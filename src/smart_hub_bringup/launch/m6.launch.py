"""Launch the M3 graph plus robot_manager with synthetic roads and external E-stop."""
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    """Robot missions stay behind the independent supervisor and acknowledged reset."""
    return LaunchDescription([
        Node(package='smart_hub_sim', executable='scenario_runner', output='screen',
             parameters=[{'m3_mode': True, 'm6_mode': True}]),
        Node(package='smart_hub_safety', executable='safety_supervisor', output='screen'),
        Node(package='smart_hub_control', executable='crossing_arbiter', output='screen'),
        Node(package='smart_hub_control', executable='route_planner', output='screen'),
        Node(package='smart_hub_control', executable='bus_manager', output='screen'),
        Node(package='smart_hub_control', executable='robot_manager', output='screen'),
        Node(package='smart_hub_control', executable='m3_synthetic_roads', output='screen'),
    ])
