SHELL := /bin/bash
.DEFAULT_GOAL := help

ROOT_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
ROS_WS ?= $(ROOT_DIR)/ros2
ROS_WS := $(abspath $(ROS_WS))
ROS_SETUP := if [ -f /opt/ros/humble/setup.bash ]; then source /opt/ros/humble/setup.bash; fi; \
	if [ -f "$(ROS_WS)/install/setup.bash" ]; then source "$(ROS_WS)/install/setup.bash"; fi

GELLO_PKG := franka_gello_state_publisher
ARM_PKG := franka_fr3_arm_controllers

.PHONY: help gello arm gello-single arm-single gello-duo arm-duo

help:
	@printf "Quick commands:\n"
	@printf "  make gello      Launch dual GELLO publisher\n"
	@printf "  make arm        Launch dual FR3 arm controller\n"
	@printf "  make gello-duo  Launch dual GELLO publisher\n"
	@printf "  make arm-duo    Launch dual FR3 arm controller\n"
	@printf "  make gello-single   Launch single GELLO publisher\n"
	@printf "  make arm-single     Launch single FR3 arm controller\n"

gello-single:
	cd "$(ROS_WS)" && { \
		$(ROS_SETUP); \
		ros2 launch $(GELLO_PKG) main.launch.py config_file:=franka_gello_single.yaml; \
	}

arm-single:
	cd "$(ROS_WS)" && { \
		$(ROS_SETUP); \
		ros2 launch $(ARM_PKG) franka_fr3_arm_controllers.launch.py robot_config_file:=example_fr3_config.yaml; \
	}

gello-duo: gello

arm-duo: arm

gello:
	cd "$(ROS_WS)" && { \
		$(ROS_SETUP); \
		ros2 launch $(GELLO_PKG) main.launch.py config_file:=franka_gello_duo.yaml; \
	}

arm:
	cd "$(ROS_WS)" && { \
		$(ROS_SETUP); \
		ros2 launch $(ARM_PKG) franka_fr3_arm_controllers.launch.py robot_config_file:=example_fr3_duo_config.yaml; \
	}
