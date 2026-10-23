cmake_minimum_required(VERSION 3.16)
project(linkguard_tcp_bridge)

if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(linkguard_interfaces REQUIRED)
find_package(rclcpp REQUIRED)
find_package(rclcpp_action REQUIRED)

add_library(linkguard_tcp_support
  src/command_parser.cpp
  src/framed_socket.cpp
)
target_compile_features(linkguard_tcp_support PUBLIC cxx_std_17)
target_include_directories(linkguard_tcp_support PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>
)

add_executable(linkguard_tcp_bridge_node
  src/main.cpp
  src/tcp_ros_bridge.cpp
)
target_compile_features(linkguard_tcp_bridge_node PUBLIC cxx_std_17)
target_include_directories(linkguard_tcp_bridge_node PRIVATE include)
target_link_libraries(linkguard_tcp_bridge_node linkguard_tcp_support)
ament_target_dependencies(linkguard_tcp_bridge_node
  linkguard_interfaces
  rclcpp
  rclcpp_action
)

install(TARGETS
  linkguard_tcp_support
  linkguard_tcp_bridge_node
  ARCHIVE DESTINATION lib
  LIBRARY DESTINATION lib
  RUNTIME DESTINATION lib/${PROJECT_NAME}
)
install(DIRECTORY include/ DESTINATION include)
install(DIRECTORY launch DESTINATION share/${PROJECT_NAME})

ament_export_include_directories(include)

ament_package()
