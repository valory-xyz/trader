stateDiagram-v2
    PostTxSettlementRound --> FinishedBetPlacementTxRound: <center>BET_PLACEMENT_DONE</center>
    PostTxSettlementRound --> FinishedMechRequestTxRound: <center>MECH_REQUESTING_DONE</center>
    PostTxSettlementRound --> FinishedRedeemingTxRound: <center>REDEEMING_DONE</center>
    PostTxSettlementRound --> PostTxSettlementRound: <center>ROUND_TIMEOUT</center>
    PostTxSettlementRound --> FinishedSellOutcomeTokensTxRound: <center>SELL_OUTCOME_TOKENS_DONE</center>
    PostTxSettlementRound --> FinishedSetApprovalTxRound: <center>SET_APPROVAL_DONE</center>
    PostTxSettlementRound --> FinishedStakingTxRound: <center>STAKING_DONE</center>
    PostTxSettlementRound --> FinishedSubscriptionTxRound: <center>SUBSCRIPTION_DONE</center>
    PostTxSettlementRound --> FinishedPolymarketSwapTxRound: <center>SWAP_DONE</center>
    PostTxSettlementRound --> FailedMultiplexerRound: <center>UNRECOGNIZED</center>
    PostTxSettlementRound --> FinishedOmenWithdrawTxRound: <center>WITHDRAW_OMEN_DONE</center>
    PostTxSettlementRound --> FinishedPolymarketWrapCollateralTxRound: <center>WRAP_COLLATERAL_DONE</center>
    PreTxSettlementRound --> ChecksPassedRound: <center>CHECKS_PASSED</center>
    PreTxSettlementRound --> PreTxSettlementRound: <center>REFILL_REQUIRED<br />ROUND_TIMEOUT<br />NO_MAJORITY</center>
