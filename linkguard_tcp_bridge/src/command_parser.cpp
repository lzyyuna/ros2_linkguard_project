#include "linkguard_tcp_bridge/command_parser.hpp"

#include <cmath>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace linkguard_tcp_bridge {
namespace {

std::vector<std::string> split_fields(const std::string &message) {
  std::vector<std::string> fields;
  std::size_t field_begin = 0;
  while (true) {
    const std::size_t separator = message.find('|', field_begin);
    if (separator == std::string::npos) {
      fields.push_back(message.substr(field_begin));
      return fields;
    }
    fields.push_back(message.substr(field_begin, separator - field_begin));
    field_begin = separator + 1;
  }
}

double parse_finite_number(const std::string &text, const char *field_name) {
  std::size_t parsed_characters = 0;
  double value = 0.0;
  try {
    value = std::stod(text, &parsed_characters);
  } catch (const std::exception &) {
    throw std::runtime_error(std::string(field_name) + "_NOT_A_NUMBER");
  }
  if (parsed_characters != text.size() || !std::isfinite(value)) {
    throw std::runtime_error(std::string(field_name) + "_NOT_A_NUMBER");
  }
  return value;
}

Command invalid(std::string error) {
  Command command;
  command.error = std::move(error);
  return command;
}

}  // namespace

Command parse_command(const std::string &message) {
  const auto fields = split_fields(message);
  if (fields.empty() || fields[0].empty()) {
    return invalid("EMPTY_COMMAND");
  }

  if (fields[0] == "START") {
    if (fields.size() != 6 || fields[1].empty()) {
      return invalid("USAGE_START_TASK_X_Y_TOLERANCE_TIMEOUT");
    }

    Command command;
    command.type = CommandType::Start;
    command.task_id = fields[1];
    try {
      command.target_x = parse_finite_number(fields[2], "TARGET_X");
      command.target_y = parse_finite_number(fields[3], "TARGET_Y");
      command.tolerance = parse_finite_number(fields[4], "TOLERANCE");
      command.max_duration_sec = parse_finite_number(fields[5], "MAX_DURATION");
    } catch (const std::exception &error) {
      return invalid(error.what());
    }

    if (command.tolerance <= 0.0) {
      return invalid("TOLERANCE_MUST_BE_POSITIVE");
    }
    if (command.max_duration_sec <= 0.0 || command.max_duration_sec > 3600.0) {
      return invalid("MAX_DURATION_OUT_OF_RANGE");
    }
    return command;
  }

  if (fields[0] == "STATUS") {
    if (fields.size() > 2 || (fields.size() == 2 && fields[1].empty())) {
      return invalid("USAGE_STATUS_OPTIONAL_TASK");
    }
    Command command;
    command.type = CommandType::Status;
    if (fields.size() == 2) {
      command.task_id = fields[1];
    }
    return command;
  }

  if (fields[0] == "STOP") {
    if (fields.size() != 2 || fields[1].empty()) {
      return invalid("USAGE_STOP_TASK");
    }
    Command command;
    command.type = CommandType::Stop;
    command.task_id = fields[1];
    return command;
  }

  if (fields[0] == "PROFILE") {
    if (fields.size() != 2 || fields[1].empty()) {
      return invalid("USAGE_PROFILE_GOOD_CONGESTED_DISCONNECTED");
    }
    if (fields[1] != "good" && fields[1] != "congested" &&
      fields[1] != "disconnected")
    {
      return invalid("UNKNOWN_PROFILE");
    }
    Command command;
    command.type = CommandType::Profile;
    command.profile = fields[1];
    return command;
  }

  if (fields[0] == "QUIT" && fields.size() == 1) {
    Command command;
    command.type = CommandType::Quit;
    return command;
  }

  return invalid("UNKNOWN_COMMAND");
}

}  // namespace linkguard_tcp_bridge
