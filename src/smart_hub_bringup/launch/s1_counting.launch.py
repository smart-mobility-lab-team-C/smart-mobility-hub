"""Run the forty-second image counting and frozen-acquisition fixture."""

from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    """Keep the passenger detector as the only queue publisher."""
    return LaunchDescription([
        Node(package='smart_hub_sim', executable='scenario_runner', output='screen',
             parameters=[{'m3_mode': True, 'publish_queue': False, 'reset_bus': False,
                          's1_counting_script': True}]),
        Node(package='smart_hub_perception', executable='passenger_detector',
             output='screen'),
        Node(package='smart_hub_safety', executable='safety_supervisor',
             output='screen'),
        Node(package='smart_hub_control', executable='crossing_arbiter',
             output='screen'),
    ])
