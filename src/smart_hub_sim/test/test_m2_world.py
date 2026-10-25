"""Pure M2 world tests for seeded observations, map constraints, and safety."""

from smart_hub_sim.world import World


def test_world_replay_and_observation_noise_are_seeded_independently():
    """Physics steps do not consume or alter the noisy-observation stream."""
    stepped = World(seed=31)
    reference = World(seed=31)
    first_observation = stepped.noisy_pose(stepped.bus)
    assert first_observation == reference.noisy_pose(reference.bus)

    stepped.step(bus_command=(0.2, 0.0), robot_command=(0.2, 0.0))
    reference.step(bus_command=(0.2, 0.0), robot_command=(0.2, 0.0))
    assert stepped.bus == reference.bus
    assert stepped.robot == reference.robot
    assert stepped.noisy_pose(stepped.bus) == reference.noisy_pose(reference.bus)


def test_world_rejects_off_graph_motion_and_accepts_permitted_edges():
    """Only bus and robot centerline edges assigned in M1 permit translation."""
    world = World(seed=4)
    world.step(bus_command=(0.4, 0.0), robot_command=(0.25, 0.0))
    assert world.bus.x > 1.0
    assert world.robot.x > 3.0

    robot_pose = (world.robot.x, world.robot.y, world.robot.yaw)
    world.step(robot_command=(0.25, 1.0))
    assert (world.robot.x, world.robot.y) == robot_pose[:2]
    assert world.nearest_edge_id('robot', 3.0, 6.0) == 'R-W'
    assert world.nearest_edge_id('bus', 1.0, 2.0) == 'A-Cs'


def test_world_allows_straight_motion_across_a_shared_graph_node():
    """A fixed physics step may straddle two collinear edges at their shared node."""
    assert World._motion_on_allowed_edge('bus', (4.981, 4.0), (5.001, 4.0))
    assert not World._motion_on_allowed_edge('bus', (4.981, 4.0), (5.001, 4.01))


def test_world_sweeps_motion_against_optional_obstacle():
    """A fast step stops before entering the obstacle's inflated footprint."""
    world = World(seed=9, obstacle_enabled=True)
    world.bus.x = 6.0
    world.bus.y = 2.0
    world.step(bus_command=(0.4, 0.0), dt=1.0)
    assert world.bus.x == 6.0
    assert world.bus.y == 2.0
    assert world.bus.speed == 0.0


def test_runtime_geometry_matches_frozen_m1_map():
    """Prevent copied runtime graph and footprint constants from drifting from M1."""
    import json
    from pathlib import Path

    from smart_hub_sim import geometry, world

    path = Path(__file__).resolve().parents[1] / 'config' / 'map_m1.yaml'
    contract = json.loads(path.read_text())
    for agent, runtime in (('bus', world.BUS_EDGES), ('robot', world.ROBOT_EDGES)):
        expected = {edge['id']: {tuple(contract['nodes'][name]) for name in edge['nodes']}
                    for edge in contract['edges'] if agent in edge['agents']}
        observed = {edge_id: {start, end} for edge_id, start, end in runtime}
        assert observed == expected
    assert world.BUS_RADIUS == contract['footprint_radius_m']['bus']
    assert world.ROBOT_RADIUS == contract['footprint_radius_m']['robot']
    assert world.CLEARANCE == contract['limits']['clearance_m']
    assert geometry.CROSSING == (*contract['zones']['C']['x'], *contract['zones']['C']['y'])


def test_observation_consumption_cannot_change_motion_and_reset_replays_noise():
    """Noise sampling changes neither physics nor the repeatability of a seeded reset."""
    sampled = World(seed=41)
    control = World(seed=41)
    first = sampled.noisy_pose(sampled.robot)
    for _ in range(20):
        sampled.noisy_pose(sampled.robot)
        sampled.step(robot_command=(0.2, 0.0))
        control.step(robot_command=(0.2, 0.0))
    assert sampled.robot == control.robot
    sampled.reset(41)
    assert sampled.noisy_pose(sampled.robot) == first
    assert sampled.robot == World(seed=41).robot


def test_pose_noise_respects_declared_clearance_error_bound():
    """A bounded observation error makes footprint-based clearance conservative."""
    import math

    from smart_hub_sim.geometry import intersects_crossing
    from smart_hub_sim.world import POSE_NOISE_BOUND_M

    world = World(seed=19)
    world.bus.x, world.bus.y = 4.21, 2.0
    assert intersects_crossing(world.bus.x, world.bus.y, 0.3)
    for _ in range(1000):
        x, y, _ = world.noisy_pose(world.bus)
        assert abs(x - world.bus.x) <= POSE_NOISE_BOUND_M
        assert abs(y - world.bus.y) <= POSE_NOISE_BOUND_M
        assert intersects_crossing(x, y, 0.3 + math.sqrt(2) * POSE_NOISE_BOUND_M)
