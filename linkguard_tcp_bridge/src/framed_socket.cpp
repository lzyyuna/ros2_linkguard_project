#include "linkguard_tcp_bridge/framed_socket.hpp"

#include <arpa/inet.h>
#include <cerrno>
#include <cstddef>
#include <cstring>
#include <stdexcept>
#include <string>
#include <sys/socket.h>
#include <unistd.h>

namespace linkguard_tcp_bridge {
namespace {

constexpr std::size_t kMaxMessageBytes = 4096;

[[noreturn]] void throw_system_error(const std::string &operation) {
  const int error = errno;
  throw std::runtime_error(operation + " failed: " + std::strerror(error));
}

void send_all(int descriptor, const char *data, std::size_t size) {
  std::size_t total_sent = 0;
  while (total_sent < size) {
    const ssize_t sent = send(
      descriptor, data + total_sent, size - total_sent, MSG_NOSIGNAL);
    if (sent < 0) {
      if (errno == EINTR) {
        continue;
      }
      throw_system_error("send");
    }
    if (sent == 0) {
      throw std::runtime_error("send returned 0 before the frame was complete");
    }
    total_sent += static_cast<std::size_t>(sent);
  }
}

bool receive_exact(int descriptor, char *data, std::size_t size) {
  std::size_t total_received = 0;
  while (total_received < size) {
    const ssize_t received = recv(
      descriptor, data + total_received, size - total_received, 0);
    if (received < 0) {
      if (errno == EINTR) {
        continue;
      }
      throw_system_error("recv");
    }
    if (received == 0) {
      if (total_received == 0) {
        return false;
      }
      throw std::runtime_error("connection closed in the middle of a frame");
    }
    total_received += static_cast<std::size_t>(received);
  }
  return true;
}

}  // namespace

Socket::Socket(int descriptor) noexcept : descriptor_(descriptor) {}

Socket::~Socket() {
  if (descriptor_ >= 0) {
    close(descriptor_);
  }
}

Socket::Socket(Socket &&other) noexcept : descriptor_(other.descriptor_) {
  other.descriptor_ = -1;
}

Socket &Socket::operator=(Socket &&other) noexcept {
  if (this != &other) {
    if (descriptor_ >= 0) {
      close(descriptor_);
    }
    descriptor_ = other.descriptor_;
    other.descriptor_ = -1;
  }
  return *this;
}

int Socket::get() const noexcept { return descriptor_; }

Socket connect_ipv4(const std::string &server_ip, std::uint16_t server_port) {
  Socket socket_handle(socket(AF_INET, SOCK_STREAM, 0));
  if (socket_handle.get() < 0) {
    throw_system_error("socket");
  }

  sockaddr_in server{};
  server.sin_family = AF_INET;
  server.sin_port = htons(server_port);
  const int parse_result = inet_pton(AF_INET, server_ip.c_str(), &server.sin_addr);
  if (parse_result == 0) {
    throw std::runtime_error("invalid IPv4 address: " + server_ip);
  }
  if (parse_result < 0) {
    throw_system_error("inet_pton");
  }

  if (connect(
      socket_handle.get(), reinterpret_cast<const sockaddr *>(&server), sizeof(server)) < 0)
  {
    throw_system_error("connect");
  }
  return socket_handle;
}

void shutdown_socket(int descriptor) noexcept {
  if (descriptor >= 0) {
    shutdown(descriptor, SHUT_RDWR);
  }
}

void send_frame(int descriptor, const std::string &message) {
  if (message.size() > kMaxMessageBytes) {
    throw std::runtime_error("outgoing message exceeds the 4096-byte limit");
  }

  const auto message_size = static_cast<std::uint32_t>(message.size());
  const std::uint32_t network_size = htonl(message_size);
  send_all(
    descriptor, reinterpret_cast<const char *>(&network_size), sizeof(network_size));
  send_all(descriptor, message.data(), message.size());
}

bool receive_frame(int descriptor, std::string &message) {
  std::uint32_t network_size = 0;
  if (!receive_exact(
      descriptor, reinterpret_cast<char *>(&network_size), sizeof(network_size)))
  {
    return false;
  }

  const std::uint32_t message_size = ntohl(network_size);
  if (message_size > kMaxMessageBytes) {
    throw std::runtime_error("incoming message exceeds the 4096-byte limit");
  }

  message.resize(message_size);
  if (message_size > 0 &&
    !receive_exact(descriptor, message.data(), static_cast<std::size_t>(message_size)))
  {
    throw std::runtime_error("connection closed before the frame body arrived");
  }
  return true;
}

}  // namespace linkguard_tcp_bridge
