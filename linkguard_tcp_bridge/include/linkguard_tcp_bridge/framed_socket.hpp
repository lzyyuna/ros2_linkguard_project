#pragma once

#include <cstdint>
#include <string>

namespace linkguard_tcp_bridge {

class Socket {
public:
  explicit Socket(int descriptor = -1) noexcept;
  ~Socket();

  Socket(const Socket &) = delete;
  Socket &operator=(const Socket &) = delete;
  Socket(Socket &&other) noexcept;
  Socket &operator=(Socket &&other) noexcept;

  [[nodiscard]] int get() const noexcept;

private:
  int descriptor_;
};

Socket connect_ipv4(const std::string &server_ip, std::uint16_t server_port);
void shutdown_socket(int descriptor) noexcept;
void send_frame(int descriptor, const std::string &message);
bool receive_frame(int descriptor, std::string &message);

}  // namespace linkguard_tcp_bridge
