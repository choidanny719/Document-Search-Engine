#include "search/corpus.h"

#include <algorithm>
#include <fstream>
#include <stdexcept>

namespace search {

std::vector<Document> loadCorpus(const std::filesystem::path& directory) {
    constexpr std::uintmax_t max_file_size = 1024 * 1024;
    constexpr std::uintmax_t max_corpus_size = 64 * 1024 * 1024;
    constexpr std::size_t max_documents = 50000;

    if (!std::filesystem::is_directory(directory)) {
        throw std::runtime_error("Document directory does not exist: " + directory.string());
    }

    std::vector<std::filesystem::path> paths;
    for (const auto& entry : std::filesystem::recursive_directory_iterator(directory)) {
        if (entry.is_symlink() || !entry.is_regular_file()) {
            continue;
        }
        const auto extension = entry.path().extension();
        if (extension == ".txt" || extension == ".md") {
            paths.push_back(entry.path());
            if (paths.size() > max_documents) {
                throw std::runtime_error("Corpus exceeds 50000 documents");
            }
        }
    }
    std::sort(paths.begin(), paths.end());

    std::uintmax_t total_size = 0;
    std::vector<Document> documents;
    for (const auto& path : paths) {
        const auto size = std::filesystem::file_size(path);
        total_size += size;
        if (size > max_file_size || total_size > max_corpus_size) {
            throw std::runtime_error("Document size limit exceeded: " + path.string());
        }

        std::ifstream input(path, std::ios::binary);
        std::string text(size, '\0');
        input.read(text.data(), static_cast<std::streamsize>(size));
        if (!input || input.peek() != std::char_traits<char>::eof()) {
            throw std::runtime_error("Could not read document: " + path.string());
        }
        if (text.find('\0') != std::string::npos) {
            throw std::runtime_error("Document contains binary data: " + path.string());
        }

        auto title = path.stem().string();
        std::replace(title.begin(), title.end(), '-', ' ');
        std::replace(title.begin(), title.end(), '_', ' ');
        documents.push_back({path.lexically_relative(directory).generic_string(),
                             std::move(title), std::move(text)});
    }
    return documents;
}

}
