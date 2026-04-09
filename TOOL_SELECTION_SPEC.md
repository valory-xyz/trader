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

All four gates run in `populate_tools()` (`behaviours/mech_info.py:71-100`), the same function that today applies the `irrelevant_tools` filter at line 96. Mechs that fail a mech-level gate (category, capability, reputation) are skipped with `continue`, so their `relevant_tools` are never populated. The name gate runs at tool level within the mech's tool list (same site as today's `relevant_tools = set(res) - self.params.irrelevant_tools`). The `mech_tools` property (`states/base.py:319-324`) stays read-only — it simply unions `relevant_tools` across mechs, and all filtering has already happened upstream.

### Gate composition order (logical)

```
for mech in candidate_mechs:
    if not category_match(mech, task_type):            # 1. Category gate
        skip(mech); continue
    if not capability_match(mech, allowed_payment_types):  # 2. Capability gate
        skip(mech); continue
    if mech.received_requests < COLD_START_GRACE:     # 3. Grace bypass (reputation only)
        admit(mech, filter_tools_by=irrelevant_tools)
        continue
    if mech.gate_score < min_mech_score:              # 4. Reputation gate
        skip(mech); continue
    admit(mech, filter_tools_by=irrelevant_tools)      # 5. Name gate (per-tool)
```

**Key property:** grace exempts a mech from Wilson/reputation checks only. Category, capability, and name gates still apply to mechs in the grace window — because those aren't about evidence, they're about correctness. A new image-generation mech can't fake its way into a prediction agent's pool by being new.

**Implementation may reorder gates for efficiency** as long as the AND-semantics are preserved. In particular: reputation and grace data (`received_requests`, `self_delivered`, `last_delivered`) is already on `MechInfo` from the subgraph query, so checking reputation/grace first saves the cost of fetching IPFS metadata and the payment-type contract call for mechs that would be excluded anyway. Efficient execution order is typically reputation-or-grace → capability → IPFS fetch → category → name. The final pool is identical to the logical order because all gates are AND conditions.

### 1. Cold-start grace period

**Locked.** A mech with `received_requests < 20` (counted from the subgraph, **global** across all agents) bypasses **only the reputation gate**. Category, capability, and name gates still apply — grace is a reputation exception, not a correctness exception.

- **Rationale:** prevents the death spiral where a new mech can't earn reputation because the gate excludes it before it gets a chance.
- **Why only reputation:** Wilson lower bound needs evidence to compute a meaningful score. Category (wrong type of tool), capability (unpayable), and name (explicit blocklist) are not about evidence — they're about whether the mech belongs in the pool at all. A new image-generation mech is never valid for a prediction agent regardless of age.
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

**Vocabulary:** the existing `PaymentType` enum (currently `mech_interact_abci/behaviours/request.py:71-83`, relocating to `mech_interact_abci/payment_types.py` per prerequisite below):
- `NATIVE`
- `TOKEN_USDC`
- `TOKEN_OLAS`
- `NATIVE_NVM`
- `TOKEN_NVM_USDC`

The related constants (`TOKEN_PAYMENT_TYPES`, `NVM_PAYMENT_TYPES`, `PAYMENT_TYPE_TO_NVM_CONTRACT`) at `request.py:85-91` move to the same new module.

**Plumbing (locked):** today, payment type is discovered *per request* in `_fetch_and_validate_payment_type()` (`behaviours/request.py:690`), which calls `_get_payment_type()` (`behaviours/request.py:634-647`) against `MechMM.contract_id`. The contract call exists, but as currently written it's bound to `MechRequestBehaviour`, reads `self.priority_mech_address` implicitly, and stores the result in a fixed placeholder (`MechRequestBehaviour.mech_payment_type`). It can't be called as-is from `MechInformationBehaviour`, so the plumbing is a real refactor, not a wiring move.

**Prerequisites:**

1. **Move `PaymentType` to a neutral module.** Create `packages/valory/skills/mech_interact_abci/payment_types.py` and move the `PaymentType` enum + related constants from `behaviours/request.py:71-91` into it. `behaviours/request.py` and `states/base.py` both import from the new module. Reason: `MechInfo` lives in `states/base.py`, and today `behaviours/` imports from `states/` — never the reverse. Adding `payment_type: Optional[PaymentType]` to `MechInfo` without this move creates a circular import.

2. **Refactor `_get_payment_type()` into the shared base.** Move `_get_payment_type` (and `_mech_mm_contract_interact` if it's also hard-coded to `self.priority_mech_address`) from `MechRequestBehaviour` into `MechInteractBaseBehaviour` (`behaviours/base.py`). Signature becomes `_get_payment_type_for(self, mech_address: str) -> Generator[...]` and stores the fetched value in a generic placeholder attribute (e.g. `self._last_fetched_payment_type`) that callers read after the `yield from`. `MechRequestBehaviour` updates its usage to pass its own `priority_mech_address` and copy the result into `self._mech_payment_type`. `MechInformationBehaviour` calls it per candidate mech with `mech.address`.

**Implementation:**

1. **`MechInfo` field:** add `payment_type: Optional[PaymentType] = None` to the dataclass at `states/base.py:168-272`, importing `PaymentType` from the new neutral module.
2. **Behaviour-level cache:** add `_payment_type_cache: Dict[str, PaymentType]` as an instance attribute on `MechInformationBehaviour` (`behaviours/mech_info.py:48`). Cache key is **`mech.address`** — mech addresses are contract addresses, immutable for the life of that deployment. Mech redeployment at a new address is a cache miss → fresh fetch, which is the correct invalidation semantic. Cold starts re-fetch; in-memory only for v1.
3. **Populate in `populate_tools()`:** alongside the existing IPFS metadata fetch for each mech, check the cache. On hit, copy into `mech.payment_type`. On miss, `yield from self._get_payment_type_for(mech.address)`, read `self._last_fetched_payment_type`, store on cache and on `mech.payment_type`.
4. **Capability filter in `populate_tools()`:** the filter runs in the same function as the existing `irrelevant_tools` filter (at `mech_info.py:96`), not in the read-only `mech_tools` property. Mechs whose `payment_type ∉ self.params.allowed_payment_types` (when the param is non-`None`) are skipped with `continue` so their `relevant_tools` are never populated.
5. **Cold-start cost:** at ~50 mechs with ~100-200ms per eth_call, ~5-10s total cold-start overhead on top of the existing per-mech HTTP metadata fetch (~5-25s). Worst-case total is ~10-35s per cold start, which is at or above the current `MechInformationRound` timeout of **30s** (`rounds.py:168-170`). The existing retry path (`mech_tools_api.increment_retries()`) recovers from `ROUND_TIMEOUT` by re-running `populate_tools` on the next period. **Validate during implementation with real RPC latency measurements; may need to bump the round timeout to 60s if cold starts consistently exceed the budget.** Not pre-emptively changing the timeout because the decision should be evidence-driven.
6. **Persistence (deferred):** in-memory only for v1. If durability across agent restarts becomes desirable, plumb through `storage_manager.py` (same pattern as `tools_accuracy_hash`) as a follow-up.

**Subgraph extension considered and deferred.** The query at `graph_tooling/queries/mechs_info.py:24-57` does not currently expose `payment_type`. Adding it would eliminate the contract calls but requires subgraph migration; not worth the cost at this scale.

**NVM deadlock fix as a side effect:** trader sets `allowed_payment_types: ["NATIVE", "TOKEN_USDC", "TOKEN_OLAS"]`, NVM mechs never reach the FSM, the deadlock is impossible. This is the long-term proper fix; the short-term ship-now patch (Option B from `BUG_REPORT_NVM_SUBSCRIPTION_DEADLOCK.md` — penalize NVM mech and fall through) remains valid until the capability gate ships.

### 4. Reputation gate (Gate 2 in source docs)

After category and capability, enforce a quality floor on mech reliability + activity.

**Score formula:**
```
gate_score = 0.6 × wilson_reliability + 0.4 × gate_liveness

wilson_reliability = Wilson lower bound (95% confidence) on (self_delivered / received_requests)
gate_liveness      = exp(-age_seconds / gate_taf)
                     where gate_taf = gate_liveness_half_life_seconds / ln(2)
```

**Important: the gate's liveness uses its own half-life constant, NOT the existing `HALF_LIFE_SECONDS`.** The existing `HALF_LIFE_SECONDS = 60 * 60` (`states/base.py:48`) feeds `Service.liveness` → `MechInfo.liveness` → `MechInfo.__lt__`, which is the *existing* priority-ranking mechanism and must not be changed silently. The gate introduces a new parameter `gate_liveness_half_life_seconds` in `MechInteractParams` (default `86400`, i.e. 24h) that controls the gate's own liveness calculation independently.

Why different half-lives: ranking and gate measure different things. `__lt__` is a soft priority order (idle mechs rank lower but aren't excluded), so a fast 1h decay is fine. The gate is a hard exclusion threshold — using the same 1h decay would evict established mechs during brief idle periods, which is over-eager. 24h for the gate is more forgiving of transient idleness while still evicting truly dormant mechs.

**Why Wilson, not Laplace:** the existing mech-ranking formula uses Laplace smoothing `(self_delivered + 8) / (received_requests + 9)`, which gives a brand-new mech an assumed 89% reliability. That's fine for *ranking* (let new mechs get requests so they build history) but wrong for a *gate* — a spam mech registering with zero deliveries would pass. Wilson lower bound returns 0.0 for zero observations and only rises as evidence accumulates.

| Deliveries | Success rate | Laplace (existing rank) | Wilson lower bound (new gate) |
|---|---|---|---|
| 0 of 0 | — | 89% (passes freely) | 0% (must earn it) |
| 1 of 1 | 100% | 90% | 5% |
| 9 of 10 | 90% | 81% | 59% |
| 90 of 100 | 90% | 90% | 83% |
| 990 of 1000 | 99% | 99% | 97% |

The grace period (Gate 0) handles the cold-start tension: new mechs bypass Wilson entirely for their first 20 global requests.

**Liveness with 24h gate half-life (locked):**

| Mech state | wilson | gate_liveness | gate_score |
|---|---|---|---|
| 90/100 deliveries, fresh | 0.83 | 1.00 | **0.90** |
| 90/100 deliveries, idle 24h | 0.83 | 0.50 | **0.70** |
| 90/100 deliveries, idle 48h | 0.83 | 0.25 | **0.60** |
| 0/0 deliveries, fresh (post-grace) | 0.00 | 1.00 | **0.40** |
| 0/0 deliveries, idle 24h | 0.00 | 0.50 | **0.20** |

**Threshold:** `min_mech_score: 0.0` default (gate disabled). Recommended production value: `0.3`.

**Params (in `MechInteractParams`):**
```yaml
min_mech_score: 0.0                           # default: gate disabled
gate_liveness_half_life_seconds: 86400        # 24h — gate-specific, independent of HALF_LIFE_SECONDS
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

**Mechanism (open for reviewer input on sync approach):** hash-pin with committed `.sha256` files + nightly cross-repo check.

- Both repos commit `category_keywords.py` AND `category_keywords.sha256` next to it.
- Each repo's CI runs `sha256sum -c category_keywords.sha256` on every PR — catches **local drift** immediately (someone edited the file without updating the hash).
- A scheduled GitHub Action in one repo (the canonical source — suggest mech-predict) runs nightly: fetches the other repo's file via `gh api repos/valory-xyz/trader/contents/.../category_keywords.py`, compares hashes, opens an issue on divergence. Catches **cross-repo drift**.
- Updating the classifier requires coordinated PRs across both repos with matching `.py` + `.sha256`.
- Rationale: minimum tooling (`sha256sum` + ~30 lines of workflow YAML), no runtime/build dependencies, no submodule pain. The nightly latency for cross-repo detection is acceptable because local drift is caught immediately at PR time.
- **Alternatives considered:** commit-pin (consumer stores canonical SHA, downloads at PR time — stricter semantics but adds a cross-repo auth dependency), git submodule (standard but known UX pain), tiny PyPI package (overkill for a ~50-line file). **This decision is explicitly open for reviewer input** — other sync mechanisms may be preferable depending on ops constraints.

**Source of truth (today):** [`benchmark/datasets/fetch_production.py`](https://github.com/valory-xyz/mech-predict/blob/main/benchmark/datasets/fetch_production.py) in mech-predict (`CATEGORY_KEYWORDS` + `classify_category()` around lines 95–646 and ~1291). 14 categories: the 9 that overlap with Polymarket's API tags (`business, politics, science, technology, health, entertainment, weather, finance, international`) plus 5 extras (`travel, sports, sustainability, curiosities, pets`). Mech-predict already runs this on Omen titles whenever the FPMM category is empty (which is always for Omen) — see [`benchmark/datasets/fetch_open.py`](https://github.com/valory-xyz/mech-predict/blob/main/benchmark/datasets/fetch_open.py) around line 207.

**Trader-side changes:**
- `Bet.category` is populated by `classify_category(market_title)` for both Polymarket and Omen. Polymarket's API tag becomes informational, not canonical.
- The existing `_validate_market_category()` and `POLYMARKET_CATEGORY_KEYWORDS` in `polymarket_fetch_market.py:51-110` are **replaced** by the shared classifier (trader-only change, no external consumers of the validator's output).
- A new `tradeable_categories: List[str]` config in `market_manager_abci/skill.yaml` makes the trader's previously-implicit "we only trade categories we have keywords for" rule explicit. Markets classified into a non-tradeable category are filtered out at market-fetch time, so downstream code never sees them. **Initial value mirrors the trader's current 9 Polymarket categories** (today's `POLYMARKET_CATEGORY_KEYWORDS` keys): `business, politics, science, technology, health, entertainment, weather, finance, international`. Chosen to match today's behaviour for zero net change at rollout, not hand-picked. After migration to the shared classifier, `POLYMARKET_CATEGORY_KEYWORDS` is removed and `tradeable_categories` becomes a configurable subset of the shared classifier's vocabulary.
- **Travel was dropped from polystrat due to anti-predictive tool performance** (tools were systematically wrong on travel markets — Layer 3 diagnostic territory). On omenstrat, travel was filtered upstream at the market-creator level. Note that both statements describe different layers and both hold: Omen has no travel markets upstream (filtered at market creator), but the keyword classifier may still tag some Omen titles as travel via title keywords (e.g., a market about Boeing whose title mentions "airlines"). `tradeable_categories` is the safety net for these classifier false positives — it catches mis-tags regardless of what upstream does, so excluding travel via this config is doing genuine work even on Omen.

**Separation of concerns:**

| Layer | Owner | Decision |
|---|---|---|
| Classifier | Shared file (mech-predict + trader) | What category does this market belong to? |
| Tradeable filter | Trader (`tradeable_categories` config) | Which categories does *this trader* trade? |
| Layer 2 lookup | Trader (`EGreedyPolicy`) | Which tool wins for this category cell? |
| Benchmark scope | Mech-predict | Which categories does *the benchmark* score? |

This means mech-predict can keep benchmarking on travel/sports/etc., the CSV will have those rows, and the trader simply never queries them. Each consumer decides its own scope; the classifier is the only thing they share.

**Omen behaviour changes:** `Bet.category` is no longer `None` for Omen — it's whatever the shared classifier returns from the title. Omen now gets per-category routing through the same Layer 2 fallback chain as Polymarket. The aggregate fallback remains the safety net for tools whose Omen-category cells are sparse or missing.

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
- A row exists per `(tool, category)` cell where `n ≥ N_MIN_CELL` (currently proposed: 30 — see open question #8).
- **Fully backward compatible:** old CSVs without a `category` column parse as all-aggregate; old trader binaries reading the new CSV can ignore the column entirely.

### `EGreedyPolicy` changes

**Shape: nested dict.** `accuracy_store` and `weighted_accuracy` move from `Dict[str, ...]` to `Dict[str, Dict[str, ...]]` — outer key is the tool name, inner key is the category string (with `""` reserved for the aggregate row). This shape was chosen over a flat `Dict[Tuple[str, str], ...]` specifically because **it requires zero changes to the existing `DataclassEncoder` / `EGreedyPolicyDecoder`** — the decoder's hook matches dict contents against dataclass field names, so inner `{requests, pending, accuracy}` dicts still auto-reconstruct into `AccuracyInfo` and the outer two levels stay as plain dicts. Tuple keys would have forced a custom encode/decode hook because JSON keys must be strings.

**Full dataclass** (only two field type annotations change from current):

```python
@dataclass
class EGreedyPolicy:
    """An e-Greedy policy for the tool selection based on tool accuracy."""

    eps: float
    consecutive_failures_threshold: int
    quarantine_duration: int
    # CHANGED: nested {tool: {category: AccuracyInfo}} — category="" is aggregate
    accuracy_store: Dict[str, Dict[str, AccuracyInfo]] = field(default_factory=dict)
    # CHANGED: nested {tool: {category: float}}
    weighted_accuracy: Dict[str, Dict[str, float]] = field(default_factory=dict)
    # Per-tool (unchanged) — quarantine is tool-level, not category-level
    consecutive_failures: Dict[str, ConsecutiveFailures] = field(default_factory=dict)
    updated_ts: int = 0
```

**`select_tool` preserves its existing contract** (`Optional[str]` return, `n_tools == 0` guard, `RandomnessType` argument):

```python
def select_tool(
    self,
    randomness: RandomnessType = None,
    category: Optional[str] = None,
) -> Optional[str]:
    """Select a Mech tool and return its name."""
    if self.n_tools == 0:
        return None

    if randomness is not None:
        random.seed(randomness)

    candidates = self._candidates_for_category(category)
    if not candidates:
        # No tools have data for this category or the aggregate —
        # same path today's code takes when has_updated is False.
        return self.random_tool if not self.has_updated else None

    if random.random() < self.eps:  # nosec
        return random.choice(candidates)

    return max(
        candidates,
        key=lambda t: self._weighted_accuracy_for(t, category),
    )
```

### Candidate selection and fallback

**Precise definition of `_candidates_for_category`:**

```python
def _candidates_for_category(self, category: Optional[str]) -> List[str]:
    """Return the set of tools eligible for selection for this category.

    A tool is eligible if either:
      - It has a specific (tool, category) cell with n >= N_MIN_CELL, or
      - It has an aggregate row (tool, "") regardless of n.

    Quarantined tools are excluded. Deduped by tool name.
    """
    candidates = []
    for tool, cells in self.accuracy_store.items():
        if self.is_quarantined(tool):
            continue
        if category is not None:
            cell = cells.get(category)
            if cell is not None and cell.requests >= N_MIN_CELL:
                candidates.append(tool)
                continue
        if "" in cells:
            candidates.append(tool)
    return candidates
```

**And the corresponding weighted_accuracy lookup** uses the specific cell when it qualifies, otherwise the aggregate:

```python
def _weighted_accuracy_for(self, tool: str, category: Optional[str]) -> float:
    cells = self.weighted_accuracy[tool]
    if category is not None:
        specific_cell = self.accuracy_store[tool].get(category)
        if specific_cell is not None and specific_cell.requests >= N_MIN_CELL:
            return cells[category]
    return cells[""]  # aggregate fallback
```

**`N_MIN_CELL`** is the open question #8 (currently 30 as a placeholder).

**Fallback rule rationale:** the n-threshold applies only to per-category cells, not to the aggregate row. Sparsely-observed tools (e.g. a tool with only 5 total requests) stay eligible via the aggregate row — matching today's behaviour that any tool with any data is a candidate. This preserves "low-sample tools participate" while still routing on segment-specific data when enough evidence exists.

**Realistic fragmentation check** (using polystrat data): `prediction-request-reasoning` has 6605 total requests — fragmented across ~10 Polymarket categories that's ~660/category, comfortably above `n ≥ 30`. Lighter tools like `prediction-offline` (184 total) fragment to ~18/category, below the floor — they correctly fall back to aggregate. Most tools will route on aggregate for most categories until their per-category cells fill. Heavy tools get the most segment-specific routing benefit, which is the right place for it.

### Quarantine and exploration

- **Quarantine stays tool-level**, not category-level. A tool that times out / errors consecutively is broken everywhere, not "broken on politics but fine on crypto." Matches the failure mode (bugs/timeouts, not domain weakness).
- **Epsilon-exploration is category-scoped:** picks a random tool from the candidates eligible for the current category, not from the global pool. Otherwise exploration undoes routing.
- **Cross-category exploration** is Layer 3's job: the benchmark runs all tools regardless of production routing, so the CSV stays fresh.

### Call site change

`ToolSelectionBehaviour._select_tool()` (`decision_maker_abci/behaviours/tool_selection.py:40-79`) currently calls `policy.select_tool(randomness)`. The new call passes `category` from the active `Bet`:

```python
tool = self.policy.select_tool(
    randomness=randomness,
    category=bet.category,
)
```

`Bet.category` already exists at `market_manager_abci/bets.py:173`. Post-migration to the shared classifier, both Polymarket and Omen bets will have non-`None` categories.

### Migration notes

Checklist of implementation touchpoints Layer 2 must cover. Grouped by file.

**`packages/valory/skills/decision_maker_abci/policy.py`**

- `EGreedyPolicy.accuracy_store` type annotation: `Dict[str, AccuracyInfo]` → `Dict[str, Dict[str, AccuracyInfo]]`
- `EGreedyPolicy.weighted_accuracy` type annotation: `Dict[str, float]` → `Dict[str, Dict[str, float]]`
- All other fields (`eps`, `consecutive_failures_threshold`, `quarantine_duration`, `consecutive_failures`, `updated_ts`) preserved unchanged
- `select_tool` signature: add `category: Optional[str] = None` parameter. Preserve `Optional[str]` return type and the `n_tools == 0` guard.
- New methods: `_candidates_for_category(category)` and `_weighted_accuracy_for(tool, category)` — see definitions above
- `update_accuracy_store(tool, winning)`: update to write `accuracy_store[tool][""]` (aggregate row) instead of `accuracy_store[tool]`. Per-category cells are updated by Layer 3 via the IPFS CSV refresh, not by per-resolution updates in the trader.
- `tool_used(tool)`, `tool_responded(tool, ...)`: no change — they operate on tool-level consecutive_failures and aggregate pending counts
- **No changes to `DataclassEncoder` / `EGreedyPolicyDecoder`** — the nested dict shape was chosen specifically to avoid this. The decoder's existing hook (matches dict contents against dataclass field names) auto-reconstructs `AccuracyInfo` instances from the innermost level; outer levels stay as plain dicts. Confirmed by walking through the hook with the new shape.

**`packages/valory/skills/decision_maker_abci/behaviours/storage_manager.py`**

- `acc_info_fields` config: add a new `category` field name (the CSV column header)
- `_parse_global_info_row` (line 317): extract `category = row[acc_info_fields.category]` alongside `tool`, key the returned structure by `(tool, category)`
- `_parse_global_info` (line 343): return type changes from `Dict[str, Dict[str, str]]` to `Dict[str, Dict[str, Dict[str, str]]]` (one row per `(tool, category)`, nested)
- `_overwrite_local_info` (line 365): iterate the nested structure; `accuracy_store[tool][category] = AccuracyInfo(...)` instead of `accuracy_store[tool] = ...`
- `_update_accuracy_store` (line 384): seed the aggregate row for new tools — `accuracy_store.setdefault(tool, {}); accuracy_store[tool].setdefault("", AccuracyInfo())` — instead of `accuracy_store.setdefault(tool, AccuracyInfo())`
- `_remove_irrelevant_tools` (line 295-300): no change — `accuracy_store.pop(tool, None)` still works, removing the entire nested `{category: AccuracyInfo}` for the tool
- Update `weighted_accuracy` population to match the new nested shape

**`packages/valory/skills/decision_maker_abci/behaviours/tool_selection.py`**

- `_select_tool()` (lines 40-79): update the `policy.select_tool()` call to pass `category=bet.category`
- The chat-UI restricted policy override at lines 55-79 (`restricted_policy.accuracy_store = {t: v for t, v in ... if t in allowed_intersection}`) **stays unchanged** under the nested dict shape — `t` is still the outer tool-name string and `t in allowed_intersection` continues to work. This was a tuple-key concern that the nested shape eliminates.
- Synchronized-data payload serialization at line 96 also flows through `EGreedyPolicy.serialize()`, which continues to work unchanged.

**`packages/valory/skills/market_manager_abci/behaviours/polymarket_fetch_market.py`**

- Remove the hand-curated `POLYMARKET_CATEGORY_KEYWORDS` dict (lines 51-110)
- Remove `_validate_market_category()` (line 158) and `_validate_markets_by_category()` (line 185) — replaced by the shared classifier
- Keep the per-category fetch loop (it's driven by Polymarket's API tags, not by our keyword dict)
- Populate `Bet.category` via `classify_category(market_title)` from the shared classifier module
- Apply `tradeable_categories` filter here (drop markets whose classified category is not in the caller's allowed list)

**`packages/valory/skills/market_manager_abci/bets.py`**

- `Bet.category` stays as `Optional[str]` in the dataclass (no type change needed), but semantically it becomes non-`None` after the classifier change

**`packages/valory/skills/market_manager_abci/skill.yaml`**

- Add `tradeable_categories: list` parameter. Default: the current 9 categories (see Trader-side changes above).

**Shared classifier file** (new, both repos)

- `packages/valory/skills/market_manager_abci/category_keywords.py` (trader) — duplicated from [`benchmark/datasets/fetch_production.py`](https://github.com/valory-xyz/mech-predict/blob/main/benchmark/datasets/fetch_production.py) (mech-predict)
- `packages/valory/skills/market_manager_abci/category_keywords.sha256` — committed hash, verified by CI
- CI hook in both repos: `sha256sum -c category_keywords.sha256`
- Nightly cross-repo drift check (scheduled GitHub Action) — see "Mechanism" in the Category source section above. **Open for reviewer input on exact sync approach.**

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
| 11 | Capability gate plumbing locked: `payment_type` field on `MechInfo`, in-memory cache on `MechInformationBehaviour` keyed by `mech.address`, populated alongside IPFS metadata fetch via refactored `_get_payment_type_for(mech_address)` in `MechInteractBaseBehaviour`. ~50 mech pool, payment types stable, cross-period caching acceptable. | "1. number of mechs shouldn't matter... 2. stable in practice 3. look 2" |
| 12 | `irrelevant_tools` is **kept as a fourth gate dimension** (name-level, tool-scoped), not deprecated. Sits alongside category, capability, reputation in the gate framework. | "what. that would still be needed maybe?" |
| 13 | `EGreedyPolicy` accuracy store becomes **nested dict** `Dict[str, Dict[str, AccuracyInfo]]` (outer=tool, inner=category, `""` key = aggregate). Chosen over flat tuple keys specifically because it requires zero changes to the existing encoder/decoder. | review #1 |
| 14 | `PaymentType` enum + related constants move from `behaviours/request.py` to new neutral module `mech_interact_abci/payment_types.py`. Required to let `states/base.py` import without creating a circular dependency. | review #2 |
| 15 | `_get_payment_type` refactored into `MechInteractBaseBehaviour` with explicit `mech_address` parameter and generic result attribute. Existing `MechRequestBehaviour` callers are updated to pass their own `priority_mech_address` and read the result. | review #3 |
| 16 | Grace bypass exempts **only the reputation gate**. Category, capability, and name gates still apply to mechs in grace. | review #8 |
| 17 | Gate liveness uses a new parameter `gate_liveness_half_life_seconds` (default 24h). The existing `HALF_LIFE_SECONDS = 60 * 60` in `states/base.py:48` stays unchanged — it feeds `MechInfo.__lt__` priority ranking and must not be silently changed. Ranking and gate tune independently. | review #9 |
| 18 | Classifier sync mechanism = hash-pin with committed `.sha256` files + nightly cross-repo check. **This specific mechanism is open for reviewer input** — alternatives (commit-pin, submodule, PyPI package) were considered but hash-pin is the minimum tooling that catches both local and cross-repo drift. | review #12 |
| 19 | `_candidates_for_category` rule: `n ≥ N_MIN_CELL` applies only to per-category cells; aggregate row is always valid as fallback regardless of sample size. Preserves today's behaviour that any tool with any data is a candidate. | review #15 |

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
2. **`PaymentType` relocation prerequisite**: create `mech_interact_abci/payment_types.py`, move `PaymentType` enum + `TOKEN_PAYMENT_TYPES` / `NVM_PAYMENT_TYPES` / `PAYMENT_TYPE_TO_NVM_CONTRACT` from `behaviours/request.py:71-91` into it. Update imports in `behaviours/request.py` and anywhere else the enum is referenced. Non-functional refactor; unblocks the `MechInfo.payment_type` field.
3. **`_get_payment_type` refactor prerequisite**: move into `MechInteractBaseBehaviour` with explicit `mech_address` parameter and generic result attribute. Update `MechRequestBehaviour` callers to pass their own `priority_mech_address` and read the new result attribute. Non-functional refactor; unblocks per-mech payment-type fetching from `MechInformationBehaviour`.
4. **Layer 1 capability gate plumbing**: add `payment_type` field to `MechInfo`, add `_payment_type_cache` to `MechInformationBehaviour`, populate in `populate_tools()`, add `allowed_payment_types` param, apply filter. Enables capability gate and resolves the NVM deadlock long-term. *(Requires #2 and #3.)*
5. **Layer 1 reputation gate**: Wilson lower bound + `gate_liveness_half_life_seconds` param (default 24h) + grace bypass (reputation only). Default disabled via `min_mech_score = 0.0`. `HALF_LIFE_SECONDS` in `states/base.py:48` stays unchanged.
6. **Layer 1 category gate**: IPFS schema parser (hybrid per-tool/mech-level/uncategorized fallback) + `task_type` filter. Default disabled.
7. **Shared classifier file + CI hash check**: create `category_keywords.py` + `category_keywords.sha256` in both repos, wire `sha256sum -c` into CI, set up the nightly cross-repo drift check GitHub Action.
8. **Layer 3 scorer additions**: `by_tool_category` cross-breakdown, conditional accuracy, disagreement-stratified Brier. *(Owned by mech-predict, parallelisable with #4–#6.)*
9. **Layer 3 IPFS publish**: extended CSV with optional `category` column pinned by CI. *(Depends on #7 + #8.)*
10. **Layer 2 trader policy bump**: extend `EGreedyPolicy` to nested `{tool: {category: ...}}` accuracy store, update storage_manager.py parsing, update `ToolSelectionBehaviour` call site, plumb `Bet.category` through, replace `POLYMARKET_CATEGORY_KEYWORDS` with shared classifier, add `tradeable_categories` config. See Migration notes checklist. *(Requires #7 + #9.)*
11. **Production rollout**: enable Layer 1 gates one at a time (`task_type`, then `allowed_payment_types`, then `min_mech_score = 0.3`). Monitor pool size and selection diversity at each step.
12. **Shrink** `irrelevant_tools` as Layer 1 gates prove themselves in production. Wrong-category entries can be removed once the category gate is enforcing. Within-category entries stay.
