FROM ubuntu:24.04 AS build
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates cmake g++ make && rm -rf /var/lib/apt/lists/*
WORKDIR /source
COPY . .
RUN cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_TESTING=OFF -DBUILD_BENCHMARKS=OFF && cmake --build build -j 2

FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends \
    libstdc++6 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=build /source/build/search_server ./search_server
COPY web ./web
COPY data/sample ./data/sample
USER 10001:10001
EXPOSE 8080
ENTRYPOINT ["/app/search_server"]
CMD ["--host", "0.0.0.0"]
