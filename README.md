# Polymarket Trader (AI Skill)

A lightweight AI skill and CLI wrapper for Polymarket CLOB: browse markets, inspect orderbooks, place/cancel orders, and run diagnostics. Built on `py-clob-client`. Works with any AI agent that can read `SKILL.md` (Codex-compatible) or use the CLI directly.

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

## Features

- Read-only market data: list markets, orderbooks, quotes
- Trading: buy/sell, cancel orders, buy with a USD cap
- Proxy wallet support (Safe): signer vs funder handling
- Diagnostics: balance/allowance + optional onchain allowance check
- Environment file auto-load: `~/.polymarket.env`

## Quick Start (Polymarket UI / Proxy Wallet)

Most Polymarket accounts use a proxy wallet (Safe) that holds funds, while your MetaMask EOA signs orders. The UI shows the proxy address.

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

## Using from source (no install)

```
uv run --with py-clob-client scripts/poly_wrapper.py whoami
uv run --with py-clob-client scripts/poly_wrapper.py balance --asset-type collateral
```

For the full command list, see `SKILL.md`.

## Safety

- Never paste private keys into chat or commit them to git.
- `~/.polymarket.env` is loaded automatically and should be kept local.

## Publishing

Build a wheel/sdist:
```
uv run --with build -m build
```

## License

MIT (add a LICENSE file if you want this explicit).
