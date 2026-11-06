# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2026 Valory AG
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#
# ------------------------------------------------------------------------------

"""Tests for the ranked market list."""

import json
import random
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Type
from unittest.mock import MagicMock

import pytest
import yaml

from packages.valory.skills.abstract_round_abci.base import AbciAppDB
from packages.valory.skills.decision_maker_abci.behaviours.blacklisting import (
    BlacklistingBehaviour,
)
from packages.valory.skills.decision_maker_abci.behaviours.ranking import (
    QUIET_LOGGER,
    RANKING_MAX_MARKETS,
    RankingReceiveBehaviour,
    RankingRequestBehaviour,
)
from packages.valory.skills.decision_maker_abci.behaviours.round_behaviour import (
    AgentDecisionMakerRoundBehaviour,
)
from packages.valory.skills.decision_maker_abci.behaviours.sampling import (
    RANKING_MAX_AGE,
    SamplingBehaviour,
)
from packages.valory.skills.decision_maker_abci.models import SharedState
from packages.valory.skills.decision_maker_abci.payloads import RankingRequestPayload
from packages.valory.skills.decision_maker_abci.rounds import DecisionMakerAbciApp
from packages.valory.skills.decision_maker_abci.rounds_info import ROUNDS_INFO
from packages.valory.skills.decision_maker_abci.states.base import (
    Event,
    RANKING_TOOL,
    SynchronizedData,
)
from packages.valory.skills.decision_maker_abci.states.blacklisting import (
    BlacklistingRound,
)
from packages.valory.skills.decision_maker_abci.states.decision_receive import (
    DecisionReceiveRound,
)
from packages.valory.skills.decision_maker_abci.states.final_states import (
    FinishedRankingRequestRound,
    FinishedWithoutDecisionRound,
)
from packages.valory.skills.decision_maker_abci.states.randomness import (
    BenchmarkingRandomnessRound,
    RandomnessRound,
)
from packages.valory.skills.decision_maker_abci.states.ranking import (
    RankingReceiveRound,
    RankingRequestRound,
)
from packages.valory.skills.decision_maker_abci.states.sampling import SamplingRound
from packages.valory.skills.decision_maker_abci.utils.tool_suitability import (
    explain_prediction_tool,
)
from packages.valory.skills.market_manager_abci.bets import (
    Bet,
    BetsDecoder,
    QueueStatus,
    serialize_bets,
)
from packages.valory.skills.market_manager_abci.payloads import UpdateBetsPayload

NOW = 1_800_000_000
DAY = 86400
COOLDOWN = 3600
LISTED_TOOL = f"valory::{RANKING_TOOL}"
PREDICTION_TOOL = "valory::prediction-online"


def _bet(i: int, **kwargs: Any) -> Bet:
    """Build an untried, bettable Polymarket market; a larger i has more liquidity."""
    fields: Dict[str, Any] = dict(
        id=f"m{i}",
        market="polymarket",
        title=f"market {i}",
        collateralToken="",
        creator="0x0",
        fee=0,
        openingTimestamp=NOW + 3 * DAY,
        outcomeSlotCount=2,
        outcomeTokenAmounts=[10, 10],
        outcomeTokenMarginalPrices=[0.5, 0.5],
        outcomes=["Yes", "No"],
        scaledLiquidityMeasure=100.0 + i,
        queue_status=QueueStatus.TO_PROCESS,
    )
    fields.update(kwargs)
    return Bet(**fields)


def _todays_pick(bets: List[Bet]) -> str:
    """Today's pick: the first non-empty queue, the highest priority key."""
    queue = [b for b in bets if b.queue_status == QueueStatus.TO_PROCESS] or bets
    return max(
        queue,
        key=lambda b: (
            b.invested_amount,
            -b.processed_timestamp,
            b.scaledLiquidityMeasure,
            b.openingTimestamp,
        ),
    ).id


def _db(**data: Any) -> AbciAppDB:
    """Build a period db holding the given values."""
    data.setdefault("is_marketplace_v2", True)
    data.setdefault("available_mech_tools", json.dumps([LISTED_TOOL, PREDICTION_TOOL]))
    data.setdefault("most_voted_randomness", "ab" * 32)
    return AbciAppDB(setup_data=AbciAppDB.data_to_lists(data))


def _behaviour(
    cls: Type[Any],
    bets: List[Bet],
    db: Optional[AbciAppDB] = None,
    now: int = NOW,
    benchmarking: bool = False,
) -> Any:
    """Build a behaviour over the given bets, a real period db and mocked services."""
    behaviour = object.__new__(cls)
    context = MagicMock()
    context.agent_address = "agent"
    context.benchmarking_mode.enabled = benchmarking
    context.state.synchronized_data.db = db or _db()
    context.state.round_sequence.last_round_transition_timestamp = (
        datetime.fromtimestamp(now)
    )
    context.state.liquidity_cache = {}
    params = context.params
    params.slot_count = 2
    params.use_multi_bets_mode = False
    params.enable_multi_bets_fallback = False
    params.sample_bets_closing_days = 10
    params.opening_margin = 300
    params.safe_voting_range = 600
    params.declined_market_cooldown = COOLDOWN
    params.is_outcome_side_threshold_filter_enabled = True
    params.outcome_side_threshold_filter_threshold = 0.8
    params.is_running_on_polymarket = True
    params.exclude_neg_risk_markets = True
    params.disabled_polymarket_tags = ["weather"]
    params.enable_market_ranking = True
    params.ranking_min_score = 0.5
    params.polymarket_spread_min = 0.0
    params.polymarket_spread_max = 0.1
    params.orderbook_unavailable_threshold = 5
    # the CLOB answers until a test says otherwise, counted as SharedState does
    state = context.state
    state.orderbook_failures = 0
    state.orderbook_failing_since = None
    state.record_orderbook_fetch.side_effect = (
        lambda reached, timestamp: SharedState.record_orderbook_fetch(
            state, reached, timestamp
        )
    )
    state.record_orderbook_response.side_effect = (
        lambda response, timestamp: SharedState.record_orderbook_response(
            state, response, timestamp
        )
    )
    state.is_orderbook_unavailable.side_effect = (
        lambda threshold: SharedState.is_orderbook_unavailable(state, threshold)
    )
    behaviour.__dict__["_context"] = context
    behaviour.bets = bets
    behaviour.store_bets = MagicMock()
    behaviour.hash_stored_bets = MagicMock(return_value="bets_hash")
    behaviour.read_bets = MagicMock()
    behaviour.payloads = []

    def _finish(payload: Any) -> Generator:
        behaviour.payloads.append(payload)
        yield

    behaviour.finish_behaviour = _finish
    return behaviour


def _act(behaviour: Any) -> Any:
    """Run the behaviour's act and return its payload."""
    for _ in behaviour.async_act():
        pass
    return behaviour.payloads[-1]


def _request(bets: List[Bet], **kwargs: Any) -> RankingRequestPayload:
    """Run the ranking request round's behaviour and return its payload."""
    return _act(_behaviour(RankingRequestBehaviour, bets, **kwargs))


def _ranked_ids(payload: RankingRequestPayload) -> List[str]:
    """Get the market ids a ranking request asks about."""
    (request,) = json.loads(payload.mech_requests or "")
    assert request["tool"] == RANKING_TOOL
    return [market["id"] for market in json.loads(request["prompt"])["markets"]]


def _sampled(bets: List[Bet], **kwargs: Any) -> Optional[str]:
    """Run Sampling's pick and return the market id."""
    idx = _behaviour(SamplingBehaviour, bets, **kwargs)._sample()
    return None if idx is None else bets[idx].id


def _receive(
    bets: List[Bet], result: Optional[str], ranking: bool = True, **response: Any
) -> Any:
    """Run the router round's behaviour over a mech answer and return it."""
    db = _db(
        mech_tool=RANKING_TOOL if ranking else "prediction-online",
        sampled_bet_index=None if ranking else 0,
        mech_responses=json.dumps([{"nonce": "n", "result": result, **response}]),
    )
    behaviour = _behaviour(RankingReceiveBehaviour, bets, db=db)
    _act(behaviour)
    return behaviour


def _listed(n: int, ranked_at: int = NOW - 60, **kwargs: Any) -> List[Bet]:
    """Build a ranked list of n unscored markets."""
    return [_bet(i, ranked_at=ranked_at, **kwargs) for i in range(n)]


def _end_block(round_cls: Type[Any], payload: Any, **data: Any) -> Any:
    """Run a round over the payload of the single agent and return the (state, event) pair."""
    db = _db(
        participants=["agent"],
        all_participants=["agent"],
        consensus_threshold=1,
        **data,
    )
    context = MagicMock()
    context.benchmarking_mode.enabled = False
    round_ = round_cls(SynchronizedData(db), context)
    round_.process_payload(payload)
    return round_.end_block()


def test_row_1_no_ranking_keeps_todays_picks() -> None:
    """Tool not listed, older mech path, benchmarking, no or stale list: today's picks."""
    bets = [_bet(i) for i in range(15)]
    stale = [
        _bet(i, ranked_at=NOW - RANKING_MAX_AGE, research_score=i / 20)
        for i in range(15)
    ]
    stale[0].research_score = 1.0
    unlisted = _db(available_mech_tools=json.dumps([PREDICTION_TOOL]))
    for db in (unlisted, _db(is_marketplace_v2=False)):
        assert _request(bets, db=db).mech_tool is None
        assert _request(stale, db=db).mech_tool is None
    # the feature switched off: no ranking request, today's picks
    switched_off = _behaviour(RankingRequestBehaviour, bets)
    switched_off.context.params.enable_market_ranking = False
    assert _act(switched_off).mech_tool is None
    # benchmarking never enters the ranking round, and Sampling ignores a list
    assert (
        DecisionMakerAbciApp.transition_function[BenchmarkingRandomnessRound][
            Event.DONE
        ]
        is SamplingRound
    )
    fresh = _listed(15)
    fresh[0].research_score = 1.0
    sampler = _behaviour(SamplingBehaviour, fresh, benchmarking=True)
    assert fresh[sampler._sampled_bet_idx(fresh)].id == _todays_pick(fresh)
    # without a list, or with a list older than 24 h, the pick is today's
    for market_list in (bets, stale):
        assert _sampled(market_list) == _todays_pick(market_list) == "m14"


def test_row_2_first_period_requests_a_ranking_of_prefiltered_markets() -> None:
    """One request of prefiltered markets, straight to the mech; scores stored, no bet."""
    candidates = [_bet(i) for i in range(12)]
    dropped = [
        _bet(20, investments={"Yes": [5], "No": []}),
        _bet(22, scaledLiquidityMeasure=0.0),
        _bet(23, outcomeTokenMarginalPrices=[0.85, 0.15]),
        _bet(24, neg_risk=True),
        _bet(25, poly_tags=["Weather"]),
        _bet(26, openingTimestamp=NOW + 11 * DAY),
        _bet(27, processed_timestamp=NOW - 60),
        _bet(28, queue_status=QueueStatus.PROCESSED),
    ]
    behaviour = _behaviour(RankingRequestBehaviour, candidates + dropped)
    payload = _act(behaviour)

    assert payload.mech_tool == RANKING_TOOL and payload.index is None
    assert payload.bets_hash == "bets_hash"
    assert _ranked_ids(payload) == [f"m{i}" for i in range(11, -1, -1)]
    assert all(bet.ranked_at == NOW for bet in candidates)
    assert all(bet.ranked_at == 0 for bet in dropped)
    behaviour.store_bets.assert_called_once()
    assert behaviour.context.state.mech_timed_out is False
    # straight to the mech request, and the period becomes a ranking period
    event = _end_block(RankingRequestRound, payload)
    assert event[1] == Event.DONE
    assert SynchronizedData(event[0].db).is_ranking_period
    assert (
        DecisionMakerAbciApp.transition_function[RankingRequestRound][Event.DONE]
        is FinishedRankingRequestRound
    )

    # the answer is stored and the period ends without a bet
    answer = {"ranking": [{"id": "m3", "score": 0.9}, {"id": "m7", "score": 0.4}]}
    receiver = _receive(candidates, json.dumps(answer))
    assert {b.id: b.research_score for b in candidates if b.research_score} == {
        "m3": 0.9,
        "m7": 0.4,
    }
    assert receiver.payloads[-1].bets_hash == "bets_hash"
    assert (
        DecisionMakerAbciApp.transition_function[RankingReceiveRound][Event.DONE]
        is FinishedWithoutDecisionRound
    )


def test_row_3_next_periods_pick_best_score_with_checks_unchanged() -> None:
    """Best score first; held, cooling and book-failed markets as today."""
    bets = _listed(12)
    bets[2].research_score, bets[5].research_score = 0.9, 0.95
    bets[5].investments = {"Yes": [5], "No": []}  # held: not re-bet
    assert _sampled(bets) == "m2"

    bets[2].processed_timestamp = NOW - 60  # declined a minute ago: cooling
    bets[9].research_score = 0.6
    assert _sampled(bets) == "m9"

    # the book of m9 cannot take a bet: it is stamped, and the next market is tried
    sampler = _behaviour(SamplingBehaviour, bets)
    sampler._book_can_take_bet = lambda bet: (yield) or bet.id != "m9"
    payload = _act(sampler)
    assert (
        bets[payload.index].id == "m11"
    )  # unscored list markets follow today's order, by liquidity
    assert bets[9].processed_timestamp == NOW

    # after the cooldown, a stamped list market goes after every untried one
    later = NOW + COOLDOWN
    assert _sampled(bets, now=later) == "m11"
    for bet in bets:
        if bet.id not in ("m2", "m9"):
            bet.queue_status = QueueStatus.PROCESSED
    assert _sampled(bets, now=later) == "m2"


def test_row_4_renewal_rule() -> None:
    """Re-rank when 24 h old or used up with 10+ never-ranked; else today's order."""
    expired = _listed(12, ranked_at=NOW - RANKING_MAX_AGE)
    assert len(_ranked_ids(_request(expired))) == 12

    used_up = _listed(12, queue_status=QueueStatus.PROCESSED)
    fresh = [_bet(i) for i in range(30, 40)]
    assert sorted(_ranked_ids(_request(used_up + fresh))) == sorted(b.id for b in fresh)

    few_fresh = fresh[:9]
    assert _request(used_up + few_fresh).mech_tool is None
    assert _sampled(used_up + few_fresh) == _todays_pick(few_fresh) == "m38"

    # every list market fails the price rule: no request, today's order
    skewed = _listed(12, outcomeTokenMarginalPrices=[0.9, 0.1])
    assert _request(skewed + few_fresh).mech_tool is None
    assert _sampled(skewed + few_fresh) == "m38"

    # one request takes today's first 100 markets; the next period sends the
    # rest on the same list
    many = [_bet(i) for i in range(RANKING_MAX_MARKETS + 20)]
    ids = _ranked_ids(_request(many))
    assert len(ids) == RANKING_MAX_MARKETS and ids[0] == f"m{len(many) - 1}"
    assert {bet.ranked_at for bet in many} == {NOW, -NOW}
    rest = _ranked_ids(_request(many, now=NOW + 60))
    assert sorted(rest) == sorted(f"m{i}" for i in range(20))
    assert {bet.ranked_at for bet in many} == {NOW}

    # an unscored answer: nothing is re-sent while no market was never ranked
    _receive(many, None)
    assert _request(many, now=NOW + 120).mech_tool is None

    # a 24 h renewal keeps today's order and queues again what does not fit in its request
    pool = [_bet(i) for i in range(180)]
    first = _ranked_ids(_request(pool))
    for bet in pool:
        if bet.ranked_at == NOW:
            bet.research_score = 0.9
    # never-ranked markets less liquid than today's first 100 stay behind them
    pool += [_bet(i, scaledLiquidityMeasure=1.0) for i in range(200, 220)]
    assert _ranked_ids(_request(pool, now=NOW + RANKING_MAX_AGE)) == first
    assert {bet.ranked_at for bet in pool} == {
        NOW + RANKING_MAX_AGE,
        -NOW - RANKING_MAX_AGE,
    }


@pytest.mark.parametrize(
    "result, expected",
    [
        (None, {}),
        ('{"error": "invalid_input"}', {}),
        ("not json", {}),
        ('{"ranking": "m1"}', {}),
        ('{"ranking": [{"id": ["m1"], "score": 0.5}]}', {}),
        (
            json.dumps(
                {
                    "ranking": [
                        {"id": "m1", "score": 0.7},
                        {"id": "m1", "score": 0.1},
                        {"id": "m2", "score": None},
                        {"id": "m3", "score": 1.7},
                        {"id": "m4", "score": "0.5"},
                        {"id": "m5", "score": float("nan")},
                        {"id": "unknown", "score": 0.9},
                        {"id": "m6", "score": 0},
                    ]
                }
            ),
            {"m1": 0.7, "m6": 0.0},
        ),
    ],
    ids=["timeout", "error", "bad-json", "not-a-list", "bad-entry", "partial"],
)
def test_row_5_failed_or_malformed_ranking_keeps_valid_scores(
    result: Optional[str], expected: Dict[str, float]
) -> None:
    """Valid scores kept, the rest unscored, and no second ranking."""
    bets = _listed(12)
    stale = _bet(40, ranked_at=NOW - DAY, research_score=0.2)  # an older list
    _receive(bets + [stale], result)
    scores = {b.id: b.research_score for b in bets if b.research_score is not None}
    assert scores == expected
    assert stale.research_score == 0.2
    assert _request(bets + [stale]).mech_tool is None
    expected_pick = max(expected, key=expected.__getitem__) if expected else "m11"
    assert _sampled(bets) == expected_pick


def test_row_6_too_few_candidates_or_empty_pool_requests_nothing() -> None:
    """Fewer than 10 candidates, or an empty pool: no ranking, as today."""
    nine = [_bet(i) for i in range(9)]
    assert _request(nine).mech_tool is None
    assert _sampled(nine) == "m8"
    assert _request([]).mech_tool is None
    assert _sampled([]) is None
    assert _end_block(RankingRequestRound, _request(nine))[1] == Event.NONE
    assert (
        DecisionMakerAbciApp.transition_function[RankingRequestRound][Event.NONE]
        is SamplingRound
    )


def test_row_7_router_and_blacklisting() -> None:
    """A prediction goes to decision-receive; a ranking never; a failed ranking is a no-op blacklisting."""
    bets = _listed(12)
    receiver = _receive(bets, '{"p_yes": 0.9, "p_no": 0.1}', ranking=False)
    assert receiver.payloads[-1].bets_hash is None
    receiver.read_bets.assert_not_called()
    receiver.store_bets.assert_not_called()
    none = _end_block(RankingReceiveRound, UpdateBetsPayload("agent", None))
    assert none[1] == Event.NONE
    assert (
        DecisionMakerAbciApp.transition_function[RankingReceiveRound][Event.NONE]
        is DecisionReceiveRound
    )

    done = _end_block(RankingReceiveRound, UpdateBetsPayload("agent", "bets_hash"))
    assert done[1] == Event.DONE
    targets = set(
        DecisionMakerAbciApp.transition_function[RankingReceiveRound].values()
    )
    assert targets == {
        FinishedWithoutDecisionRound,
        DecisionReceiveRound,
        RankingReceiveRound,
    }

    # a timed-out or failed ranking reaches blacklisting, which changes nothing
    db = _db(
        mech_tool=RANKING_TOOL,
        sampled_bet_index=None,
        tx_submitter="mech_request_round",
    )
    blacklister = _behaviour(BlacklistingBehaviour, bets, db=db)
    blacklister.context.state.mech_timed_out = True
    blacklister._setup_policy_and_tools = lambda: (yield) or True
    blacklister._policy = MagicMock()
    blacklister._policy.serialize.return_value = "policy"
    payload = _act(blacklister)
    assert (payload.bets_hash, payload.policy) == (None, "policy")
    blacklister.context.state.penalize_last_called_mech.assert_called_once()
    blacklister._policy.tool_responded.assert_not_called()
    blacklister.store_bets.assert_not_called()
    assert all(
        b.queue_status == QueueStatus.TO_PROCESS and not b.processed_timestamp
        for b in bets
    )
    assert _end_block(BlacklistingRound, payload)[1] == Event.DONE
    assert (
        DecisionMakerAbciApp.transition_function[BlacklistingRound][Event.DONE]
        is FinishedWithoutDecisionRound
    )


def test_row_8_prediction_path_unchanged() -> None:
    """Tool selection and decision request untouched; the classifier rejects the ranking tool."""
    # the published metadata of the ranking tool, as built from mech-predict-internal
    metadata = {
        "description": (
            "Orders a list of candidate markets by how much public information can "
            "inform them. One model call scores each market from 0 to 1 and returns "
            "the market ids in rank order. Optional inputs are each market's "
            "liquidity and the caller's own settings as context. It does not search "
            "the web and does not answer any market question."
        ),
        "input": {
            "type": "object",
            "description": (
                "JSON object with a markets list (each market has an id, a title, and "
                "optional close_time in epoch seconds and liquidity in USD) and an "
                "optional context object of short texts describing the caller's own "
                "settings"
            ),
        },
        "output": {
            "type": "object",
            "schema": {
                "properties": {
                    "result": {
                        "type": "string",
                        "example": '{"ranking": [{"id": "0x9f2c", "score": 0.82}]}',
                    }
                }
            },
        },
    }
    assert explain_prediction_tool(metadata)[0] is False
    # a ranking tool picked by tool selection stays on the prediction path
    picked = SynchronizedData(_db(mech_tool=RANKING_TOOL, sampled_bet_index=3))
    assert not picked.is_ranking_period
    assert not SynchronizedData(_db()).is_ranking_period
    transitions = DecisionMakerAbciApp.transition_function
    assert transitions[RandomnessRound][Event.DONE] is RankingRequestRound
    assert transitions[SamplingRound][Event.DONE].__name__ == "ToolSelectionRound"
    behaviours = AgentDecisionMakerRoundBehaviour.behaviours
    assert {RankingRequestBehaviour, RankingReceiveBehaviour} <= behaviours
    assert {"ranking_request_round", "ranking_receive_round"} <= set(ROUNDS_INFO)


def test_row_9_old_market_file_and_restart() -> None:
    """An old market file loads; a restart mid-ranking does not re-request."""
    old = json.loads(serialize_bets([_bet(1)]) or "")
    del old[0]["ranked_at"], old[0]["research_score"]
    (loaded,) = json.loads(json.dumps(old), cls=BetsDecoder)
    assert (loaded.ranked_at, loaded.research_score) == (0, None)
    roundtrip = json.loads(serialize_bets(_listed(1)) or "", cls=BetsDecoder)
    assert roundtrip[0].ranked_at == NOW - 60

    # restarted after the stamp was stored, before the answer arrived
    stamped = json.loads(serialize_bets(_listed(12)) or "", cls=BetsDecoder)
    assert _request(stamped, now=NOW + 600).mech_tool is None
    assert _request(stamped, now=NOW - 60 + RANKING_MAX_AGE).mech_tool == RANKING_TOOL


def test_answer_without_a_ranking_is_logged() -> None:
    """A failed request logs the mech's error; an answer with no usable ranking logs the cause."""
    receiver = _receive(_listed(3), None, error="mech timed out")
    receiver.context.logger.warning.assert_called_once()
    message = receiver.context.logger.warning.call_args[0][0]
    assert "no answer from the mech" in message
    assert "mech timed out" in message

    receiver = _receive(_listed(3), json.dumps({"scores": []}))
    receiver.context.logger.warning.assert_called_once()
    assert "no ranking in the answer" in receiver.context.logger.warning.call_args[0][0]


def test_quiet_pool_logs() -> None:
    """The ranking round runs the pool checks without Sampling's per-period logs."""
    requester = _behaviour(RankingRequestBehaviour, [])
    assert requester.pool_logger is QUIET_LOGGER and QUIET_LOGGER.disabled
    sampler = _behaviour(SamplingBehaviour, [])
    assert sampler.pool_logger is sampler.context.logger


def test_review_fixes() -> None:
    """Tools unset, held and book-failed markets, and malformed or boolean scores."""
    bets = [_bet(i) for i in range(12)]
    # the tools are unset until the first redeem round reaches consensus
    assert _request(bets, db=_db(available_mech_tools=None)).mech_tool is None

    # held markets keep their priority in multi-bets mode
    listed = _listed(12)
    listed[3].research_score = 0.9
    held = _bet(50, investments={"Yes": [5], "No": []})
    sampler = _behaviour(SamplingBehaviour, listed + [held])
    assert (listed + [held])[sampler._sampled_bet_idx(listed + [held])].id == "m50"

    # a list market whose book check failed goes back to today's order
    stamped = _listed(3, processed_timestamp=NOW - 2 * COOLDOWN)
    untried = [_bet(i) for i in range(30, 35)]
    assert _sampled(stamped + untried) == _todays_pick(stamped + untried) == "m34"

    # a malformed entry is skipped, and a boolean is not a score
    answer = [
        {"id": "m1", "score": 0.7},
        {"id": "m2"},
        "junk",
        {"id": "m3", "score": True},
    ]
    _receive(listed, json.dumps({"ranking": answer}))
    assert listed[1].research_score == 0.7
    assert listed[3].research_score == 0.9 and listed[2].research_score is None


def _run(gen: Generator) -> Any:
    """Run a generator to the end and return its value."""
    while True:
        try:
            next(gen)
        except StopIteration as stop:
            return stop.value


def _gamma_books(bet: Bet) -> Dict[str, Dict[str, Any]]:
    """The order books the book check reads, built from a market's best bid and ask."""

    def level(price: Optional[float]) -> List[Dict[str, Any]]:
        return [] if price is None or not 0 < price < 1 else [{"price": str(price)}]

    bid, ask = bet.best_bid, bet.best_ask
    return {
        "t-yes": {"asks": level(ask), "bids": level(bid)},
        "t-no": {
            "asks": level(None if bid is None else float(f"{1 - bid:.2f}")),
            "bids": level(None if ask is None else float(f"{1 - ask:.2f}")),
        },
    }


def _book_check(bet: Bet) -> bool:
    """Run Sampling's book check on the books of the market's stored best bid and ask."""
    sampler = _behaviour(SamplingBehaviour, [bet])

    def send(request: Dict[str, Any]) -> Generator[None, None, Dict[str, Any]]:
        yield
        return _gamma_books(bet)[request["params"]["token_id"]]

    sampler.send_polymarket_connection_request = send
    return _run(sampler._book_can_take_bet(bet))


TOKENS = {"Yes": "t-yes", "No": "t-no"}
BOOKS = [
    (0.45, 0.5),  # spread 0.05: accepted
    (0.3, 0.5),  # spread 0.2: rejected
    (0.02, 1.0),  # no Yes ask; No asks 0.98 with no bid: accepted
    (0.0, 0.995),  # Yes ask 0.995 and no No ask: rejected
    (0.004, 0.9),  # No ask 0.996; Yes ask 0.9 with spread 0.896: rejected
    (0.41, 0.51),  # spread 0.1 at the band's edge: accepted
    (None, 0.5),  # no bid stored: the Yes side has asks and no spread, accepted
    (None, None),  # not stored: accepted, as an unreadable book
]


def test_book_rule_and_score_floor() -> None:
    """The list leaves out the markets the book check would reject on their stored book; low scores follow today's order."""
    bets = [_bet(i, outcome_token_ids=TOKENS) for i in range(14)]
    for bet, (bid, ask) in zip(bets, BOOKS):
        bet.best_bid, bet.best_ask = bid, ask
    ids = _ranked_ids(_request(bets))
    assert {"m1", "m3", "m4"}.isdisjoint(ids)
    assert {"m0", "m2", "m5", "m6", "m7", "m8"} <= set(ids)
    # the stored rule is Sampling's book check on the same prices
    requester = _behaviour(RankingRequestBehaviour, bets)
    for bet in bets[: len(BOOKS) - 1]:
        assert requester._has_room_to_trade(bet) is _book_check(bet)
    # the book rule applies on Polymarket only
    requester.context.params.is_running_on_polymarket = False
    assert requester._has_room_to_trade(bets[1])

    # list markets scored under ranking_min_score follow today's order
    listed = _listed(12)
    listed[3].research_score, listed[4].research_score = 0.4, 0.6
    assert _sampled(listed) == "m4"
    listed[4].research_score = 0.45
    assert _sampled(listed) == _todays_pick(listed) == "m11"


def test_weighted_pick_spreads_over_the_list() -> None:
    """The pick is a score-weighted draw: the same in one period, spread over periods, high scores more often."""
    listed = _listed(12)
    for i, bet in enumerate(listed):
        bet.research_score = 0.5 + i * 0.04  # 0.50 to 0.94
    picks = [
        _sampled(listed, db=_db(most_voted_randomness=f"{seed:064x}"))
        for seed in range(300)
    ]
    assert _sampled(listed, db=_db(most_voted_randomness="01" * 32)) == _sampled(
        listed, db=_db(most_voted_randomness="01" * 32)
    )
    assert len(set(picks)) >= 8
    assert picks.count("m11") > picks.count("m0")
    # the draw is seeded apart from the tool policy, which reads the same value
    randomness = "ab" * 32
    rng = random.Random(f"{randomness}:ranked-pick")
    assert rng.random() != random.Random(randomness).random()

    # a zero floor with zero scores falls back to an even draw
    for bet in listed:
        bet.research_score = 0.0
    sampler = _behaviour(SamplingBehaviour, listed)
    sampler.context.params.ranking_min_score = 0.0
    assert listed[sampler._sampled_bet_idx(listed)].id in {b.id for b in listed}


def test_the_list_holds_every_market_todays_pick_could_send() -> None:
    """Every untried market Sampling's checks and book check accept is ranked, the markets of one event included."""
    accepted = [
        _bet(i, title="Will Trump say X?", best_bid=0.45, best_ask=0.5)
        for i in range(150)
    ]
    rejected = [
        _bet(300, outcomeTokenMarginalPrices=[0.85, 0.15]),
        _bet(301, neg_risk=True),
        _bet(302, poly_tags=["weather"]),
        _bet(303, best_bid=0.2, best_ask=0.5),
        _bet(304, queue_status=QueueStatus.PROCESSED),
    ]
    pool = accepted + rejected
    sent = _ranked_ids(_request(pool)) + _ranked_ids(_request(pool, now=NOW + 60))
    assert sorted(sent) == sorted(bet.id for bet in accepted)
    assert {bet.ranked_at for bet in accepted} == {NOW}
    assert {bet.ranked_at for bet in rejected} == {0}

    # a market of the second request is picked like one of the first
    for bet in accepted:
        bet.research_score = 0.0
    accepted[0].research_score = 0.9
    assert _sampled(pool) == "m0"


def test_the_queue_is_sent_once_and_holds_untried_markets_only() -> None:
    """A queued market that misses its request waits for a renewal; a failed book check keeps a market off the list."""
    pool = [_bet(i) for i in range(RANKING_MAX_MARKETS + 5)]
    _request(pool)
    queued = [bet for bet in pool if bet.ranked_at == -NOW]
    assert len(queued) == 5
    # two queued markets are skewed when the queue goes out: three are sent
    for bet in queued[:2]:
        bet.outcomeTokenMarginalPrices = [0.95, 0.05]
    assert len(_ranked_ids(_request(pool, now=NOW + 60))) == 3
    assert {bet.ranked_at for bet in queued[:2]} == {0}
    # back in range, they bring no request of their own while the list is in use
    for bet in queued[:2]:
        bet.outcomeTokenMarginalPrices = [0.5, 0.5]
    assert _request(pool, now=NOW + 120).mech_tool is None

    # when every queued market misses its request, the reset is stored and nothing is sent
    waiting = [_bet(i) for i in range(RANKING_MAX_MARKETS + 5)]
    _request(waiting)
    gone = [bet for bet in waiting if bet.ranked_at == -NOW]
    for bet in gone:
        bet.outcomeTokenMarginalPrices = [0.95, 0.05]
    requester = _behaviour(RankingRequestBehaviour, waiting, now=NOW + 60)
    assert _act(requester).mech_tool is None
    requester.store_bets.assert_called_once()
    assert {bet.ranked_at for bet in gone} == {0}

    # a list takes at most three requests; the markets past them follow today's order
    big = [_bet(i) for i in range(3 * RANKING_MAX_MARKETS + 50)]
    sizes = [len(_ranked_ids(_request(big, now=NOW + 60 * k))) for k in range(3)]
    assert sizes == [RANKING_MAX_MARKETS] * 3
    tail = {bet.id for bet in big if bet.ranked_at == 0}
    assert len(tail) == 50
    # scored, the list is in use and the tail brings no request
    for bet in big:
        bet.research_score = 0.9 if bet.ranked_at > 0 else None
    assert _request(big, now=NOW + 180).mech_tool is None
    # all unscored, the next list sends the tail first and then nothing is left to renew
    for bet in big:
        bet.research_score = None
    assert tail <= set(_ranked_ids(_request(big, now=NOW + 240)))
    later = [_request(big, now=NOW + 300 + 60 * k).mech_tool for k in range(3)]
    assert later == [RANKING_TOOL, RANKING_TOOL, None]

    # a market whose book check failed is not a candidate, so it is never queued
    untried = [_bet(i) for i in range(RANKING_MAX_MARKETS)]
    stamped = [_bet(200 + i, processed_timestamp=NOW - 2 * COOLDOWN) for i in range(3)]
    assert len(_ranked_ids(_request(untried + stamped))) == RANKING_MAX_MARKETS
    assert all(bet.ranked_at == 0 for bet in stamped)
    assert _request(untried + stamped, now=NOW + 60).mech_tool is None


def test_one_market_per_event() -> None:
    """A ranking sends one market per Polymarket event, none from an event with a live position."""
    bets = [_bet(i, poly_event_id=f"e{i}") for i in range(12)]
    rungs = [_bet(i, poly_event_id="ladder") for i in range(20, 24)]
    held = _bet(30, poly_event_id="e5", investments={"Yes": [5], "No": []})
    unknown = [_bet(i) for i in range(40, 42)]  # stored before the event id existed
    ids = _ranked_ids(_request(bets + rungs + [held] + unknown))
    assert set(ids) & {"m20", "m21", "m22", "m23"} == {"m23"}  # the most liquid rung
    assert "m5" not in ids and "m30" not in ids
    assert {"m40", "m41"} <= set(ids)

    # a position in an expired market of the event does not keep the event out
    held.queue_status = QueueStatus.EXPIRED
    assert "m5" in _ranked_ids(_request(bets + [held], now=NOW + DAY))

    # a listed rung whose unranked sibling became more liquid does not renew a fresh list
    listed = [
        _bet(100 + i, poly_event_id=f"e{i}", ranked_at=NOW - 60, research_score=0.9)
        for i in range(12)
    ]
    siblings = [
        _bet(200 + i, poly_event_id=f"e{i}", scaledLiquidityMeasure=500.0)
        for i in range(12)
    ]
    assert _request(listed + siblings).mech_tool is None
    assert _sampled(listed + siblings) in {b.id for b in listed}

    # a refetch refreshes the stored event id
    stored, fetched = _bet(1), _bet(1, poly_event_id="e1")
    stored.update_market_info(fetched)
    assert stored.poly_event_id == "e1"


def test_one_market_per_event_in_the_queue_and_renewals() -> None:
    """The queue, a used-up renewal and its 10+ gate all count one market per event."""
    # a queued market whose sibling became more liquid is not sent, and is reset
    bets = [_bet(i, poly_event_id=f"e{i}") for i in range(RANKING_MAX_MARKETS + 5)]
    _request(bets)
    queued = [bet for bet in bets if bet.ranked_at == -NOW]
    siblings = [
        _bet(500 + i, poly_event_id=bet.poly_event_id) for i, bet in enumerate(queued)
    ]
    assert _request(bets + siblings, now=NOW + 60).mech_tool is None
    assert {bet.ranked_at for bet in queued} == {0}

    # a used-up list renews with one market per event
    used = [
        _bet(
            100 + i,
            poly_event_id=f"used{i}",
            ranked_at=NOW - 60,
            research_score=0.9,
            processed_timestamp=NOW - 10,
        )
        for i in range(12)
    ]
    fresh = [_bet(i, poly_event_id=f"e{i}") for i in range(12)]
    rungs = [_bet(50 + i, poly_event_id="ladder") for i in range(3)]
    ids = _ranked_ids(_request(used + fresh + rungs))
    assert len(set(ids) & {"m50", "m51", "m52"}) == 1

    # the 10+ gate counts events, not markets
    clustered = [_bet(200 + i, poly_event_id=f"c{i % 3}") for i in range(12)]
    assert _request(used + clustered).mech_tool is None


FLAGGED_LOG = "[RANKING] Polymarket's CLOB unreachable: no ranking request this period."


def _flagged(cls: Type[Any], bets: List[Bet], failures: int = 5, **kwargs: Any) -> Any:
    """Build a behaviour with the given count of failed book fetches in a row; 5 flags the CLOB."""
    behaviour = _behaviour(cls, bets, **kwargs)
    behaviour.context.state.orderbook_failures = failures
    return behaviour


def _probing(sampler: Any, reached: bool) -> Any:
    """Make Sampling's probe reach the CLOB or not, and let any book it reads take a bet."""

    def send(request: Dict[str, Any]) -> Generator[None, None, Any]:
        yield
        return {"asks": [], "bids": []} if reached else None

    sampler.send_polymarket_connection_request = send
    sampler._book_can_take_bet = lambda bet: (yield) or True
    return sampler


def test_no_ranking_request_while_the_clob_is_flagged() -> None:
    """Flagged: no request whether or not a list is due, no stamp touched, one log line, on to Sampling."""
    used_up = _listed(12, queue_status=QueueStatus.PROCESSED)
    due = {
        "no list": [_bet(i) for i in range(12)],
        "expired list": _listed(12, ranked_at=NOW - RANKING_MAX_AGE),
        # an unscored list with 10+ never-ranked markets is due for renewal
        "used-up list": used_up + [_bet(i) for i in range(30, 40)],
        "not due": _listed(12),
    }
    for bets in due.values():
        stamps = [bet.ranked_at for bet in bets]
        requester = _flagged(RankingRequestBehaviour, bets)
        payload = _act(requester)
        assert payload.mech_tool is None and payload.mech_requests is None
        assert [bet.ranked_at for bet in bets] == stamps
        requester.store_bets.assert_not_called()
        requester.context.logger.info.assert_called_once_with(FLAGGED_LOG)
        assert _end_block(RankingRequestRound, payload)[1] == Event.NONE

    # one failure short of the threshold, the request goes out as today
    below = _flagged(RankingRequestBehaviour, due["no list"], failures=4)
    assert _act(below).mech_tool == RANKING_TOOL
    # the threshold is the configured one
    lower = _flagged(RankingRequestBehaviour, due["no list"], failures=3)
    lower.context.params.orderbook_unavailable_threshold = 3
    assert _act(lower).mech_tool is None


def test_flagged_for_twelve_periods_sends_no_mech_request() -> None:
    """A list due and 10+ never-ranked markets, the CLOB unreachable for 12 periods: no ranking, no prediction."""
    bets = [_bet(i, outcome_token_ids=TOKENS) for i in range(12)]
    failures, rankings, predictions = 5, 0, 0
    for period in range(12):
        now = NOW + 300 * period
        request = _act(_flagged(RankingRequestBehaviour, bets, failures, now=now))
        rankings += request.mech_tool is not None
        sampler = _probing(_flagged(SamplingBehaviour, bets, failures, now=now), False)
        predictions += _act(sampler).index is not None
        failures = sampler.context.state.orderbook_failures
    assert (rankings, predictions) == (0, 0)
    assert failures == 5 + 12
    assert all(bet.ranked_at == 0 for bet in bets)


def test_recovery_predicts_first_and_ranks_from_the_next_period() -> None:
    """The period the CLOB answers: no ranking, one prediction from a fresh list or today's order; a due list follows."""
    fresh = _listed(12, outcome_token_ids=TOKENS)
    fresh[3].research_score = 0.9
    stale = _listed(12, ranked_at=NOW - RANKING_MAX_AGE, outcome_token_ids=TOKENS)
    stale[3].research_score = 0.9
    for bets, pick in ((fresh, "m3"), (stale, _todays_pick(stale))):
        assert _act(_flagged(RankingRequestBehaviour, bets)).mech_tool is None
        sampler = _probing(_flagged(SamplingBehaviour, bets), True)
        assert bets[_act(sampler).index].id == pick
        failures = sampler.context.state.orderbook_failures
        assert failures == 0
        later = _flagged(RankingRequestBehaviour, bets, failures, now=NOW + 300)
        assert (_act(later).mech_tool == RANKING_TOOL) is (bets is stale)


def test_the_rest_of_a_list_waits_while_flagged() -> None:
    """Flagged after request 1 of 3: the rest goes out within a day of the list, a fresh list after it."""
    for recovered, continued in ((NOW + DAY - 600, True), (NOW + DAY, False)):
        pool = [_bet(i) for i in range(3 * RANKING_MAX_MARKETS)]
        first = _ranked_ids(_request(pool))
        queued = {bet.id for bet in pool if bet.ranked_at == -NOW}
        assert len(queued) == 2 * RANKING_MAX_MARKETS
        for period in range(1, 4):
            assert (
                _act(
                    _flagged(RankingRequestBehaviour, pool, now=NOW + 300 * period)
                ).mech_requests
                is None
            )
        assert {bet.id for bet in pool if bet.ranked_at == -NOW} == queued

        ids = _ranked_ids(_request(pool, now=recovered))
        if continued:
            ids += _ranked_ids(_request(pool, now=recovered + 60))
            assert sorted(first + ids) == sorted(bet.id for bet in pool)
            assert {bet.ranked_at for bet in pool} == {NOW}
        else:
            assert ids[0] == first[0]
            assert {bet.ranked_at for bet in pool} == {recovered, -recovered}


def test_the_flag_applies_on_polymarket_with_ranking_on_only() -> None:
    """Omenstrat, benchmarking and ranking off: as today, whatever the failure count."""
    bets = [_bet(i) for i in range(12)]
    omen = _flagged(RankingRequestBehaviour, bets)
    omen.context.params.is_running_on_polymarket = False
    assert _act(omen).mech_tool == RANKING_TOOL

    benchmarking = _flagged(
        RankingRequestBehaviour, bets, benchmarking=True, now=NOW + DAY
    )
    assert _act(benchmarking).mech_tool == RANKING_TOOL

    switched_off = _flagged(RankingRequestBehaviour, bets, now=NOW + 2 * DAY)
    switched_off.context.params.enable_market_ranking = False
    assert _act(switched_off).mech_tool is None
    switched_off.context.logger.info.assert_not_called()


GATED = ["hide-from-new"]
LIVE = NOW - 60


def _gated(i: int, **kwargs: Any) -> Bet:
    """Build an untried hide-from-new market."""
    return _bet(i, poly_tags=GATED, **kwargs)


def test_gated_markets_reach_the_ranking_batch() -> None:
    """Hide-from-new markets are ranked; with the tag disabled again they are not."""
    bets = [_gated(i) for i in range(12)]
    requester = _behaviour(RankingRequestBehaviour, bets)
    skill = Path(__file__).parents[1] / "skill.yaml"
    params = yaml.safe_load(skill.read_text())["models"]["params"]["args"]
    requester.context.params.disabled_polymarket_tags = params[
        "disabled_polymarket_tags"
    ]
    assert sorted(_ranked_ids(_act(requester))) == sorted(b.id for b in bets)

    rolled_back = _behaviour(RankingRequestBehaviour, [_gated(i) for i in range(12)])
    rolled_back.context.params.disabled_polymarket_tags = GATED
    assert _act(rolled_back).mech_tool is None


def test_gated_market_scored_on_the_live_list_can_be_picked() -> None:
    """A score at or above the minimum on the latest list, under a day old."""
    untagged = _bet(1, ranked_at=LIVE)
    on_list = _gated(40, ranked_at=LIVE, research_score=0.5)
    assert _sampled([untagged, on_list]) == "m40"

    almost_a_day = NOW - RANKING_MAX_AGE + 1
    old = [
        _bet(1, ranked_at=almost_a_day),
        _gated(40, ranked_at=almost_a_day, research_score=0.9),
    ]
    # both declined once, so plain order: the gated one less recently
    old[0].processed_timestamp = NOW - COOLDOWN - 1
    old[1].processed_timestamp = NOW - 2 * COOLDOWN
    assert _sampled(old) == "m40"


@pytest.mark.parametrize(
    "latest, gated_kwargs",
    (
        (0, dict()),
        (LIVE, dict(ranked_at=LIVE, research_score=0.49)),
        (LIVE, dict(ranked_at=LIVE)),
        (LIVE, dict(ranked_at=LIVE - 60, research_score=0.9)),
        (LIVE, dict(ranked_at=-LIVE, research_score=0.9)),
        (
            NOW - RANKING_MAX_AGE,
            dict(ranked_at=NOW - RANKING_MAX_AGE, research_score=0.9),
        ),
    ),
    ids=(
        "no-list",
        "below-the-minimum",
        "missed-answer",
        "stale-score-from-an-older-list",
        "queued-for-a-later-request",
        "list-a-day-old",
    ),
)
def test_unheld_gated_market_without_a_qualifying_score_is_not_picked(
    latest: int, gated_kwargs: Dict[str, Any]
) -> None:
    """Today's order would pick the more liquid gated market; the gate drops it."""
    bets = [_bet(1, ranked_at=latest), _gated(40, **gated_kwargs)]
    assert _todays_pick(bets) == "m40"
    assert _sampled(bets) == "m1"

    # ranking off leaves no list, and no score
    assert _sampled([_bet(1), _gated(40)]) == "m1"
    assert _sampled([_gated(40)]) is None


def test_unscored_gated_market_is_not_picked_with_a_zero_minimum() -> None:
    """A missed answer is no score, even when any score would qualify."""
    bets = [_bet(1, ranked_at=LIVE), _gated(40, ranked_at=LIVE)]
    sampler = _behaviour(SamplingBehaviour, bets)
    sampler.context.params.ranking_min_score = 0.0
    assert bets[sampler._sample()].id == "m1"

    alone = _behaviour(SamplingBehaviour, bets[1:])
    assert alone._sample() is None
    alone.context.logger.warning.assert_any_call(
        "All 1 candidate bets were dropped by the score gate!"
    )


def test_gate_holds_when_the_list_is_skipped_for_a_held_market() -> None:
    """A held market skips the list; plain order still never picks a low score."""
    held = _bet(2, ranked_at=LIVE, queue_status=QueueStatus.PROCESSED)
    held.investments = {"Yes": [5], "No": []}
    low = _gated(40, ranked_at=LIVE, research_score=0.2)
    high = _gated(3, ranked_at=LIVE, research_score=0.9)
    untagged = _bet(1, ranked_at=LIVE)
    bets = [held, low, high, untagged]
    sampler = _behaviour(SamplingBehaviour, bets)
    sampler.context.params.use_multi_bets_mode = True
    assert _todays_pick(bets) == "m40"
    assert bets[sampler._sample()].id == "m3"


def test_held_gated_market_is_picked_as_today() -> None:
    """A held hide-from-new market keeps its pick, whatever its score."""
    held = _gated(40, ranked_at=LIVE - DAY, research_score=0.1)
    held.investments = {"Yes": [5], "No": []}
    bets = [_bet(1, ranked_at=LIVE), held]
    sampler = _behaviour(SamplingBehaviour, bets)
    sampler.context.params.use_multi_bets_mode = True
    assert bets[sampler._sample()].id == "m40"
    sampler.context.logger.info.assert_any_call(
        "[POLYSTRAT] filter=score_gate input=2 dropped=0 kept=2 held=1 list_live=true"
    )


def test_gate_matches_the_tag_as_the_disabled_tag_filter_does() -> None:
    """Casing and padding on the stored tag do not let a market through."""
    bets = [_bet(1), _bet(40, poly_tags=["  Hide-From-New "])]
    sampler = _behaviour(SamplingBehaviour, bets)
    assert bets[sampler._sample()].id == "m1"
    sampler.context.logger.info.assert_any_call(
        "[POLYSTRAT] filter=score_gate input=2 dropped=1 kept=1 held=0 list_live=false"
    )


def test_gated_market_disabled_again_is_never_picked() -> None:
    """Rollback: with the tag back in the disabled list, even a top score is dropped."""
    bets = [_bet(1, ranked_at=LIVE), _gated(40, ranked_at=LIVE, research_score=0.9)]
    sampler = _behaviour(SamplingBehaviour, bets)
    sampler.context.params.disabled_polymarket_tags = GATED
    assert bets[sampler._sample()].id == "m1"
    # the disabled-tag filter runs first, so the gate never sees the market
    sampler.context.logger.info.assert_any_call(
        "[POLYSTRAT] filter=score_gate input=1 dropped=0 kept=1 held=0 list_live=true"
    )


def test_gate_is_off_in_benchmarking_mode() -> None:
    """Benchmarking never uses the list, so unscored gated markets stay in."""
    unscored = [_gated(40)]
    sampler = _behaviour(SamplingBehaviour, unscored, benchmarking=True)
    assert sampler._drop_ungated(unscored, NOW) == unscored
