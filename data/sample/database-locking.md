# Database locking

A database uses row level locking to coordinate concurrent updates. A transaction
that reserves inventory locks the product row before checking available stock.
Other transactions updating the same row wait until the lock is released.

Keep transactions short. Acquire multiple locks in a consistent order to reduce
deadlocks. A timeout lets an application retry instead of waiting indefinitely.
