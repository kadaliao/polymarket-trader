#!/usr/bin/env python3
import os
import sys
import json
import argparse
import re
import datetime
import time
import urllib.parse
import urllib.request
import urllib.error
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import (
    AssetType,
    BalanceAllowanceParams,
    OrderArgs,
    OrderType,
    TradeParams,
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

def _http_get_json(url, timeout=15):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "polymarket-trader/1.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError("non-JSON response")

def _parse_kv_params(kv_list):
    params = {}
    if not kv_list:
        return params
    for raw in kv_list:
        if "=" not in raw:
            raise ValueError(f"Invalid param '{raw}', expected key=value")
        key, value = raw.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if key in params:
            if isinstance(params[key], list):
                params[key].append(value)
            else:
                params[key] = [params[key], value]
        else:
            params[key] = value
    return params


def _parse_token_ids(raw):
    if raw is None:
        return None
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return [raw]
    return None

def _select_fields(item, fields):
    if not fields:
        return item
    return {k: item.get(k) for k in fields}

def _title_from_item(item):
    return (
        item.get("title")
        or item.get("question")
        or item.get("name")
    )

def _split_terms(raw):
    if not raw:
        return []
    if "," in raw:
        parts = raw.split(",")
    else:
        parts = raw.split()
    return [p.strip().lower() for p in parts if p.strip()]

def _expand_terms(terms):
    if not terms:
        return terms
    aliases = {
        "btc": ["btc", "bitcoin"],
        "eth": ["eth", "ethereum"],
        "sol": ["sol", "solana"],
        "xrp": ["xrp", "ripple"],
        "ada": ["ada", "cardano"],
        "doge": ["doge", "dogecoin"],
        "ltc": ["ltc", "litecoin"],
        "dot": ["dot", "polkadot"],
        "link": ["link", "chainlink"],
        "bnb": ["bnb", "binance"],
    }
    expanded = []
    for term in terms:
        expanded.extend(aliases.get(term, [term]))
    return list(dict.fromkeys(expanded))

def _match_title(title, args):
    if not any([args.title_like, args.title_any, args.title_all, args.title_regex]):
        return True
    if not title:
        return False
    t = title.lower()
    if args.title_like and args.title_like.lower() not in t:
        return False
    if args.title_any:
        terms = _expand_terms(_split_terms(args.title_any))
        if terms and not any(term in t for term in terms):
            return False
    if args.title_all:
        terms = _expand_terms(_split_terms(args.title_all))
        if terms and not all(term in t for term in terms):
            return False
    if args.title_regex:
        try:
            if not re.search(args.title_regex, title, flags=re.IGNORECASE):
                return False
        except re.error:
            raise ValueError("Invalid --title-regex pattern")
    return True

def _apply_ai_defaults(args, fields_map):
    if not getattr(args, "ai", False):
        return
    args.compact = True
    if not args.fields:
        fields = fields_map.get(getattr(args, "gamma_path", None)) or fields_map.get("default")
        if fields:
            args.fields = fields


def _parse_iso_dt(value):
    if not value:
        return None
    if isinstance(value, (int, float)):
        return datetime.datetime.fromtimestamp(value, tz=datetime.timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _within_hours(dt, hours):
    if not dt or hours is None:
        return False
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    delta = dt - now
    return datetime.timedelta(0) <= delta <= datetime.timedelta(hours=hours)

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


def _trade_matches_order(trade, order_id):
    if not isinstance(trade, dict):
        return False
    if trade.get("taker_order_id") == order_id:
        return True
    if trade.get("order_id") == order_id:
        return True
    maker_orders = trade.get("maker_orders") or []
    for mo in maker_orders:
        if isinstance(mo, dict) and mo.get("order_id") == order_id:
            return True
    return False


def _rpc_tx_receipt(rpc_url, tx_hash):
    if not rpc_url:
        return None
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_getTransactionReceipt",
        "params": [tx_hash],
    }
    req = urllib.request.Request(
        rpc_url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    if "result" not in data or data["result"] is None:
        return {"transaction_hash": tx_hash, "status": "pending"}
    receipt = data["result"]
    status_hex = receipt.get("status")
    status = "unknown"
    if status_hex is not None:
        try:
            status = "success" if int(status_hex, 16) == 1 else "reverted"
        except ValueError:
            status = "unknown"
    return {
        "transaction_hash": tx_hash,
        "status": status,
        "block_number": receipt.get("blockNumber"),
    }


def cmd_markets(args):
    client = get_client(require_auth=False)
    try:
        def _gamma_public_search(query):
            base = os.getenv("POLYMARKET_GAMMA_HOST", "https://gamma-api.polymarket.com")
            path = "/public-search"
            max_pages = args.max_pages or 1
            max_results = args.limit
            limit = min(int(args.limit or 100), 200)
            offset = 0
            collected = []
            for _ in range(max_pages):
                params = {"q": query, "limit": str(limit), "offset": str(offset)}
                url = base.rstrip("/") + path + "?" + urllib.parse.urlencode(params)
                resp = _http_get_json(url, timeout=15)
                if isinstance(resp, dict):
                    if isinstance(resp.get("events"), list):
                        items = resp.get("events", [])
                    elif isinstance(resp.get("markets"), list):
                        items = resp.get("markets", [])
                    else:
                        break
                elif isinstance(resp, list):
                    items = resp
                else:
                    break
                collected.extend(items)
                if max_results and len(collected) >= max_results:
                    collected = collected[:max_results]
                    break
                if len(items) < limit:
                    break
                offset += limit
            return collected

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
            title_filters = any([args.title_like, args.title_any, args.title_all, args.title_regex])
            if title_filters:
                if args.title_source is None:
                    args.title_source = "gamma"
                if args.title_source == "clob":
                    args.with_title = True
            _apply_ai_defaults(
                args,
                {
                    "default": "condition_id,token_id,token_ids,title,accepting_orders",
                },
            )
            fields = None
            if args.fields:
                fields = [f.strip() for f in args.fields.split(",") if f.strip()]
                if "title" in fields:
                    args.with_title = True
            all_items = []
            max_results = args.limit
            if args.title_source == "gamma" and title_filters:
                query = args.title_query
                if not query:
                    if args.title_like:
                        query = args.title_like
                    elif args.title_any:
                        query = " ".join(_split_terms(args.title_any))
                    elif args.title_all:
                        query = " ".join(_split_terms(args.title_all))
                if not query:
                    raise ValueError(
                        "Gamma title search requires --title-query or --title-like/--title-any/--title-all."
                    )
                gamma_items = _gamma_public_search(query)
                for item in gamma_items:
                    if isinstance(item, dict) and isinstance(item.get("markets"), list):
                        event_title = item.get("title")
                        markets = item.get("markets", [])
                    else:
                        event_title = None
                        markets = [item]
                    for m in markets:
                        if not isinstance(m, dict):
                            continue
                        out = {
                            "condition_id": m.get("conditionId") or m.get("condition_id"),
                            "token_ids": _parse_token_ids(
                                m.get("clobTokenIds") or m.get("clob_token_ids")
                            ),
                            "accepting_orders": m.get("acceptingOrders") or m.get("accepting_orders"),
                            "active": m.get("active"),
                            "closed": m.get("closed"),
                            "archived": m.get("archived"),
                        }
                        if out.get("token_ids"):
                            out["token_id"] = out["token_ids"][0]
                        title_val = m.get("question") or m.get("title") or event_title
                        if title_val:
                            out["title"] = title_val
                        if args.accepting_only and out.get("accepting_orders") is False:
                            continue
                        if not _match_title(title_val, args):
                            continue
                        all_items.append(out)
                        if max_results and len(all_items) >= max_results:
                            break
                    if max_results and len(all_items) >= max_results:
                        break
            else:
                max_pages = args.max_pages or 1
                cursor = args.cursor
                next_cursor = cursor

                def _get_page(next_cur):
                    if args.sampling:
                        return client.get_sampling_simplified_markets(
                            next_cursor=next_cur or "MA=="
                        )
                    if next_cur:
                        return client.get_simplified_markets(next_cursor=next_cur)
                    return client.get_simplified_markets()

                pages = 0
                while True:
                    resp = _get_page(next_cursor)
                    items = resp.get("data", [])
                    for m in items:
                        if args.accepting_only and not m.get("accepting_orders"):
                            continue
                        title_val = None
                        if args.with_title or args.title_like:
                            condition_id = m.get("condition_id")
                            if condition_id:
                                try:
                                    detail = client.get_market(condition_id)
                                    title_val = _title_from_item(detail)
                                except Exception:
                                    title_val = None
                            m["title"] = title_val
                        if not _match_title(title_val, args):
                            continue
                        all_items.append(m)
                        if max_results and len(all_items) >= max_results:
                            break
                    pages += 1
                    if max_results and len(all_items) >= max_results:
                        break
                    next_cursor = resp.get("next_cursor")
                    if not next_cursor or pages >= max_pages:
                        break
            if fields:
                all_items = [_select_fields(m, fields) for m in all_items]
            if args.compact:
                print(json.dumps(all_items, indent=2))
            else:
                out = {
                    "data": all_items,
                    "count": len(all_items),
                }
                if next_cursor:
                    out["next_cursor"] = next_cursor
                print(json.dumps(out, indent=2))
    except Exception as e:
        print(f"Error fetching markets: {e}", file=sys.stderr)

def cmd_gamma(args):
    try:
        base = os.getenv("POLYMARKET_GAMMA_HOST", "https://gamma-api.polymarket.com")
        path = getattr(args, "gamma_path", None) or args.path
        if not path.startswith("/"):
            path = "/" + path
        _apply_ai_defaults(
            args,
            {
                "/events": "id,title,slug,active,closed,markets",
                "/markets": "id,condition_id,slug,title,question,active,closed",
                "/public-search": "id,title,slug,active,closed",
                "default": "id,title,slug,question,name,active,closed,condition_id",
            },
        )

        params = _parse_kv_params(args.param)
        if args.limit is not None and "limit" not in params:
            params["limit"] = str(args.limit)
        if args.offset is not None and "offset" not in params:
            params["offset"] = str(args.offset)
        if args.order and "order" not in params:
            params["order"] = args.order

        def _fetch_pages(extra_params):
            merged = dict(params)
            merged.update(extra_params or {})
            limit = int(merged.get("limit") or args.limit or 100)
            offset = int(merged.get("offset") or args.offset or 0)
            max_pages = args.max_pages or 1
            max_results = args.max_results
            all_items = []
            first_resp = None
            items_key = None
            for _ in range(max_pages):
                page_params = dict(merged)
                if limit:
                    page_params["limit"] = str(limit)
                if offset is not None:
                    page_params["offset"] = str(offset)
                url = base.rstrip("/") + path
                if page_params:
                    url = url + "?" + urllib.parse.urlencode(page_params, doseq=True)
                resp = _http_get_json(url, timeout=args.timeout)
                if first_resp is None:
                    first_resp = resp
                if isinstance(resp, dict):
                    if isinstance(resp.get("data"), list):
                        items = resp.get("data")
                        items_key = "data"
                    elif isinstance(resp.get("events"), list):
                        items = resp.get("events")
                        items_key = "events"
                    elif isinstance(resp.get("markets"), list):
                        items = resp.get("markets")
                        items_key = "markets"
                    else:
                        return resp, None, None
                elif isinstance(resp, list):
                    items = resp
                else:
                    return resp, None, None
                all_items.extend(items)
                if max_results and len(all_items) >= max_results:
                    all_items = all_items[:max_results]
                    break
                if not limit or len(items) < limit:
                    break
                offset += limit
            return first_resp, all_items, items_key

        resp = None
        items = None
        items_key = None
        if args.q:
            if args.q_param:
                resp, items, items_key = _fetch_pages({args.q_param: args.q})
            else:
                if path == "/public-search":
                    default_q_try = "q,search,query,text"
                else:
                    default_q_try = "search,query,q,text"
                tried = _split_terms(args.q_try or default_q_try)
                last_error = None
                for name in tried:
                    try:
                        resp, items, items_key = _fetch_pages({name: args.q})
                    except urllib.error.HTTPError as e:
                        last_error = e
                        if e.code in (400, 404, 422):
                            continue
                        raise
                    if items is not None and len(items) > 0:
                        break
                if resp is None and last_error:
                    raise last_error
        if resp is None:
            resp, items, items_key = _fetch_pages({})

        fields = None
        if args.fields:
            fields = [f.strip() for f in args.fields.split(",") if f.strip()]
        if items is not None:
            filtered = []
            for m in items:
                if isinstance(m, dict):
                    if args.active_only and not m.get("active"):
                        continue
                    if args.open_only and m.get("closed"):
                        continue
                    if args.not_archived and m.get("archived"):
                        continue
                    if args.end_within_hours is not None:
                        dt = _parse_iso_dt(
                            m.get("endDate")
                            or m.get("endDateIso")
                            or m.get("endDateISO")
                            or m.get("end_date")
                        )
                        if not _within_hours(dt, args.end_within_hours):
                            continue
                    title_val = _title_from_item(m)
                    if not _match_title(title_val, args):
                        continue
                filtered.append(m)
            items = filtered
            if fields:
                items = [_select_fields(m, fields) if isinstance(m, dict) else m for m in items]
            if args.compact:
                print(json.dumps(items, indent=2))
            else:
                if isinstance(resp, dict):
                    if items_key:
                        resp[items_key] = items
                    else:
                        resp["data"] = items
                    print(json.dumps(resp, indent=2))
                else:
                    print(json.dumps(items, indent=2))
        else:
            print(json.dumps(resp, indent=2))
    except Exception as e:
        print(f"Error fetching gamma data: {e}", file=sys.stderr)

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


def _fetch_order_status(client, order_id, include_trades=True, include_receipts=False):
    order = client.get_order(order_id)
    order_payload = _to_json_payload(order)
    maker_address = None
    asset_id = None
    market = None
    if isinstance(order_payload, dict):
        maker_address = order_payload.get("maker_address")
        asset_id = order_payload.get("asset_id")
        market = order_payload.get("market")

    result = {
        "order": order_payload,
        "trades": [],
    }

    if include_trades and maker_address and asset_id:
        params = TradeParams(maker_address=maker_address, asset_id=asset_id, market=market)
        trades = client.get_trades(params)
        trades_payload = _to_json_payload(trades)
        matched = []
        if isinstance(trades_payload, list):
            for trade in trades_payload:
                if _trade_matches_order(trade, order_id):
                    matched.append(trade)
        result["trades"] = matched

        if include_receipts:
            rpc_url = os.getenv("POLYMARKET_RPC")
            receipts = []
            for trade in matched:
                tx_hash = trade.get("transaction_hash") if isinstance(trade, dict) else None
                if tx_hash:
                    try:
                        rec = _rpc_tx_receipt(rpc_url, tx_hash)
                    except Exception as e:
                        rec = {"transaction_hash": tx_hash, "status": "error", "error": str(e)}
                    receipts.append(rec or {"transaction_hash": tx_hash, "status": "unknown"})
            result["receipts"] = receipts

    return result


def _is_pending_trade_status(status):
    if not status:
        return True
    status = str(status).upper()
    return status in {"RETRYING", "PENDING", "SUBMITTED"}


def _normalize_status(value):
    if value is None:
        return ""
    return str(value).upper()


def _summarize_settlement(trades, receipts):
    if not trades:
        return "no_trades"
    trade_statuses = [_normalize_status(t.get("status")) for t in trades if isinstance(t, dict)]
    if any(_is_pending_trade_status(s) for s in trade_statuses):
        return "pending"
    if any(s in {"FAILED", "REVERTED", "CANCELED", "CANCELLED", "EXPIRED"} for s in trade_statuses):
        return "failed"
    if receipts:
        receipt_statuses = [(r or {}).get("status") for r in receipts if isinstance(r, dict)]
        if any(s == "reverted" for s in receipt_statuses):
            return "reverted"
        if any(s == "pending" for s in receipt_statuses):
            return "pending"
        if receipt_statuses and all(s == "success" for s in receipt_statuses):
            return "settled"
        if receipt_statuses and all(s == "unknown" for s in receipt_statuses):
            return "unknown"
    return "matched"


def cmd_order_status(args):
    client = get_client(require_auth=True)
    try:
        result = _fetch_order_status(
            client,
            args.order_id,
            include_trades=not args.no_trades,
            include_receipts=False,
        )
        trades = result.get("trades") or []
        order_status = None
        if isinstance(result.get("order"), dict):
            order_status = result["order"].get("status")
        result["summary"] = {
            "order_status": order_status,
            "trade_statuses": sorted(
                {t.get("status") for t in trades if isinstance(t, dict) and t.get("status")}
            ),
            "settlement": _summarize_settlement(trades, []),
        }
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(f"Error fetching order status: {e}", file=sys.stderr)


def cmd_order_diagnose(args):
    client = get_client(require_auth=True)
    try:
        include_receipts = bool(args.with_receipt)
        if not args.watch:
            result = _fetch_order_status(
                client,
                args.order_id,
                include_trades=not args.no_trades,
                include_receipts=include_receipts,
            )
            trades = result.get("trades") or []
            receipts = result.get("receipts") or []
            order_status = None
            if isinstance(result.get("order"), dict):
                order_status = result["order"].get("status")
            result["summary"] = {
                "order_status": order_status,
                "trade_statuses": sorted(
                    {t.get("status") for t in trades if isinstance(t, dict) and t.get("status")}
                ),
                "receipt_statuses": sorted(
                    {r.get("status") for r in receipts if isinstance(r, dict) and r.get("status")}
                ),
                "settlement": _summarize_settlement(trades, receipts),
            }
            print(json.dumps(result, indent=2))
            return

        watch_seconds = float(args.watch_seconds or 0)
        watch_interval = float(args.watch_interval or 0)
        if watch_seconds <= 0:
            watch_seconds = 300.0
        if watch_interval <= 0:
            watch_interval = 10.0
        deadline = time.time() + watch_seconds
        last_result = None
        while True:
            result = _fetch_order_status(
                client,
                args.order_id,
                include_trades=not args.no_trades,
                include_receipts=include_receipts,
            )
            last_result = result
            trades = result.get("trades") or []
            receipts = result.get("receipts") or []
            if trades:
                pending = [t for t in trades if _is_pending_trade_status(t.get("status"))]
                if receipts:
                    receipt_pending = [r for r in receipts if r and r.get("status") == "pending"]
                else:
                    receipt_pending = []
                if not pending and not receipt_pending:
                    break
            if time.time() >= deadline:
                print("order-diagnose watch timed out; showing last result", file=sys.stderr)
                break
            time.sleep(watch_interval)
        trades = last_result.get("trades") or []
        receipts = last_result.get("receipts") or []
        order_status = None
        if isinstance(last_result.get("order"), dict):
            order_status = last_result["order"].get("status")
        last_result["summary"] = {
            "order_status": order_status,
            "trade_statuses": sorted(
                {t.get("status") for t in trades if isinstance(t, dict) and t.get("status")}
            ),
            "receipt_statuses": sorted(
                {r.get("status") for r in receipts if isinstance(r, dict) and r.get("status")}
            ),
            "settlement": _summarize_settlement(trades, receipts),
        }
        print(json.dumps(last_result, indent=2))
    except Exception as e:
        print(f"Error fetching order diagnosis: {e}", file=sys.stderr)


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
        "--max-pages",
        type=int,
        help="Max pages to scan (default 1)",
    )
    p_markets.add_argument(
        "--with-title",
        action="store_true",
        help="Fetch market details to include title (uses condition_id)",
    )
    p_markets.add_argument(
        "--title-like",
        help="Filter markets by title substring (case-insensitive)",
    )
    p_markets.add_argument(
        "--title-any",
        help="Filter markets by any term in title (comma or space separated)",
    )
    p_markets.add_argument(
        "--title-all",
        help="Filter markets by all terms in title (comma or space separated)",
    )
    p_markets.add_argument(
        "--title-regex",
        help="Filter markets by title regex (case-insensitive)",
    )
    p_markets.add_argument(
        "--title-source",
        choices=["clob", "gamma"],
        help="Title filter source: clob (slower) or gamma (faster). Defaults to gamma when filters set.",
    )
    p_markets.add_argument(
        "--title-query",
        help="Override gamma title search query when using --title-source gamma",
    )
    p_markets.add_argument(
        "--fields",
        help="Comma-separated fields to keep in output items",
    )
    p_markets.add_argument(
        "--compact",
        action="store_true",
        help="Output a list of items only (no wrapper object)",
    )
    p_markets.add_argument(
        "--ai",
        action="store_true",
        help="AI-friendly output (compact + default fields)",
    )

    # Gamma (discovery/search)
    p_gamma = subparsers.add_parser("gamma")
    p_gamma.add_argument("path", help="Gamma API path, e.g. /events or /markets")
    p_gamma.add_argument("--param", action="append", help="Query param key=value (repeatable)")
    p_gamma.add_argument("--limit", type=int, help="Limit number of returned items")
    p_gamma.add_argument("--offset", type=int, help="Offset for pagination")
    p_gamma.add_argument("--max-pages", type=int, help="Auto paginate up to N pages")
    p_gamma.add_argument("--max-results", type=int, help="Cap total items returned")
    p_gamma.add_argument("--order", help="Order parameter (if supported)")
    p_gamma.add_argument("--q", help="Search string (mapped to --q-param)")
    p_gamma.add_argument("--q-param", help="Query parameter name for --q")
    p_gamma.add_argument("--q-try", help="Comma/space list of query param names to try")
    p_gamma.add_argument("--fields", help="Comma-separated fields to keep in output items")
    p_gamma.add_argument("--compact", action="store_true", help="Output a list of items only")
    p_gamma.add_argument("--title-like", help="Filter by title/question/name substring")
    p_gamma.add_argument("--title-any", help="Filter by any term in title (comma or space separated)")
    p_gamma.add_argument("--title-all", help="Filter by all terms in title (comma or space separated)")
    p_gamma.add_argument("--title-regex", help="Filter by title regex (case-insensitive)")
    p_gamma.add_argument("--active-only", action="store_true", help="Only items with active=true")
    p_gamma.add_argument("--open-only", action="store_true", help="Only items with closed=false")
    p_gamma.add_argument("--not-archived", action="store_true", help="Only items with archived=false")
    p_gamma.add_argument("--end-within-hours", type=float, help="Filter by endDate within N hours")
    p_gamma.add_argument("--timeout", type=int, default=15, help="HTTP timeout seconds")
    p_gamma.add_argument("--ai", action="store_true", help="AI-friendly output (compact + default fields)")
    p_gamma.set_defaults(func=cmd_gamma)

    p_gamma_events = subparsers.add_parser("gamma-events")
    p_gamma_events.add_argument("--param", action="append", help="Query param key=value (repeatable)")
    p_gamma_events.add_argument("--limit", type=int, help="Limit number of returned items")
    p_gamma_events.add_argument("--offset", type=int, help="Offset for pagination")
    p_gamma_events.add_argument("--max-pages", type=int, help="Auto paginate up to N pages")
    p_gamma_events.add_argument("--max-results", type=int, help="Cap total items returned")
    p_gamma_events.add_argument("--order", help="Order parameter (if supported)")
    p_gamma_events.add_argument("--q", help="Search string (mapped to --q-param)")
    p_gamma_events.add_argument("--q-param", help="Query parameter name for --q")
    p_gamma_events.add_argument("--q-try", help="Comma/space list of query param names to try")
    p_gamma_events.add_argument("--fields", help="Comma-separated fields to keep in output items")
    p_gamma_events.add_argument("--compact", action="store_true", help="Output a list of items only")
    p_gamma_events.add_argument("--title-like", help="Filter by title/question/name substring")
    p_gamma_events.add_argument("--title-any", help="Filter by any term in title (comma or space separated)")
    p_gamma_events.add_argument("--title-all", help="Filter by all terms in title (comma or space separated)")
    p_gamma_events.add_argument("--title-regex", help="Filter by title regex (case-insensitive)")
    p_gamma_events.add_argument("--active-only", action="store_true", help="Only items with active=true")
    p_gamma_events.add_argument("--open-only", action="store_true", help="Only items with closed=false")
    p_gamma_events.add_argument("--not-archived", action="store_true", help="Only items with archived=false")
    p_gamma_events.add_argument("--end-within-hours", type=float, help="Filter by endDate within N hours")
    p_gamma_events.add_argument("--timeout", type=int, default=15, help="HTTP timeout seconds")
    p_gamma_events.add_argument("--ai", action="store_true", help="AI-friendly output (compact + default fields)")
    p_gamma_events.set_defaults(func=cmd_gamma, gamma_path="/events")

    p_gamma_markets = subparsers.add_parser("gamma-markets")
    p_gamma_markets.add_argument("--param", action="append", help="Query param key=value (repeatable)")
    p_gamma_markets.add_argument("--limit", type=int, help="Limit number of returned items")
    p_gamma_markets.add_argument("--offset", type=int, help="Offset for pagination")
    p_gamma_markets.add_argument("--max-pages", type=int, help="Auto paginate up to N pages")
    p_gamma_markets.add_argument("--max-results", type=int, help="Cap total items returned")
    p_gamma_markets.add_argument("--order", help="Order parameter (if supported)")
    p_gamma_markets.add_argument("--q", help="Search string (mapped to --q-param)")
    p_gamma_markets.add_argument("--q-param", help="Query parameter name for --q")
    p_gamma_markets.add_argument("--q-try", help="Comma/space list of query param names to try")
    p_gamma_markets.add_argument("--fields", help="Comma-separated fields to keep in output items")
    p_gamma_markets.add_argument("--compact", action="store_true", help="Output a list of items only")
    p_gamma_markets.add_argument("--title-like", help="Filter by title/question/name substring")
    p_gamma_markets.add_argument("--title-any", help="Filter by any term in title (comma or space separated)")
    p_gamma_markets.add_argument("--title-all", help="Filter by all terms in title (comma or space separated)")
    p_gamma_markets.add_argument("--title-regex", help="Filter by title regex (case-insensitive)")
    p_gamma_markets.add_argument("--active-only", action="store_true", help="Only items with active=true")
    p_gamma_markets.add_argument("--open-only", action="store_true", help="Only items with closed=false")
    p_gamma_markets.add_argument("--not-archived", action="store_true", help="Only items with archived=false")
    p_gamma_markets.add_argument("--end-within-hours", type=float, help="Filter by endDate within N hours")
    p_gamma_markets.add_argument("--timeout", type=int, default=15, help="HTTP timeout seconds")
    p_gamma_markets.add_argument("--ai", action="store_true", help="AI-friendly output (compact + default fields)")
    p_gamma_markets.set_defaults(func=cmd_gamma, gamma_path="/markets")

    p_gamma_search = subparsers.add_parser("gamma-search")
    p_gamma_search.add_argument("--param", action="append", help="Query param key=value (repeatable)")
    p_gamma_search.add_argument("--limit", type=int, help="Limit number of returned items")
    p_gamma_search.add_argument("--offset", type=int, help="Offset for pagination")
    p_gamma_search.add_argument("--max-pages", type=int, help="Auto paginate up to N pages")
    p_gamma_search.add_argument("--max-results", type=int, help="Cap total items returned")
    p_gamma_search.add_argument("--order", help="Order parameter (if supported)")
    p_gamma_search.add_argument("--q", help="Search string (mapped to --q-param)")
    p_gamma_search.add_argument("--q-param", help="Query parameter name for --q")
    p_gamma_search.add_argument("--q-try", help="Comma/space list of query param names to try")
    p_gamma_search.add_argument("--fields", help="Comma-separated fields to keep in output items")
    p_gamma_search.add_argument("--compact", action="store_true", help="Output a list of items only")
    p_gamma_search.add_argument("--title-like", help="Filter by title/question/name substring")
    p_gamma_search.add_argument("--title-any", help="Filter by any term in title (comma or space separated)")
    p_gamma_search.add_argument("--title-all", help="Filter by all terms in title (comma or space separated)")
    p_gamma_search.add_argument("--title-regex", help="Filter by title regex (case-insensitive)")
    p_gamma_search.add_argument("--active-only", action="store_true", help="Only items with active=true")
    p_gamma_search.add_argument("--open-only", action="store_true", help="Only items with closed=false")
    p_gamma_search.add_argument("--not-archived", action="store_true", help="Only items with archived=false")
    p_gamma_search.add_argument("--end-within-hours", type=float, help="Filter by endDate within N hours")
    p_gamma_search.add_argument("--timeout", type=int, default=15, help="HTTP timeout seconds")
    p_gamma_search.add_argument("--ai", action="store_true", help="AI-friendly output (compact + default fields)")
    p_gamma_search.set_defaults(func=cmd_gamma, gamma_path="/public-search")

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

    # Order status
    p_order_status = subparsers.add_parser("order-status")
    p_order_status.add_argument("--order-id", required=True, help="Order ID to inspect")
    p_order_status.add_argument(
        "--no-trades", action="store_true", help="Skip fetching associated trades"
    )

    # Order diagnose (advanced)
    p_order_diag = subparsers.add_parser("order-diagnose")
    p_order_diag.add_argument("--order-id", required=True, help="Order ID to inspect")
    p_order_diag.add_argument(
        "--no-trades", action="store_true", help="Skip fetching associated trades"
    )
    p_order_diag.add_argument(
        "--with-receipt",
        action="store_true",
        help="Also fetch onchain transaction receipt (requires POLYMARKET_RPC)",
    )
    p_order_diag.add_argument(
        "--watch", action="store_true", help="Poll until trade status is no longer pending"
    )
    p_order_diag.add_argument(
        "--watch-seconds", type=float, help="Max seconds to watch before timing out"
    )
    p_order_diag.add_argument(
        "--watch-interval", type=float, help="Seconds between polls (default 10)"
    )

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

    if hasattr(args, "func"):
        args.func(args)
        return

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
    elif args.command == "order-status":
        cmd_order_status(args)
    elif args.command == "order-diagnose":
        cmd_order_diagnose(args)
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
