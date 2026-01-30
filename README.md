# Polymarket Trader CLI

A command-line tool for Polymarket CLOB trading: browse markets, inspect orderbooks, place/cancel orders, and run diagnostics. Built on `py-clob-client`.

Note: this repo contains the CLI/tooling only. Any AI skill definitions live in a separate repo.

## Install

Recommended (uv):
```
uv tool install polymarket-trader
```

Also supported:
```
pipx install polymarket-trader
# or
pip install polymarket-trader
```

## Quick Start (Polymarket UI / Proxy Wallet)

Most Polymarket accounts use a proxy (Safe) wallet that holds funds, while your MetaMask EOA signs orders. The UI shows the proxy address.

Create `~/.polymarket.env`:

```
POLYMARKET_KEY=<your MetaMask private key>
POLYMARKET_SIG_TYPE=2
POLYMARKET_FUNDER=<proxy wallet address shown on Polymarket>
POLYMARKET_SIGNER=<your MetaMask EOA address>
POLYMARKET_RPC=https://polygon-rpc.com
```

Verify:

```
polymarket-trader whoami
polymarket-trader balance --asset-type collateral
```

If allowances are all zero, open Polymarket, click Buy on any market, and approve USDC (Enable trading).

## Commands (examples)

List markets:
```
polymarket-trader markets --sampling --accepting-only --limit 50
```

Include titles:
```
polymarket-trader markets --sampling --with-title --limit 20
```

Orderbook / quote:
```
polymarket-trader orderbook <token_id>
polymarket-trader quote <token_id>
```

Buy with USD cap (best ask by default):
```
polymarket-trader buy-max <token_id> 5
```

Diagnostics:
```
polymarket-trader diagnose --onchain --fix
```

Full command list:
```
polymarket-trader --help
```

## Environment variables

- `POLYMARKET_KEY`: signer private key (required for trading)
- `POLYMARKET_SIG_TYPE`: 0=EOA, 1=POLY_PROXY, 2=POLY_GNOSIS_SAFE
- `POLYMARKET_FUNDER`: proxy wallet address that holds collateral
- `POLYMARKET_SIGNER`: expected EOA address for safety checks
- `POLYMARKET_ENV_FILE`: override env file path (default `~/.polymarket.env`)
- `POLYMARKET_HOST`: CLOB API host (default `https://clob.polymarket.com`)
- `POLYMARKET_CHAIN_ID`: chain id (default `137` for Polygon)
- `POLYMARKET_RPC`: RPC URL (used for onchain allowance/receipt checks)

## Using from source (no install)

```
uv run --with py-clob-client -m polymarket_trader whoami
uv run --with py-clob-client -m polymarket_trader balance --asset-type collateral
```

## Publishing

Local build + publish:
```
uv build
uv publish
```

CI (Trusted Publishing):
1) Create a GitHub environment named `pypi` (matches the workflow).
2) Configure a PyPI Trusted Publisher pointing to `.github/workflows/publish.yml` and the `pypi` environment.
3) Create and push a version tag like `v0.2.0`.
4) GitHub Actions will build and publish the package automatically.

## Safety

- Never paste private keys into chat or commit them to git.
- `~/.polymarket.env` is loaded automatically and should be kept local.

## License

MIT (see LICENSE).
