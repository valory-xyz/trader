"""This module contains the sell outcome token state of the decision-making abci app."""

from packages.valory.skills.decision_maker_abci.states.base import TxPreparationRound


class SellOutcomeTokenRound(TxPreparationRound):
    """A round for selling a token."""
