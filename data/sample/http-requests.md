# HTTP requests

An HTTP client sends a method, a path, headers, and sometimes a request body.
A server returns a status code, headers, and a response body. JSON is a common
format for API responses.

Validate query parameters before processing a request. Set timeouts and limit
request sizes. Return a clear client error for invalid input and avoid exposing
internal file paths in error responses.
