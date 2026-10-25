# Official ROS image index resolved 2026-10-22; refresh deliberately via PR.
FROM ros:jazzy-ros-base-noble@sha256:103b6c417973394659af6804d4917cd489b91e5ed22eb7bef263025a3bed2410
ENV LANG=C.UTF-8 LC_ALL=C.UTF-8
RUN apt-get update && apt-get install -y --no-install-recommends \
    git python3-matplotlib python3-opencv ros-jazzy-rosbag2 ros-dev-tools ros-jazzy-demo-nodes-cpp ros-jazzy-demo-nodes-py \
    ros-jazzy-rosidl-default-generators ros-jazzy-ament-flake8 \
    ros-jazzy-ament-pep257 ros-jazzy-launch-testing-ros \
    ros-jazzy-std-srvs ros-jazzy-visualization-msgs \
    && rm -rf /var/lib/apt/lists/*
RUN test -f /etc/ros/rosdep/sources.list.d/20-default.list || rosdep init
RUN dpkg-query -W > /opt/smh-package-versions.tsv
WORKDIR /workspace
# Container processes use the caller's UID/GID, set by bootstrap.
