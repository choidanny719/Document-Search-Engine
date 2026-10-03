# C++ containers

A vector stores elements contiguously and supports fast sequential access. An
unordered map uses hashing to locate values by key. A priority queue keeps its
highest priority element available for removal.

Choose containers based on access patterns and memory costs. Reserving capacity
can reduce vector reallocations. Read-only data can be shared between threads
when no thread modifies it during a query.
