#include "search/corpus.h"
#include "search/index.h"
#include "search/tokenizer.h"

#include <charconv>
#include <chrono>
#include <fstream>
#include <httplib.h>
#include <iostream>
#include <nlohmann/json.hpp>
#include <stdexcept>

using nlohmann::json;

int parseNumber(std::string_view value, int minimum, int maximum) {
    int number = 0;
    const auto [end, error] = std::from_chars(value.data(), value.data() + value.size(), number);
    if (error != std::errc{} || end != value.data() + value.size() ||
        number < minimum || number > maximum) {
        throw std::invalid_argument("Number must be between " + std::to_string(minimum) +
                                    " and " + std::to_string(maximum));
    }
    return number;
}

void sendJson(httplib::Response& response, const json& body, int status = 200) {
    response.status = status;
    response.set_content(body.dump(-1, ' ', false, json::error_handler_t::replace),
                         "application/json; charset=utf-8");
}

std::string preview(std::string_view text) {
    std::string result;
    for (const unsigned char ch : text) {
        if (result.size() >= 200) {
            result += "...";
            break;
        }
        if (ch == ' ' || ch == '\n' || ch == '\r' || ch == '\t') {
            if (!result.empty() && result.back() != ' ') {
                result += ' ';
            }
        } else {
            result += static_cast<char>(ch);
        }
    }
    return result;
}

void addRoutes(httplib::Server& server, const search::Index& index, const std::string& page) {
    server.Get("/", [page](const auto&, auto& response) {
        response.set_content(page, "text/html; charset=utf-8");
    });

    server.Get("/health", [&index](const auto&, auto& response) {
        sendJson(response, {{"status", "ok"}, {"documents", index.documents().size()},
                            {"terms", index.termCount()}});
    });

    server.Get("/search", [&index](const auto& request, auto& response) {
        const auto query = request.get_param_value("q");
        if (query.size() > 512 || search::tokenize(query).empty()) {
            sendJson(response, {{"error", "q must contain a word and be at most 512 bytes"}}, 400);
            return;
        }

        const auto mode = request.has_param("mode") ? request.get_param_value("mode") : "any";
        if (mode != "any" && mode != "all") {
            sendJson(response, {{"error", "mode must be any or all"}}, 400);
            return;
        }

        int limit = 10;
        try {
            if (request.has_param("limit")) {
                limit = parseNumber(request.get_param_value("limit"), 1, 100);
            }
        } catch (const std::invalid_argument&) {
            sendJson(response, {{"error", "limit must be an integer between 1 and 100"}}, 400);
            return;
        }

        const auto start = std::chrono::steady_clock::now();
        const auto results = index.search(query, limit,
            mode == "all" ? search::MatchMode::All : search::MatchMode::Any);
        const double elapsed = std::chrono::duration<double, std::milli>(
            std::chrono::steady_clock::now() - start).count();

        auto hits = json::array();
        for (const auto& hit : results.hits) {
            const auto& document = index.documents()[hit.document];
            hits.push_back({{"id", document.id}, {"title", document.title},
                            {"score", hit.score}, {"preview", preview(document.text)}});
        }
        sendJson(response, {{"query", query}, {"mode", mode}, {"total", results.total},
                            {"elapsed_ms", elapsed}, {"results", hits}});
    });

    server.Get("/document", [&index](const auto& request, auto& response) {
        const auto* document = index.find(request.get_param_value("id"));
        if (document == nullptr) {
            sendJson(response, {{"error", "Document not found"}}, 404);
            return;
        }
        response.set_content(document->text, "text/plain; charset=utf-8");
    });

    server.set_error_handler([](const auto&, auto& response) {
        if (response.body.empty()) {
            sendJson(response, {{"error", response.status == 404 ? "Route not found" : "Request failed"}},
                     response.status);
        }
    });
    server.set_exception_handler([](const auto&, auto& response, std::exception_ptr) {
        sendJson(response, {{"error", "Internal server error"}}, 500);
    });
}

int main(int argc, char* argv[]) {
    try {
        std::string directory = "data/sample";
        std::string web = "web";
        std::string host = "127.0.0.1";
        int port = 8080;
        for (int i = 1; i < argc; ++i) {
            const std::string option = argv[i];
            if (option == "--help") {
                std::cout << "search_server [--data directory] [--web directory] [--host address] [--port number]\n";
                return 0;
            }
            if (i + 1 == argc) {
                throw std::invalid_argument("Missing value for " + option);
            }
            const std::string value = argv[++i];
            if (option == "--data") directory = value;
            else if (option == "--web") web = value;
            else if (option == "--host") host = value;
            else if (option == "--port") port = parseNumber(value, 0, 65535);
            else throw std::invalid_argument("Unknown option: " + option);
        }

        const search::Index index(search::loadCorpus(directory));
        std::ifstream page_file(std::filesystem::path(web) / "index.html");
        if (!page_file) {
            throw std::runtime_error("Cannot read web/index.html; run from the project root or use --web");
        }
        const std::string page((std::istreambuf_iterator<char>(page_file)), {});

        httplib::Server server;
        server.new_task_queue = [] { return new httplib::ThreadPool(8, 8, 64); };
        server.set_read_timeout(5, 0);
        server.set_write_timeout(5, 0);
        server.set_keep_alive_max_count(20);
        server.set_keep_alive_timeout(2);
        server.set_payload_max_length(1024);
        server.set_default_headers({{"X-Content-Type-Options", "nosniff"},
                                    {"Content-Security-Policy", "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"}});
        addRoutes(server, index, page);

        if (port == 0) port = server.bind_to_any_port(host);
        else if (!server.bind_to_port(host, port)) port = -1;
        if (port < 0) {
            throw std::runtime_error("Could not bind the server port");
        }
        std::cout << "Listening on http://" << host << ':' << port << " ("
                  << index.documents().size() << " documents)" << std::endl;
        return server.listen_after_bind() ? 0 : 1;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
