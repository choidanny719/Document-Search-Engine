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

TEST(Tokenizer, ClassifiesEveryByteWithoutLocaleDependentLetters) {
    const std::string alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
    const std::string normalized = "abcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyz0123456789";
    for (int value = 0; value < 256; ++value) {
        SCOPED_TRACE(value);
        const auto byte = static_cast<char>(value);
        const auto position = alphabet.find(byte);
        const std::string input = std::string("L") + byte + "R";
        const std::vector<std::string> expected = position == std::string::npos
            ? std::vector<std::string>{"l", "r"}
            : std::vector<std::string>{std::string("l") + normalized[position] + "r"};
        EXPECT_EQ(search::tokenize(input), expected);
    }
}

TEST(Tokenizer, RespectsStringViewBoundariesAndEmbeddedNulls) {
    const std::string text = "beforeALPHAafter";
    EXPECT_EQ(search::tokenize(std::string_view(text).substr(6, 5)),
              (std::vector<std::string>{"alpha"}));
    EXPECT_EQ(search::tokenize(std::string("one\0TWO\0three", 13)),
              (std::vector<std::string>{"one", "two", "three"}));
    EXPECT_TRUE(search::tokenize(std::string_view{}).empty());
}

TEST(Tokenizer, PreservesLongTokensAndFlushesTheFinalWord) {
    const std::string word(8192, 'A');
    const std::string lower(8192, 'a');
    EXPECT_EQ(search::tokenize(word), (std::vector<std::string>{lower}));
    EXPECT_EQ(search::tokenize("\n\t" + word + "--99"),
              (std::vector<std::string>{lower, "99"}));
}
