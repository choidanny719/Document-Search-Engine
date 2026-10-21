#pragma once

#include "search/index.h"

#include <string>
#include <string_view>

namespace httplib {
class Server;
}

namespace search::http {

int parseNumber(std::string_view value, int minimum, int maximum);
void addRoutes(httplib::Server& server, const Index& index, const std::string& page);

}
