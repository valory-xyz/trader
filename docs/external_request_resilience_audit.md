# External Request Resilience Audit

Deep analysis of every external HTTP dependency: what happens under each failure mode
(HTTP errors, unreachable, malformed data, empty 200s) and how failures propagate through the FSM.

**Audit date:** 2026-03-13
**Scope:** All skills, connections, and handlers under `packages/valory/`

---

## How the framework handles HTTP

### Stack 1: Framework path (`get_http_response` via `BaseBehaviour`)

Used by behaviours that call `yield from self.get_http_response(...)`.

- Returns an `HttpMessage` with `status_code`, `status_text`, `body`
- **Unreachable / DNS / timeout**: HTTP client connection catches all exceptions and returns `status_code=600` with the traceback in `body`
- `ApiSpecs.process_response()` then attempts JSON parse on body:
  - **JSON decode error** -> returns `None` (logs error)
  - **Key/index mismatch** -> raises `UnexpectedResponseError` -> caught -> returns `None`
  - **Does NOT check status_code** -- a 500 with valid JSON body will be parsed normally
- Retry pattern via `_handle_response()` in querying behaviours:
  - `res is None` -> increments retries, sleeps with `backoff_factor^retries_attempted`, sets `FetchStatus.FAIL` when retries exceeded
  - `res is not None` -> resets retries, returns data

### Stack 2: Direct path (`requests.get` / `requests.post`)

Used by connections and handlers that import `requests` directly.

- **Unreachable / timeout / SSL**: `requests.exceptions.RequestException` raised
- **4xx/5xx**: must call `raise_for_status()` explicitly; otherwise status code is silently accepted
- **JSON decode on non-JSON body**: `response.json()` raises `json.JSONDecodeError` which is **NOT** a subclass of `RequestException` -- it inherits from `ValueError`
- **Critical bug pattern**: code that catches `RequestException` will NOT catch `JSONDecodeError` from `response.json()`

### Stack 3: Third-party library wrappers

- **py_clob_client** (ClobClient): uses `httpx` internally, raises `PolyApiException` on HTTP errors. The module-level `httpx.Client` has **no timeout configured**.
- **py_builder_relayer_client** (RelayClient): uses `requests` internally, raises `RelayerApiException`. The internal `requests.request()` call has **no timeout configured**.

### HTTP handler dispatch (no global try-catch)

`decision_maker_abci/handlers.py:253` calls `handler(http_msg, http_dialogue, **kwargs)` **without any try-catch wrapper**. If a handler throws an unhandled exception, no HTTP response is sent to the client -- the client hangs until its own timeout.

### Exception propagation in behaviours

The framework's execution path for behaviours:

```
async_act() (generator) -> __handle_tick() -> async_act_wrapper()
```

**Critical:** `async_act_wrapper()` and `__handle_tick()` in `behaviour_utils.py` only catch `StopIteration`. Any other exception in a behaviour's generator **propagates uncaught**.

What happens after a behaviour crash:
1. The generator raises an exception that escapes `__handle_tick()`
2. The AEA framework's skill handler catches it and logs a traceback
3. **The behaviour is marked as done without sending a payload**
4. The round never receives a payload from this agent
5. If enough agents crash (below consensus threshold), the round can never reach consensus
6. `Event.ROUND_TIMEOUT` fires -> FSM transitions per the round's timeout mapping
7. If no timeout is configured for the round: **the agent is stuck permanently**

---

## 1. The Graph Subgraphs (Omen)

| | |
|---|---|
| **Base URLs** | Configurable via `ApiSpecs` in skill.yaml (e.g. `api.subgraph.staging.autonolas.tech`, `api.thegraph.com`) |
| **Endpoints** | Omen subgraph, conditional tokens, Realitio, network block number |
| **Called from** | `market_manager_abci/graph_tooling/requests.py`, `agent_performance_summary_abci/graph_tooling/requests.py` |
| **Method** | POST (GraphQL) |
| **Purpose** | Fetch bets, trades, redeem info, block numbers, claim params, resolved markets, mech requests |

### Failure matrix

| Failure mode | `_fetch_bets` / `_fetch_redeem_info` / `fetch_trades` | `fetch_claim_params` |
|---|---|---|
| **HTTP 500** | `process_response` -> JSON parse fails or returns unexpected structure -> `None` -> retries with backoff | Same |
| **HTTP 429 / 403** | Same as 500 -- no status code differentiation | Same |
| **Unreachable / DNS / timeout** | `status_code=600` -> body is error text -> `json.loads` fails -> `None` -> retries | Same |
| **200 but non-JSON body** | `json.loads` fails -> `None` -> retries | Same |
| **200 but `{}`** | `UnexpectedResponseError` (missing `response_key`) -> `None` -> retries | Same |
| **200 but `{"data": null}`** | Extracts `None` -> returns `None` -> retries | Extracts `None` -> returns `None` |
| **200 but unexpected keys** | `_parse_response_data` raises `UnexpectedResponseError` -> `None` -> retries | **Direct dict indexing crashes** (see bugs) |

### FSM impact

```
Subgraph unreachable -> _handle_response returns None -> retries with backoff
-> retries exceeded -> FetchStatus.FAIL -> payload with bets_hash=None
-> UpdateBetsRound fires none_event=Event.FETCH_ERROR
-> FailedMarketManagerRound (terminal/degenerate)
-> ResetAndPauseRound -> back to initial state
-> Next period: retries from scratch
```

In the composed FSM, `FailedMarketManagerRound` maps to `Event.FETCH_ERROR` -> **`ImpossibleRound`** in `decision_maker_abci` (from `SamplingRound` and `BlacklistingRound` via `MarketManagerEvent.FETCH_ERROR`). `ImpossibleRound` is a degenerate terminal state -- the period ends and the agent restarts from the top on the next period.

Under sustained outage: the agent loops through periods without placing any trades. `ResetAndPauseRound` has its own timeout; if it also fails: `FinishedResetAndPauseErrorRound` -> `ResetAndPauseRound` (loops).

### Bugs found

**BUG 1 -- HIGH: `Subgraph.process_response` crashes on `None` error message**
- Location: `market_manager_abci/models.py:67` and `agent_performance_summary_abci/models.py:339`
- Code: `if self.context.params.the_graph_payment_required_error in error_message`
- When The Graph returns an error response where the error message key is missing, `error_data.get(error_message_key, None)` returns `None`. The `in` operator on `None` raises `TypeError: argument of type 'NoneType' is not iterable`.
- This crashes the behaviour generator. Since `async_act_wrapper()` only catches `StopIteration`, the exception propagates up. The round never receives a payload, and `ROUND_TIMEOUT` fires -> FSM transitions to timeout mapping.
- **Trigger likelihood**: Medium -- The Graph error responses may omit the expected message key.

**BUG 2 -- HIGH: `fetch_claim_params` crashes on malformed subgraph data**
- Location: `market_manager_abci/graph_tooling/requests.py:298-313`
- Code: `answer["answer"][2:]`, `answer["question"]["questionId"][2:]`, `answer["question"]["historyHash"][2:]`, etc.
- Direct dict key access without `.get()`. If the subgraph returns answers with missing or renamed keys, `KeyError` crashes the behaviour generator.
- **Trigger likelihood**: Low-Medium -- depends on subgraph schema stability.

**BUG 3 -- MEDIUM: Batched trade fetching crashes on missing keys**
- Location: `market_manager_abci/graph_tooling/requests.py:244` (`trades_chunk[-1]["fpmm"]["creationTimestamp"]`) and line 363 (`trades_chunk[-1]["creationTimestamp"]`)
- If a trade object lacks `"fpmm"` or `"creationTimestamp"`, `KeyError` crashes the generator.

**BUG 4 -- MEDIUM: Retry backoff can exceed round timeout**
- With default `backoff_factor=2.0` and 5 retries, cumulative sleep = 1+2+4+8+16 = 31s. Default `ROUND_TIMEOUT` = 30s. The 5th retry will never complete before timeout.
- The sleep is `yield from self.sleep()`, which is cooperative. The round timeout fires via Tendermint's `update_time()` on the next block. The timeout event transitions the FSM, but the sleeping behaviour continues until it yields -- it just becomes irrelevant because the round has moved on.

---

## 2. Polymarket Gamma API

| | |
|---|---|
| **Base URL** | `https://gamma-api.polymarket.com` (GAMMA_API_BASE_URL) |
| **Endpoints** | `/tags/slug/{slug}`, `/markets`, `/markets/slug/{slug}`, `/markets/{id}` |
| **Called from** | `connection.py:441` (`_request_with_retries`), `connection.py:704` (`_fetch_market_by_slug`), `polymarket_predictions_helper.py:606` (`_fetch_market_slug`) |
| **Method** | GET |
| **Purpose** | Discover markets by category, fetch market metadata, get market slugs for UI links |

### Failure matrix

| Failure mode | `_request_with_retries` (connection.py:441) | `_fetch_market_by_slug` (connection.py:704) | `_fetch_market_slug` (predictions_helper.py:606) |
|---|---|---|---|
| **HTTP 500** | `raise_for_status()` -> `HTTPError` -> caught by `RequestException` handler -> retried 3x with linear backoff `RETRY_DELAY * (attempt+1)` -> returns `(None, error_msg)` | `raise_for_status()` -> `HTTPError` -> caught -> returns `(None, error_msg)` | `raise_for_status()` -> `HTTPError` -> caught by broad `except` -> returns `""` |
| **HTTP 429 / 403 / 404** | Same as 500: `raise_for_status()` triggers retry | Same: returns `(None, error_msg)` | Same: returns `""` |
| **Unreachable / DNS / timeout** | `ConnectionError`/`Timeout` -> caught -> retried 3x -> returns `(None, error_msg)` | Caught -> returns `(None, error_msg)` | Caught -> returns `""` |
| **200 but non-JSON body** | **`JSONDecodeError` escapes** (see BUG 5) | **`JSONDecodeError` caught by broad `except Exception`** | Caught by broad `except Exception` -> returns `""` |
| **200 but `{}`** | Returns `({}, None)` -> `tag_data.get("id")` -> `None` -> caller logs "No tag ID found" and skips category | Returns `({}, None)` -> caller uses empty dict | `response.json().get("slug", "")` -> returns `""` |
| **200 but unexpected keys** | `.get()` with defaults -> falls through to validation -> category skipped | Passes up to caller; no key validation | `.get("slug", "")` -> `""` |

### FSM impact

**Market discovery path:** `PolymarketFetchMarketRound` behaviour calls `_fetch_markets()` -> iterates 11 categories. Per-category failures are skipped (line 651-652); remaining categories still produce markets. If ALL categories fail: empty dict passed to behaviour -> `UpdateBetsRound` receives `bets_hash=None` -> `none_event = Event.FETCH_ERROR` -> **`FailedMarketManagerRound`** -> **`ImpossibleRound`** in `decision_maker_abci`.

**Position detail path:** `_fetch_market_slug` returns `""` -> `external_url = ""` -> UI shows position with no link. HTTP endpoint returns 200 with empty URL field. No FSM impact.

### Bugs found

**BUG 5 -- HIGH: `JSONDecodeError` bypasses retry logic in `_request_with_retries`**
- Location: `connections/polymarket_client/connection.py:443-444`
- Code: `response.json()` inside `try` that only catches `requests.exceptions.RequestException`
- `json.JSONDecodeError` is a `ValueError`, not `RequestException`. A 200 response with malformed body (HTML error page from CDN, truncated JSON) will crash out of the retry loop entirely.
- The exception is caught by `_route_request`'s broad `except Exception`, so the connection won't crash, but retries are completely bypassed.
- Same bug exists in `_fetch_market_by_slug` (connection.py:707).
- **This is BP1.**

**BUG 6 -- HIGH: Thread blocking -- `_fetch_markets` worst case 11+ minutes**
- `_request_with_retries` uses `time.sleep(RETRY_DELAY * (attempt + 1))` with `RETRY_DELAY=10`. Worst case per call: 60s (10s timeout * 3 attempts + 10s + 20s sleep).
- `_fetch_markets` calls this once per category tag (11 categories) plus once per paginated page per category.
- With `MAX_WORKER_THREADS=1`, the single connection thread is blocked. ALL other Polymarket requests (bet placement, position queries, etc.) queue behind it.
- **This is BP8.**

**BUG 7 -- MEDIUM: No retries on `_fetch_market_by_slug`, `_get_positions`, `_get_trades`**
- Inconsistent with `_request_with_retries` used by `_fetch_markets`. A transient network error causes immediate failure for these endpoints.

---

## 3. Polymarket Data API

| | |
|---|---|
| **Base URL** | `https://data-api.polymarket.com` (DATA_API_BASE_URL) |
| **Endpoints** | `/positions`, `/trades` |
| **Called from** | `connections/polymarket_client/connection.py` (via `_get_positions`, `_get_trades`, and their paginated wrappers) |
| **Method** | GET |
| **Purpose** | Fetch user positions and trade history on Polymarket |

### Failure matrix

| Failure mode | `_get_positions` / `_get_trades` |
|---|---|
| **HTTP 5xx / 4xx** | `raise_for_status()` -> `RequestException` -> caught -> returns `(None, error_msg)` |
| **Unreachable** | `ConnectionError`/`Timeout` -> caught -> returns `(None, error_msg)` |
| **200 but non-JSON** | `response.json()` raises `JSONDecodeError` -> **NOT caught** by `RequestException` handler -> caught by broad `except Exception` -> returns `(None, error_msg)` |
| **200 but `{"positions": []}`** | Empty list returned -> caller sees no positions |

### FSM impact

Position data feeds into the connection's response to the behaviour. On failure the behaviour receives an error response. This data is used for checking existing bets before placing new ones -- stale or missing positions could lead to duplicate bet attempts (which would then fail at the relayer level).

The paginated wrappers `_fetch_all_positions()` and `_fetch_all_trades()` call these in a loop -- if any single page fails, the entire operation fails immediately.

---

## 4. ClobClient / Polymarket Order API

| | |
|---|---|
| **Base URL** | Polymarket CLOB API (configured via `host` param) |
| **Endpoints** | `get_ok()`, `create_market_order()`, `post_order()` |
| **Called from** | `connections/polymarket_client/connection.py:350,376,380` |
| **Method** | GET/POST |
| **Purpose** | Test connection, create and submit market orders (bet placement) |

### Failure matrix

| Failure mode | `get_ok()` | `create_market_order()` / `post_order()` |
|---|---|---|
| **HTTP 500** | `PolyApiException` -> caught | `PolyApiException` -> caught at line 388 |
| **Unreachable / timeout** | **Hangs indefinitely** (see BUG 8) | **Hangs indefinitely** |
| **Invalid price/tick** | N/A | Bare `Exception("price...")` raised (not `PolyApiException`) -> caught by `_route_request` broad except |
| **Malformed response** | Library-dependent error -> caught by broad except | Same |
| **Rate limited (429)** | `PolyApiException` -> caught | Same |

### FSM impact

**Bet placement:** `PolymarketBetPlacementRound` receives error -> `Event.BET_PLACEMENT_FAILED` -> **loops back to same round** (retries). After repeated failures -> `Event.ROUND_TIMEOUT` -> loops again. Eventually the outer period timeout fires and the agent moves to the next period.

No funds at risk (tx never reaches chain), but the agent is stuck retrying until timeouts fire.

### Bugs found

**BUG 8 -- LOW: httpx Client in py_clob_client — default timeout is adequate**
- The module-level `httpx.Client(http2=True)` does NOT explicitly set a timeout.
- However, httpx 0.28.1 (the installed version) **defaults to `Timeout(timeout=5.0)`** — 5 seconds for connect, read, write, and pool.
- If the API is down (connection refused, DNS failure), httpx throws `httpx.ConnectError` immediately.
- If the API is half-open (accepts connection, never responds), the 5s read timeout fires.
- **Not a real risk.** The only scenario where this matters is if someone pins httpx to an old version (<0.11) where the default was no timeout.

---

## 5. RelayClient / Polymarket Relayer

| | |
|---|---|
| **Base URL** | `https://relayer-v2.polymarket.com/` |
| **Endpoints** | `execute()` (redeem positions, set approvals) |
| **Called from** | `connections/polymarket_client/connection.py:1018,1137` |
| **Method** | POST |
| **Purpose** | Submit multi-call transactions for position redemption and approval setting |

### Failure matrix

| Failure mode | `execute()` (redeem) | `execute()` (approval) |
|---|---|---|
| **HTTP 500** | `RelayerApiException` -> caught by broad `except Exception` | Same |
| **Unreachable / timeout** | **Hangs indefinitely** (see BUG 9) | Same |
| **Invalid nonce / safe not deployed** | `RelayerClientException` -> caught | Same |
| **200 but error in body** | Library-specific parsing; `RelayerApiException` raised on API-level errors | Same |

Additionally, `result.get_transaction()` (line 1022) makes another HTTP call to the relayer to fetch transaction details -- this can also fail with `RelayerApiException` or hang.

### FSM impact

**Token approval:** `PolymarketSetApprovalRound` -> `Event.APPROVAL_FAILED` -> loops back to `PolymarketSetApprovalRound` (retries).

**Redeem:** `PolymarketRedeemRound` -> `Event.ROUND_TIMEOUT` -> loops. Special `REDEEM_ROUND_TIMEOUT` (3600s) eventually fires -> `FinishedWithoutRedeemingRound` (exits without redeeming). In the composed FSM: `FinishedWithoutRedeemingRound` -> `CallCheckpointRound`.

No funds at risk (tx never reaches chain), but the agent is stuck retrying until timeouts fire.

### Bugs found

**BUG 9 -- MEDIUM: RelayClient requests.request has no timeout**
- The internal `requests.request()` call in `py_builder_relayer_client/http_helpers/helpers.py:13` has no `timeout=` parameter.
- Unlike httpx, the `requests` library has **no default timeout** — `requests.request()` without `timeout=` will wait forever.
- If the API is fully down (connection refused, DNS failure), `requests` throws `ConnectionError` immediately — no hang.
- **The risk is half-open connections only**: load balancer accepts the TCP connection but the backend never responds. In this case, the single worker thread blocks indefinitely and all Polymarket operations stall. This scenario is uncommon but real (e.g., during partial infrastructure failures).
- **Constraint**: `py-builder-relayer-client==0.0.1` is a pinned third-party dependency — we cannot patch the library internals directly. Workaround: wrap RelayClient calls with `future.result(timeout=60)` at the connection layer.

---

## 6. CoinGecko API (POL price)

| | |
|---|---|
| **URL** | Configurable via `coingecko_pol_in_usd_price_url` param |
| **Called from** | `trader_abci/handlers.py:502` (direct `requests.get`) |
| **Method** | GET |
| **Purpose** | POL-to-USD rate for fund status display |

### Failure matrix

| Failure mode | Behavior | Fallback |
|---|---|---|
| **HTTP 500 / 429 / 403** | `status_code != 200` check -> log warning -> return cached rate or `FALLBACK_POL_TO_USD_RATE` (0.089935) | Stale cache -> hardcoded |
| **Unreachable / timeout** | `requests.get(timeout=10)` raises `ConnectionError`/`Timeout` -> caught by `except Exception` -> same fallback | Same |
| **200 but non-JSON** | `response.json()` raises -> caught by `except Exception` -> same fallback | Same |
| **200 but missing keys** | `data.get(POLYGON_POL_ADDRESS, {}).get("usd", None)` -> `None` -> `if not price_usd` -> log error -> same fallback | Same |
| **200 but `{"0x...1010": {"usd": 0}}`** | `price_usd = 0` -> `if not price_usd` is truthy for 0 -> **treats zero price as missing** -> uses fallback | Incorrect: zero is a valid (if unlikely) price |
| **`synced_timestamp` unavailable** (agent hasn't transitioned yet) | `current_time = None` -> skips cache check -> fetches fresh rate -> **doesn't cache result** (line 526) -> refetches every call | No caching until first FSM transition |

### FSM impact

Called from `_handle_get_funds_status()` -> `_get_adjusted_funds_status()` -> `_get_pol_to_usdc_rate()`. This runs in the HTTP handler context (not the FSM). If `_get_adjusted_funds_status()` hits a `KeyError` (line 446 when chain config tokens are missing from funds_status), the exception IS caught at line 446-450 and returns the unadjusted `funds_status`. No unhandled crash from that path.

### Bugs found

**BUG 10 -- MEDIUM: Stale hardcoded fallback exchange rate**
- Location: `trader_abci/handlers.py:117`
- Code: `FALLBACK_POL_TO_USD_RATE = 0.089935  # AS of 2026-02-11T18:35:09Z`
- This 30-day-old rate is used when both the API call fails AND the cache is empty. Over time it diverges from reality.
- Impact: The `/funds-status` endpoint reports incorrect USDC-to-POL conversion, causing the UI to show wrong fund levels. This could trigger unnecessary top-up warnings or hide genuine shortfalls. Used by `_ensure_sufficient_funds_for_x402_payments()` to decide if a swap is needed -- a stale rate could cause: (a) unnecessary swap (rate lower than reality -> thinks USDC is worth less POL), wasting gas, or (b) skipped swap (rate higher than reality -> thinks USDC is worth more POL), leaving USDC balance insufficient for x402. **Does NOT affect bet sizing or placement directly** -- those use on-chain data.

**BUG 11 -- LOW: `if not price_usd` treats zero as missing**
- Location: `trader_abci/handlers.py:516`
- Code: `if not price_usd:` -- returns fallback when price is 0
- If CoinGecko ever returns `"usd": 0` (extreme market event), the code treats it as a missing value and falls back to the stale rate. This is **BP4**.
- **Trigger likelihood**: Extremely low but non-zero.

**BUG 12 -- MEDIUM: Handler `_get_pol_to_usdc_rate` blocks the agent event loop**
- Location: `trader_abci/handlers.py:502`
- `requests.get(url, timeout=10)` is a synchronous call inside a handler method (NOT in the thread pool executor).
- Called from `_handle_get_funds_status` -> `_get_adjusted_funds_status` -> `_get_pol_equivalent_for_usdc` -> `_get_pol_to_usdc_rate`.
- Blocks the agent's event loop for up to 10 seconds. During this time, the agent cannot process ANY other messages.

---

## 7. CoinGecko API (OLAS price)

| | |
|---|---|
| **URL** | Configurable via `coingecko_olas_in_usd_price_url` param |
| **Called from** | `agent_performance_summary_abci/graph_tooling/requests.py:429` (framework `get_http_response`) |
| **Method** | GET |
| **Purpose** | OLAS token USD price for performance summary ROI calculations |

### Failure matrix

| Failure mode | Behavior |
|---|---|
| **HTTP 500 / unreachable** | Framework returns `HttpMessage` with `status_code=600` (unreachable) or `500`. `response.body.decode()` produces error text -> `json.loads()` fails -> caught at line 438 -> returns `None` |
| **200 but non-JSON** | `json.loads(decoded_response)` fails -> caught -> returns `None` |
| **200 but missing OLAS address key** | `.get(OLAS_TOKEN_ADDRESS, {}).get(USD_PRICE_FIELD)` -> `None` -> returns `None` |
| **200 but `{"0xce11...": {"usd": null}}`** | `usd_price = None` -> check at line 445 -> returns `None` |
| **Binary garbage in body** | `response.body.decode()` could raise `UnicodeDecodeError` -- **NOT caught** -> propagates through the behaviour's generator (see BUG 23) |

### FSM impact

Called from `calculate_roi()` in the performance summary behaviour (line 379). Returns `None` -> `calculate_roi()` returns `(None, None)` -> `self._partial_roi = None`, `self._final_roi = None` -> ROI metric gets value `"N/A"` -> `success = False` (any N/A metric fails the check) -> `FetchPerformanceDataPayload(vote=False)` -> `FetchPerformanceDataRound` receives negative votes -> **`Event.FAIL` -> `UpdateAchievementsRound`** -> proceeds to terminal state. Stale data preserved from previous successful fetch.

### Bugs found

**BUG 23 -- MEDIUM: `UnicodeDecodeError` not caught in OLAS price fetch**
- Location: `agent_performance_summary_abci/graph_tooling/requests.py:434`
- Code: `decoded_response = res_raw.body.decode()` -- no try-except
- If CoinGecko returns binary garbage (e.g., gzipped response without proper content-encoding), `UnicodeDecodeError` crashes the behaviour generator.
- **Trigger likelihood**: Low -- requires binary garbage from CoinGecko.

---

## 8. LiFi API

| | |
|---|---|
| **Base URL** | `https://li.quest/v1/quote` (hardcoded) and `https://li.quest/v1/quote/toAmount` (configurable) |
| **Endpoints** | `/quote` (swap quote), `/quote/toAmount` (reverse quote) |
| **Called from** | `decision_maker_abci/behaviours/polymarket_swap.py:261`, `agent_performance_summary_abci/behaviours.py:773`, `trader_abci/handlers.py:763` |
| **Method** | GET |
| **Purpose** | Get token swap quotes (POL<->USDC) for Polymarket operations and x402 payment funding |

### Failure matrix -- handler path (x402 top-up)

| Failure mode | Behavior |
|---|---|
| **HTTP 500 / 429 / 400 / 502** | `status_code != 200` -> log warning -> returns `None` -> `_ensure_sufficient_funds_for_x402_payments` logs "Failed to get LiFi quote" -> returns `False` |
| **Unreachable** | `requests.get(timeout=30)` raises -> caught by `except Exception` -> returns `None` |
| **200 but non-JSON** | `response.json()` raises -> caught by `except Exception` -> returns `None` |
| **200 but missing `transactionRequest`** | Caller checks `quote.get("transactionRequest")` -> `None` -> logs error -> returns `False` |

### Failure matrix -- behaviour path (swap quote / POL-USDC rate)

| Failure mode | Behavior |
|---|---|
| **HTTP 500 / unreachable** | Framework returns status 600 or 500 -> `status_code != 200` -> returns `None` (swap); returns stale `self._pol_usdc_rate` (rate, could be `None` if never fetched) |
| **200 but non-JSON** | `json.loads` raises `ValueError` -> caught -> returns `None` |
| **200 but missing `estimate.toAmount`** | `response_data.get("estimate", {}).get("toAmount")` -> `None` -> returns stale cache |

### FSM impact

**Behaviour path (swap):**
```
LiFi returns error -> _get_lifi_quote returns None -> get_tx_hash returns None
-> payload with tx_hash=None, should_swap=False
-> PolymarketSwapUsdcRound fires none_event=Event.NONE
-> DecisionRequestRound (swap skipped, pipeline continues)
```
This is resilient -- the swap is skipped but trading continues.

**Handler path (x402):** Runs in background `ThreadPoolExecutor` -- no FSM impact. Silent failure means x402 USDC balance isn't maintained.

**Behaviour path (rate):** Returns stale rate or `None` -> used for USDC equivalent calculation in performance metrics. `None` rate -> `_get_usdc_equivalent_for_pol()` returns `None` -> metrics show without USDC conversion -> performance summary is partial but not failed.

### Bugs found

No critical bugs. Error handling is adequate across all three call sites.

---

## 9. IPFS Gateway

| | |
|---|---|
| **Base URL** | `https://gateway.autonolas.tech/ipfs/` (configurable) |
| **Endpoints** | `/{CID}` (mech tools), `/{tools_accuracy_hash}` (accuracy CSV) |
| **Called from** | `decision_maker_abci/behaviours/storage_manager.py:198,275` |
| **Method** | GET |
| **Purpose** | Fetch mech tool definitions and tool accuracy data |

### Failure matrix

| Failure mode | `_get_mech_tools` | `_fetch_accuracy_info` |
|---|---|---|
| **HTTP 500** | `process_response` returns `None` -> retries | Status code check -> returns `False` -> retries via `wait_for_condition_with_sleep` |
| **Unreachable** | `status_code=600` -> `None` -> retries | Same |
| **200 but non-JSON** | `json.loads` fails -> `None` -> retries | Body decoded as text -> CSV parse produces no valid rows -> returns `False` |
| **200 but `{}`** | Empty dict stored as mech_tools -> downstream may fail | N/A (expects CSV) |

### FSM impact

```
IPFS unreachable -> retries via wait_for_condition_with_sleep (no max retry count!)
-> relies entirely on round timeout (30s) to stop retrying
-> SamplingRound fires Event.NONE -> FinishedWithoutDecisionRound
-> Service skips decision-making for this period
```

### Bugs found

**BUG 13 -- LOW: `_fetch_accuracy_info` has no max retry bound**
- Location: `decision_maker_abci/behaviours/storage_manager.py:270`
- Called via `wait_for_condition_with_sleep` which loops until `True` or round timeout. No explicit max retry count.
- Not a crash risk, but wastes the full round timeout on retries if gateway is down.

---

## 10. Olas Agents Subgraph (GraphQL)

| | |
|---|---|
| **URL** | Configurable (`context.olas_agents_subgraph.url`) |
| **Called from** | `predictions_helper.py` (direct `requests.post`), `graph_tooling/requests.py` (framework path) |
| **Method** | POST |
| **Purpose** | Trader agent data, bets, performance, prediction history, resolved markets |

### Failure matrix -- direct path (predictions_helper.py)

| Failure mode | `_fetch_trader_agent_bets` | `_fetch_bet_from_subgraph` |
|---|---|---|
| **HTTP 500** | `status_code != 200` -> returns `None` | `status_code != 200` -> returns `None` |
| **Unreachable** | `requests.post(timeout=30)` raises -> caught -> returns `None` | Same |
| **200, `{"data": null}`** | `response_data.get("data", {})` -> `None` -> `.get("marketParticipants")` -> **`AttributeError` on None** -> caught by broad `except` -> returns `None` (see BUG 24) | `.get("data", {}) or {}` -> empty dict -> `.get("traderAgent")` -> `None` -> returns `None` |
| **200, `{"data": {"marketParticipants": null}}`** | `.get("marketParticipants") or []` -> `[]` -> `if not participants` -> returns `None` | N/A for this endpoint |
| **200, bets list doesn't contain requested bet_id** | N/A | `next((b for b in bets if b.get("id") == bet_id), bets[0])` -> **falls back to first bet** -- **returns WRONG BET** (see BUG 25) |
| **200, participants exist but `"bets"` key missing** | `.get("bets", []) or []` -> empty list -> loop skips -> returns `{"totalBets": X, "bets": []}` | N/A |

### Failure matrix -- framework path (requests.py)

| Failure mode | `_fetch_from_subgraph` |
|---|---|
| **Unreachable** | Framework returns status 600 -> `process_response` tries JSON parse on traceback -> fails -> returns `None` -> `_handle_response` increments retries, sleeps |
| **HTTP 500 with JSON error body** | `process_response` parses JSON -> tries key extraction -> `UnexpectedResponseError` -> returns `None` |
| **HTTP 500 with HTML body** | JSON parse fails -> returns `None` |
| **200, valid JSON, missing expected key** | `_parse_response_data` raises `UnexpectedResponseError` -> returns `None` |
| **Retries exhausted** | `is_retries_exceeded()` -> `FetchStatus.FAIL` -> behaviour handles based on which fetch failed |

### FSM impact

**Performance summary behaviour:** Each `_fetch_*` method returning `None` causes the corresponding metric to get value `"N/A"`. Any N/A metric -> `success = False` -> `FetchPerformanceDataPayload(vote=False)`.

```
FetchPerformanceDataRound:
  - k agents vote False -> Event.FAIL -> UpdateAchievementsRound -> FinishedFetchPerformanceDataRound
  - Round timeout (30s) -> Event.ROUND_TIMEOUT -> UpdateAchievementsRound -> same terminal
  - No majority -> Event.NO_MAJORITY -> loop back to FetchPerformanceDataRound
```

**Key preservation:** Before voting, the behaviour replaces N/A metrics with values from the previous successful fetch (behaviours.py:1735-1769). Metrics, agent_details, agent_performance, profit_over_time, and prediction_history are individually preserved if the new fetch failed but existing data exists. So stale data is preserved and served to the UI even when the subgraph is down.

**Prediction history handler:** `_handle_get_predictions()` (agent_performance_summary_abci/handlers.py):
- First tries stored history from `agent_performance.json`
- Falls back to live subgraph query via `PredictionsFetcher`
- If both fail: `except Exception` -> sends HTTP 500 to client
- If stored history exists but is stale: serves stale data with HTTP 200

**Position details handler:** `_handle_get_position_details()`:
- Reads from `agent_performance.json` first
- Falls back to subgraph
- If both return `None`: sends HTTP 404 to client
- `except Exception` -> sends HTTP 500

### Bugs found

**BUG 24 -- MEDIUM: `{"data": null}` AttributeError in `_fetch_trader_agent_bets`**
- Location: `predictions_helper.py:152`
- Code: `response_data.get("data", {}).get("marketParticipants")` -- `.get("data", {})` returns `None` (not `{}`) when value is explicitly null, then `.get("marketParticipants")` raises `AttributeError`.
- Caught by broad `except Exception`, so no crash, but the `or {}` guard is missing.

**BUG 25 -- HIGH: Wrong bet returned in `_fetch_bet_from_subgraph`**
- Location: `predictions_helper.py:526`
- Code: `bet = next((b for b in bets if b.get("id") == bet_id), bets[0])` -- falls back to first bet when requested ID not found.
- **Returns WRONG BET data** (wrong profit/loss, wrong status, wrong market title) to the `/api/v1/agent/position-details/{id}` UI endpoint.
- No automated decision uses this data, but users could make manual decisions based on false information.

---

## 11. Polymarket Agents Subgraph (GraphQL)

| | |
|---|---|
| **URL** | Configurable (`context.polymarket_agents_subgraph.url`) |
| **Called from** | `polymarket_predictions_helper.py` (direct `requests.post`), `graph_tooling/requests.py` (framework) |
| **Method** | POST |

### Failure matrix

| Failure mode | `_fetch_market_participants` | `_fetch_bet_from_subgraph` |
|---|---|---|
| **HTTP 500** | Returns `None` | Returns `None` |
| **Unreachable** | Caught -> `None` | Caught -> `None` |
| **200, `{"data": null}`** | `.get("data", {}).get("marketParticipants", [])` -> `None.get()` -> **`AttributeError`** -> caught by broad except -> `None` (see BUG 26) | `.get("data", {}) or {}` -> `{}` -> `.get("marketParticipants", [])` -> `[]` -> returns `None` |
| **200, `{"data": {"marketParticipants": null}}`** | `.get("marketParticipants", [])` -> `None` (the default `[]` only applies when key is absent, not when value is null) -> returned as-is -> caller `if not market_participants` catches it | Same but with `or` guard |
| **200, bet not found** | N/A | Loop through all participants' bets -> no match -> returns `None` at line 589 |
| **200, resolution is null** | N/A | `resolution = question.get("resolution")` -> `None` -> `if not resolution` -> `net_profit = 0.0`, `status = "pending"` -- **correct behavior** |

### FSM impact

Same as Olas Agents Subgraph (#10). Performance summary uses framework path with retries. Handler endpoints fall back to stored data, then subgraph, then HTTP 404/500.

### Bugs found

**BUG 26 -- MEDIUM: `{"data": null}` AttributeError in `_fetch_market_participants`**
- Location: `polymarket_predictions_helper.py:136`
- Code: `response_data.get("data", {}).get("marketParticipants", [])` -- `.get("data", {})` returns `None`, then `.get("marketParticipants", [])` fails with `AttributeError`.
- Caught by broad `except Exception`, but the root cause is missing `or {}` guard.

---

## 12. Olas/Polygon Mech Subgraphs (GraphQL)

| | |
|---|---|
| **URL** | Configurable (`context.olas_mech_subgraph.url`, `context.polygon_mech_subgraph.url`) |
| **Called from** | `predictions_helper.py` (direct `requests.post`), `polymarket_predictions_helper.py` (direct), `graph_tooling/requests.py` (framework) |
| **Method** | POST |
| **Purpose** | Mech tool names, prediction responses (p_yes, p_no, confidence, info_utility) |

### Failure matrix

| Failure mode | `fetch_mech_tool_for_question` | `_fetch_prediction_response_from_mech` |
|---|---|---|
| **HTTP 500** | Returns `None` | Returns `None` |
| **Unreachable** | `requests.post(timeout=30)` raises -> caught -> `None` | Same |
| **200, `{"data": null}`** | `.get("data", {}) or {}` -> `{}` -> `.get("sender") or {}` -> `{}` -> `.get("requests") or []` -> `[]` -> returns `None` | `.get("data", {}) or {}` -> `.get("requests", []) or []` -> `[]` -> returns `None` |
| **200, deliveries[0].toolResponse is invalid JSON** | N/A | `json.loads(tool_response_raw)` -> `JSONDecodeError` -> caught -> returns `None` |
| **200, requests list but parsedRequest missing** | `.get("parsedRequest") or {}` -> `{}` -> `if not parsed_request` -> returns `None` | N/A |

### FSM impact

These are **enrichment-only** calls used in position detail responses. `None` return values propagate to:
- `prediction_tool: null` in API response
- `implied_probability: 0`, `confidence_score: 0`, `utility_score: 0`

No FSM state change. No round failure. Core bet data (amount, side, status, payout) is unaffected.

---

## 13. Staking Subgraphs (Gnosis + Polygon)

| | |
|---|---|
| **URL** | Configurable (`context.gnosis_staking_subgraph.url`, `context.polygon_staking_subgraph.url`) |
| **Called from** | `agent_performance_summary_abci/graph_tooling/requests.py:256-275` (framework path only) |
| **Method** | POST |

### Failure matrix

All failures go through `_fetch_from_subgraph` -> `_handle_response` retry logic.

| Failure mode | Behavior |
|---|---|
| **Any HTTP error / unreachable** | `process_response` returns `None` -> retries with backoff -> `FetchStatus.FAIL` on exhaustion |
| **200, missing expected keys** | `process_response` -> `UnexpectedResponseError` -> `None` |

### FSM impact

Called from `calculate_roi()` in performance behaviour (line 370). Returns `None` -> `calculate_roi()` returns `(None, None)` -> ROI metrics become N/A -> `vote=False` -> same flow as #7. Stale ROI data preserved from previous fetch.

---

## 14. Open Markets Subgraph (Omen)

| | |
|---|---|
| **URL** | Configurable (`context.open_markets_subgraph.url`) |
| **Called from** | `market_manager_abci/graph_tooling/requests.py` (framework path) |
| **Method** | POST |
| **Purpose** | Discover open prediction markets for Omen trading |

### Failure matrix

Same retry/backoff path as other framework subgraph calls in section 1.

### FSM impact

This feeds the `UpdateBetsRound` in `market_manager_abci`. On fetch failure:
- Behaviour sends `bets_hash=None` payload
- `UpdateBetsRound` (a `CollectSameUntilThresholdRound`) fires `none_event = Event.FETCH_ERROR`
- -> **`FailedMarketManagerRound`** (terminal)
- In composed FSM: `Event.FETCH_ERROR` -> **`ImpossibleRound`** in decision_maker
- The `ImpossibleRound` is a degenerate/terminal state -- the period ends and the agent restarts the FSM from the top on the next period.

---

## 15. Daily Profit Statistics (via Subgraph)

Not a separate service, but a distinct call path worth documenting.

| | |
|---|---|
| **Called from** | `agent_performance_summary_abci/graph_tooling/requests.py:452-508` (framework path) |
| **Purpose** | Daily profit data for profit-over-time charts |

### Failure matrix

| Failure mode | Behavior |
|---|---|
| **Fetch returns None** | `if not result: break` -> returns empty list `[]` |
| **200, `{"traderAgent": null}`** | Line 490: `result.get("traderAgent") or {}` -> `{}` -> line 493: `.get("dailyProfitStatistics")` -> `None` -> `if not result.get(...)` -> breaks loop |
| **200, stat missing `"date"` key** | Line 1341 in behaviours.py: `int(stat["date"])` -> **`KeyError`** -- **NOT caught** -> propagates up through generator (see BUG 27) |

### FSM impact

Called during `_build_profit_over_time_data()`. The `KeyError` on missing `"date"` would crash the behaviour's generator -> the behaviour fails to produce a payload within the round timeout -> `Event.ROUND_TIMEOUT` -> `UpdateAchievementsRound` -> terminal state. Stale profit data preserved.

### Bugs found

**BUG 27 -- MEDIUM: Uncaught `KeyError` on missing `"date"` in daily profit statistics**
- Location: `agent_performance_summary_abci/behaviours.py:1341`
- Code: `date_timestamp = int(stat["date"])` -- direct dict key access with no `.get()` fallback.
- If the subgraph returns a stat object without a `"date"` key, `KeyError` crashes the behaviour generator.
- **Trigger likelihood**: Low -- requires subgraph schema change.

---

## 16. Blockchain RPC (Web3)

| | |
|---|---|
| **Base URLs** | `https://1rpc.io/matic` (Polygon), `https://rpc.gnosischain.com/` (Gnosis) -- configurable |
| **Endpoints** | `eth_call`, `eth_sendRawTransaction`, `eth_getTransactionReceipt`, `eth_getTransactionCount`, `eth_gasPrice`, `eth_estimateGas` |
| **Called from** | `trader_abci/handlers.py:669-881`, `connections/polymarket_client/connection.py:1153-1189` |
| **Method** | POST (JSON-RPC) |
| **Purpose** | Check balances, submit transactions, wait for receipts, estimate gas, check allowances |

### Failure matrix

| Failure mode | `_get_web3_instance` | `_check_usdc_balance` | `_sign_and_submit_tx_web3` | `_estimate_gas` |
|---|---|---|---|---|
| **RPC unreachable** | Web3 constructor succeeds (lazy); first call fails | `w3.eth.contract().functions.balanceOf().call()` throws -> caught -> returns `None` | `w3.eth.send_raw_transaction()` throws -> caught -> returns `None` | `w3.eth.estimate_gas()` throws -> caught -> returns `None` |
| **RPC returns error JSON** | N/A | Web3 parses JSON-RPC error -> raises `ContractLogicError` or similar -> caught -> `None` | Web3 raises tx-specific exception -> caught -> `None` | Web3 raises -> caught -> `None` |
| **RPC URL empty/None** | Logs warning, returns `None` (line 662) | Gets `None` from `_get_web3_instance` -> returns `None` | Same | Same -- but returns `False` (see BUG 15) |

Connection Web3 calls (`_check_erc20_allowance`, `_check_erc1155_approval`) have **no try/except** at their own level -- caught by caller's broad except in `_check_approval`.

### FSM impact

RPC calls in the handler happen in **two contexts**:

1. **Background thread** (via `self.executor.submit`): `_ensure_sufficient_funds_for_x402_payments()` runs in a ThreadPoolExecutor. Failures log errors but do NOT block the HTTP handler or FSM. The x402 USDC balance simply doesn't get topped up.

2. **Framework ledger connection** (for main trading operations): The FSM behaviours use the framework's ledger API handler for on-chain interactions. RPC failures there cause the ledger API handler to return error responses -> behaviour receives failure -> round-specific handling (usually timeout -> retry).

### Bugs found

**BUG 14 -- MEDIUM: Web3 HTTPProvider has no timeout configured**
- Location: `trader_abci/handlers.py:669`, `connections/polymarket_client/connection.py:202`
- Code: `Web3(Web3.HTTPProvider(rpc_url))` -- no `request_kwargs={"timeout": N}`
- Default web3.py timeout is implementation-dependent. If the RPC node is unresponsive, individual calls can hang for an extended period.
- In the handler context (not thread pool), this blocks the event loop.

**BUG 15 -- MEDIUM: `_estimate_gas` returns `False` instead of `None`**
- Location: `trader_abci/handlers.py:855`
- Code: `return False` when Web3 instance creation fails (declared return type is `Optional[int]`)
- Caller checks `if tx_gas is None:` -- `False is not None` evaluates to `True`, so `False` is used as the gas value.
- `tx_data["gas"] = False` will cause a Web3 serialization error when submitting the transaction.
- **Type bug that produces confusing downstream errors.**

---

## 17. Drand Randomness Beacon

| | |
|---|---|
| **Base URL** | `https://drand.cloudflare.com/public/latest` (configurable via `RandomnessApi` in skill.yaml) |
| **Called from** | Framework randomness behaviour |
| **Method** | GET |
| **Purpose** | Fetch randomness for agent selection |

This uses the standard `ApiSpecs`/`get_http_response` framework path. Failure -> retries -> `Event.RANDOMNESS_INVALID` -> appropriate FSM handling. No custom bugs identified.

---

## 18. HTTP Handler Dispatch

| | |
|---|---|
| **Called from** | `decision_maker_abci/handlers.py:253` |
| **Purpose** | Route incoming HTTP requests to handler methods |

### Bugs found

**BUG 16 -- HIGH: No global try-catch in handler dispatch**
- Location: `decision_maker_abci/handlers.py:253`
- Code: `handler(http_msg, http_dialogue, **kwargs)` -- no try-except wrapping
- If any handler raises an unhandled exception, the HTTP client never receives a response. The connection hangs until its own timeout.
- **Affected unprotected routes:**
  - `_handle_get_agent_info` (trader_abci:279) -- no try-except at all
  - `_handle_get_funds_status` (trader_abci:593) -- no try-except
  - `_handle_get_health` (decision_maker_abci:315) -- partial protection
  - `_handle_chatui_prompt` (chatui_abci:202) -- `json.loads` without try-except
  - `_handle_get_static_file` (trader_abci:328) -- only catches `FileNotFoundError`
  - `_handle_get_features` (chatui_abci:140) -- no try-except

**BUG 17 -- HIGH: `_handle_get_agent_info` crashes pre-FSM**
- Location: `trader_abci/handlers.py:279-295`
- No try-except. Accesses `self.synchronized_data.safe_contract_address`, `self.agent_ids` (calls `json.loads`), `self.shared_state.chatui_config.trading_strategy`.
- Before the FSM has started (during agent initialization), these properties raise `AttributeError`, `TypeError`, or `JSONDecodeError`.
- Combined with BUG 16: HTTP client gets no response.

**BUG 18 -- MEDIUM: `_handle_chatui_prompt` crashes on malformed POST body**
- Location: `chatui_abci/handlers.py:202`
- Code: `data = json.loads(http_msg.body.decode("utf-8"))` -- no try-except
- A POST with non-JSON body raises `json.JSONDecodeError` that escapes to the framework.

**BUG 19 -- MEDIUM: `_handle_get_funds_status` has no try-except**
- Location: `trader_abci/handlers.py:593-605`
- Calls `_get_adjusted_funds_status()` which only catches `KeyError`. Any other exception (e.g., `AttributeError` if `funds_status` isn't populated) -> no HTTP response.

**BUG 20 -- LOW: `_handle_get_static_file` only catches `FileNotFoundError`**
- Location: `trader_abci/handlers.py:328`
- Does not catch `PermissionError`, `IsADirectoryError`, `UnicodeDecodeError`, or `OSError`.

---

## 19. x402 Payment Swap Flow

| | |
|---|---|
| **Called from** | `trader_abci/handlers.py:883` (runs in ThreadPoolExecutor) |
| **Purpose** | Auto-swap POL to USDC when USDC balance is low for x402 payments |

### Bugs found

**BUG 21 -- MEDIUM: No deduplication of swap tasks**
- Location: `trader_abci/handlers.py:599`
- Every `/funds-status` request submits `_ensure_sufficient_funds_for_x402_payments` to the single-worker executor.
- The method calls `wait_for_transaction_receipt(timeout=60)`, so a single swap blocks the executor for ~90+ seconds.
- During that time, subsequent requests queue more swap tasks. Multiple concurrent swaps could be submitted for the same shortfall.
- **Financial risk**: duplicate swap transactions drain funds.

---

## 20. Polymarket Connection Dispatch

| | |
|---|---|
| **Called from** | `connections/polymarket_client/connection.py:253` (`on_send`) |
| **Purpose** | Deserialize SRR payload and route to handler methods |

### Bugs found

**BUG 22 -- LOW: `json.loads` outside try-except in connection `on_send`**
- Location: `connections/polymarket_client/connection.py:253`
- Code: `json.loads(srr_message.payload)` is outside the `_route_request` try-except.
- A malformed SRR payload from the agent raises `JSONDecodeError` in `on_send()`. No error response is sent. The agent behaviour waits forever for a response that never comes.

---

## Summary: All Bugs Found

| # | Severity | Location | Bug | Status |
|---|----------|----------|-----|--------|
| 9 | **MEDIUM** | py_builder_relayer_client (RelayClient) | `requests.request` has no timeout -- can block worker thread on half-open connections | Open |
| 8 | **LOW** | py_clob_client (ClobClient) | httpx Client has no explicit timeout, but httpx 0.28.1 defaults to 5s -- adequate | N/A |
| 1 | **HIGH** | `market_manager_abci/models.py:67` | `Subgraph.process_response` crashes with `TypeError` when error message is `None` (`in` on `NoneType`) | **Fixed** |
| 2 | **HIGH** | `market_manager_abci/graph_tooling/requests.py:298-313` | `fetch_claim_params` uses direct dict indexing -- `KeyError` crashes generator | Open |
| 5 | **HIGH** | `connections/polymarket_client/connection.py:443` | `JSONDecodeError` bypasses retry logic in `_request_with_retries` and `_fetch_market_by_slug` (BP1) | **Fixed** |
| 6 | **HIGH** | `connections/polymarket_client/connection.py` | `_fetch_markets` can block worker thread for 11+ minutes (BP8) | Open |
| 16 | **HIGH** | `decision_maker_abci/handlers.py:253` | No global try-catch in handler dispatch | **Fixed** |
| 17 | **HIGH** | `trader_abci/handlers.py:279` | `_handle_get_agent_info` has no error handling, crashes pre-FSM | **Fixed** |
| 25 | **HIGH** | `predictions_helper.py:526` | Wrong bet returned: `next(..., bets[0])` falls back to first bet instead of `None` | **Fixed** |
| 3 | **MEDIUM** | `market_manager_abci/graph_tooling/requests.py:244,363` | Batched trade fetching crashes on missing dict keys | Open |
| 4 | **MEDIUM** | `market_manager_abci/graph_tooling/requests.py` | Retry backoff (31s) exceeds round timeout (30s) | Open |
| 10 | **MEDIUM** | `trader_abci/handlers.py:117` | Stale hardcoded `FALLBACK_POL_TO_USD_RATE` (30 days old) | Open |
| 12 | **MEDIUM** | `trader_abci/handlers.py:502` | Synchronous `requests.get` in handler blocks event loop up to 10s | Open |
| 14 | **MEDIUM** | `trader_abci/handlers.py:669` | Web3 HTTPProvider has no timeout configured | Open |
| 15 | **MEDIUM** | `trader_abci/handlers.py:855` | `_estimate_gas` returns `False` instead of `None` (type bug) | **Fixed** |
| 18 | **MEDIUM** | `chatui_abci/handlers.py:202` | `json.loads` without try-except crashes on malformed POST | **Fixed** |
| 19 | **MEDIUM** | `trader_abci/handlers.py:593` | `_handle_get_funds_status` has no try-except | **Fixed** |
| 21 | **MEDIUM** | `trader_abci/handlers.py:599` | No deduplication of x402 swap tasks -- duplicate transactions possible | Open |
| 7 | **MEDIUM** | `connections/polymarket_client/connection.py` | No retries on `_fetch_market_by_slug`, `_get_positions`, `_get_trades` | Open |
| 23 | **MEDIUM** | `agent_performance_summary_abci/graph_tooling/requests.py:434` | `UnicodeDecodeError` not caught in OLAS price fetch | **Fixed** |
| 24 | **MEDIUM** | `predictions_helper.py:152` | `{"data": null}` -> `AttributeError` -- missing `or {}` guard | **Fixed** |
| 26 | **MEDIUM** | `polymarket_predictions_helper.py:136` | `{"data": null}` -> `AttributeError` -- missing `or {}` guard | **Fixed** |
| 27 | **MEDIUM** | `agent_performance_summary_abci/behaviours.py:1341` | Uncaught `KeyError` on missing `"date"` in daily profit statistics | **Fixed** |
| 11 | **LOW** | `trader_abci/handlers.py:516` | `if not price_usd` treats zero as missing (BP4) | **Fixed** |
| 13 | **LOW** | `decision_maker_abci/behaviours/storage_manager.py` | `_fetch_accuracy_info` has no max retry bound | Open |
| 20 | **LOW** | `trader_abci/handlers.py:328` | `_handle_get_static_file` only catches `FileNotFoundError` | Open |
| 22 | **LOW** | `connections/polymarket_client/connection.py:253` | `json.loads` outside try-except in `on_send` | **Fixed** |

---

## Severity Classification by Service

| Severity | Service | Failure Impact | FSM Outcome |
|----------|---------|----------------|-------------|
| **MEDIUM** | Polymarket Relayer (#5) | Trades cannot execute; half-open connections block worker thread | Round retries until timeout; period ends without trading. Half-open hang requires restart (rare). |
| **LOW** | CLOB API (#4) | Bet placement blocked; httpx default 5s timeout adequate | httpx 0.28.1 defaults to `Timeout(timeout=5.0)`. Down API throws immediately; half-open times out in 5s. |
| **HIGH** | Gamma API (#2) | No new markets discovered | `FETCH_ERROR` -> `FailedMarketManagerRound` -> `ImpossibleRound` |
| **HIGH** | Open Markets Subgraph (#14) | No Omen markets discovered | Same as Gamma API |
| **HIGH** | Agents Subgraphs (#10, #11) | Performance + prediction history unavailable | `Event.FAIL` -> stale data preserved; UI endpoints fall back to stored data or return 404/500 |
| **MEDIUM** | LiFi API (#8) | x402 USDC top-up fails | Background thread; no FSM impact; agent may lose paid API access |
| **MEDIUM** | Data API (#3) | Position data missing | Connection returns error; potential duplicate bet attempts |
| **LOW** | CoinGecko POL (#6) | Cache -> hardcoded fallback | No FSM impact; UI fund status shows stale rate |
| **LOW** | CoinGecko OLAS (#7) | ROI calculation aborted | `Event.FAIL` in perf summary; stale ROI preserved |
| **LOW** | Mech Subgraphs (#12) | Enrichment fields null | No FSM impact; UI shows 0 for probability/confidence |
| **LOW** | Staking Subgraphs (#13) | ROI calculation aborted | Same as OLAS price |

---

## Operational Impact Classification

### A. What can CRASH the agent

| # | Trigger | Where the exception escapes | How external failure causes it |
|---|---------|---------------------------|-------------------------------|
| A1 | **`JSONDecodeError` in Polymarket connection** (BUG 5) | `_request_with_retries` (connection.py:443) and `_fetch_market_by_slug` (connection.py:707) call `response.json()` after `raise_for_status()`. `JSONDecodeError` is a `ValueError`, not `RequestException`, so it escapes the except clause. | Gamma API / Data API returns HTTP 200 with HTML body (common during CDN outages or API gateway errors). The connection handler crashes. Since BaseSyncConnection runs in a thread, this kills the connection thread -- all subsequent Polymarket requests fail with no response. |
| A2 | **`TypeError` in `Subgraph.process_response`** (BUG 1) | `models.py:67`: `the_graph_payment_required_error in error_message` where `error_message` is `None`. | The Graph returns error response with unexpected structure (missing message key). |
| A3 | **`KeyError` in `fetch_claim_params`** (BUG 2) | `requests.py:298-313`: direct dict indexing on subgraph answer data. | Subgraph returns answer with missing keys (schema change or partial response). |
| A4 | **`KeyError` on missing `"date"` in daily profit stats** (BUG 27) | `behaviours.py:1341`: `int(stat["date"])` with no fallback. Called from `_build_profit_over_time_data()` -> `_fetch_agent_performance_summary()` -> `async_act()`. No try-catch at any level. | Subgraph returns a stat object with unexpected schema (missing `"date"` key). The `FetchPerformanceSummaryBehaviour` generator crashes. Payload is never sent. |
| A5 | **`UnicodeDecodeError` in OLAS price fetch** (BUG 23) | `requests.py:434`: `response.body.decode()` with no except. | CoinGecko returns binary garbage in response body (e.g., gzipped response without proper content-encoding). |
| A6 | **`KeyError` in batched trade fetching** (BUG 3) | `requests.py:244`: `trades_chunk[-1]["fpmm"]["creationTimestamp"]`. | Subgraph returns trade with missing `fpmm` key. |
| A7 | **`AttributeError` on `_handle_get_agent_info`** (BUG 17) | `handlers.py:279`: accesses `synchronized_data.safe_contract_address` before FSM starts. | Early health check from load balancer or monitoring system. |
| A8 | **`JSONDecodeError` on chatui POST** (BUG 18) | `chatui_abci/handlers.py:202`: `json.loads(http_msg.body.decode("utf-8"))`. | Malformed POST body from client. |

**What happens after a behaviour crash:**
1. The generator raises an exception that escapes `__handle_tick()`.
2. The AEA framework's skill handler catches it and logs a traceback.
3. **The behaviour is marked as done without sending a payload.**
4. The round never receives a payload from this agent.
5. If enough agents crash (below consensus threshold), the round can never reach consensus.
6. `Event.ROUND_TIMEOUT` (30s) fires -> FSM transitions per the round's timeout mapping.
7. For `FetchPerformanceDataRound`: timeout -> `UpdateAchievementsRound` -> `FinishedFetchPerformanceDataRound` -> period continues. **Agent survives.**
8. For `UpdateBetsRound`: timeout -> loops back to `UpdateBetsRound` -> if it keeps crashing, the agent is stuck in a timeout loop until the period timeout fires.

**Net assessment:** A1 is the most likely crash path. CDN outages returning HTML 200 are common. A2 depends on The Graph's error response format (outside our control). A4 and A5 require subgraph schema change or binary garbage (rare). A7 is common in containerized deployments with health checks.

---

### B. What can get the agent STUCK

| # | Trigger | Mechanism | Duration | Recovery |
|---|---------|-----------|----------|----------|
| B1 | **Relayer API half-open connection** (BUG 9) | requests.request with no timeout blocks worker thread on half-open connection (load balancer accepts TCP but backend never responds) | **Indefinite** (half-open only) | Agent restart only. Note: fully down API throws `ConnectionError` immediately. |
| B2 | ~~CLOB API unresponsive~~ (BUG 8) | httpx 0.28.1 defaults to `Timeout(timeout=5.0)` — 5s for connect, read, write, pool. Not a real stuck risk. | **5s max** | Automatic |
| B3 | **Gamma API returning 5xx on all categories** (BUG 6) | 11 categories x 60s retry ceiling in single thread | **11+ minutes** | Automatic (retries exhaust) |
| B4 | **Background executor blocks on RPC** | `_ensure_sufficient_funds_for_x402_payments()` runs in `ThreadPoolExecutor(max_workers=1)`. `w3.eth.wait_for_transaction_receipt(timeout=60)` blocks the thread. Second submission queues behind. | **60-120s per blocked call** | Executor is not on the FSM path -- agent trading continues. But `/funds-status` HTTP endpoint blocks until executor is free. |
| B5 | **Subgraph retry backoff exceeds round timeout** (BUG 4) | `_handle_response()` sleeps with exponential backoff: `backoff_factor^retries_attempted`. 5 retries = 1+2+4+8+16 = 31s total. Round timeout is 30s. | **31s worst case** | The sleep is `yield from self.sleep()`, which is cooperative. The round timeout fires via Tendermint. The timeout event transitions the FSM, but the sleeping behaviour continues until it yields -- it just becomes irrelevant because the round has moved on. |
| B6 | **CoinGecko slow/down** (BUG 12) | Synchronous `requests.get(timeout=10)` in handler blocks event loop | **Up to 10s** | Automatic (timeout) |
| B7 | **RPC node unresponsive** (BUG 14) | Web3 calls without explicit timeout | **Default timeout (varies)** | Automatic (eventual timeout) |
| B8 | **Malformed SRR payload** (BUG 22) | No response sent, behaviour waits forever | **Until round timeout** | Automatic if timeout configured |
| B9 | **`FailedMarketManagerRound` -> `ResetAndPauseRound` loop** | If market fetching fails every period: fail -> reset -> fetch -> fail again. | **Indefinite** (until API recovers) | By design -- agent keeps retrying each period. `ResetAndPauseRound` has its own timeout; if it also fails: `FinishedResetAndPauseErrorRound` -> `ResetAndPauseRound` (loops). |
| B10 | **`ImpossibleRound` in decision_maker** | Some error transitions go to `ImpossibleRound` (degenerate terminal). Reachable from `SamplingRound`, `BlacklistingRound`, `BenchmarkingRandomnessRound`, etc. via `FETCH_ERROR` or `NONE` events. | **Period stuck** | Period timeout eventually fires and resets. |

**Net assessment:** B1 (Relayer half-open connection) is the only indefinite-hang risk, but requires the rare condition of a half-open TCP connection. B3 (Gamma API blocking 11+ minutes) is the most impactful in practice — it stalls the single worker thread for the entire retry budget. B9 is the most common under sustained outage — agent loops without trading.

---

### C. Agent keeps running with UNINTENDED SIDE-EFFECTS

| # | Trigger | Side-effect | Severity | Trading impact? |
|---|---------|-------------|----------|-----------------|
| C1 | **Stale `FALLBACK_POL_TO_USD_RATE`** (BUG 10) | When CoinGecko fails and cache is empty, fund status uses a hardcoded rate from 2026-02-11 (0.089935). | **HIGH** | **Indirect.** Used by `/funds-status` and `_ensure_sufficient_funds_for_x402_payments()` to decide if a swap is needed. Stale rate could cause: (a) unnecessary swap (wasting gas), or (b) skipped swap (leaving USDC insufficient for x402). **Does NOT affect bet sizing or placement directly** -- those use on-chain data. |
| C2 | **Wrong bet returned in position details** (BUG 25) | `predictions_helper.py:526` returns first bet when requested ID not found. Wrong profit/loss, wrong status, wrong market title shown to user. | **MEDIUM** | **No.** Only affects `/api/v1/agent/position-details/{id}` UI endpoint. No automated decision uses this data. However, user could make manual decisions based on false information. |
| C3 | **Stale market categories (partial Gamma API failure)** | If Gamma API fails for some categories but not others, agent trades only on available categories. | **MEDIUM** | **Yes, indirectly.** No diversification enforcement exists. If only 2 of 10 categories return markets, the agent concentrates bets there. Existing bet priority logic still applies -- won't over-bet on a single market, but a narrow set of categories. Concentration risk, not a bug -- but an unintended consequence of partial API failure. |
| C4 | **Duplicate swap transactions** (BUG 21) | Multiple rapid `/funds-status` requests queue duplicate swaps in the single-worker executor. | **MEDIUM** | **Yes, financial.** Excess swaps drain POL balance. |
| C5 | **`_estimate_gas` returns `False`** (BUG 15) | `tx_gas=False` used in transaction dict. Web3 serialization error on submit. | **MEDIUM** | Transaction fails with confusing error rather than being cleanly skipped. |
| C6 | **Zero-default prediction scores in UI** | When mech subgraph fails, position details show `implied_probability: 0`, `confidence_score: 0`, `utility_score: 0`. | **LOW** | **No.** Trading decisions use mech responses from synchronized data, not cached position details. UI-only. |
| C7 | **Empty `external_url` for positions** | When `_fetch_market_slug()` fails silently. | **NONE** | Purely a broken link in the UI. |
| C8 | **Stale performance summary with `vote=False`** | When subgraph fetches fail, stale metrics are preserved from previous successful fetch (behaviours.py:1735-1769). | **LOW** | **No.** Performance summary is read by UI endpoints only. Achievements may be calculated on stale data, but achievements don't affect trading. |
| C9 | **x402 USDC not topped up** | Background thread fails to swap native token -> USDC. | **MEDIUM** | **Partial.** x402 is used by the GenAI connection for chat/UI features, NOT for mech interactions or trading. If USDC runs out, the chat interface breaks but trading continues. |
| C10 | **Duplicate bet placement on Polymarket** | If the connection response for a successful bet is lost (crash between placement and state update), the agent could re-sample the same market. | **LOW** (with caveats) | **Theoretically yes, but well-mitigated.** Sampling logic uses `queue_status` and `processed_timestamp` from `bets.json`. The only gap: crash AFTER relayer accepts order but BEFORE `bets.json` update. Mitigated by: (a) Polymarket's "duplicated order" detection, (b) market price movement, (c) blacklisting mechanism. Real-world risk is very low. |

**Net assessment:** C1 is the highest-risk side-effect because it affects financial calculations with a stale rate that diverges over time. C4 (duplicate swaps) has direct financial risk. C3 is an inherent risk of partial API failure with no mitigation. The rest are UI-only or well-mitigated.

---

## Cross-cutting Issues

### CC1: Inconsistent retry strategies

| Call site | Retries | Backoff type | Max wait per call | Timeout param |
|-----------|---------|-------------|-------------------|---------------|
| Subgraph queries (framework path) | Configurable (default ~5) | Exponential (`2^n`) | ~31s total sleep | Framework default |
| `_request_with_retries` (connection) | 3 | Linear (`10 * (n+1)`) | 60s total | 10s |
| `_fetch_market_by_slug` (connection) | 0 | N/A | 10s | 10s |
| `_get_positions` / `_get_trades` (connection) | 0 | N/A | 10s | 10s |
| CoinGecko (handler) | 0 | N/A | 10s | 10s |
| LiFi (behaviour) | 0 | N/A | Framework default | Framework default |
| LiFi (handler) | 0 | N/A | 30s | 30s |
| ClobClient (library) | 0 | N/A | **5s** (httpx default) | **5s** (httpx 0.28.1 default `Timeout(timeout=5.0)`) |
| RelayClient (library) | 0 | N/A | **None (infinite)** | **None** (requests has no default timeout) |
| Web3 RPC (handler) | 0 | N/A | **Default (varies)** | **Not set** |
| Subgraph queries (direct requests) | 0 | N/A | 30s | 30s |
| IPFS gateway (behaviour) | Unbounded | Via `wait_for_condition_with_sleep` | Round timeout | Framework default |
| `_fetch_market_slug` (predictions helper) | 0 | N/A | 10s | 10s |

**Assessment:** Wide inconsistency. The RelayClient (position redemption) has zero retries and no timeout, while market data queries have 3 retries with 60s blocking. ClobClient benefits from httpx's 5s default timeout but still has zero retries.

### CC2: No circuit breaker

No circuit breaker pattern exists anywhere in the codebase. Under sustained API outage:
- Subgraph queries retry every period (every ~30s), burning the full retry budget each time
- Connection retries block the single worker thread repeatedly
- No backoff between periods -- the agent immediately retries after each failed period

### CC3: Inconsistent error reporting

- Subgraph failures: `WARNING` or `ERROR` depending on the specific call
- Connection failures: `WARNING` during retries, `ERROR` on final failure
- Handler failures: Mix of `WARNING`, `ERROR`, and **silent returns** (no logging at all in some paths)
- No structured error tracking, metrics, or alerting hooks

### CC4: Stale cached/fallback data

| Value | Location | Max staleness | Drift impact |
|-------|----------|---------------|--------------|
| `FALLBACK_POL_TO_USD_RATE = 0.089935` | `handlers.py:117` | Unbounded (hardcoded) | POL price can move 10-50% in a month |
| `_pol_usdc_rate` cache | `handlers.py:134-136` | 2 hours (`COINGECKO_RATE_CACHE_SECONDS`) | Low risk within 2h window |
| `LIFI_RATE_LIMIT_SECONDS = 7200` | `behaviours.py:85` | N/A (rate limit, not data) | N/A |
| Performance summary metrics | `agent_performance.json` (via behaviours.py:1735-1769) | Unbounded (preserved from last successful fetch) | N/A for trading; UI shows increasingly stale performance data |

### CC5: Missing `timeout` on requests

| Call site | Library | Timeout set? |
|-----------|---------|-------------|
| `_request_with_retries` | requests | Yes (10s) |
| `_fetch_market_by_slug` | requests | Yes (10s) |
| `_get_positions` / `_get_trades` | requests | Yes (10s) |
| CoinGecko handler | requests | Yes (10s) |
| LiFi handler | requests | Yes (30s) |
| Prediction helpers (all) | requests | Yes (30s) |
| Gamma API (perf summary) | requests | Yes (10s) |
| ClobClient internal | httpx | Yes (5s default) |
| RelayClient internal | requests | **NO** |
| Web3 HTTPProvider | urllib3 | **NO (default)** |

### CC6: Thread safety

With `MAX_WORKER_THREADS=1` in the Polymarket connection, data races on instance variables are prevented. The handler's `ThreadPoolExecutor(max_workers=1)` similarly prevents races.

However, BUG 21 (duplicate swap tasks) is a concurrency issue: multiple tasks can be queued in the executor, each performing the same swap operation because there's no lock or deduplication guard.

### CC7: `{"data": null}` vs `{"data": {}}` inconsistency

Multiple methods use `.get("data", {})` expecting a dict default, but when the API returns `"data": null`, `.get()` returns `None` (not the default `{}`). The `or {}` guard is applied inconsistently -- present in some methods (e.g., `_fetch_bet_from_subgraph` in polymarket helper), missing in others (e.g., `_fetch_trader_agent_bets` at predictions_helper.py:152, `_fetch_market_participants` at polymarket_predictions_helper.py:136).

---

## Combined Priority Matrix

| Priority | Issue | Category | Fix complexity | Fix description | Status |
|----------|-------|----------|----------------|-----------------|--------|
| **P0** | BUG 16: No global try-catch in handler dispatch | Crash | Low | Wrap `handler(http_msg, http_dialogue, **kwargs)` at `decision_maker_abci/handlers.py:253` in `try/except Exception` that sends HTTP 500. | **Fixed** |
| **P0** | BUG 5: JSONDecodeError bypasses retries and crashes connection | Crash | Low | Change `except requests.exceptions.RequestException` to `except (requests.exceptions.RequestException, ValueError)` in `_request_with_retries` and `_fetch_market_by_slug`. | **Fixed** |
| **P1** | BUG 1: Subgraph.process_response TypeError on None error message | Crash | Low | Add `if error_message is not None:` guard before the `in` check at `models.py:67`. | **Fixed** |
| **P1** | BUG 21: No deduplication of x402 swap tasks | Side-effect | Low | Add a `self._swap_in_progress` flag checked before `executor.submit()`. Use `threading.Lock` or check `Future.running()`. | Open |
| **P1** | BUG 10: Stale fallback exchange rate | Side-effect | Medium | Add timestamp tracking; refuse to use fallback older than N hours; log critical alert. | Open |
| **P1** | BUG 25: Wrong bet returned in position details | Side-effect | Low | Change `next(..., bets[0])` to `next(..., None)` at `predictions_helper.py:526`. | **Fixed** |
| **P2** | BUG 2: fetch_claim_params KeyError risk | Crash | Medium | Wrap the list comprehension at `requests.py:298-313` in try/except KeyError, or use `.get()` with validation. | Open |
| **P2** | BUG 17: _handle_get_agent_info no error handling | Crash | Low | Wrap body in try/except Exception that sends HTTP 500. | **Fixed** |
| **P2** | BUG 15: _estimate_gas returns False | Side-effect | Low | Change `return False` to `return None` at `handlers.py:855`. | **Fixed** |
| **P2** | BUG 18: _handle_chatui_prompt json.loads crash | Crash | Low | Wrap `json.loads` in try/except JSONDecodeError that sends 400 Bad Request. | **Fixed** |
| **P2** | BUG 9: RelayClient requests has no timeout (half-open risk) | Stuck | Medium | `py-builder-relayer-client==0.0.1` is a third-party dep. Wrap RelayClient calls with `future.result(timeout=60)` to enforce a deadline at the connection layer. | Open |
| **P2** | BUG 12: Synchronous requests.get blocks event loop | Stuck | Medium | Move CoinGecko fetch into the ThreadPoolExecutor, or use the framework's async HTTP path. Increase `max_workers` to 2 if sharing executor. | Open |
| **P2** | BUG 14: Web3 HTTPProvider no timeout | Stuck | Low | Add `request_kwargs={"timeout": 30}` to `Web3.HTTPProvider()` calls. | Open |
| **P2** | BUG 24/26: `{"data": null}` AttributeError guards | Crash (potential) | Low | Add `or {}` after `.get("data", {})` in `predictions_helper.py:152` and `polymarket_predictions_helper.py:136`. | **Fixed** |
| **P2** | BUG 27: KeyError on missing "date" in profit stats | Crash | Low | `stat.get("date")` with fallback, or wrap loop body in try-except. | **Fixed** |
| **P3** | BUG 23: UnicodeDecodeError in OLAS price fetch | Crash | Low | Wrap `response.body.decode()` in try-except at `requests.py:434`. | **Fixed** |
| **P3** | BUG 6: _fetch_markets blocks thread 11+ min | Stuck | Medium | Cap total retry time per `_fetch_markets` call. Add a deadline parameter. Consider parallelizing category fetches. | Open |
| **P3** | BUG 4: Retry backoff exceeds round timeout | Stuck | Low | Cap cumulative sleep to 80% of round timeout, or make retry logic aware of remaining time. | Open |
| **P3** | BUG 19: _handle_get_funds_status no try-except | Crash | Low | Wrap body in try/except Exception. | **Fixed** |
| **P3** | BUG 3: Batched trade fetching KeyError | Crash | Low | Use `.get()` with validation for `fpmm` and `creationTimestamp` keys. | Open |
| **P3** | C3: Category concentration risk | Side-effect | High | Add minimum-category-count check before proceeding with trading. | Open |
| **P3** | CC1: Inconsistent retry strategies | All | High | Standardize retry configuration. Create a shared retry utility with configurable max retries, backoff type, and timeout awareness. | Open |
| **P3** | CC2: No circuit breaker | All | High | Implement circuit breaker pattern for repeated failures to the same service. Track consecutive failures; skip retries for N seconds after M failures. | Open |
| **P3** | B9: Reset loop under sustained outage | Stuck | Medium | Add exponential backoff between periods during repeated failures. | Open |
| **P4** | BUG 7: Inconsistent retries in connection | Various | Medium | Add retry logic to `_fetch_market_by_slug`, `_get_positions`, `_get_trades`. | Open |
| **P4** | BUG 11: `if not price_usd` treats zero as missing | Side-effect | Low | Change to `if price_usd is None:`. | **Fixed** |
| **P4** | BUG 13: No max retry for accuracy fetch | Stuck | Low | Add max_retries parameter to `wait_for_condition_with_sleep` call. | Open |
| **P4** | BUG 20: Static file handler incomplete exception handling | Crash | Low | Broaden except clause to catch `OSError`. | Open |
| **P4** | BUG 8: ClobClient httpx timeout | N/A | None | httpx 0.28.1 defaults to `Timeout(timeout=5.0)`. No fix needed — default timeout is adequate. | N/A |
| **P4** | BUG 22: json.loads outside try-except in on_send | Stuck | Low | Move `json.loads(srr_message.payload)` inside `_route_request` or add try/except in `on_send`. | **Fixed** |
| **P4** | C9: x402 USDC depletion | Side-effect | Low | Add monitoring/alerting for x402 balance. | Open |
