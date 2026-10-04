#include "search/index.h"

#include <algorithm>
#include <cmath>
#include <gtest/gtest.h>

using search::Document;
using search::Index;
using search::MatchMode;

TEST(Index, SupportsAnyAndAllWordsWithoutRequiringAPhrase) {
    const Index index({{"a", "A", "database row locking"},
                       {"b", "B", "database backup guide"},
                       {"c", "C", "cooking pasta guide"}});
    EXPECT_EQ(index.match("DATABASE locking", MatchMode::Any),
              (std::vector<std::size_t>{0, 1}));
    EXPECT_EQ(index.match("database locking", MatchMode::All),
              (std::vector<std::size_t>{0}));
    const auto results = index.search("database locking");
    ASSERT_EQ(results.total, 2);
    EXPECT_EQ(results.hits.front().document, 0);
}

TEST(Index, HandlesUnknownRepeatedAndEmptyTerms) {
    const Index index({{"a", "A", "database locking"}, {"b", "B", "database"}});
    EXPECT_EQ(index.match("database database", MatchMode::All).size(), 2);
    EXPECT_EQ(index.match("database missing", MatchMode::Any).size(), 2);
    EXPECT_TRUE(index.match("database missing", MatchMode::All).empty());
    EXPECT_TRUE(index.search("missing").hits.empty());
    EXPECT_TRUE(index.search(" ! ").hits.empty());
}

TEST(Index, UsesSmoothedIdfAndCosineNormalization) {
    const Index index({{"a", "A", "alpha beta"}, {"b", "B", "alpha"}});
    const double beta_idf = 1.0 + std::log(3.0 / 2.0);
    const auto results = index.search("alpha");
    ASSERT_EQ(results.hits.size(), 2);
    EXPECT_EQ(results.hits[0].document, 1);
    EXPECT_NEAR(results.hits[0].score, 1.0, 1e-12);
    EXPECT_NEAR(results.hits[1].score, 1.0 / std::sqrt(1 + beta_idf * beta_idf), 1e-12);
}

TEST(Index, AppliesLogarithmicTermFrequency) {
    const Index index({{"a", "A", "alpha alpha beta"}, {"b", "B", "alpha beta"}});
    const double tf = 1.0 + std::log(2.0);
    const auto results = index.search("alpha");
    EXPECT_EQ(results.hits.front().document, 0);
    EXPECT_NEAR(results.hits.front().score, tf / std::sqrt(tf * tf + 1), 1e-12);
}

TEST(Index, ReturnsBestKAndBreaksTiesByDocumentId) {
    const Index index({{"z", "Z", "search"}, {"a", "A", "search"},
                       {"b", "B", "search"}, {"c", "C", "search extra"}});
    const auto results = index.search("search", 2);
    EXPECT_EQ(results.total, 4);
    ASSERT_EQ(results.hits.size(), 2);
    EXPECT_EQ(results.hits[0].document, 1);
    EXPECT_EQ(results.hits[1].document, 2);
    EXPECT_THROW(index.search("search", 0), std::invalid_argument);
}

TEST(Index, HandlesEmptyCorporaAndDocuments) {
    const Index empty({});
    EXPECT_TRUE(empty.search("anything").hits.empty());
    EXPECT_EQ(empty.termCount(), 0);
    const Index index({{"empty", "Empty", ""}, {"a", "A", "search"}});
    const auto results = index.search("search");
    ASSERT_EQ(results.hits.size(), 1);
    EXPECT_TRUE(std::isfinite(results.hits[0].score));
}

TEST(Index, ValidatesIdentifiersAndFindsDocuments) {
    EXPECT_THROW((Index({{"", "A", "a"}})), std::invalid_argument);
    EXPECT_THROW((Index({{"a", "A", "a"}, {"a", "B", "b"}})), std::invalid_argument);
    const Index index({{"a", "A", "alpha"}});
    ASSERT_NE(index.find("a"), nullptr);
    EXPECT_EQ(index.find("a")->text, "alpha");
    EXPECT_EQ(index.find("missing"), nullptr);
}

TEST(Index, TopKMatchesThePrefixOfTheFullRanking) {
    std::vector<Document> documents;
    for (int i = 0; i < 80; ++i) {
        documents.push_back({std::to_string(i), "Document", std::string(i % 9 + 1, ' ') +
                             "search search " + (i % 3 == 0 ? "index index" : "query")});
    }
    const Index index(std::move(documents));
    const auto full = index.search("search index", 80);
    const auto limited = index.search("search index", 7);
    ASSERT_EQ(limited.hits.size(), 7);
    for (std::size_t i = 0; i < limited.hits.size(); ++i) {
        EXPECT_EQ(limited.hits[i].document, full.hits[i].document);
        EXPECT_DOUBLE_EQ(limited.hits[i].score, full.hits[i].score);
    }
}

TEST(Index, WeightsRepeatedQueryWordsAndIgnoresUnknownWordsInScores) {
    const Index index({{"a", "A", "alpha beta"}, {"b", "B", "alpha alpha beta"}});
    const double tf = 1.0 + std::log(2.0);
    const auto results = index.search("alpha alpha beta missing");
    ASSERT_EQ(results.hits.size(), 2);
    EXPECT_EQ(results.hits[0].document, 1);
    EXPECT_NEAR(results.hits[0].score, 1.0, 1e-12);
    EXPECT_NEAR(results.hits[1].score, (tf + 1.0) / std::sqrt(2.0 * (tf * tf + 1.0)), 1e-12);
    const auto known = index.search("alpha alpha beta");
    for (std::size_t i = 0; i < results.hits.size(); ++i) {
        EXPECT_EQ(results.hits[i].document, known.hits[i].document);
        EXPECT_DOUBLE_EQ(results.hits[i].score, known.hits[i].score);
    }
}

TEST(Index, RequiresAllKnownTermsEvenWhenTheyOccurInDifferentDocuments) {
    const Index index({{"a", "A", "alpha"}, {"b", "B", "beta"}, {"c", "C", "gamma"}});
    EXPECT_TRUE(index.match("alpha beta gamma", MatchMode::All).empty());
    EXPECT_TRUE(index.search("alpha beta gamma", 10, MatchMode::All).hits.empty());
    EXPECT_EQ(index.match("alpha beta gamma", MatchMode::Any).size(), 3);
}

TEST(Index, FiltersRankedResultsInAllMode) {
    const Index index({{"a", "A", "alpha beta"}, {"b", "B", "alpha"},
                       {"c", "C", "beta"}, {"d", "D", "alpha beta gamma"}});
    const auto results = index.search("alpha beta alpha", 100, MatchMode::All);
    EXPECT_EQ(results.total, 2);
    ASSERT_EQ(results.hits.size(), 2);
    EXPECT_EQ(results.hits[0].document, 0);
    EXPECT_EQ(results.hits[1].document, 3);
    for (const auto& hit : results.hits) {
        EXPECT_TRUE(std::isfinite(hit.score));
        EXPECT_GT(hit.score, 0);
        EXPECT_LE(hit.score, 1.0 + 1e-12);
    }
}

TEST(Index, RankingDoesNotDependOnDocumentOrQueryWordOrder) {
    std::vector<Document> documents{{"z", "Z", "alpha beta"}, {"a", "A", "alpha beta"},
                                    {"b", "B", "alpha gamma"}, {"c", "C", "beta beta"}};
    const Index forward(documents);
    std::reverse(documents.begin(), documents.end());
    const Index reversed(documents);
    for (const auto mode : {MatchMode::Any, MatchMode::All}) {
        for (const auto limit : {1, 2, 4, 100}) {
            const auto left = forward.search("alpha beta", limit, mode);
            const auto right = reversed.search("beta alpha", limit, mode);
            ASSERT_EQ(left.hits.size(), right.hits.size());
            EXPECT_EQ(left.total, right.total);
            for (std::size_t i = 0; i < left.hits.size(); ++i) {
                EXPECT_EQ(forward.documents()[left.hits[i].document].id,
                          reversed.documents()[right.hits[i].document].id);
                EXPECT_NEAR(left.hits[i].score, right.hits[i].score, 1e-12);
            }
        }
    }
}
