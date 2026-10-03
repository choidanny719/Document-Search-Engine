#include "search/index.h"
#include "search/tokenizer.h"

#include <algorithm>
#include <charconv>
#include <chrono>
#include <iomanip>
#include <iostream>
#include <random>
#include <stdexcept>

using Clock = std::chrono::steady_clock;

std::vector<std::size_t> scan(const std::vector<std::vector<std::string>>& documents,
                             const std::string& query, search::MatchMode mode) {
    const auto words = search::tokenize(query);
    std::vector<std::size_t> matches;
    for (std::size_t id = 0; id < documents.size(); ++id) {
        std::size_t found = 0;
        for (const auto& word : words) {
            found += std::binary_search(documents[id].begin(), documents[id].end(), word);
        }
        if ((mode == search::MatchMode::All && found == words.size()) ||
            (mode == search::MatchMode::Any && found > 0)) {
            matches.push_back(id);
        }
    }
    return matches;
}

double milliseconds(Clock::time_point start) {
    return std::chrono::duration<double, std::milli>(Clock::now() - start).count();
}

void report(const std::string& name, std::vector<double> times) {
    std::sort(times.begin(), times.end());
    std::cout << name << ',' << times[times.size() / 2] << ','
              << times[(times.size() - 1) * 95 / 100] << '\n';
}

int main(int argc, char* argv[]) {
    try {
        int count = 10000;
        if (argc > 2) {
            throw std::invalid_argument("Usage: search_benchmark [document_count]");
        }
        if (argc == 2) {
            const std::string value = argv[1];
            const auto [end, error] = std::from_chars(value.data(), value.data() + value.size(), count);
            if (error != std::errc{} || end != value.data() + value.size() || count < 1 || count > 50000) {
                throw std::invalid_argument("Document count must be between 1 and 50000");
            }
        }

        std::mt19937 random(42);
        std::uniform_int_distribution<int> vocabulary(0, 1999);
        std::vector<search::Document> documents;
        std::vector<std::vector<std::string>> scan_documents;
        for (int id = 0; id < count; ++id) {
            std::string text;
            for (int word = 0; word < 80; ++word) {
                text += "word" + std::to_string(vocabulary(random)) + ' ';
            }
            auto words = search::tokenize(text);
            std::sort(words.begin(), words.end());
            scan_documents.push_back(std::move(words));
            documents.push_back({std::to_string(id), "Document", std::move(text)});
        }

        const auto build_start = Clock::now();
        const search::Index index(std::move(documents));
        const auto build_ms = milliseconds(build_start);
        std::vector<double> indexed_times, scan_times, ranked_times;
        std::size_t verified_queries = 0;
        for (int round = 0; round < 4; ++round) {
            for (int number = 0; number < 24; ++number) {
                const auto query = "word" + std::to_string(number * 71) +
                                   " word" + std::to_string(number * 37 + 9);
                for (const auto mode : {search::MatchMode::Any, search::MatchMode::All}) {
                    const auto index_start = Clock::now();
                    const auto indexed = index.match(query, mode);
                    const auto index_ms = milliseconds(index_start);
                    const auto scan_start = Clock::now();
                    const auto scanned = scan(scan_documents, query, mode);
                    const auto scan_ms = milliseconds(scan_start);
                    if (indexed != scanned) {
                        throw std::runtime_error("Indexed and scanned matches differ");
                    }
                    const auto rank_start = Clock::now();
                    const auto ranked = index.search(query, 10, mode);
                    const auto rank_ms = milliseconds(rank_start);
                    if (ranked.total != scanned.size() || ranked.hits.size() != std::min<std::size_t>(10, scanned.size())) {
                        throw std::runtime_error("Ranked result count differs");
                    }
                    ++verified_queries;
                    if (round > 0) {
                        indexed_times.push_back(index_ms);
                        scan_times.push_back(scan_ms);
                        ranked_times.push_back(rank_ms);
                    }
                }
            }
        }

        std::cout << std::fixed << std::setprecision(4);
        std::cout << "documents=" << count << " words_per_document=80 seed=42\n";
        std::cout << "index_build_ms=" << build_ms << " verified_queries=" << verified_queries << '\n';
        std::cout << "method,p50_ms,p95_ms\n";
        report("inverted_index_match", indexed_times);
        report("full_corpus_match", scan_times);
        report("ranked_top_10", ranked_times);
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
