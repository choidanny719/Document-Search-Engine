#include "search/index.h"

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
