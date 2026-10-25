#pragma once

#include <cstdint>
#include <cstdlib>
#include <string>
#include <vector>

inline uint16_t mudiro_crc16(const std::vector<uint8_t> &payload) {
  uint16_t crc = 0xFFFF;
  for (uint8_t value : payload) {
    crc ^= value;
    for (int bit = 0; bit < 8; bit++) {
      crc = (crc & 1U) ? static_cast<uint16_t>((crc >> 1) ^ 0xA001) : static_cast<uint16_t>(crc >> 1);
    }
  }
  return crc;
}

inline void mudiro_append_be16(std::vector<uint8_t> &packet, uint16_t value) {
  packet.push_back(static_cast<uint8_t>((value >> 8) & 0xFF));
  packet.push_back(static_cast<uint8_t>(value & 0xFF));
}

inline void mudiro_append_be32(std::vector<uint8_t> &packet, uint32_t value) {
  packet.push_back(static_cast<uint8_t>((value >> 24) & 0xFF));
  packet.push_back(static_cast<uint8_t>((value >> 16) & 0xFF));
  packet.push_back(static_cast<uint8_t>((value >> 8) & 0xFF));
  packet.push_back(static_cast<uint8_t>(value & 0xFF));
}

inline std::vector<uint8_t> mudiro_session_packet(uint8_t opcode, uint32_t timestamp, uint32_t password) {
  std::vector<uint8_t> packet{0x29, 0x0D, opcode, 0};
  mudiro_append_be32(packet, timestamp);
  if (opcode == 0xFF) {
    packet.insert(packet.end(), {0, 0, 0, 0});
  } else {
    mudiro_append_be32(packet, password);
  }
  packet.push_back(1);
  mudiro_append_be16(packet, mudiro_crc16(packet));
  return packet;
}

inline std::vector<uint8_t> mudiro_poll_packet(uint8_t run_type, uint8_t target, uint16_t altitude) {
  std::vector<uint8_t> packet{0xA5, 0x09, 0x01, 0x00, run_type, target};
  mudiro_append_be16(packet, altitude);
  packet.push_back(1);
  mudiro_append_be16(packet, mudiro_crc16(packet));
  return packet;
}

inline std::vector<uint8_t> mudiro_parse_hex(const std::string &hex) {
  std::vector<uint8_t> out;
  std::string cleaned;
  cleaned.reserve(hex.size());
  for (char ch : hex) {
    if (ch != ' ' && ch != ':') {
      cleaned.push_back(ch);
    }
  }
  if (cleaned.size() % 2 != 0) {
    return out;
  }
  for (size_t i = 0; i < cleaned.size(); i += 2) {
    out.push_back(static_cast<uint8_t>(strtoul(cleaned.substr(i, 2).c_str(), nullptr, 16)));
  }
  return out;
}

inline const char *mudiro_frame_name(const std::vector<uint8_t> &bytes) {
  if (bytes.size() >= 2 && bytes[0] == 0x5C && bytes[1] == 0x16) {
    return "5C16 config";
  }
  if (bytes.size() >= 2 && bytes[0] == 0xA5) {
    return "A5 run-settings";
  }
  if (!bytes.empty() && bytes[0] == 0x5D) {
    return "5D board-info";
  }
  if (bytes.size() == 39 && bytes[0] == 0x5A && bytes[1] == 0x25) {
    return "5A25 status";
  }
  return "other";
}

inline std::string mudiro_to_hex(const std::vector<uint8_t> &data) {
  static const char *digits = "0123456789abcdef";
  std::string hex;
  hex.resize(data.size() * 2);
  for (size_t i = 0; i < data.size(); i++) {
    hex[i * 2] = digits[(data[i] >> 4) & 0x0F];
    hex[i * 2 + 1] = digits[data[i] & 0x0F];
  }
  return hex;
}
