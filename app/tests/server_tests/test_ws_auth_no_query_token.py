from server.api.ws_auth import _extract_token


def test_ws_auth_ignores_query_token() -> None:
    scope = {"query_string": b"token=secret", "headers": []}
    assert _extract_token(scope) is None
