#pragma once

#include <cstddef>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

namespace search {

struct Document {
    std::string id;
    std::string title;
    std::string text;
};

enum class MatchMode { Any, All };

struct SearchHit {
    std::size_t document;
    double score;
};

struct SearchResults {
    std::size_t total;
    std::vector<SearchHit> hits;
};

class Index {
public:
    explicit Index(std::vector<Document> documents);

    std::vector<std::size_t> match(std::string_view query, MatchMode mode) const;
    SearchResults search(std::string_view query, std::size_t limit = 10,
                         MatchMode mode = MatchMode::Any) const;
    const std::vector<Document>& documents() const;
    const Document* find(std::string_view id) const;
    std::size_t termCount() const;

private:
    struct Posting {
        std::size_t document;
        double weight;
    };

    struct Term {
        std::vector<Posting> postings;
        double idf = 0;
    };

    std::vector<Document> documents_;
    std::unordered_map<std::string, std::size_t> document_ids_;
    std::unordered_map<std::string, Term> terms_;
    std::vector<double> norms_;
};

}
