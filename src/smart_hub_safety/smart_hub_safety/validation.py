"""Pure validation helpers used by the independent safety supervisor."""

import math


def stamp_seconds(stamp):
    """Return a ROS builtin time message as floating-point seconds."""
    return float(stamp.sec) + float(stamp.nanosec) * 1.0e-9


def timestamp_age(stamp, now_ros_seconds, future_tolerance=0.0):
    """Return source age, or ``None`` when the timestamp is invalid/future."""
    try:
        stamp_value = stamp_seconds(stamp)
        age = float(now_ros_seconds) - stamp_value
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(stamp_value) or not math.isfinite(age):
        return None
    if age < -float(future_tolerance):
        return None
    return max(0.0, age)


def observation_fresh(stamp, receipt_monotonic, now_ros_seconds,
                      now_monotonic, source_limit, receipt_limit=None,
                      future_tolerance=0.0):
    """Check source and local receipt ages without mixing clock domains."""
    age = timestamp_age(stamp, now_ros_seconds, future_tolerance)
    receipt_age = float(now_monotonic) - float(receipt_monotonic)
    if age is None or not math.isfinite(receipt_age) or receipt_age < 0.0:
        return False
    if age > float(source_limit):
        return False
    return receipt_limit is None or receipt_age <= float(receipt_limit)


def validate_candidate(message, agent, now_ros_seconds, receipt_monotonic,
                       now_monotonic, max_source_age=0.5,
                       max_receipt_age=0.5, linear_limit=None,
                       angular_limit=1.0, future_tolerance=0.0):
    """Return a stable reason code for an invalid candidate, else ``None``."""
    if agent not in ('robot', 'bus'):
        return 'unknown_agent'
    expected_frame = agent + '/base_link'
    if getattr(message.header, 'frame_id', '') != expected_frame:
        return 'candidate_bad_frame'
    if not observation_fresh(
            message.header.stamp, receipt_monotonic, now_ros_seconds,
            now_monotonic, max_source_age, max_receipt_age,
            future_tolerance):
        return 'candidate_stale'
    twist = message.twist
    values = (twist.linear.x, twist.linear.y, twist.linear.z,
              twist.angular.x, twist.angular.y, twist.angular.z)
    if not all(math.isfinite(float(value)) for value in values):
        return 'candidate_nonfinite'
    if any(float(value) != 0.0 for value in
           (twist.linear.y, twist.linear.z, twist.angular.x,
            twist.angular.y)):
        return 'candidate_unsupported_component'
    if linear_limit is not None and abs(float(twist.linear.x)) > linear_limit:
        return 'candidate_speed_limit'
    if abs(float(twist.angular.z)) > angular_limit:
        return 'candidate_angular_limit'
    return None


def finite_vehicle(vehicle):
    """Whether a vehicle observation has a valid finite pose and speed."""
    pose = vehicle.pose
    return (bool(vehicle.valid) and all(math.isfinite(float(value)) for value in
            (pose.x, pose.y, pose.theta, vehicle.speed_mps)))


def zero_twist(twist):
    """Whether all six measured Twist components are exactly zero."""
    return all(float(value) == 0.0 for value in (
        twist.linear.x, twist.linear.y, twist.linear.z,
        twist.angular.x, twist.angular.y, twist.angular.z))
