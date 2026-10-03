# Message queues

A message queue separates producers from consumers. A producer publishes work
and a consumer processes it later. Acknowledgments indicate that processing has
finished, while retries handle temporary failures.

A consumer may receive a message more than once. Idempotent processing prevents
duplicate effects. A bounded retry policy can send repeatedly failing messages
to a separate queue for inspection.
