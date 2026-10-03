#include "search/tokenizer.h"

#include <gtest/gtest.h>

TEST(Tokenizer, NormalizesCaseAndSeparatesPunctuation) {
    EXPECT_EQ(search::tokenize("Database ROW-level locking!"),
              (std::vector<std::string>{"database", "row", "level", "locking"}));
}

TEST(Tokenizer, PreservesNumbersAndRepeatedWords) {
    EXPECT_EQ(search::tokenize("HTTP2 404 retry retry"),
              (std::vector<std::string>{"http2", "404", "retry", "retry"}));
}

TEST(Tokenizer, HandlesEmptyAndPunctuationOnlyInput) {
    EXPECT_TRUE(search::tokenize("").empty());
    EXPECT_TRUE(search::tokenize(" \n\t.,!?--").empty());
}

TEST(Tokenizer, TreatsNonAsciiBytesAsSeparators) {
    EXPECT_EQ(search::tokenize("hello\xC2\xA0world"),
              (std::vector<std::string>{"hello", "world"}));
}
