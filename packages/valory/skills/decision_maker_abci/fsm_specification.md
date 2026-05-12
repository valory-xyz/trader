stateDiagram-v2
    CheckBenchmarkingModeRound --> PolymarketWrapCollateralRound: <center>BENCHMARKING_DISABLED</center>
    CheckBenchmarkingModeRound --> BenchmarkingRandomnessRound: <center>BENCHMARKING_ENABLED</center>
    CheckBenchmarkingModeRound --> ImpossibleRound: <center>NONE</center>
    CheckBenchmarkingModeRound --> CheckBenchmarkingModeRound: <center>NO_MAJORITY<br />ROUND_TIMEOUT</center>
    CheckBenchmarkingModeRound --> PolymarketSetApprovalRound: <center>SET_APPROVAL</center>
    DecisionReceiveRound --> BetPlacementRound: <center>DONE</center>
    DecisionReceiveRound --> FinishedDecisionMakerRound: <center>DONE_NO_SELL</center>
    DecisionReceiveRound --> SellOutcomeTokensRound: <center>DONE_SELL</center>
    DecisionReceiveRound --> BlacklistingRound: <center>UNPROFITABLE<br />MECH_RESPONSE_ERROR<br />TIE</center>
    DecisionReceiveRound --> DecisionReceiveRound: <center>NO_MAJORITY<br />ROUND_TIMEOUT</center>
    DecisionReceiveRound --> PolymarketBetPlacementRound: <center>POLYMARKET_DONE</center>
    DecisionRequestRound --> FinishedDecisionRequestRound: <center>DONE</center>
    DecisionRequestRound --> DecisionReceiveRound: <center>MOCK_MECH_REQUEST</center>
    DecisionRequestRound --> DecisionRequestRound: <center>NO_MAJORITY<br />ROUND_TIMEOUT</center>
    DecisionRequestRound --> BlacklistingRound: <center>SLOTS_UNSUPPORTED_ERROR</center>
    HandleFailedTxRound --> BlacklistingRound: <center>BLACKLIST</center>
    HandleFailedTxRound --> HandleFailedTxRound: <center>NO_MAJORITY</center>
    HandleFailedTxRound --> RedeemRound: <center>NO_OP</center>
    OmenWithdrawRound --> OmenWithdrawRound: <center>NO_MAJORITY<br />NONE</center>
    OmenWithdrawRound --> FinishedOmenWithdrawRound: <center>PREPARE_TX</center>
    OmenWithdrawRound --> WithdrawalIdleRound: <center>WITHDRAWAL_ROUND_TIMEOUT<br />WITHDRAWAL_DONE</center>
    PolymarketPostSetApprovalRound --> PolymarketSetApprovalRound: <center>APPROVAL_FAILED</center>
    PolymarketPostSetApprovalRound --> PolymarketWrapCollateralRound: <center>DONE</center>
    PolymarketPostSetApprovalRound --> ImpossibleRound: <center>NONE</center>
    PolymarketPostSetApprovalRound --> PolymarketPostSetApprovalRound: <center>NO_MAJORITY<br />ROUND_TIMEOUT</center>
    PolymarketWithdrawRound --> PolymarketWithdrawRound: <center>NO_MAJORITY<br />NONE</center>
    PolymarketWithdrawRound --> WithdrawalIdleRound: <center>WITHDRAWAL_ROUND_TIMEOUT<br />WITHDRAWAL_DONE</center>
    PostBetUpdateRound --> FinishedPostBetUpdateRound: <center>DONE</center>
    PostBetUpdateRound --> PostBetUpdateRound: <center>NO_MAJORITY<br />NONE<br />ROUND_TIMEOUT</center>
    PostOmenWithdrawRound --> PostOmenWithdrawRound: <center>NO_MAJORITY<br />WITHDRAWAL_ROUND_TIMEOUT<br />NONE</center>
    PostOmenWithdrawRound --> WithdrawalIdleRound: <center>WITHDRAWAL_DONE</center>
    RandomnessRound --> SamplingRound: <center>DONE</center>
    RandomnessRound --> ImpossibleRound: <center>NONE</center>
    RandomnessRound --> RandomnessRound: <center>NO_MAJORITY<br />ROUND_TIMEOUT</center>
    RedeemRouterRound --> RedeemRound: <center>DONE</center>
    RedeemRouterRound --> RedeemRouterRound: <center>NO_MAJORITY<br />NONE</center>
    RedeemRouterRound --> PolymarketRedeemRound: <center>POLYMARKET_DONE</center>
    BenchmarkingRandomnessRound --> SamplingRound: <center>DONE</center>
    BenchmarkingRandomnessRound --> ImpossibleRound: <center>NONE</center>
    BenchmarkingRandomnessRound --> BenchmarkingRandomnessRound: <center>NO_MAJORITY<br />ROUND_TIMEOUT</center>
    BetPlacementRound --> HandleFailedTxRound: <center>CALC_BUY_AMOUNT_FAILED</center>
    BetPlacementRound --> FinishedDecisionMakerRound: <center>DONE</center>
    BetPlacementRound --> RefillRequiredRound: <center>INSUFFICIENT_BALANCE</center>
    BetPlacementRound --> RedeemRound: <center>MOCK_TX</center>
    BetPlacementRound --> ImpossibleRound: <center>NONE</center>
    BetPlacementRound --> BetPlacementRound: <center>NO_MAJORITY<br />ROUND_TIMEOUT</center>
    BlacklistingRound --> FinishedWithoutDecisionRound: <center>MOCK_TX<br />DONE</center>
    BlacklistingRound --> ImpossibleRound: <center>FETCH_ERROR<br />NONE</center>
    BlacklistingRound --> BlacklistingRound: <center>NO_MAJORITY<br />ROUND_TIMEOUT</center>
    PolymarketBetPlacementRound --> FinishedPolymarketBetPlacementRound: <center>MOCK_TX<br />BET_PLACEMENT_DONE<br />DONE</center>
    PolymarketBetPlacementRound --> PolymarketBetPlacementRound: <center>BET_PLACEMENT_FAILED<br />NO_MAJORITY<br />ROUND_TIMEOUT</center>
    PolymarketBetPlacementRound --> BlacklistingRound: <center>BET_PLACEMENT_IMPOSSIBLE</center>
    PolymarketBetPlacementRound --> RefillRequiredRound: <center>INSUFFICIENT_BALANCE</center>
    PolymarketBetPlacementRound --> ImpossibleRound: <center>NONE</center>
    PolymarketRedeemRound --> FinishedPolymarketRedeemRound: <center>MOCK_TX<br />DONE</center>
    PolymarketRedeemRound --> PolymarketRedeemRound: <center>NO_MAJORITY<br />NONE</center>
    PolymarketRedeemRound --> FinishedWithoutRedeemingRound: <center>NO_REDEEMING</center>
    PolymarketRedeemRound --> FinishedRedeemTxPreparationRound: <center>PREPARE_TX</center>
    PolymarketRedeemRound --> FinishedDecisionMakerRound: <center>REDEEM_ROUND_TIMEOUT</center>
    PolymarketSetApprovalRound --> PolymarketPostSetApprovalRound: <center>MOCK_TX<br />DONE</center>
    PolymarketSetApprovalRound --> ImpossibleRound: <center>NONE</center>
    PolymarketSetApprovalRound --> PolymarketSetApprovalRound: <center>NO_MAJORITY<br />ROUND_TIMEOUT</center>
    PolymarketSetApprovalRound --> FinishedSetApprovalTxPreparationRound: <center>PREPARE_TX</center>
    PolymarketSwapUsdcRound --> DecisionRequestRound: <center>MOCK_TX<br />NONE<br />DONE</center>
    PolymarketSwapUsdcRound --> PolymarketSwapUsdcRound: <center>NO_MAJORITY<br />ROUND_TIMEOUT</center>
    PolymarketSwapUsdcRound --> FinishedPolymarketSwapTxPreparationRound: <center>PREPARE_TX</center>
    PolymarketWrapCollateralRound --> BenchmarkingModeDisabledRound: <center>MOCK_TX<br />NONE<br />DONE</center>
    PolymarketWrapCollateralRound --> PolymarketWrapCollateralRound: <center>NO_MAJORITY<br />ROUND_TIMEOUT</center>
    PolymarketWrapCollateralRound --> FinishedPolymarketWrapCollateralTxPreparationRound: <center>PREPARE_TX</center>
    RedeemRound --> FinishedDecisionMakerRound: <center>DONE</center>
    RedeemRound --> SamplingRound: <center>MOCK_TX</center>
    RedeemRound --> ImpossibleRound: <center>NONE</center>
    RedeemRound --> RedeemRound: <center>NO_MAJORITY</center>
    RedeemRound --> FinishedWithoutRedeemingRound: <center>REDEEM_ROUND_TIMEOUT<br />NO_REDEEMING</center>
    SamplingRound --> ToolSelectionRound: <center>BENCHMARKING_ENABLED<br />DONE</center>
    SamplingRound --> BenchmarkingDoneRound: <center>BENCHMARKING_FINISHED</center>
    SamplingRound --> ImpossibleRound: <center>FETCH_ERROR</center>
    SamplingRound --> SamplingRound: <center>NO_MAJORITY<br />NEW_SIMULATED_RESAMPLE<br />ROUND_TIMEOUT</center>
    SamplingRound --> FinishedWithoutDecisionRound: <center>NONE</center>
    SellOutcomeTokensRound --> HandleFailedTxRound: <center>CALC_SELL_AMOUNT_FAILED</center>
    SellOutcomeTokensRound --> FinishedDecisionMakerRound: <center>DONE</center>
    SellOutcomeTokensRound --> BetPlacementRound: <center>MOCK_TX</center>
    SellOutcomeTokensRound --> ImpossibleRound: <center>NONE</center>
    SellOutcomeTokensRound --> SellOutcomeTokensRound: <center>NO_MAJORITY<br />ROUND_TIMEOUT</center>
    ToolSelectionRound --> PolymarketSwapUsdcRound: <center>DONE</center>
    ToolSelectionRound --> ToolSelectionRound: <center>NO_MAJORITY<br />NONE<br />ROUND_TIMEOUT</center>
