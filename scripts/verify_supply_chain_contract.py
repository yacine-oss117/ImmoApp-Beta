from __future__ import annotations

from pathlib import Path


def _require(path: str) -> Path:
    p = Path(path)
    if not p.exists():
        raise AssertionError(f"Missing required supply-chain file: {path}")
    return p


def _assert_tokens(path: Path, tokens: tuple[str, ...]) -> None:
    text = path.read_text(encoding="utf-8")
    for token in tokens:
        if token not in text:
            raise AssertionError(f"{path}: missing token {token!r}")


def main() -> None:
    sbom = _require("scripts/generate_sbom.ps1")
    sign = _require("scripts/sign_images.ps1")
    verify = _require("scripts/verify_signed_images.ps1")

    _assert_tokens(
        sbom,
        (
            "pip freeze",
            "cyclonedx_py requirements",
            "cyclonedx.json",
        ),
    )
    _assert_tokens(
        sign,
        (
            "cosign sign",
            "IMMOAPP_SIGN_IMAGES",
            "image_signatures.json",
        ),
    )
    _assert_tokens(
        verify,
        (
            "IMMOAPP_SUPPLYCHAIN_ENFORCE_SIGNED_IMAGES",
            "cosign verify",
            "FailOnUnsignedTest",
        ),
    )
    print("verify_supply_chain_contract: OK")


if __name__ == "__main__":
    main()
