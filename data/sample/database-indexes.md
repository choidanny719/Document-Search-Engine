# Database indexes

A database index helps locate rows without scanning an entire table. B-tree
indexes support equality and range queries. Indexes consume storage and add work
to writes, so index the columns used by frequent queries.

Use an execution plan to check whether a query scans the table or uses an index.
A composite index can support queries that filter on its leading columns.
