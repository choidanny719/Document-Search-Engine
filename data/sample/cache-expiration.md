# Cache expiration

A cache stores reusable results to avoid repeated work. Entries expire after a
time to live, or when an application explicitly invalidates them. Cached results
can become stale when the source data changes.

Bound the cache size and choose an eviction policy. Least recently used eviction
removes entries that have not been accessed recently. Cache misses still require
access to the original data source.
