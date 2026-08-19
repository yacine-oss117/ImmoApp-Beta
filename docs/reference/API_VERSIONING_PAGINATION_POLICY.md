# API Versioning And Pagination Policy

## Versioning

- stable API routes live under `/api/v1/`
- `server/immoapp_server/urls.py` must keep
  `path("api/v1/", include("server.api.urls"))`
- breaking surface changes require a new major path, not silent mutation of
  `/api/v1/`
- auth transport endpoints under `/api/auth/*` are governed separately

## List contract

Collection endpoints must return:

- `items`
- `total`

Cursor-style endpoints may also return:

- `next_cursor`

Delta/sync endpoints may return:

- `next_since`
- `next_after_id`

## Request parameters

- offset style: `limit`, `offset`
- cursor style: `cursor`, `limit`
- delta style: `since`, `after_id`, `limit`

## Error contract

- user-facing responses must not leak raw exception internals
- standard error payload shape is:
  - `detail`
  - `code`
  - optional `errors`

Enforced by:

- `server/api/exception_handler.py`
- `scripts/verify_no_exception_leakage.py`

## Enforcement

- `scripts/verify_api_contract_policies.py`
- `app/tests/server_tests/test_openapi_schema_runtime.py`
- `app/tests/server_tests/test_api_route_security_contract.py`
