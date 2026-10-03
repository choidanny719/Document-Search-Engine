cmake_minimum_required(VERSION 3.24)
project(document_search VERSION 1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

include(FetchContent)
include(CTest)

add_library(search_core src/tokenizer.cpp src/index.cpp src/corpus.cpp)
target_include_directories(search_core PUBLIC include)
if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(search_core PRIVATE -Wall -Wextra -Wpedantic)
endif()

if(BUILD_TESTING)
    FetchContent_Declare(googletest
        URL https://codeload.github.com/google/googletest/tar.gz/refs/tags/v1.18.0
        URL_HASH SHA256=6e3191c1455468b3fc35a417fb565c1c5071aee1b7e7f85e30cf48a98d37d8b5
        DOWNLOAD_EXTRACT_TIMESTAMP TRUE)
    set(gtest_force_shared_crt ON CACHE BOOL "" FORCE)
    FetchContent_MakeAvailable(googletest)
    add_executable(search_tests tests/tokenizer_test.cpp tests/index_test.cpp tests/corpus_test.cpp)
    target_link_libraries(search_tests PRIVATE search_core GTest::gtest_main)
    include(GoogleTest)
    gtest_discover_tests(search_tests)
endif()
