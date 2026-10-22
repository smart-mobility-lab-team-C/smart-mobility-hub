"""Pure checks for M2 safety input validation boundaries."""

from types import SimpleNamespace

from smart_hub_safety.validation import (
    observation_fresh,
    timestamp_age,
    validate_candidate,
    zero_twist,
)


def _candidate(stamp=10, frame='robot/base_link', linear=0.25,
               angular=1.0, unsupported=0.0):
    """Build the minimum TwistStamped-shaped object used by validation."""
    return SimpleNamespace(
        header=SimpleNamespace(
            stamp=SimpleNamespace(sec=stamp, nanosec=0), frame_id=frame),
        twist=SimpleNamespace(
            linear=SimpleNamespace(x=linear, y=unsupported, z=0.0),
            angular=SimpleNamespace(x=0.0, y=0.0, z=angular)))


def test_source_age_includes_exact_freshness_boundary_and_rejects_future():
    """The configured maximum is inclusive; future timestamps fail closed."""
    stamp = SimpleNamespace(sec=9, nanosec=500_000_000)
    assert timestamp_age(stamp, 10.0) == 0.5
    assert timestamp_age(SimpleNamespace(sec=11, nanosec=0), 10.0) is None
    assert observation_fresh(stamp, 2.0, 10.0, 2.5, 0.5, 0.5)
    assert not observation_fresh(stamp, 2.0, 10.0, 2.5001, 0.5, 0.5)


def test_candidate_accepts_approved_speed_and_angular_limits():
    """Robot candidate limits include the approved maximum values."""
    assert validate_candidate(
        _candidate(), 'robot', 10.0, 100.0, 100.0,
        linear_limit=0.25, angular_limit=1.0) is None


def test_candidate_rejects_wrong_frame_stale_nonfinite_and_unsupported_axes():
    """Invalid frames, stale data, NaNs and unused Twist axes are rejected."""
    assert validate_candidate(
        _candidate(frame='map'), 'robot', 10.0, 100.0, 100.0,
        linear_limit=0.25) == 'candidate_bad_frame'
    assert validate_candidate(
        _candidate(), 'robot', 10.6, 100.0, 100.0,
        linear_limit=0.25) == 'candidate_stale'
    assert validate_candidate(
        _candidate(linear=float('nan')), 'robot', 10.0, 100.0, 100.0,
        linear_limit=0.25) == 'candidate_nonfinite'
    assert validate_candidate(
        _candidate(unsupported=0.01), 'robot', 10.0, 100.0, 100.0,
        linear_limit=0.25) == 'candidate_unsupported_component'


def test_exact_zero_measured_twist_requires_all_components_zero():
    """Recovery checks do not round measured motion down to zero."""
    zero = SimpleNamespace(
        linear=SimpleNamespace(x=0.0, y=0.0, z=0.0),
        angular=SimpleNamespace(x=0.0, y=0.0, z=0.0))
    moving = SimpleNamespace(
        linear=SimpleNamespace(x=0.0, y=0.0, z=0.0),
        angular=SimpleNamespace(x=0.0, y=0.0, z=1.0e-12))
    assert zero_twist(zero)
    assert not zero_twist(moving)
