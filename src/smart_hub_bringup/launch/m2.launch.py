"""Launch the mandatory M2 simulator, safety and crossing participants."""
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    """Keep synthetic detector inputs and operator estop explicitly external."""
    return LaunchDescription([
        Node(package='smart_hub_sim', executable='scenario_runner', output='screen'),
        Node(package='smart_hub_safety', executable='safety_supervisor', output='screen'),
        Node(package='smart_hub_control', executable='crossing_arbiter', output='screen'),
        Node(package='smart_hub_bringup', executable='reset_coordinator', output='screen'),
    ])
