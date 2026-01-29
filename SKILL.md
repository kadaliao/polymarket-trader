---
name: polymarket-trader
description: Manage Polymarket trades. Use this skill to view markets, place buy/sell orders, and cancel orders on Polymarket via the py-clob-client using uv for dependency management.
---

# Polymarket Trader

## Overview

This skill allows you to interact with the Polymarket exchange to view market data and execute trades. It uses a Python script wrapper around the `py-clob-client` library, executed via `uv run` to manage dependencies.

## Quick Start (Proxy Wallet / Polymarket UI)

Most Polymarket accounts use a proxy (Safe) wallet that **holds funds**, while your MetaMask EOA **signs** orders. The UI shows the proxy wallet address.

1) Put these values into `~/.polymarket.env` (the wrapper auto-loads this file):
```bash
POLYMARKET_KEY=<your MetaMask private key>
POLYMARKET_SIG_TYPE=2
POLYMARKET_FUNDER=<proxy wallet address shown on Polymarket>
POLYMARKET_SIGNER=<your MetaMask EOA address>
```

2) Verify:
```bash
uv run --with py-clob-client scripts/poly_wrapper.py whoami
uv run --with py-clob-client scripts/poly_wrapper.py balance --asset-type collateral
```
Expected: `whoami.funder` matches the proxy address, and `balance` is non-zero.

3) If `allowances` are all zero, you must approve USDC on the Polymarket UI (Enable trading).

## Prerequisites

1.  **uv**: Ensure `uv` is installed on your system.
2.  **Authentication**: You must set your Polymarket private key as an environment variable for trading or canceling orders. Market and orderbook reads do not require a key.
    ```bash
    export POLYMARKET_KEY="<your_private_key_here>"
    ```
    If the environment is not picking up your exports, create `~/.polymarket.env`:
    ```bash
    POLYMARKET_KEY=<your_private_key_here>
    POLYMARKET_SIG_TYPE=2
    POLYMARKET_FUNDER=0x79F743CC78BcD13fC600e1e50C62957D4853C48C
    POLYMARKET_SIGNER=0x<your_eoa_signer_address>
    POLYMARKET_RPC=https://polygon-rpc.com
    ```
    The wrapper will auto-load this file if present.
    Optional (proxy wallet / advanced):
    ```bash
    # Signature type: 0=EOA, 1=POLY_PROXY, 2=POLY_GNOSIS_SAFE
    export POLYMARKET_SIG_TYPE="1"
    # Funder/proxy address that actually holds collateral
    export POLYMARKET_FUNDER="0x..."
    ```
    *Note: Never share your private key in the chat.*

## Commands

All commands are executed using `uv run --with py-clob-client` to ensure the required library is available without manual installation.

### 1. View Markets
List simplified market information or get details for a specific market.

- **List markets**:
  ```bash
  uv run --with py-clob-client scripts/poly_wrapper.py markets
  ```
- **Sampling markets (smaller, fresher set)**:
  ```bash
  uv run --with py-clob-client scripts/poly_wrapper.py markets --sampling
  ```
- **Only markets accepting orders**:
  ```bash
  uv run --with py-clob-client scripts/poly_wrapper.py markets --sampling --accepting-only --limit 50
  ```
- **Include market titles (extra API calls)**:
  ```bash
  uv run --with py-clob-client scripts/poly_wrapper.py markets --sampling --with-title --limit 20
  ```
- **Paginate + filter by title (local filter)**:
  ```bash
  uv run --with py-clob-client scripts/poly_wrapper.py markets --sampling --max-pages 5 --title-like btc --limit 50
  ```
- **Title filters default to Gamma for speed** (use `--title-source clob` to force CLOB):
  ```bash
  uv run --with py-clob-client scripts/poly_wrapper.py markets --title-any "btc,bitcoin" --title-source gamma --limit 20
  ```
- **Reduce output fields**:
  ```bash
  uv run --with py-clob-client scripts/poly_wrapper.py markets --sampling --fields condition_id,token_id,title --compact
  ```
- **AI-friendly output**:
  ```bash
  uv run --with py-clob-client scripts/poly_wrapper.py markets --sampling --ai
  ```
- **Get specific market details**:
  ```bash
  uv run --with py-clob-client scripts/poly_wrapper.py markets --id <condition_id_or_token_id>
  ```

### 2. View Orderbook
View the current bids and asks for a specific token.

```bash
uv run --with py-clob-client scripts/poly_wrapper.py orderbook <token_id>
```

### 3. Quote (Best Bid/Ask)
Get best bid/ask and minimum order size for a token.

```bash
uv run --with py-clob-client scripts/poly_wrapper.py quote <token_id>
```

### 4. Identity / Wallet Info
Show signer address, funder, signature type, and contract addresses.

```bash
uv run --with py-clob-client scripts/poly_wrapper.py whoami
```

### 4b. Diagnose
Run a full diagnostic including whoami + balance/allowance. Use `--onchain` to compare with onchain USDC allowances.

```bash
uv run --with py-clob-client scripts/poly_wrapper.py diagnose
uv run --with py-clob-client scripts/poly_wrapper.py diagnose --onchain
uv run --with py-clob-client scripts/poly_wrapper.py diagnose --onchain --fix
```
`--fix` adds action-oriented recommendations and next-step commands.

### 5. Place Orders
Place LIMIT orders to buy or sell outcome tokens.

- **Buy**:
  ```bash
  uv run --with py-clob-client scripts/poly_wrapper.py buy <token_id> <size> <price>
  ```
  Example: `uv run --with py-clob-client scripts/poly_wrapper.py buy 0x123... 100 0.55` (Buy 100 shares at $0.55)

- **Sell**:
  ```bash
  uv run --with py-clob-client scripts/poly_wrapper.py sell <token_id> <size> <price>
  ```

- **Buy with a max USD cap (uses best ask by default)**:
  ```bash
  uv run --with py-clob-client scripts/poly_wrapper.py buy-max <token_id> <max_usd>
  ```
  Optional limit price:
  ```bash
  uv run --with py-clob-client scripts/poly_wrapper.py buy-max <token_id> <max_usd> --price <price>
  ```

### 6. Cancel Orders
Cancel existing orders.

- **Cancel a specific order**:
  ```bash
  uv run --with py-clob-client scripts/poly_wrapper.py cancel --order-id <order_id>
  ```
- **Cancel ALL open orders**:
  ```bash
  uv run --with py-clob-client scripts/poly_wrapper.py cancel --all
  ```

### 6b. Order Status (Match vs Settlement)
Check an order and any associated trades (lightweight).

```bash
uv run --with py-clob-client scripts/poly_wrapper.py order-status --order-id <order_id>
```
`order-status` output includes a lightweight `summary.settlement` field.

### 6c. Order Diagnose (Advanced)
Includes optional onchain receipt checks and a watch mode.

Watch until settlement completes (polls and exits when status is no longer pending):
```bash
uv run --with py-clob-client scripts/poly_wrapper.py order-diagnose --order-id <order_id> --watch
```
Include onchain receipt (requires `POLYMARKET_RPC`):
```bash
uv run --with py-clob-client scripts/poly_wrapper.py order-diagnose --order-id <order_id> --with-receipt
```
`order-diagnose` output includes a `summary.settlement` field (`pending`, `settled`, `reverted`, `failed`, `matched`, `unknown`).

## Troubleshooting

- **Authentication Errors**: Ensure `POLYMARKET_KEY` is set correctly in the environment.
- **Dependency Issues**: `uv run --with py-clob-client` handles dependencies automatically. Ensure you have internet access for the first run.
- **Minimum notional**: Marketable BUY orders require at least ~$1 notional. Use `buy-max` with `max_usd >= 1` or place a non-marketable limit price below best ask.
- **Balance/allowance**: Trading requires USDC balance and allowance. Check with:
  ```bash
  uv run --with py-clob-client scripts/poly_wrapper.py balance --asset-type collateral
  ```
  If you recently funded or approved, refresh API cache:
  ```bash
  uv run --with py-clob-client scripts/poly_wrapper.py refresh-balance --asset-type collateral
  ```
  If your Polymarket account uses a proxy wallet (site shows a different trading address), set `POLYMARKET_SIG_TYPE` and `POLYMARKET_FUNDER` to match the proxy wallet.

## Gamma API (Discovery/Search)

These endpoints are better for finding markets by text than CLOB simplified markets. You can also override the host:
```bash
export POLYMARKET_GAMMA_HOST="https://gamma-api.polymarket.com"
```

- **Generic Gamma request**:
  ```bash
  uv run --with py-clob-client scripts/poly_wrapper.py gamma /events --param limit=50 --param offset=0 --q "bitcoin"
  ```
- **Events (convenience)**:
  ```bash
  uv run --with py-clob-client scripts/poly_wrapper.py gamma-events --q "btc" --limit 50
  ```
- **Markets (convenience)**:
  ```bash
  uv run --with py-clob-client scripts/poly_wrapper.py gamma-markets --q "eth" --limit 50
  ```
- **Public search (convenience)**:
  ```bash
  uv run --with py-clob-client scripts/poly_wrapper.py gamma-search --q "fomc" --limit 50
  ```
- **Local filter + field trimming**:
  ```bash
  uv run --with py-clob-client scripts/poly_wrapper.py gamma-events --q "election" --title-like "2028" --fields id,title --compact
  ```
- **Auto pagination + AI-friendly output**:
  ```bash
  uv run --with py-clob-client scripts/poly_wrapper.py gamma-events --q "btc" --max-pages 5 --max-results 200 --ai
  ```
- **Open/active only + ending soon**:
  ```bash
  uv run --with py-clob-client scripts/poly_wrapper.py gamma-markets --q "btc" --open-only --active-only --end-within-hours 24 --ai
  ```
- **Try multiple query param names**:
  ```bash
  uv run --with py-clob-client scripts/poly_wrapper.py gamma-search --q "fomc" --q-try "search,query,q" --limit 50
  ```

## Troubleshooting Checklist

1) **Signer mismatch**  
   - `whoami.address` must equal your MetaMask EOA address.  
   - If not, update `POLYMARKET_KEY` or set `POLYMARKET_SIGNER` to force validation.

2) **Proxy wallet mismatch**  
   - `whoami.funder` must equal the Polymarket UI “account/proxy” address.  
   - If not, set `POLYMARKET_FUNDER` to the UI address and `POLYMARKET_SIG_TYPE=2`.

3) **Balance is correct but allowance is 0**  
   - You must approve USDC to the CLOB Exchange contract via the Polymarket UI.  
   - After approval, run `refresh-balance` and re-check.

4) **Order still fails after balance/allowance OK**  
   - Check `quote` and ensure `min_order_size` and the $1 minimum notional for marketable buys.
   - Use `buy-max <token> 1` or set a non‑marketable limit price.

5) **Still stuck**  
   - Run `diagnose --onchain` and paste outputs (no private keys) to diagnose.
