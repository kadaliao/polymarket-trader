#!/usr/bin/env python3
import os
import sys
import json
import argparse
import urllib.request
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import (
    AssetType,
    BalanceAllowanceParams,
    OrderArgs,
    OrderType,
)
from py_clob_client.order_builder.constants import BUY, SELL

def _load_env_file():
    path = os.getenv("POLYMARKET_ENV_FILE")
    if not path:
        path = os.path.expanduser("~/.polymarket.env")
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[len("export ") :].strip()
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip("\"'").strip()
                if key and value:
                    # Allow file to override existing env values for automation
                    os.environ[key] = value
    except Exception:
        # Silent failure to avoid leaking secrets in error output
        pass


def _env_int(name):
    val = os.getenv(name)
    if val is None or val == "":
        return None
    try:
        return int(val)
    except ValueError:
        raise ValueError(f"{name} must be an integer")


def get_client(require_auth):
    _load_env_file()
    host = os.getenv("POLYMARKET_HOST", "https://clob.polymarket.com")
    chain_id = _env_int("POLYMARKET_CHAIN_ID") or 137  # Polygon
    signature_type = _env_int("POLYMARKET_SIG_TYPE")
    funder = os.getenv("POLYMARKET_FUNDER")
    expected_signer = os.getenv("POLYMARKET_SIGNER")

    if not require_auth:
        return ClobClient(host)

    key = os.getenv("POLYMARKET_KEY")
    if not key:
        print("Error: POLYMARKET_KEY environment variable not set.", file=sys.stderr)
        sys.exit(1)

    # Simple initialization for EOA (External Owned Account)
    # For more complex setups (Agent wallets), this might need adjustment.
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
                print(
                    "Error: POLYMARKET_SIGNER does not match POLYMARKET_KEY-derived address.",
                    file=sys.stderr,
                )
                print(
                    f"Expected: {expected_signer}  Got: {client.get_address()}",
                    file=sys.stderr,
                )
                sys.exit(1)
        return client
    except Exception as e:
        print(f"Error initializing client: {e}", file=sys.stderr)
        sys.exit(1)

def _best_order(orders, best_fn):
    if not orders:
        return None
    return best_fn(orders, key=lambda x: float(x.price))


def _best_bid_ask(book):
    best_bid = _best_order(book.bids, max)
    best_ask = _best_order(book.asks, min)
    return best_bid, best_ask


def _get_balance_allowance(client, token_id=None):
    params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
    if token_id:
        params.token_id = token_id
    return client.get_balance_allowance(params)


def _max_allowance(allowances):
    if not allowances:
        return 0.0
    return max(float(v) for v in allowances.values())


def _rpc_allowance(rpc_url, owner, spender, token):
    selector = "0xdd62ed3e"  # allowance(address,address)

    def _pad(addr):
        return addr.lower().replace("0x", "").rjust(64, "0")

    call_data = selector + _pad(owner) + _pad(spender)
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_call",
        "params": [{"to": token, "data": call_data}, "latest"],
    }
    req = urllib.request.Request(
        rpc_url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    if "result" not in data:
        raise ValueError(f"rpc error: {data}")
    return int(data["result"], 16)

def _to_json_payload(obj):
    if hasattr(obj, "json"):
        try:
            return json.loads(obj.json)
        except Exception:
            return obj.json
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    return obj


def cmd_markets(args):
    client = get_client(require_auth=False)
    try:
        # Simplification: Fetch specific market if ID provided, or search/list top
        if args.id:
            market = client.get_market(args.id)
            print(json.dumps(market, indent=2))
        else:
            # Listing all markets can be huge. Just returning a message or implementing search if library supports it.
            # The library has get_markets() but it might return a lot.
            # Let's try to get simplified markets or sampling.
            # For now, let's just support getting by ID or next_cursor pagination if supported.
            # The library doc says get_simplified_markets()
            if args.with_title and args.limit is None:
                args.limit = 20
            if args.sampling:
                resp = client.get_sampling_simplified_markets(
                    next_cursor=args.cursor or "MA=="
                )
            else:
                if args.cursor:
                    resp = client.get_simplified_markets(next_cursor=args.cursor)
                else:
                    resp = client.get_simplified_markets()
            if args.accepting_only:
                resp["data"] = [
                    m
                    for m in resp.get("data", [])
                    if m.get("accepting_orders")
                ]
            if args.limit:
                resp["data"] = resp.get("data", [])[: args.limit]
            if args.with_title:
                for m in resp.get("data", []):
                    condition_id = m.get("condition_id")
                    if not condition_id:
                        continue
                    try:
                        detail = client.get_market(condition_id)
                        m["title"] = (
                            detail.get("question")
                            or detail.get("name")
                            or detail.get("title")
                        )
                    except Exception:
                        m["title"] = None
            print(json.dumps(resp, indent=2))
    except Exception as e:
        print(f"Error fetching markets: {e}", file=sys.stderr)

def cmd_orderbook(args):
    client = get_client(require_auth=False)
    try:
        book = client.get_order_book(args.token_id)
        payload = _to_json_payload(book)
        if isinstance(payload, str):
            print(payload)
        else:
            print(json.dumps(payload, indent=2))
    except Exception as e:
        print(f"Error fetching orderbook: {e}", file=sys.stderr)

def cmd_buy(args):
    client = get_client(require_auth=True)
    try:
        price = float(args.price)
        size = float(args.size)
        notional = price * size

        try:
            bal = _get_balance_allowance(client)
            balance = float(bal.get("balance", 0))
            max_allow = _max_allowance(bal.get("allowances"))
            if balance <= 0 or max_allow <= 0:
                raise ValueError(
                    "insufficient balance/allowance (balance or allowance is 0)"
                )
        except Exception as e:
            print(
                f"Warning: could not preflight balance/allowance: {e}",
                file=sys.stderr,
            )
        
        order_args = OrderArgs(
            price=price,
            size=size,
            side=BUY,
            token_id=args.token_id,
        )
        signed_order = client.create_order(order_args)
        resp = client.post_order(signed_order, OrderType.GTC)
        print(json.dumps(resp, indent=2))
    except Exception as e:
        print(f"Error placing buy order: {e}", file=sys.stderr)

def cmd_sell(args):
    client = get_client(require_auth=True)
    try:
        price = float(args.price)
        size = float(args.size)
        
        order_args = OrderArgs(
            price=price,
            size=size,
            side=SELL,
            token_id=args.token_id,
        )
        signed_order = client.create_order(order_args)
        resp = client.post_order(signed_order, OrderType.GTC)
        print(json.dumps(resp, indent=2))
    except Exception as e:
        print(f"Error placing sell order: {e}", file=sys.stderr)

def cmd_cancel(args):
    client = get_client(require_auth=True)
    try:
        if args.all and args.order_id:
            print("Error: use either --all or --order-id, not both.", file=sys.stderr)
            sys.exit(1)
        if not args.all and not args.order_id:
            print("Error: provide --order-id or use --all.", file=sys.stderr)
            sys.exit(1)
        if args.all:
            resp = client.cancel_all()
        else:
            resp = client.cancel(args.order_id)
        print(json.dumps(resp, indent=2))
    except Exception as e:
        print(f"Error canceling order: {e}", file=sys.stderr)


def cmd_quote(args):
    client = get_client(require_auth=False)
    try:
        book = client.get_order_book(args.token_id)
        best_bid, best_ask = _best_bid_ask(book)
        payload = {
            "token_id": args.token_id,
            "best_bid": {
                "price": float(best_bid.price),
                "size": float(best_bid.size),
            }
            if best_bid
            else None,
            "best_ask": {
                "price": float(best_ask.price),
                "size": float(best_ask.size),
            }
            if best_ask
            else None,
            "min_order_size": float(book.min_order_size or 0),
            "tick_size": book.tick_size,
            "last_trade_price": book.last_trade_price,
        }
        print(json.dumps(payload, indent=2))
    except Exception as e:
        print(f"Error fetching quote: {e}", file=sys.stderr)


def cmd_buy_max(args):
    client = get_client(require_auth=True)
    try:
        book = client.get_order_book(args.token_id)
        best_bid, best_ask = _best_bid_ask(book)
        price = float(args.price) if args.price else None
        if price is None:
            if not best_ask:
                raise ValueError("No asks available for this token.")
            price = float(best_ask.price)

        cap = float(args.max_usd)
        if cap <= 0:
            raise ValueError("max_usd must be > 0.")

        min_size = float(book.min_order_size or 0)
        size = cap / price
        if min_size > 0 and size < min_size:
            min_cost = min_size * price
            if min_cost <= cap:
                size = min_size
            else:
                raise ValueError(
                    f"max_usd too low for min order size. "
                    f"min_cost=${min_cost:.4f} at price {price}."
                )

        # Marketable buy orders appear to require $1+ notional.
        is_marketable = bool(best_ask) and price >= float(best_ask.price)
        notional = price * size
        if is_marketable and notional < 1:
            raise ValueError(
                f"Marketable buy notional (${notional:.4f}) below $1 minimum."
            )

        try:
            bal = _get_balance_allowance(client)
            balance = float(bal.get("balance", 0))
            max_allow = _max_allowance(bal.get("allowances"))
            if balance <= 0 or max_allow <= 0:
                raise ValueError(
                    "insufficient balance/allowance (balance or allowance is 0)"
                )
        except Exception as e:
            print(
                f"Warning: could not preflight balance/allowance: {e}",
                file=sys.stderr,
            )

        size = round(size, 6)
        order_args = OrderArgs(
            price=price,
            size=size,
            side=BUY,
            token_id=args.token_id,
        )
        signed_order = client.create_order(order_args)
        resp = client.post_order(signed_order, OrderType.GTC)
        print(json.dumps(resp, indent=2))
    except Exception as e:
        print(f"Error placing buy-max order: {e}", file=sys.stderr)


def cmd_balance(args):
    client = get_client(require_auth=True)
    try:
        params = BalanceAllowanceParams()
        if args.asset_type:
            if args.asset_type.lower() == "collateral":
                params.asset_type = AssetType.COLLATERAL
            elif args.asset_type.lower() == "conditional":
                params.asset_type = AssetType.CONDITIONAL
            else:
                raise ValueError("asset_type must be collateral or conditional")
        if args.token_id:
            params.token_id = args.token_id
        if args.signature_type is not None:
            params.signature_type = args.signature_type
        resp = client.get_balance_allowance(params)
        print(json.dumps(resp, indent=2))
    except Exception as e:
        print(f"Error fetching balance/allowance: {e}", file=sys.stderr)


def cmd_refresh_balance(args):
    client = get_client(require_auth=True)
    try:
        params = BalanceAllowanceParams()
        if args.asset_type:
            if args.asset_type.lower() == "collateral":
                params.asset_type = AssetType.COLLATERAL
            elif args.asset_type.lower() == "conditional":
                params.asset_type = AssetType.CONDITIONAL
            else:
                raise ValueError("asset_type must be collateral or conditional")
        if args.token_id:
            params.token_id = args.token_id
        if args.signature_type is not None:
            params.signature_type = args.signature_type
        resp = client.update_balance_allowance(params)
        print(json.dumps(resp, indent=2))
    except Exception as e:
        print(f"Error refreshing balance/allowance: {e}", file=sys.stderr)


def cmd_whoami(args):
    client = get_client(require_auth=True)
    try:
        payload = {
            "address": client.get_address(),
            "funder": client.builder.funder if client.builder else None,
            "signature_type": client.builder.sig_type if client.builder else None,
            "host": client.host,
            "chain_id": client.chain_id,
            "collateral": client.get_collateral_address(),
            "exchange": client.get_exchange_address(),
        }
        print(json.dumps(payload, indent=2))
    except Exception as e:
        print(f"Error fetching identity: {e}", file=sys.stderr)


def cmd_diagnose(args):
    client = get_client(require_auth=True)
    try:
        who = {
            "address": client.get_address(),
            "funder": client.builder.funder if client.builder else None,
            "signature_type": client.builder.sig_type if client.builder else None,
            "host": client.host,
            "chain_id": client.chain_id,
            "collateral": client.get_collateral_address(),
            "exchange": client.get_exchange_address(),
        }
        if args.fix:
            try:
                client.update_balance_allowance(BalanceAllowanceParams())
            except Exception:
                pass
        bal = _get_balance_allowance(client)
        diag = {"whoami": who, "balance_allowance": bal}

        if args.onchain:
            rpc_url = os.getenv("POLYMARKET_RPC", "https://polygon-rpc.com")
            owner = who["funder"] or who["address"]
            token = who["collateral"]
            spenders = list((bal.get("allowances") or {}).keys()) or [who["exchange"]]
            onchain = {}
            for spender in spenders:
                try:
                    onchain[spender] = _rpc_allowance(rpc_url, owner, spender, token)
                except Exception as e:
                    onchain[spender] = f"error: {e}"
            diag["onchain_allowances"] = onchain

        if args.fix:
            recs = []
            steps = []
            balance = float(bal.get("balance", 0) or 0)
            max_allow = _max_allowance(bal.get("allowances"))
            if balance <= 0:
                recs.append(
                    "Fund the proxy wallet (funder) with USDC on Polygon."
                )
                steps.append("Fund USDC to the proxy wallet address shown in whoami.funder.")
            if max_allow <= 0:
                recs.append(
                    f"Approve USDC to CLOB Exchange in UI (spender {who['exchange']})."
                )
                steps.append(
                    f"Open Polymarket, click Buy, approve USDC (spender {who['exchange']})."
                )
            if args.onchain and "onchain_allowances" in diag:
                on_vals = [
                    v for v in diag["onchain_allowances"].values() if isinstance(v, int)
                ]
                if on_vals and max_allow <= 0 and max(on_vals) > 0:
                    recs.append("Onchain allowance exists but API shows 0: run refresh-balance.")
                    steps.append(
                        "Run: uv run --with py-clob-client scripts/poly_wrapper.py refresh-balance --asset-type collateral"
                    )
            diag["recommendations"] = recs
            diag["next_steps"] = steps

        print(json.dumps(diag, indent=2))
    except Exception as e:
        print(f"Error running diagnose: {e}", file=sys.stderr)

def main():
    parser = argparse.ArgumentParser(description="Polymarket CLI Wrapper")
    subparsers = parser.add_subparsers(dest="command")

    # Markets
    p_markets = subparsers.add_parser("markets")
    p_markets.add_argument("--id", help="Market/Token ID")
    p_markets.add_argument("--cursor", help="Pagination cursor")
    p_markets.add_argument(
        "--sampling",
        action="store_true",
        help="Use sampling simplified markets endpoint",
    )
    p_markets.add_argument(
        "--accepting-only",
        action="store_true",
        help="Only include markets accepting orders",
    )
    p_markets.add_argument(
        "--limit",
        type=int,
        help="Limit number of returned markets",
    )
    p_markets.add_argument(
        "--with-title",
        action="store_true",
        help="Fetch market details to include title (uses condition_id)",
    )

    # Orderbook
    p_ob = subparsers.add_parser("orderbook")
    p_ob.add_argument("token_id", help="Token ID")

    # Buy
    p_buy = subparsers.add_parser("buy")
    p_buy.add_argument("token_id", help="Token ID")
    p_buy.add_argument("size", help="Size/Amount")
    p_buy.add_argument("price", help="Price (0.0 - 1.0)")

    # Sell
    p_sell = subparsers.add_parser("sell")
    p_sell.add_argument("token_id", help="Token ID")
    p_sell.add_argument("size", help="Size/Amount")
    p_sell.add_argument("price", help="Price (0.0 - 1.0)")

    # Cancel
    p_cancel = subparsers.add_parser("cancel")
    p_cancel.add_argument("--order-id", help="Order ID to cancel")
    p_cancel.add_argument("--all", action="store_true", help="Cancel all orders")

    # Quote
    p_quote = subparsers.add_parser("quote")
    p_quote.add_argument("token_id", help="Token ID")

    # Buy max
    p_buy_max = subparsers.add_parser("buy-max")
    p_buy_max.add_argument("token_id", help="Token ID")
    p_buy_max.add_argument("max_usd", help="Max USD notional")
    p_buy_max.add_argument(
        "--price",
        help="Limit price; if omitted uses best ask (marketable).",
    )

    # Balance/allowance
    p_bal = subparsers.add_parser("balance")
    p_bal.add_argument("--asset-type", help="collateral or conditional")
    p_bal.add_argument("--token-id", help="Token ID")
    p_bal.add_argument("--signature-type", type=int, help="Override signature type")

    p_bal_refresh = subparsers.add_parser("refresh-balance")
    p_bal_refresh.add_argument("--asset-type", help="collateral or conditional")
    p_bal_refresh.add_argument("--token-id", help="Token ID")
    p_bal_refresh.add_argument(
        "--signature-type", type=int, help="Override signature type"
    )

    # Whoami
    p_who = subparsers.add_parser("whoami")

    # Diagnose
    p_diag = subparsers.add_parser("diagnose")
    p_diag.add_argument(
        "--onchain",
        action="store_true",
        help="Also query onchain USDC allowance via RPC",
    )
    p_diag.add_argument(
        "--fix",
        action="store_true",
        help="Attempt refresh-balance and output recommendations",
    )

    args = parser.parse_args()

    if args.command == "markets":
        cmd_markets(args)
    elif args.command == "orderbook":
        cmd_orderbook(args)
    elif args.command == "buy":
        cmd_buy(args)
    elif args.command == "sell":
        cmd_sell(args)
    elif args.command == "cancel":
        cmd_cancel(args)
    elif args.command == "quote":
        cmd_quote(args)
    elif args.command == "buy-max":
        cmd_buy_max(args)
    elif args.command == "balance":
        cmd_balance(args)
    elif args.command == "refresh-balance":
        cmd_refresh_balance(args)
    elif args.command == "whoami":
        cmd_whoami(args)
    elif args.command == "diagnose":
        cmd_diagnose(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
