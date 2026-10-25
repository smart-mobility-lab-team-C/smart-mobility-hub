"""Launch one assignment scenario graph: scenario:=S1..S9 seed:=N mode:=simulation."""

from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, LogInfo, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
import yaml

SCENARIOS = tuple(f'S{index}' for index in range(1, 10))


def _graph(context):
    """Validate arguments, then start the scenario's declared nodes."""
    scenario = LaunchConfiguration('scenario').perform(context)
    mode = LaunchConfiguration('mode').perform(context)
    seed = int(LaunchConfiguration('seed').perform(context))
    if scenario not in SCENARIOS:
        raise ValueError(f'scenario must be one of {", ".join(SCENARIOS)}')
    if mode != 'simulation':
        # A section 20.1: hardware is explicit opt-in with propulsion disabled. No hardware
        # actuator_bridge exists, so refuse rather than start anything that could move.
        raise RuntimeError('mode:=hardware is not available: no hardware actuator_bridge')
    path = Path(get_package_share_directory('smart_hub_bringup')) / 'scenarios' / (
        scenario + '.yaml')
    spec = yaml.safe_load(path.read_text())
    actions = [LogInfo(msg=f"{scenario}: {spec['title']} ({spec['source']}); "
                           f"verifier: {spec['verifier']}")]
    for node in spec['nodes']:
        parameters = dict(node['parameters'])
        if node['executable'] == 'scenario_runner':
            parameters['seed'] = seed
        actions.append(Node(package=node['package'], executable=node['executable'],
                            output='screen', parameters=[parameters] if parameters else []))
    return actions


def generate_launch_description():
    """Declare scenario, seed and mode, as A section 20.1 requires."""
    return LaunchDescription([
        DeclareLaunchArgument('scenario', default_value='S8', choices=list(SCENARIOS)),
        DeclareLaunchArgument('seed', default_value='42'),
        DeclareLaunchArgument('mode', default_value='simulation',
                              choices=['simulation', 'hardware']),
        OpaqueFunction(function=_graph),
    ])
