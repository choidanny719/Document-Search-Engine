#pragma once

#include "search/index.h"

#include <filesystem>
#include <vector>

namespace search {

std::vector<Document> loadCorpus(const std::filesystem::path& directory);

}
