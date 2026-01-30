import os
import sys

from py_clob_client.client import ClobClient

from .config import env_int, load_env_file


def get_client(require_auth):
    load_env_file()
    host = os.getenv("POLYMARKET_HOST", "https://clob.polymarket.com")
    chain_id = env_int("POLYMARKET_CHAIN_ID") or 137  # Polygon
    signature_type = env_int("POLYMARKET_SIG_TYPE")
    funder = os.getenv("POLYMARKET_FUNDER")
    expected_signer = os.getenv("POLYMARKET_SIGNER")

    if not require_auth:
        return ClobClient(host)

    key = os.getenv("POLYMARKET_KEY")
    if not key:
        raise RuntimeError("POLYMARKET_KEY environment variable not set.")

    try:
        client = ClobClient(
            host,
            key=key,
            chain_id=chain_id,
            signature_type=signature_type,
            funder=funder,
        )
        client.set_api_creds(client.create_or_derive_api_creds())
        if expected_signer:
            if client.get_address().lower() != expected_signer.lower():
                raise RuntimeError(
                    "POLYMARKET_SIGNER does not match POLYMARKET_KEY-derived address. "
                    f"Expected: {expected_signer}  Got: {client.get_address()}"
                )
        return client
    except Exception as exc:
        raise RuntimeError(f"Error initializing client: {exc}") from exc


def get_client_or_exit(require_auth):
    try:
        return get_client(require_auth)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
