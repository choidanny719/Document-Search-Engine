#include "search/corpus.h"

#include <chrono>
#include <fstream>
#include <gtest/gtest.h>

class CorpusTest : public testing::Test {
protected:
    std::filesystem::path directory;

    void SetUp() override {
        const auto stamp = std::chrono::steady_clock::now().time_since_epoch().count();
        directory = std::filesystem::temp_directory_path() / ("search-test-" + std::to_string(stamp));
        std::filesystem::create_directory(directory);
    }

    void TearDown() override {
        std::error_code error;
        std::filesystem::remove_all(directory, error);
    }

    void write(const std::string& name, const std::string& text) {
        const auto path = directory / name;
        std::filesystem::create_directories(path.parent_path());
        std::ofstream(path, std::ios::binary) << text;
    }
};

TEST_F(CorpusTest, LoadsSupportedFilesInStableOrder) {
    write("z.txt", "last document");
    write("nested/database-locking.md", "# Database locking\nTransactions use locks.");
    write("ignored.csv", "not indexed");
    const auto documents = search::loadCorpus(directory);
    ASSERT_EQ(documents.size(), 2);
    EXPECT_EQ(documents[0].id, "nested/database-locking.md");
    EXPECT_EQ(documents[0].title, "database locking");
    EXPECT_EQ(documents[0].text, "# Database locking\nTransactions use locks.");
    EXPECT_EQ(documents[1].id, "z.txt");
}

TEST_F(CorpusTest, IgnoresSymbolicLinks) {
    write("original.txt", "one document");
    std::error_code error;
    std::filesystem::create_symlink(directory / "original.txt", directory / "link.txt", error);
    if (error) {
        GTEST_SKIP();
    }
    EXPECT_EQ(search::loadCorpus(directory).size(), 1);
}

TEST_F(CorpusTest, HandlesAnEmptyDirectoryAndRejectsMissingDirectories) {
    EXPECT_TRUE(search::loadCorpus(directory).empty());
    EXPECT_THROW(search::loadCorpus(directory / "missing"), std::runtime_error);
}

TEST_F(CorpusTest, RejectsOversizedAndBinaryFiles) {
    write("large.txt", std::string(1024 * 1024 + 1, 'a'));
    EXPECT_THROW(search::loadCorpus(directory), std::runtime_error);
    std::filesystem::remove(directory / "large.txt");
    write("binary.txt", std::string("abc\0def", 7));
    EXPECT_THROW(search::loadCorpus(directory), std::runtime_error);
}

TEST_F(CorpusTest, AcceptsTheFileSizeLimitAndEmptyFiles) {
    const std::string text(1024 * 1024, 'a');
    write("full.txt", text);
    write("empty.md", "");
    const auto documents = search::loadCorpus(directory);
    ASSERT_EQ(documents.size(), 2);
    EXPECT_TRUE(documents[0].text.empty());
    EXPECT_EQ(documents[1].text, text);
}

TEST_F(CorpusTest, EnforcesTheTotalTextLimit) {
    const std::string text(1024 * 1024, 'a');
    for (int i = 0; i < 64; ++i) {
        write(std::to_string(i) + ".txt", text);
    }
    {
        const auto documents = search::loadCorpus(directory);
        ASSERT_EQ(documents.size(), 64);
        std::size_t bytes = 0;
        for (const auto& document : documents) {
            bytes += document.text.size();
        }
        EXPECT_EQ(bytes, 64 * 1024 * 1024);
    }
    write("overflow.txt", "a");
    EXPECT_THROW(search::loadCorpus(directory), std::runtime_error);
}

TEST_F(CorpusTest, EnforcesTheDocumentCountLimit) {
    for (int i = 0; i < 50000; ++i) {
        write(std::to_string(i) + ".txt", "");
    }
    EXPECT_EQ(search::loadCorpus(directory).size(), 50000);
    write("overflow.md", "");
    EXPECT_THROW(search::loadCorpus(directory), std::runtime_error);
}

TEST_F(CorpusTest, IgnoresDirectoryAndDanglingSymbolicLinks) {
    write("source/kept.txt", "search");
    std::error_code error;
    std::filesystem::create_directory_symlink(directory / "source", directory / "alias", error);
    if (error) {
        GTEST_SKIP() << error.message();
    }
    std::filesystem::create_symlink(directory / "missing.txt", directory / "broken.txt", error);
    ASSERT_FALSE(error) << error.message();
    const auto documents = search::loadCorpus(directory);
    ASSERT_EQ(documents.size(), 1);
    EXPECT_EQ(documents.front().id, "source/kept.txt");
}

TEST_F(CorpusTest, PreservesSpecialFilenamesAndNormalizesTitles) {
    write("nested/a_b-c &+.md", "search");
    const auto documents = search::loadCorpus(directory);
    ASSERT_EQ(documents.size(), 1);
    EXPECT_EQ(documents.front().id, "nested/a_b-c &+.md");
    EXPECT_EQ(documents.front().title, "a b c &+");
}

TEST_F(CorpusTest, RejectsAFileAsTheCorpusDirectory) {
    write("document.txt", "search");
    EXPECT_THROW(search::loadCorpus(directory / "document.txt"), std::runtime_error);
}

TEST_F(CorpusTest, RejectsUnreadableDocuments) {
    write("private.txt", "search");
    const auto path = directory / "private.txt";
    std::filesystem::permissions(path, std::filesystem::perms::none);
    if (std::ifstream(path).is_open()) {
        GTEST_SKIP() << "Current user can read files without permission bits";
    }
    EXPECT_THROW(search::loadCorpus(directory), std::runtime_error);
}
