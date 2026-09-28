FROM ros:jazzy-ros-base

SHELL ["/bin/bash", "-c"]

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3-colcon-common-extensions \
        python3-pytest \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /linkguard_ws
COPY . /linkguard_ws/src/ros2_linkguard_project

RUN source /opt/ros/jazzy/setup.bash \
    && colcon build --symlink-install

COPY docker/entrypoint.sh /linkguard_entrypoint.sh
RUN chmod +x /linkguard_entrypoint.sh

ENTRYPOINT ["/linkguard_entrypoint.sh"]
CMD ["bash"]
