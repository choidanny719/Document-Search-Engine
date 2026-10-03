#include "search/index.h"
#include "search/tokenizer.h"

#include <algorithm>
#include <cmath>
#include <iterator>
#include <map>
#include <queue>
#include <stdexcept>
#include <unordered_set>

namespace search {

Index::Index(std::vector<Document> documents)
    : documents_(std::move(documents)), norms_(documents_.size(), 0) {
    for (std::size_t id = 0; id < documents_.size(); ++id) {
        const auto& document = documents_[id];
        if (document.id.empty() || !document_ids_.emplace(document.id, id).second) {
            throw std::invalid_argument("Document IDs must be nonempty and unique");
        }

        std::unordered_map<std::string, std::size_t> counts;
        for (const auto& word : tokenize(document.text)) {
            ++counts[word];
        }
        for (const auto& [word, count] : counts) {
            terms_[word].postings.push_back({id, 1.0 + std::log(static_cast<double>(count))});
        }
    }

    for (auto& [word, term] : terms_) {
        term.idf = 1.0 + std::log((documents_.size() + 1.0) / (term.postings.size() + 1.0));
        for (auto& posting : term.postings) {
            posting.weight *= term.idf;
            norms_[posting.document] += posting.weight * posting.weight;
        }
    }
    for (auto& norm : norms_) {
        norm = std::sqrt(norm);
    }
}

std::vector<std::size_t> Index::match(std::string_view query, MatchMode mode) const {
    const auto words = tokenize(query);
    const std::unordered_set<std::string> unique(words.begin(), words.end());
    std::vector<const Term*> entries;

    for (const auto& word : unique) {
        const auto found = terms_.find(word);
        if (found != terms_.end()) {
            entries.push_back(&found->second);
        } else if (mode == MatchMode::All) {
            return {};
        }
    }
    std::sort(entries.begin(), entries.end(), [](const Term* left, const Term* right) {
        return left->postings.size() < right->postings.size();
    });

    std::vector<std::size_t> candidates;
    for (std::size_t i = 0; i < entries.size(); ++i) {
        std::vector<std::size_t> ids;
        ids.reserve(entries[i]->postings.size());
        for (const auto& posting : entries[i]->postings) {
            ids.push_back(posting.document);
        }
        if (i == 0) {
            candidates = std::move(ids);
            continue;
        }

        std::vector<std::size_t> combined;
        if (mode == MatchMode::All) {
            std::set_intersection(candidates.begin(), candidates.end(), ids.begin(), ids.end(),
                                  std::back_inserter(combined));
        } else {
            std::set_union(candidates.begin(), candidates.end(), ids.begin(), ids.end(),
                           std::back_inserter(combined));
        }
        candidates = std::move(combined);
        if (candidates.empty() && mode == MatchMode::All) {
            break;
        }
    }
    return candidates;
}

SearchResults Index::search(std::string_view query, std::size_t limit, MatchMode mode) const {
    if (limit == 0) {
        throw std::invalid_argument("Result limit must be positive");
    }
    const auto candidates = match(query, mode);
    if (candidates.empty()) {
        return {0, {}};
    }

    std::map<std::string, std::size_t> counts;
    for (const auto& word : tokenize(query)) {
        ++counts[word];
    }
    std::unordered_map<std::size_t, double> scores;
    double query_norm = 0;
    for (const auto& [word, count] : counts) {
        const auto found = terms_.find(word);
        if (found == terms_.end()) {
            continue;
        }
        const auto& term = found->second;
        const double weight = (1.0 + std::log(static_cast<double>(count))) * term.idf;
        query_norm += weight * weight;
        for (const auto& posting : term.postings) {
            scores[posting.document] += weight * posting.weight;
        }
    }
    query_norm = std::sqrt(query_norm);

    const auto better = [this](const SearchHit& left, const SearchHit& right) {
        if (left.score != right.score) {
            return left.score > right.score;
        }
        return documents_[left.document].id < documents_[right.document].id;
    };
    std::priority_queue<SearchHit, std::vector<SearchHit>, decltype(better)> best(better);
    for (const auto id : candidates) {
        const SearchHit hit{id, scores.at(id) / (query_norm * norms_[id])};
        if (best.size() < limit) {
            best.push(hit);
        } else if (better(hit, best.top())) {
            best.pop();
            best.push(hit);
        }
    }

    SearchResults result{candidates.size(), {}};
    while (!best.empty()) {
        result.hits.push_back(best.top());
        best.pop();
    }
    std::reverse(result.hits.begin(), result.hits.end());
    return result;
}

const std::vector<Document>& Index::documents() const {
    return documents_;
}

const Document* Index::find(std::string_view id) const {
    const auto found = document_ids_.find(std::string(id));
    return found == document_ids_.end() ? nullptr : &documents_[found->second];
}

std::size_t Index::termCount() const {
    return terms_.size();
}

}
