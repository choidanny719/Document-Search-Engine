#include "search/tokenizer.h"

namespace search {

std::vector<std::string> tokenize(std::string_view text) {
    std::vector<std::string> words;
    std::string word;

    for (unsigned char ch : text) {
        if (ch >= 'A' && ch <= 'Z') {
            word += static_cast<char>(ch - 'A' + 'a');
        } else if ((ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9')) {
            word += static_cast<char>(ch);
        } else if (!word.empty()) {
            words.push_back(std::move(word));
            word.clear();
        }
    }

    if (!word.empty()) {
        words.push_back(std::move(word));
    }
    return words;
}

}
