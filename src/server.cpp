#include "http.h"
#include "search/corpus.h"

#include <fstream>
#include <httplib.h>
#include <iostream>
#include <stdexcept>

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
            else if (option == "--port") port = search::http::parseNumber(value, 0, 65535);
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
        search::http::addRoutes(server, index, page);

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
