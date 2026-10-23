#pragma once

#include <string>

namespace linkguard_tcp_bridge {

enum class CommandType {
  Start,
  Status,
  Stop,
  Profile,
  Quit,
  Invalid,
};

struct Command {
  CommandType type = CommandType::Invalid;
  std::string task_id;
  double target_x = 0.0;
  double target_y = 0.0;
  double tolerance = 0.0;
  double max_duration_sec = 0.0;
  std::string profile;
  std::string error;
};

Command parse_command(const std::string &message);

}  // namespace linkguard_tcp_bridge
