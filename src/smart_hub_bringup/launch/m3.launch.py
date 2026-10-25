"""Launch M3 missions with explicitly synthetic queue/road inputs and external E-stop."""
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    """Preserve independent safety and require an operator E-stop heartbeat."""
    return LaunchDescription([
        Node(package='smart_hub_sim', executable='scenario_runner', output='screen',
             parameters=[{'m3_mode': True}]),
        Node(package='smart_hub_safety', executable='safety_supervisor', output='screen'),
        Node(package='smart_hub_control', executable='crossing_arbiter', output='screen'),
        Node(package='smart_hub_control', executable='route_planner', output='screen'),
        Node(package='smart_hub_control', executable='bus_manager', output='screen'),
        Node(package='smart_hub_control', executable='m3_synthetic_roads', output='screen'),
    ])
