from server.api.ws_auth import _extract_token


def test_ws_auth_extracts_token_from_subprotocol_header() -> None:
    scope = {
        "headers": [
            (b"sec-websocket-protocol", b"chat, bearer.abc.def.ghi"),
        ]
    }
    assert _extract_token(scope) == "abc.def.ghi"


def test_ws_auth_authorization_header_takes_precedence() -> None:
    scope = {
        "headers": [
            (b"authorization", b"Bearer auth.token.value"),
            (b"sec-websocket-protocol", b"bearer.proto.token"),
        ]
    }
    assert _extract_token(scope) == "auth.token.value"
