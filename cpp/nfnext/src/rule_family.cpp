#include "nfnext/rule_family.hpp"

#include <cctype>

namespace nfnext {

std::string stripTrailingIndex(const std::string& name, std::uint32_t* index) {
    if (index) *index = 0;
    if (name.empty()) return name;
    std::size_t end = name.size();
    std::size_t begin = end;
    while (begin > 0 && std::isdigit(static_cast<unsigned char>(name[begin - 1]))) --begin;
    if (begin == end || begin == 0) return name;
    const char separator = name[begin - 1];
    if (separator != '_' && separator != ':') return name;
    std::uint64_t value = 0;
    for (std::size_t i = begin; i < end; ++i)
        value = value * 10 + static_cast<unsigned>(name[i] - '0');
    if (value > 0xffffffffULL) return name;
    if (index) *index = static_cast<std::uint32_t>(value);
    return name.substr(0, begin - 1);
}

} // namespace nfnext
