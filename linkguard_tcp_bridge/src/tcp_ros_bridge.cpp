#include "linkguard_tcp_bridge/tcp_ros_bridge.hpp"

#include "linkguard_tcp_bridge/framed_socket.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <iomanip>
#include <sstream>
#include <stdexcept>
#include <utility>

namespace linkguard_tcp_bridge {
namespace {

std::string sanitize_field(std::string text) {
  for (char &character : text) {
    if (character == '|' || character == '\n' || character == '\r') {
      character = '_';
    }
  }
  return text;
}

std::string format_number(double value, int precision = 3) {
  std::ostringstream output;
  output << std::fixed << std::setprecision(precision) << value;
  return output.str();
}

}  // namespace

TcpRosBridge::TcpRosBridge() : Node("linkguard_tcp_bridge") {
  server_ip_ = declare_parameter<std::string>("server_ip", "127.0.0.1");

  const auto configured_port = declare_parameter<std::int64_t>("server_port", 19001);
  if (configured_port <= 0 || configured_port > 65535) {
    throw std::runtime_error("server_port must be in the range 1..65535");
  }
  server_port_ = static_cast<std::uint16_t>(configured_port);

  robot_id_ = declare_parameter<std::string>("robot_id", "robot01");
  if (robot_id_.empty() || robot_id_.find('|') != std::string::npos) {
    throw std::runtime_error("robot_id must be non-empty and cannot contain '|'");
  }

  const auto reconnect_delay_ms =
    declare_parameter<std::int64_t>("reconnect_delay_ms", 2000);
  if (reconnect_delay_ms <= 0) {
    throw std::runtime_error("reconnect_delay_ms must be positive");
  }
  reconnect_delay_ = std::chrono::milliseconds(reconnect_delay_ms);

  action_client_ = rclcpp_action::create_client<ExecuteMission>(this, "/execute_mission");
  profile_client_ = create_client<SetNetworkProfile>("/set_network_profile");
  command_timer_ = create_wall_timer(
    std::chrono::milliseconds(20), [this] { drain_commands(); });

  network_thread_ = std::thread([this] { network_loop(); });
}

TcpRosBridge::~TcpRosBridge() { stop_network(); }

void TcpRosBridge::network_loop() {
  while (!stop_requested_.load() && rclcpp::ok()) {
    try {
      RCLCPP_INFO(
        get_logger(), "Connecting to Windows upper computer at %s:%u",
        server_ip_.c_str(), static_cast<unsigned int>(server_port_));
      Socket socket = connect_ipv4(server_ip_, server_port_);

      {
        const std::lock_guard<std::mutex> lock(socket_mutex_);
        active_socket_ = socket.get();
      }

      run_connected_session(socket.get());

      {
        const std::lock_guard<std::mutex> lock(socket_mutex_);
        if (active_socket_ == socket.get()) {
          active_socket_ = -1;
        }
      }
    } catch (const std::exception &error) {
      {
        const std::lock_guard<std::mutex> lock(socket_mutex_);
        active_socket_ = -1;
      }
      if (!stop_requested_.load() && rclcpp::ok()) {
        RCLCPP_WARN(get_logger(), "TCP session ended: %s", error.what());
      }
    }

    session_active_.store(false);
    outgoing_condition_.notify_all();
    if (stop_requested_.load() || !rclcpp::ok()) {
      break;
    }

    RCLCPP_INFO(
      get_logger(), "Reconnecting in %.1f seconds",
      static_cast<double>(reconnect_delay_.count()) / 1000.0);
    std::unique_lock<std::mutex> lock(reconnect_mutex_);
    reconnect_condition_.wait_for(
      lock, reconnect_delay_, [this] { return stop_requested_.load() || !rclcpp::ok(); });
  }
}

void TcpRosBridge::run_connected_session(int descriptor) {
  send_frame(descriptor, "HELLO|" + robot_id_);

  std::string welcome;
  if (!receive_frame(descriptor, welcome)) {
    throw std::runtime_error("server closed during handshake");
  }
  const std::string expected_welcome = "WELCOME|" + robot_id_;
  if (welcome != expected_welcome) {
    throw std::runtime_error("unexpected handshake response: " + welcome);
  }

  clear_outgoing();
  session_active_.store(true);
  RCLCPP_INFO(get_logger(), "TCP handshake complete for %s", robot_id_.c_str());

  std::thread writer([this, descriptor] { writer_loop(descriptor); });
  try {
    while (session_active_.load() && !stop_requested_.load()) {
      std::string message;
      if (!receive_frame(descriptor, message)) {
        throw std::runtime_error("Windows upper computer closed the connection");
      }

      if (message.rfind("PING|", 0) == 0) {
        queue_outgoing("PONG|" + message.substr(5));
      } else {
        enqueue_command(std::move(message));
      }
    }
  } catch (...) {
    session_active_.store(false);
    shutdown_socket(descriptor);
    outgoing_condition_.notify_all();
    if (writer.joinable()) {
      writer.join();
    }
    throw;
  }

  session_active_.store(false);
  shutdown_socket(descriptor);
  outgoing_condition_.notify_all();
  if (writer.joinable()) {
    writer.join();
  }
}

void TcpRosBridge::writer_loop(int descriptor) {
  try {
    while (session_active_.load() && !stop_requested_.load()) {
      OutboundFrame frame;
      {
        std::unique_lock<std::mutex> lock(outgoing_mutex_);
        outgoing_condition_.wait(lock, [this] {
          return !outgoing_.empty() || !session_active_.load() || stop_requested_.load();
        });
        if (outgoing_.empty()) {
          break;
        }
        frame = std::move(outgoing_.front());
        outgoing_.pop_front();
      }

      send_frame(descriptor, frame.payload);
      if (frame.close_after_send) {
        stop_requested_.store(true);
        session_active_.store(false);
        shutdown_socket(descriptor);
        reconnect_condition_.notify_all();
        rclcpp::shutdown();
        break;
      }
    }
  } catch (const std::exception &error) {
    if (!stop_requested_.load()) {
      RCLCPP_WARN(get_logger(), "TCP writer stopped: %s", error.what());
    }
    session_active_.store(false);
    shutdown_socket(descriptor);
    outgoing_condition_.notify_all();
  }
}

void TcpRosBridge::stop_network() noexcept {
  if (stop_requested_.exchange(true)) {
    if (network_thread_.joinable()) {
      network_thread_.join();
    }
    return;
  }

  session_active_.store(false);
  {
    const std::lock_guard<std::mutex> lock(socket_mutex_);
    shutdown_socket(active_socket_);
  }
  outgoing_condition_.notify_all();
  reconnect_condition_.notify_all();
  if (network_thread_.joinable()) {
    network_thread_.join();
  }
}

void TcpRosBridge::enqueue_command(std::string command) {
  const std::lock_guard<std::mutex> lock(command_mutex_);
  commands_.push_back(std::move(command));
}

void TcpRosBridge::drain_commands() {
  std::deque<std::string> commands;
  {
    const std::lock_guard<std::mutex> lock(command_mutex_);
    commands.swap(commands_);
  }

  for (const auto &text : commands) {
    const Command command = parse_command(text);
    if (command.type == CommandType::Invalid) {
      queue_outgoing("ERROR|COMMAND|" + command.error);
      continue;
    }
    handle_command(command);
    if (command.type == CommandType::Quit) {
      break;
    }
  }
}

void TcpRosBridge::handle_command(const Command &command) {
  switch (command.type) {
    case CommandType::Start:
      handle_start(command);
      break;
    case CommandType::Status:
      handle_status(command);
      break;
    case CommandType::Stop:
      handle_stop(command);
      break;
    case CommandType::Profile:
      handle_profile(command);
      break;
    case CommandType::Quit:
      handle_quit();
      break;
    case CommandType::Invalid:
      break;
  }
}

void TcpRosBridge::handle_start(const Command &command) {
  if (!action_client_->action_server_is_ready()) {
    queue_outgoing("ERROR|" + command.task_id + "|ACTION_SERVER_UNAVAILABLE");
    return;
  }

  {
    const std::lock_guard<std::mutex> lock(mission_mutex_);
    if (is_active(mission_.state)) {
      queue_outgoing("ERROR|" + command.task_id + "|BUSY_WITH|" + mission_.task_id);
      return;
    }

    mission_ = MissionSnapshot{};
    mission_.task_id = command.task_id;
    mission_.state = MissionState::Pending;
  }

  ExecuteMission::Goal goal;
  goal.target_x = command.target_x;
  goal.target_y = command.target_y;
  goal.tolerance = command.tolerance;
  goal.max_duration_sec = command.max_duration_sec;

  rclcpp_action::Client<ExecuteMission>::SendGoalOptions options;
  options.goal_response_callback =
    [this, task_id = command.task_id](const GoalHandle::SharedPtr &goal_handle) {
      on_goal_response(task_id, goal_handle);
    };
  options.feedback_callback =
    [this, task_id = command.task_id](
      GoalHandle::SharedPtr goal_handle,
      const std::shared_ptr<const ExecuteMission::Feedback> feedback) {
      on_feedback(task_id, std::move(goal_handle), feedback);
    };
  options.result_callback =
    [this, task_id = command.task_id](const GoalHandle::WrappedResult &result) {
      on_result(task_id, result);
    };

  try {
    action_client_->async_send_goal(goal, options);
  } catch (const std::exception &error) {
    {
      const std::lock_guard<std::mutex> lock(mission_mutex_);
      if (mission_.task_id == command.task_id) {
        mission_.state = MissionState::Rejected;
        mission_.result_message = error.what();
      }
    }
    queue_outgoing(
      "ERROR|" + command.task_id + "|SEND_GOAL_FAILED|" + sanitize_field(error.what()));
  }
}

void TcpRosBridge::handle_status(const Command &command) {
  queue_outgoing(make_status(command.task_id));
}

void TcpRosBridge::handle_stop(const Command &command) {
  GoalHandle::SharedPtr goal_handle;
  {
    const std::lock_guard<std::mutex> lock(mission_mutex_);
    if (mission_.state == MissionState::Idle || mission_.task_id != command.task_id) {
      queue_outgoing("ERROR|" + command.task_id + "|TASK_NOT_FOUND");
      return;
    }
    if (!is_active(mission_.state)) {
      queue_outgoing(
        "RESULT|" + mission_.task_id + '|' + state_name(mission_.state) + '|' +
        format_number(mission_.elapsed_sec) + '|' + sanitize_field(mission_.result_message));
      return;
    }
    if (mission_.state == MissionState::Pending) {
      mission_.cancel_when_accepted = true;
      queue_outgoing("ACK|" + mission_.task_id + "|CANCEL_QUEUED");
      return;
    }
    if (mission_.state == MissionState::Canceling) {
      queue_outgoing("ACK|" + mission_.task_id + "|CANCEL_ALREADY_REQUESTED");
      return;
    }

    mission_.state = MissionState::Canceling;
    goal_handle = mission_.goal_handle;
  }

  if (!goal_handle) {
    queue_outgoing("ERROR|" + command.task_id + "|GOAL_HANDLE_UNAVAILABLE");
    return;
  }
  try {
    action_client_->async_cancel_goal(goal_handle);
    queue_outgoing("ACK|" + command.task_id + "|CANCEL_REQUESTED");
  } catch (const std::exception &error) {
    {
      const std::lock_guard<std::mutex> lock(mission_mutex_);
      if (mission_.task_id == command.task_id && mission_.state == MissionState::Canceling) {
        mission_.state = MissionState::Running;
      }
    }
    queue_outgoing(
      "ERROR|" + command.task_id + "|CANCEL_FAILED|" + sanitize_field(error.what()));
  }
}

void TcpRosBridge::handle_profile(const Command &command) {
  if (!profile_client_->service_is_ready()) {
    queue_outgoing("ERROR|PROFILE|" + command.profile + "|SERVICE_UNAVAILABLE");
    return;
  }

  auto request = std::make_shared<SetNetworkProfile::Request>();
  request->profile = command.profile;
  request->latency_ms = 0.0F;
  request->jitter_ms = 0.0F;
  request->drop_rate = 0.0F;

  try {
    profile_client_->async_send_request(
      request,
      [this, profile = command.profile](rclcpp::Client<SetNetworkProfile>::SharedFuture future) {
        try {
          const auto response = future.get();
          if (response->success) {
            RCLCPP_INFO(get_logger(), "Network profile changed to %s", profile.c_str());
            queue_outgoing("ACK|PROFILE|" + profile);
          } else {
            queue_outgoing(
              "ERROR|PROFILE|" + profile + '|' + sanitize_field(response->message));
          }
        } catch (const std::exception &error) {
          queue_outgoing(
            "ERROR|PROFILE|" + profile + "|REQUEST_FAILED|" +
            sanitize_field(error.what()));
        }
      });
  } catch (const std::exception &error) {
    queue_outgoing(
      "ERROR|PROFILE|" + command.profile + "|REQUEST_FAILED|" +
      sanitize_field(error.what()));
  }
}

void TcpRosBridge::handle_quit() {
  queue_outgoing("BYE|" + robot_id_, true);
}

void TcpRosBridge::on_goal_response(
  const std::string &task_id, const GoalHandle::SharedPtr &goal_handle)
{
  bool cancel_immediately = false;
  {
    const std::lock_guard<std::mutex> lock(mission_mutex_);
    if (mission_.task_id != task_id || mission_.state != MissionState::Pending) {
      return;
    }
    if (!goal_handle) {
      mission_.state = MissionState::Rejected;
      mission_.result_message = "goal rejected by mission_server";
      queue_outgoing("ERROR|" + task_id + "|GOAL_REJECTED");
      return;
    }

    mission_.goal_handle = goal_handle;
    cancel_immediately = mission_.cancel_when_accepted;
    mission_.state = cancel_immediately ? MissionState::Canceling : MissionState::Running;
  }

  queue_outgoing(
    "ACK|" + task_id + (cancel_immediately ? "|ACCEPTED_CANCELING" : "|ACCEPTED"));
  if (cancel_immediately) {
    try {
      action_client_->async_cancel_goal(goal_handle);
    } catch (const std::exception &error) {
      {
        const std::lock_guard<std::mutex> lock(mission_mutex_);
        if (mission_.task_id == task_id && mission_.state == MissionState::Canceling) {
          mission_.state = MissionState::Running;
        }
      }
      queue_outgoing(
        "ERROR|" + task_id + "|CANCEL_FAILED|" + sanitize_field(error.what()));
    }
  }
}

void TcpRosBridge::on_feedback(
  const std::string &task_id,
  GoalHandle::SharedPtr,
  const std::shared_ptr<const ExecuteMission::Feedback> feedback)
{
  const auto now = std::chrono::steady_clock::now();
  bool should_send = false;
  std::string message;
  {
    const std::lock_guard<std::mutex> lock(mission_mutex_);
    if (mission_.task_id != task_id || !is_active(mission_.state)) {
      return;
    }

    mission_.distance_remaining = feedback->distance_remaining;
    mission_.network_quality = feedback->network_quality;
    mission_.communication_state = feedback->communication_state;
    mission_.speed_scale = feedback->speed_scale;
    mission_.current_x = feedback->current_pose.x;
    mission_.current_y = feedback->current_pose.y;
    if (mission_.initial_distance < 0.0) {
      mission_.initial_distance = feedback->distance_remaining;
    }

    if (mission_.initial_distance <= 0.0) {
      mission_.progress_percent = 100;
    } else {
      const double progress =
        100.0 * (1.0 - mission_.distance_remaining / mission_.initial_distance);
      mission_.progress_percent = std::clamp(static_cast<int>(std::lround(progress)), 0, 99);
    }

    if (mission_.last_feedback_sent.time_since_epoch().count() == 0 ||
      now - mission_.last_feedback_sent >= std::chrono::seconds(1))
    {
      mission_.last_feedback_sent = now;
      should_send = true;
      message =
        "FEEDBACK|" + task_id + '|' + std::to_string(mission_.progress_percent) + '|' +
        format_number(mission_.distance_remaining) + '|' +
        format_number(mission_.network_quality) + '|' +
        sanitize_field(mission_.communication_state) + '|' +
        format_number(mission_.speed_scale) + '|' + format_number(mission_.current_x) + '|' +
        format_number(mission_.current_y);
    }
  }

  if (should_send) {
    queue_outgoing(std::move(message));
  }
}

void TcpRosBridge::on_result(
  const std::string &task_id, const GoalHandle::WrappedResult &result)
{
  MissionState terminal_state = MissionState::Aborted;
  switch (result.code) {
    case rclcpp_action::ResultCode::SUCCEEDED:
      terminal_state = result.result->success ? MissionState::Succeeded : MissionState::Aborted;
      break;
    case rclcpp_action::ResultCode::CANCELED:
      terminal_state = MissionState::Canceled;
      break;
    case rclcpp_action::ResultCode::ABORTED:
    case rclcpp_action::ResultCode::UNKNOWN:
      terminal_state = MissionState::Aborted;
      break;
  }

  std::string message;
  {
    const std::lock_guard<std::mutex> lock(mission_mutex_);
    if (mission_.task_id != task_id) {
      return;
    }
    mission_.state = terminal_state;
    mission_.progress_percent = terminal_state == MissionState::Succeeded ? 100 : mission_.progress_percent;
    mission_.elapsed_sec = result.result->elapsed_sec;
    mission_.result_message = result.result->message;
    mission_.goal_handle.reset();
    message =
      "RESULT|" + task_id + '|' + state_name(terminal_state) + '|' +
      format_number(mission_.elapsed_sec) + '|' + sanitize_field(mission_.result_message);
  }
  queue_outgoing(std::move(message));
}

void TcpRosBridge::queue_outgoing(std::string payload, bool close_after_send) {
  if (!session_active_.load()) {
    return;
  }
  {
    const std::lock_guard<std::mutex> lock(outgoing_mutex_);
    if (!session_active_.load()) {
      return;
    }
    outgoing_.push_back(OutboundFrame{std::move(payload), close_after_send});
  }
  outgoing_condition_.notify_one();
}

void TcpRosBridge::clear_outgoing() {
  const std::lock_guard<std::mutex> lock(outgoing_mutex_);
  outgoing_.clear();
}

std::string TcpRosBridge::make_status(const std::string &requested_task_id) const {
  const std::lock_guard<std::mutex> lock(mission_mutex_);
  if (mission_.state == MissionState::Idle) {
    return "STATUS|NONE|IDLE|0|0.000|1.000|UNKNOWN|1.000|0.000|0.000";
  }
  if (!requested_task_id.empty() && requested_task_id != mission_.task_id) {
    return "ERROR|" + requested_task_id + "|TASK_NOT_FOUND";
  }
  return
    "STATUS|" + mission_.task_id + '|' + state_name(mission_.state) + '|' +
    std::to_string(mission_.progress_percent) + '|' +
    format_number(mission_.distance_remaining) + '|' +
    format_number(mission_.network_quality) + '|' +
    sanitize_field(mission_.communication_state) + '|' +
    format_number(mission_.speed_scale) + '|' + format_number(mission_.current_x) + '|' +
    format_number(mission_.current_y);
}

const char *TcpRosBridge::state_name(MissionState state) noexcept {
  switch (state) {
    case MissionState::Idle:
      return "IDLE";
    case MissionState::Pending:
      return "PENDING";
    case MissionState::Running:
      return "RUNNING";
    case MissionState::Canceling:
      return "CANCELING";
    case MissionState::Succeeded:
      return "SUCCEEDED";
    case MissionState::Canceled:
      return "CANCELED";
    case MissionState::Aborted:
      return "ABORTED";
    case MissionState::Rejected:
      return "REJECTED";
  }
  return "UNKNOWN";
}

bool TcpRosBridge::is_active(MissionState state) noexcept {
  return state == MissionState::Pending || state == MissionState::Running ||
         state == MissionState::Canceling;
}

}  // namespace linkguard_tcp_bridge
