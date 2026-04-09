# Tool Selection Pipeline — Merged Spec (Draft)

**Status:** Draft, in active design.

### Source proposals merged

- [**Proposal: Algorithm for tool selection in mech-interact**](https://docs.google.com/document/d/14qbNuJJ9eK2_YFjlwkyx_eO_vulU6BMk9UhHdiBjPFc/edit?tab=t.0#heading=h.q1k3gt1ns4rd) — two-gate filtering (category + reputation), original proposal. The local `Proposal_ Algorithm for tool selection in mech-interact.md` at the trader repo root is an export/copy of this Google Doc; the doc is canonical.
- [**Benchmark Proposal Update gist**](https://gist.github.com/DIvyaNautiyal07/20c01c4b70304ff1d860372dab404e6b) — evaluation metrics (Brier-first), dynamic routing, scorer additions.
- [`BUG_REPORT_NVM_SUBSCRIPTION_DEADLOCK.md`](./BUG_REPORT_NVM_SUBSCRIPTION_DEADLOCK.md) — local file in this repo. Motivates the capability gate and the adjacent NVM FSM safety fixes.

### Affected components

| Component | Repo | Role in this spec |
|---|---|---|
| `trader` | [`valory-xyz/trader`](https://github.com/valory-xyz/trader) | Layer 2 (segment-aware `EGreedyPolicy`); category classifier consumer; `tradeable_categories` config |
| `mech-interact` | [`valory-xyz/mech-interact`](https://github.com/valory-xyz/mech-interact) | Layer 1 (catalog gates: category, capability, reputation, cold-start grace). Vendored into trader at `packages/valory/skills/mech_interact_abci/`; file paths in this spec refer to that vendored copy. |
| `mech-predict` | [`valory-xyz/mech-predict`](https://github.com/valory-xyz/mech-predict) | Layer 3 (benchmark loop, scorer additions, segment-keyed CSV publish, shared `classify_category()`) |

This spec describes the target end-state, locked decisions, and remaining open questions.

---

## TL;DR

Tool selection today is a single-key E-Greedy policy in the trader, with no quality filtering on the mech catalog beyond a static `irrelevant_tools` blocklist. We propose a three-layer pipeline with clean ownership boundaries:

```
ELIGIBILITY (catalog gates)  →  PERFORMANCE (segment routing)  →  FEEDBACK (benchmarks)
        in mech-interact              in trader / EGreedyPolicy        in mech-predict
```

- **Layer 1 (mech-interact):** filter the mech/tool catalog. Three gates run at pool construction time: category, capability, reputation. Plus a cold-start grace period.
- **Layer 2 (trader):** category-aware tool selection. Extend `EGreedyPolicy` to key its accuracy store by `(tool, category)` and consume one new optional column in the existing IPFS performance CSV. Platform dimension is already handled at deployment time — each service points `TOOLS_ACCURACY_HASH` at its own platform's CSV.
- **Layer 3 (mech-predict):** benchmark loop produces the category-keyed CSVs (per platform). Brier-first ranking; edge and conditional accuracy are diagnostics, not ranking signals.

---

## Architectural principles

- **Mech selection is mech-interact's job. Tool selection is the caller's job.** Mech-interact provides a clean catalog and routes a chosen tool to a qualified mech. The caller (trader) decides *which tool* to use given task-specific signals. mech-interact never sees Brier scores, market platforms, or question categories.
- **Catalog filtering is declarative and composable.** Each gate filters on a single attribute. The four gates are: category (mech-level), capability (mech-level), reputation (mech-level), and name (tool-level — the existing `irrelevant_tools` list, kept as a first-class fourth dimension).
- **Cold start is explicit.** A grace period guarantees new mechs a fair trial; the gate's spam-filtering teeth take over after the trial.
- **Brier first.** Tool ranking optimises for accuracy, not edge. Edge is a system diagnostic, not a tool ranking signal.
- **Backward compatibility = safe default.** Every new param defaults to "off" / "no gate" so existing deployments are unaffected until they opt in.

---

## Layer 1 — Catalog gates (mech-interact)

All gates run inside `mech_interact_abci/behaviours/mech_info.py::populate_tools()` (or its successor) at pool construction time. Pool is rebuilt per period.

### Gate composition order

```
for mech in candidate_mechs:
    if mech.received_requests < COLD_START_GRACE:    # 1. Grace bypass
        admit(mech)
        continue
    if not category_match(mech, task_type):           # 2. Category gate
        skip(mech); continue
    if not capability_match(mech, allowed_payment_types):  # 3. Capability gate
        skip(mech); continue
    if mech.gate_score < min_mech_score:              # 4. Reputation gate
        skip(mech); continue
    admit(mech)
```

Order rationale: grace runs first (otherwise it'd be redundant). Category is cheap and discards the most volume. Capability requires `payment_type` cached on `MechInfo`. Reputation is last because the score computation is the most expensive.

### 1. Cold-start grace period

**Locked.** A mech with `received_requests < 20` (counted from the subgraph, **global** across all agents) bypasses all reputation/capability/category checks and enters the pool.

- **Rationale:** prevents the death spiral where a new mech can't earn reputation because the gate excludes it before it gets a chance.
- **Why global:** if the mech has already been hammered by other agents on the network and proven bad, this agent shouldn't grant it a fresh local trial. Subgraph already exposes `received_requests` per mech.
- **Why 20:** at 20/20 successful deliveries, Wilson lower bound ≈ 0.83 → `gate_score ≈ 0.90` — solidly clear of the reputation gate. At 0/20, Wilson ≈ 0 → fails immediately at request #21. Clean handoff.

### 2. Category gate (Gate 1 in source docs)

Mech operators self-declare a `category` in IPFS metadata. Caller sets `task_type` in `skill.yaml`. Tool is admitted if its declared category matches `task_type`.

**IPFS metadata schema (hybrid, backward compatible):**

```json
// Per-tool (most flexible)
{ "tools": [
    { "name": "prediction-online", "category": "prediction" },
    { "name": "image-gen-sd", "category": "image_generation" }
] }

// Mech-level (simpler, single-purpose mechs)
{ "tools": ["prediction-online", "prediction-offline"], "category": "prediction" }

// Legacy (still works, all tools = uncategorized)
{ "tools": ["prediction-online", "prediction-offline"] }
```

**Parser fallback chain:** per-tool category → mech-level category → `"uncategorized"`.

**Caller behaviour:**
- `task_type = null` (default): no filtering, all categories pass (today's behaviour)
- `task_type = "prediction"`: only tools with declared category `"prediction"` pass; **uncategorized tools are excluded** (caller opted in)

**Vocabulary:** free-form initially (npm-keywords-style). Operators converge on common values. Registry deferred until collisions are observed.

**Caller config (trader):** `task_type: prediction` in `decision_maker_abci/skill.yaml`.

**Known limits (acknowledged):**
- Self-declared, no on-chain verification — a mech can lie. Reputation gate + Layer 3 benchmarks catch this over time.
- No enforcement of category semantics — a mech can declare `prediction` and return random numbers. Same answer: Layer 3.

### 3. Capability gate (new — from NVM bug)

Filter mechs whose payment type the caller cannot satisfy.

**Param shape (in `MechInteractParams`):**
```yaml
allowed_payment_types: null   # default: no gate, today's behaviour
# or e.g.
allowed_payment_types: ["NATIVE", "TOKEN_USDC", "TOKEN_OLAS"]
```

**Vocabulary:** the existing `PaymentType` enum (`mech_interact_abci/behaviours/request.py:85-91`):
- `NATIVE`
- `TOKEN_USDC`
- `TOKEN_OLAS`
- `NATIVE_NVM`
- `TOKEN_NVM_USDC`

**Plumbing (locked):** today, payment type is discovered *per request* in `_fetch_and_validate_payment_type()` (`behaviours/request.py:690`), which calls `_get_payment_type()` (`behaviours/request.py:634-647`) against `MechMM.contract_id`. The wrapper, the contract method, and the data flow all already exist — they're just wired into the request path instead of pool construction.

**Implementation:**

1. **`MechInfo` field:** add `payment_type: Optional[PaymentType] = None` to the dataclass at `states/base.py:168-272`.
2. **Behaviour-level cache:** add `_payment_type_cache: Dict[str, PaymentType]` as an instance attribute on `MechInformationBehaviour` (`behaviours/mech_info.py:48`). Lives for the agent's lifetime; cold starts re-fetch.
3. **Populate in `populate_tools()`:** after the IPFS metadata fetch for each mech (already a per-mech HTTP call), check the cache. On hit, copy into `mech.payment_type`. On miss, `yield from self._get_payment_type_for(mech.address)`, store on cache and on `mech.payment_type`.
4. **Capability filter:** in the `mech_tools` property (`states/base.py:319-324`) or alongside the existing `irrelevant_tools` filter, drop mechs whose `payment_type ∉ self.params.allowed_payment_types` (when the param is non-`None`).
5. **Cold start cost:** ~50 sequential eth_calls × ~100ms ≈ ~5 seconds, once per agent lifetime. Subsequent periods amortise to ~0 (only any new mechs require a fresh call).
6. **Persistence (deferred):** in-memory only for v1. If durability across agent restarts becomes desirable, plumb through `storage_manager.py` (same pattern as `tools_accuracy_hash`) as a follow-up.

**Subgraph extension considered and deferred.** The query at `graph_tooling/queries/mechs_info.py:24-57` does not currently expose `payment_type`. Adding it would eliminate the contract calls but requires subgraph migration; not worth the cost at this scale.

**NVM deadlock fix as a side effect:** trader sets `allowed_payment_types: ["NATIVE", "TOKEN_USDC", "TOKEN_OLAS"]`, NVM mechs never reach the FSM, the deadlock is impossible. This is the long-term proper fix; the short-term ship-now patch (Option B from `BUG_REPORT_NVM_SUBSCRIPTION_DEADLOCK.md` — penalize NVM mech and fall through) remains valid until the capability gate ships.

### 4. Reputation gate (Gate 2 in source docs)

After category and capability, enforce a quality floor on mech reliability + activity.

**Score formula:**
```
gate_score = 0.6 × wilson_reliability + 0.4 × liveness

wilson_reliability = Wilson lower bound (95% confidence) on (self_delivered / received_requests)
liveness          = exp(-age_seconds / time_constant)
                    where time_constant gives a 24-hour half-life
```

**Why Wilson, not Laplace:** the existing mech-ranking formula uses Laplace smoothing `(self_delivered + 8) / (received_requests + 9)`, which gives a brand-new mech an assumed 89% reliability. That's fine for *ranking* (let new mechs get requests so they build history) but wrong for a *gate* — a spam mech registering with zero deliveries would pass. Wilson lower bound returns 0.0 for zero observations and only rises as evidence accumulates.

| Deliveries | Success rate | Laplace (existing rank) | Wilson lower bound (new gate) |
|---|---|---|---|
| 0 of 0 | — | 89% (passes freely) | 0% (must earn it) |
| 1 of 1 | 100% | 90% | 5% |
| 9 of 10 | 90% | 81% | 59% |
| 90 of 100 | 90% | 90% | 83% |
| 990 of 1000 | 99% | 99% | 97% |

The grace period (Gate 0) handles the cold-start tension: new mechs bypass Wilson entirely for their first 20 global requests.

**Liveness with 24h half-life (locked):**

| Mech state | wilson | liveness | gate_score |
|---|---|---|---|
| 90/100 deliveries, fresh | 0.83 | 1.00 | **0.90** |
| 90/100 deliveries, idle 24h | 0.83 | 0.50 | **0.70** |
| 90/100 deliveries, idle 48h | 0.83 | 0.25 | **0.60** |
| 0/0 deliveries, fresh (post-grace) | 0.00 | 1.00 | **0.40** |
| 0/0 deliveries, idle 24h | 0.00 | 0.50 | **0.20** |

**Threshold:** `min_mech_score: 0.0` default (gate disabled). Recommended production value: `0.3`.

**Param (in `MechInteractParams`):**
```yaml
min_mech_score: 0.0   # default: gate disabled
```

**Note: gate is mech-level, not tool-level.** A mech with strong reputation across `prediction-online` also vouches for any new tool it adds. Per-tool delivery tracking would require a subgraph schema change and is out of scope. Layer 3 benchmarks handle per-tool quality.

### `irrelevant_tools` — kept as a fourth gate dimension

`irrelevant_tools: Set[str]` in `MechInteractParams` is **not deprecated**. It's a name-level filter that follows the same producer/consumer pattern as the other gates: mech-interact provides the mechanism, the caller provides the policy via `MechInteractParams` overrides. Treat it as a fourth gate alongside category, capability, and reputation.

It does two distinct jobs:

1. **Wrong-category exclusion** — most entries in the trader's current list (e.g. `native-transfer`, `openai-gpt-3.5-turbo`, `stabilityai-stable-diffusion-*`, `deepmind-optimization`) are tools whose purpose is not prediction at all. The category gate replaces this job once mechs declare categories properly; these entries can be removed as Layer 1 lands.
2. **Within-category exclusion** — entries like `prediction-online-lite`, `claude-prediction-online-lite`, `prediction-offline-sme`, `prediction-online-sum-url-content` are prediction tools, just inferior variants the trader has decided not to use. The category gate doesn't touch them. Layer 2 (Brier ranking) may *deprioritise* such tools over time, but soft preference isn't a substitute for hard exclusion — the operator may still want a name-level kill switch for tools they never want to use regardless of measured performance.

**Future evolution:** as Layer 1 gates land and mechs adopt category metadata, the wrong-category portion of the list shrinks naturally. The within-category portion stays. Each removal is a deliberate per-tool decision, not a wholesale deprecation.

**Composition order with the new gates** (revised):

```
for mech in candidate_mechs:
    if mech.received_requests < COLD_START_GRACE:    # 1. Grace bypass
        admit(mech, filter_tools_by=irrelevant_tools)  # name gate still applies
        continue
    if not category_match(mech, task_type):           # 2. Category gate
        skip(mech); continue
    if not capability_match(mech, allowed_payment_types):  # 3. Capability gate
        skip(mech); continue
    if mech.gate_score < min_mech_score:              # 4. Reputation gate
        skip(mech); continue
    admit(mech, filter_tools_by=irrelevant_tools)     # 5. Name gate (per-tool filter)
```

The name gate runs at the tool-level (after a mech is admitted, filter out individually-blocked tools from its `relevant_tools`), unlike the other gates which operate at the mech level.

---

## Layer 2 — Category-aware tool selection (trader)

All changes inside `decision_maker_abci/policy.py` and `decision_maker_abci/behaviours/storage_manager.py`. No changes to mech-interact.

**Platform is deployment-time, not data-time.** Each service already points its `TOOLS_ACCURACY_HASH` env var at a different IPFS CSV — `polymarket_trader/service.yaml:99` uses the Polymarket-derived CSV, `trader_pearl/service.yaml:99` uses the Omen-derived CSV. The trader binary loads whichever CSV the service points to. So Layer 2 only needs to add **one** new dimension to the existing pipeline: `category`.

### Category source — shared classifier

**The classifier is the contract.** Both trader and mech-predict run the same `classify_category()` function on the same input (market title) so a market lands in the same bucket regardless of which side does the lookup. Sharing the *vocabulary* alone is insufficient — independently-maintained classifiers will drift even with the same category names.

**Mechanism:** a small standalone file (`category_keywords.py` or similar) duplicated in both repos, with a CI hash check to detect drift. A shared package or git submodule would be cleaner but introduces dependency overhead disproportionate to a 50-line file.

**Source of truth (today):** [`benchmark/datasets/fetch_production.py`](https://github.com/valory-xyz/mech-predict/blob/main/benchmark/datasets/fetch_production.py) in mech-predict (`CATEGORY_KEYWORDS` + `classify_category()` around lines 95–646 and ~1291). 14 categories: the 9 that overlap with Polymarket's API tags (`business, politics, science, technology, health, entertainment, weather, finance, international`) plus 5 extras (`travel, sports, sustainability, curiosities, pets`). Mech-predict already runs this on Omen titles whenever the FPMM category is empty (which is always for Omen) — see [`benchmark/datasets/fetch_open.py`](https://github.com/valory-xyz/mech-predict/blob/main/benchmark/datasets/fetch_open.py) around line 207.

**Trader-side changes:**
- `Bet.category` is populated by `classify_category(market_title)` for both Polymarket and Omen. Polymarket's API tag becomes informational, not canonical.
- The existing `_validate_market_category()` and `POLYMARKET_CATEGORY_KEYWORDS` in `polymarket_fetch_market.py:51-110` are **replaced** by the shared classifier (trader-only change, no external consumers of the validator's output).
- A new `tradeable_categories: List[str]` config in `market_manager_abci/skill.yaml` makes the trader's previously-implicit "we only trade categories we have keywords for" rule explicit. Markets classified into a non-tradeable category are filtered out at market-fetch time, so downstream code never sees them. Initial value: the current 9 (`business, politics, science, technology, health, entertainment, weather, finance, international`).
- **Travel was dropped from polystrat due to anti-predictive tool performance.** On omenstrat, travel was filtered upstream at the market-creator level. The classifier may still tag some Omen titles as travel via keywords; `tradeable_categories` catches those uniformly regardless of platform.

**Separation of concerns:**

| Layer | Owner | Decision |
|---|---|---|
| Classifier | Shared file (mech-predict + trader) | What category does this market belong to? |
| Tradeable filter | Trader (`tradeable_categories` config) | Which categories does *this trader* trade? |
| Layer 2 lookup | Trader (`EGreedyPolicy`) | Which tool wins for this category cell? |
| Benchmark scope | Mech-predict | Which categories does *the benchmark* score? |

This means mech-predict can keep benchmarking on travel/sports/etc., the CSV will have those rows, and the trader simply never queries them. Each consumer decides its own scope; the classifier is the only thing they share.

**Omen behaviour changes:** `Bet.category` is no longer `None` for Omen — it's whatever the classifier returns from the title. Omen now gets per-category routing through the same Layer 2 fallback chain as Polymarket. The aggregate fallback remains the safety net for tools whose Omen-category cells are sparse.

### Today's CSV (single-key)

```
tool,tool_accuracy,total_requests,min,max
superforcaster,72.58,485,2026-01-22 16:52:08,2026-03-17 14:43:19
prediction-request-reasoning,62.33,6605,2026-01-26 10:49:05,2026-03-17 19:06:49
prediction-offline,64.67,184,2026-02-04 14:13:22,2026-03-16 14:38:35
```

Sample fetched from polystrat hash `QmdNF1cidJASsVKSnbvSSmZLLaYfBPixBzpT4Pw3ZvmYTu`. `tool_accuracy` is a percentage (0–100), `total_requests` is `n`, `min` and `max` bracket the data window.

### Proposed CSV (one new optional column)

```
tool,category,tool_accuracy,total_requests,min,max
prediction-request-reasoning,,62.33,6605,2026-01-26,2026-03-17       # aggregate, no category
prediction-request-reasoning,politics,71.20,891,2026-01-26,2026-03-17
prediction-request-reasoning,crypto,55.10,402,2026-01-28,2026-03-17
prediction-request-reasoning,health,68.40,213,2026-02-02,2026-03-17
superforcaster,,72.58,485,2026-01-22,2026-03-17
superforcaster,politics,75.20,142,2026-02-04,2026-03-17
```

- An empty `category` cell is the platform-wide aggregate for that tool — exactly what today's CSV already represents.
- A row exists per `(tool, category)` cell where `n ≥ 30`.
- **Fully backward compatible:** old CSVs without a `category` column parse as all-aggregate; old trader binaries reading the new CSV can ignore the column entirely.

The Omen CSV may stay single-key if categories aren't meaningfully derivable from Omen markets. Polymarket CSV gets the new rows.

### `EGreedyPolicy` changes

```python
@dataclass
class EGreedyPolicy:
    # was: Dict[str, AccuracyInfo]
    accuracy_store: Dict[Tuple[str, str], AccuracyInfo]
    #                    ^tool ^category   (category="" for aggregate)

    # was: Dict[str, float]
    weighted_accuracy: Dict[Tuple[str, str], float]

    consecutive_failures: Dict[str, ConsecutiveFailures]   # stays per-tool — quarantine is global
    eps: float
    quarantine_duration: int

    def select_tool(
        self,
        randomness: float,
        category: Optional[str] = None,
    ) -> str:
        candidates = self._candidates_for_category(category)
        if not candidates or randomness < self.eps:
            return self._random_from(candidates or self.valid_tools)
        return max(
            candidates,
            key=lambda t: self.weighted_accuracy[(t, category or "")],
        )
```

### Lookup fallback chain (two levels)

1. **Specific cell:** `(tool, category)` rows with `n ≥ 30`. If non-empty → return.
2. **Aggregate:** `(tool, "")` rows. Always populated; this is what the existing single-key CSV already provides. Final safety net.

When `category is None` (which shouldn't happen post-classifier-adoption — every market gets a category from `classify_category()`), skip step 1 entirely and go straight to the aggregate. The aggregate also catches sparse-cell cases where a tool's category cell has `n < 30`.

**Realistic fragmentation check** (using polystrat data): `prediction-request-reasoning` has 6605 total requests — fragmented across ~10 Polymarket categories that's ~660/category, comfortably above `n ≥ 30`. Lighter tools like `prediction-offline` (184 total) fragment to ~18/category, below the floor — they correctly fall back to aggregate. This means most tools will route on aggregate for most categories until their per-category cells fill. Heavy tools get the most segment-specific routing benefit, which is the right place for it.

### Quarantine and exploration

- **Quarantine stays tool-level**, not category-level. A tool that times out / errors consecutively is broken everywhere, not "broken on politics but fine on crypto." Matches the failure mode (bugs/timeouts, not domain weakness).
- **Epsilon-exploration is category-scoped:** picks a random tool from the candidates eligible for the current category, not from the global pool. Otherwise exploration undoes routing.
- **Cross-category exploration** is Layer 3's job: the benchmark runs all tools regardless of production routing, so the CSV stays fresh.

### Call site change

`ToolSelectionBehaviour._select_tool()` (`decision_maker_abci/behaviours/tool_selection.py:40-79`) currently calls `policy.select_tool(randomness)`. The new call passes `category` from the active `Bet`:

```python
tool = self.policy.select_tool(
    randomness=randomness,
    category=bet.category,   # may be None for Omen
)
```

`Bet.category` already exists at `market_manager_abci/bets.py:173` — Polymarket questions populate it, Omen questions set `None`.

---

## Layer 3 — Benchmark evaluation loop (mech-predict)

Lives in the `mech-predict` repo, not trader. Summarised here because it produces the data Layer 2 consumes.

### Tool ranking

**Primary metric: Brier score.** Lower is better. Random = 0.25, perfect = 0.0.

```
brier = mean((p_yes - outcome)²)
```

Tools are ranked by Brier per `(platform, category)` cell, with `n ≥ 30` minimum for cell-level rankings. Reliability (`valid_outputs / attempted_runs`) is a hard gate at 80%; below that the tool is excluded entirely.

### Why not edge

Edge over market is **a consequence of accuracy, not a goal.** Optimising tools directly for edge incentivises contrarianism (disagreeing with the market for the sake of it) rather than accuracy. A tool that deliberately disagrees with an accurate market loses money. Edge is reported as a system-level diagnostic — useful for understanding *why* the trader is profitable or not — but not for ranking tools.

### Why not feed market_prob into the tool prompt

Anchoring bias: LLMs anchor heavily on numbers in their prompts. A tool that sees "the market thinks 0.60" outputs something near 0.60 regardless of evidence. This collapses the tool's independent signal. The tool's value *is* its independence; the market price is for the *trader*, not the tool.

### Diagnostic metrics (reported, not used for ranking)

- **Edge over market** — is the tool more accurate than the market on average?
- **Conditional accuracy when disagreeing** — when the tool disagrees enough to trigger a Kelly bet (`|p_yes - market_prob| > min_edge`), is it more often right than the market?
- **Disagreement-stratified Brier** — Brier bucketed by disagreement magnitude. Reveals whether a tool is accurate on the high-leverage questions where Kelly bets the most.

### Required scorer additions

- `by_tool_category` cross-breakdown (tool × platform × category) — directly produces the Layer 2 CSV.
- Conditional accuracy when disagreeing.
- Disagreement-stratified Brier.

### Performance table publishing

The benchmark CI pins **one CSV per platform** to IPFS. Trader consumes via the existing `tools_accuracy_hash` mechanism — the per-platform hash mechanism already exists (`polymarket_trader/service.yaml:99` and `trader_pearl/service.yaml:99` already point at different hashes). Only the data shape changes: add an optional `category` column.

| Service | Hash points to | Categories? |
|---|---|---|
| `polymarket_trader` | Polymarket-derived CSV | yes (per-category rows + aggregate) |
| `trader_pearl` (Omen) | Omen-derived CSV | yes (per-category rows + aggregate) — mech-predict already classifies Omen titles via the shared classifier |

**Net-new work in mech-predict** (no existing CSV artifact today):

1. CSV export step — flatten `scores.json`'s `by_tool × by_category` nests into the row format above. The `by_category` bucketing already exists in [`benchmark/scorer.py`](https://github.com/valory-xyz/mech-predict/blob/main/benchmark/scorer.py) around lines 303–307.
2. IPFS publish step — pin from CI, surface the hash so trader's `TOOLS_ACCURACY_HASH` env var can be updated. No `tools_accuracy.csv` artifact exists today; the benchmark pipeline produces `scores.json` + `scores_history.jsonl` + `report.md` as GitHub workflow artifacts (see [`benchmark_flywheel.yaml`](https://github.com/valory-xyz/mech-predict/blob/main/.github/workflows/benchmark_flywheel.yaml) lines 84–91), and the only thing currently pinned to IPFS is tool metadata via [`scripts/publish_metadata.py`](https://github.com/valory-xyz/mech-predict/blob/main/scripts/publish_metadata.py).
3. Coordinate with the existing [`BENCHMARK_BRANCH_PLAN.md`](https://github.com/valory-xyz/mech-predict/blob/main/BENCHMARK_BRANCH_PLAN.md) / [`WORKFLOW_SPLIT_PLAN.md`](https://github.com/valory-xyz/mech-predict/blob/main/WORKFLOW_SPLIT_PLAN.md) plan files at the mech-predict repo root before opening a third doc.
4. **No re-bucketing of historical data needed** — mech-predict keeps its current classifier and history.

---

## Locked decisions

| # | Decision | Locked at |
|---|---|---|
| 1 | Mech selection lives in mech-interact; tool selection lives in the caller (trader's `EGreedyPolicy`) | "2A makes sense" |
| 2 | Layer 1 changes are first-class — we own `mech_interact_abci`, no upstream-vs-fork dance | "we have access to mech_interact_abci" |
| 3 | Liveness half-life = 24 hours | "half life 24 hours" |
| 4 | Cold-start grace period = first **20** global requests | "20 requests makes sense" |
| 5 | Grace counter = global (subgraph `received_requests`), not local | "global" |
| 6 | Capability gate via `allowed_payment_types: Optional[List[str]]` param, default `None` | "maybe a field that gates payment types..." |
| 7 | Tool ranking metric = Brier score; edge is diagnostic only | from gist |
| 8 | Do NOT feed `market_prob` into tool prompts (anchoring) | from gist |
| 9 | Platform dimension is deployment-time (per-service `TOOLS_ACCURACY_HASH`), not data-time. Layer 2 only adds `category` to the CSV schema. | "we already have ways to set different accuracy hash for each platform" |
| 10 | CSV schema bump = one new optional `category` column. Empty = aggregate (today's behaviour). | inferred from polystrat CSV inspection |
| 11 | Capability gate plumbing locked: `payment_type` field on `MechInfo`, in-memory cache on `MechInformationBehaviour`, populated alongside IPFS metadata fetch. ~50 mech pool, payment types stable, cross-period caching acceptable. | "1. number of mechs shouldn't matter... 2. stable in practice 3. look 2" |
| 12 | `irrelevant_tools` is **kept as a fourth gate dimension** (name-level, tool-scoped), not deprecated. Sits alongside category, capability, reputation in the gate framework. | "what. that would still be needed maybe?" |

## Open questions

| # | Question | Section |
|---|---|---|
| 1 | Wilson confidence level. **Recommended default: 95%** (standard binomial CI). Open for revision after seeing real mech data. | Layer 1 reputation |
| 2 | IPFS metadata schema: per-tool vs mech-level vs hybrid. **Recommended: hybrid** — parser checks per-tool category first, falls back to mech-level, falls back to `"uncategorized"`. Backward compatible with legacy flat lists. | Layer 1 category |
| ~~3~~ | ~~Capability gate plumbing~~ — **closed**: add `payment_type` field to `MechInfo`, populate in `MechInformationBehaviour.populate_tools()` via existing `_get_payment_type()` contract call, cache in-memory on the behaviour across periods. Pool is ~10 active / 50 historical mechs, payment types are stable in practice, cross-period caching is acceptable. Cold start re-fetches; persistence is a deferred follow-up. | Layer 1 capability |
| ~~4~~ | ~~Deprecation timeline for `irrelevant_tools` blocklist~~ — **closed**: not deprecated. Reframed as a first-class fourth gate (name-level, tool-scoped). Its current contents do two jobs: wrong-category exclusion (will shrink as Layer 1 lands and mechs declare categories) and within-category exclusion (stays — Brier ranking is a soft preference, not a substitute for hard kill switch). | Layer 1 |
| ~~5~~ | ~~Omen `Bet.category = None` handling~~ — **closed (revised)**: trader adopts mech-predict's shared `classify_category()`, so Omen markets get a category from their title. No `None` case in normal operation. Aggregate fallback still catches sparse cells. | Layer 2 |
| 6 | `min_mech_score` production default. **Recommended: 0.3** (per gist). Open for revision after observing the gate's effect on real mech data. | Layer 1 reputation |
| 7 | Free-form category vocabulary vs registry | Layer 1 category |
| 8 | Min `n` per cell for routing (proposed: 30) | Layer 2 fallback |
| ~~11~~ | ~~Category vocabulary alignment~~ — **closed**: trader adopts mech-predict's `classify_category()` directly. Shared classifier > shared vocabulary. | Layer 2 / Layer 3 |
| ~~12~~ | ~~Sharing mechanism~~ — **closed**: duplicated file with CI hash check. | Layer 2 / Layer 3 |
| ~~13~~ | ~~Travel disposition~~ — **closed**: mech-predict keeps travel in the classifier; trader filters via `tradeable_categories`. Travel was dropped on polystrat due to *anti-predictive tool performance* (Layer 3 diagnostic territory). On omenstrat it was dropped at market creator level — Omen has no travel markets to begin with. | Layer 2 |
| ~~14~~ | ~~`tradeable_categories` location~~ — **closed**: lives in trader's `market_manager_abci/skill.yaml`. Filtering at market-fetch time means downstream code never sees non-tradeable markets. Initial value: current 9 (`business, politics, science, technology, health, entertainment, weather, finance, international`). | Layer 2 |
| ~~15~~ | ~~Validator replacement scope~~ — **closed**: trader-only, no external consumers of the existing validator's output. | Layer 2 |
| 16 | **Future:** make `tradeable_categories` data-driven from Layer 3 disagreement-stratified Brier (auto-exclude categories where best-tool Brier is worse than no-skill). Travel-dropped-from-polystrat is the canonical example this would have caught automatically. Not in scope for the initial implementation. | Layer 2 / Layer 3 |

---

## Adjacent must-fixes (orthogonal to selection)

From `BUG_REPORT_NVM_SUBSCRIPTION_DEADLOCK.md` — these are FSM safety issues, not selection logic, but they should ship alongside Layer 1 since they touch the same package:

1. **Add a failure exit to `MechPurchaseSubscriptionRound`** (`mech_interact_abci/rounds.py:136-141`). Currently `ROUND_TIMEOUT` self-loops; it should transition to a `FailedMechPurchaseSubscriptionRound(DegenerateRound)`.
2. **Add retry limits to `_prepare_safe_tx`** (`mech_interact_abci/behaviours/purchase_subcription.py:674-694`). Currently calls `wait_for_condition_with_sleep(timeout=None)`.
3. **Ship-now mitigation** (`request.py:920-925`): penalize the NVM mech and fall through, instead of triggering `BUY_SUBSCRIPTION` unconditionally. Subsumed by the capability gate once that lands.

---

## Rollout sequence

Roughly in dependency order; parallelisable where noted.

1. **Adjacent NVM bug fixes** (FSM safety) — independent, ship now.
2. **Layer 1 capability gate plumbing**: cache `payment_type` on `MechInfo` via `MechInformationRound`. Enables capability gate and resolves the NVM deadlock long-term.
3. **Layer 1 reputation gate**: Wilson lower bound + 24h liveness + grace bypass. Default disabled.
4. **Layer 1 category gate**: IPFS schema parser + `task_type` filter. Default disabled. *(Parallelisable with #3.)*
5. **Layer 3 scorer additions**: `by_tool_category` cross-breakdown, conditional accuracy, disagreement-stratified Brier. *(Owned by mech-predict, parallelisable with #2-#4.)*
6. **Layer 3 IPFS publish**: extended segment-keyed CSV pinned by CI.
7. **Layer 2 trader policy bump**: extend `EGreedyPolicy` to segment-keyed accuracy store, update `ToolSelectionBehaviour` call site, plumb `Bet.category` through. Defaults to single-key fallback when CSV is in old format.
8. **Production rollout**: enable Layer 1 gates one at a time (`task_type`, then `allowed_payment_types`, then `min_mech_score = 0.3`). Monitor pool size and selection diversity at each step.
9. **Deprecate** `irrelevant_tools` after Layer 1 gates are stable in production.
