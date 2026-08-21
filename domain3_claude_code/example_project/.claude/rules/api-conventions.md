---
paths: ["src/api/**/*.py"]
---

# API Handler Conventions

Loads only when editing something under `src/api/`.

- Handlers are `async def` and do no I/O directly — they delegate to a service.
- Validate the request body with a Pydantic model at the boundary. Never trust
  the client, and never validate deeper in the stack.
- Errors return the shared envelope:
  `{"error": {"code": "SNAKE_CASE", "message": "...", "retryable": bool}}`
  The `retryable` flag is the client's retry decision — set it deliberately.
- Never leak an internal exception message into a response body.
- Every handler is registered in `src/api/routes.py`; no route decorators inline.
