# Deferred items — quick 261110-cuk

- **Raw JSON `NaN` in a request body gives a 500, not a 422 (pre-existing, every JSON endpoint).**
  FastAPI's default `RequestValidationError` handler echoes the rejected input; a body such as
  `{"lat": NaN}` (Python's json accepts the literal) is refused by pydantic (`allow_inf_nan=False`)
  but the 422 response then fails to serialize (`ValueError: Out of range float values are not
  JSON compliant`). The existing tests (test_manual_wind.py) send `"NaN"` as a string, which is
  handled. Found while writing tests/web/test_start_api.py; out of scope (core/hardening.py /
  app-wide exception handler). Fix idea: a `RequestValidationError` handler in create_app that
  builds the body with `include_input=False`.
