#include "search/index.h"

#include <algorithm>
#include <cmath>
#include <gtest/gtest.h>
#include <numeric>
#include <random>

namespace {

using Counts = std::vector<unsigned>;

const std::vector<std::string> vocabulary{
    "alpha", "beta", "delta", "epsilon", "gamma", "kappa", "lambda", "omega", "unknown"
};

std::string textFor(const Counts& counts) {
    std::string text;
    for (std::size_t term = 0; term < counts.size(); ++term) {
        for (unsigned occurrence = 0; occurrence < counts[term]; ++occurrence) {
            text += vocabulary[term] + ' ';
        }
    }
    return text;
}

std::vector<search::SearchHit> referenceRanking(const std::vector<search::Document>& documents,
                                               const std::vector<Counts>& frequencies,
                                               const Counts& query, search::MatchMode mode) {
    std::vector<double> idf(vocabulary.size(), 0);
    for (std::size_t term = 0; term < vocabulary.size(); ++term) {
        const auto count = std::count_if(frequencies.begin(), frequencies.end(),
            [term](const auto& document) { return document[term] > 0; });
        if (count > 0) {
            idf[term] = 1 + std::log((documents.size() + 1.0) / (count + 1.0));
        }
    }
    const auto weights = [&idf](const Counts& counts) {
        std::vector<double> result(counts.size(), 0);
        for (std::size_t term = 0; term < counts.size(); ++term) {
            if (counts[term]) result[term] = (1 + std::log(counts[term])) * idf[term];
        }
        return result;
    };
    const auto query_vector = weights(query);
    const auto norm = [](const auto& vector) {
        return std::sqrt(std::inner_product(vector.begin(), vector.end(), vector.begin(), 0.0));
    };
    std::vector<search::SearchHit> matches;
    for (std::size_t document = 0; document < documents.size(); ++document) {
        bool any = false;
        bool all = true;
        for (std::size_t term = 0; term < query.size(); ++term) {
            if (query[term]) {
                any = any || frequencies[document][term] > 0;
                all = all && frequencies[document][term] > 0;
            }
        }
        if (!any || (mode == search::MatchMode::All && !all)) continue;
        const auto document_vector = weights(frequencies[document]);
        const double dot = std::inner_product(query_vector.begin(), query_vector.end(),
                                             document_vector.begin(), 0.0);
        matches.push_back({document, dot / (norm(query_vector) * norm(document_vector))});
    }
    std::sort(matches.begin(), matches.end(), [&documents](const auto& left, const auto& right) {
        if (left.score != right.score) return left.score > right.score;
        return documents[left.document].id < documents[right.document].id;
    });
    return matches;
}

}

TEST(Ranking, MatchesAnIndependentDenseCalculationForBothModesAndLimits) {
    std::mt19937 random(7319);
    std::vector<search::Document> documents;
    std::vector<Counts> frequencies;
    for (unsigned id = 0; id < 48; ++id) {
        Counts counts(vocabulary.size(), 0);
        if (id % 11 != 0) {
            for (std::size_t term = 0; term + 1 < counts.size(); ++term) counts[term] = random() % 6;
        }
        documents.push_back({"document-" + std::to_string(48 - id), "Document", textFor(counts)});
        frequencies.push_back(std::move(counts));
    }
    const search::Index index(documents);
    std::vector<Counts> queries{
        Counts(vocabulary.size(), 0),
        {1, 0, 0, 0, 0, 0, 0, 0, 0},
        {0, 0, 0, 0, 0, 0, 0, 0, 1},
        {2, 1, 0, 0, 0, 0, 0, 0, 1},
        {1, 1, 1, 1, 1, 1, 1, 1, 0}
    };
    for (unsigned number = 0; number < 12; ++number) {
        Counts query(vocabulary.size(), 0);
        for (auto& count : query) count = random() % 4;
        queries.push_back(std::move(query));
    }
    for (const auto& query : queries) {
        const auto text = textFor(query);
        SCOPED_TRACE(text);
        for (const auto mode : {search::MatchMode::Any, search::MatchMode::All}) {
            SCOPED_TRACE(mode == search::MatchMode::All ? "all" : "any");
            const auto expected = referenceRanking(documents, frequencies, query, mode);
            std::vector<std::size_t> identifiers;
            for (const auto& hit : expected) identifiers.push_back(hit.document);
            std::sort(identifiers.begin(), identifiers.end());
            EXPECT_EQ(index.match(text, mode), identifiers);
            for (const std::size_t limit : {1, 3, 10, 48, 100}) {
                SCOPED_TRACE(limit);
                const auto actual = index.search(text, limit, mode);
                EXPECT_EQ(actual.total, expected.size());
                ASSERT_EQ(actual.hits.size(), std::min(limit, expected.size()));
                for (std::size_t rank = 0; rank < actual.hits.size(); ++rank) {
                    EXPECT_EQ(actual.hits[rank].document, expected[rank].document);
                    EXPECT_NEAR(actual.hits[rank].score, expected[rank].score, 1e-12);
                    EXPECT_TRUE(std::isfinite(actual.hits[rank].score));
                    EXPECT_GT(actual.hits[rank].score, 0);
                    EXPECT_LE(actual.hits[rank].score, 1 + 1e-12);
                }
            }
        }
    }
}
