#pragma once

#include <string>
#include <string_view>
#include <vector>

namespace search {

std::vector<std::string> tokenize(std::string_view text);

}
