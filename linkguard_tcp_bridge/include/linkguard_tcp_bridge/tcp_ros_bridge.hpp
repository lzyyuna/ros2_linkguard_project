#pragma once

#include "linkguard_interfaces/action/execute_mission.hpp"
#include "linkguard_interfaces/srv/set_network_profile.hpp"
#include "linkguard_tcp_bridge/command_parser.hpp"

#include <rclcpp/rclcpp.hpp>
#include <rclcpp_action/rclcpp_action.hpp>

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <memory>
#include <mutex>
#include <string>
#include <thread>

namespace linkguard_tcp_bridge {

class TcpRosBridge final : public rclcpp::Node {
public:
  using ExecuteMission = linkguard_interfaces::action::ExecuteMission;
  using GoalHandle = rclcpp_action::ClientGoalHandle<ExecuteMission>;
  using SetNetworkProfile = linkguard_interfaces::srv::SetNetworkProfile;

  TcpRosBridge();
  ~TcpRosBridge() override;

private:
  enum class MissionState {
    Idle,
    Pending,
    Running,
    Canceling,
    Succeeded,
    Canceled,
    Aborted,
    Rejected,
  };

  struct MissionSnapshot {
    std::string task_id;
    MissionState state = MissionState::Idle;
    int progress_percent = 0;
    double initial_distance = -1.0;
    double distance_remaining = 0.0;
    double network_quality = 1.0;
    std::string communication_state = "UNKNOWN";
    double speed_scale = 1.0;
    double current_x = 0.0;
    double current_y = 0.0;
    double elapsed_sec = 0.0;
    std::string result_message;
    GoalHandle::SharedPtr goal_handle;
    bool cancel_when_accepted = false;
    std::chrono::steady_clock::time_point last_feedback_sent{};
  };

  struct OutboundFrame {
    std::string payload;
    bool close_after_send = false;
  };

  void network_loop();
  void run_connected_session(int descriptor);
  void writer_loop(int descriptor);
  void stop_network() noexcept;

  void enqueue_command(std::string command);
  void drain_commands();
  void handle_command(const Command &command);
  void handle_start(const Command &command);
  void handle_status(const Command &command);
  void handle_stop(const Command &command);
  void handle_profile(const Command &command);
  void handle_quit();

  void on_goal_response(const std::string &task_id, const GoalHandle::SharedPtr &goal_handle);
  void on_feedback(
    const std::string &task_id,
    GoalHandle::SharedPtr,
    const std::shared_ptr<const ExecuteMission::Feedback> feedback);
  void on_result(const std::string &task_id, const GoalHandle::WrappedResult &result);

  void queue_outgoing(std::string payload, bool close_after_send = false);
  void clear_outgoing();
  std::string make_status(const std::string &requested_task_id) const;
  static const char *state_name(MissionState state) noexcept;
  static bool is_active(MissionState state) noexcept;

  rclcpp_action::Client<ExecuteMission>::SharedPtr action_client_;
  rclcpp::Client<SetNetworkProfile>::SharedPtr profile_client_;
  rclcpp::TimerBase::SharedPtr command_timer_;

  std::string server_ip_;
  std::uint16_t server_port_;
  std::string robot_id_;
  std::chrono::milliseconds reconnect_delay_{2000};

  mutable std::mutex mission_mutex_;
  MissionSnapshot mission_;

  std::mutex command_mutex_;
  std::deque<std::string> commands_;

  std::mutex outgoing_mutex_;
  std::condition_variable outgoing_condition_;
  std::deque<OutboundFrame> outgoing_;

  std::atomic<bool> stop_requested_{false};
  std::atomic<bool> session_active_{false};
  std::thread network_thread_;
  std::mutex socket_mutex_;
  int active_socket_ = -1;
  std::mutex reconnect_mutex_;
  std::condition_variable reconnect_condition_;
};

}  // namespace linkguard_tcp_bridge
