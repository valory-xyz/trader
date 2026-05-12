stateDiagram-v2
    RegistrationRound --> FetchPerformanceDataRound: <center>DONE</center>
    RegistrationRound --> RegistrationRound: <center>NO_MAJORITY</center>
    RegistrationStartupRound --> FetchPerformanceDataRound: <center>DONE</center>
    BenchmarkingRandomnessRound --> SamplingRound: <center>DONE</center>
    BenchmarkingRandomnessRound --> ImpossibleRound: <center>NONE</center>
    BenchmarkingRandomnessRound --> BenchmarkingRandomnessRound: <center>NO_MAJORITY<br />ROUND_TIMEOUT</center>
    BetPlacementRound --> HandleFailedTxRound: <center>CALC_BUY_AMOUNT_FAILED</center>
    BetPlacementRound --> PreTxSettlementRound: <center>DONE</center>
    BetPlacementRound --> ResetAndPauseRound: <center>INSUFFICIENT_BALANCE</center>
    BetPlacementRound --> RedeemRound: <center>MOCK_TX</center>
    BetPlacementRound --> ImpossibleRound: <center>NONE</center>
    BetPlacementRound --> BetPlacementRound: <center>NO_MAJORITY<br />ROUND_TIMEOUT</center>
    BlacklistingRound --> CallCheckpointRound: <center>DONE<br />MOCK_TX</center>
    BlacklistingRound --> ImpossibleRound: <center>FETCH_ERROR<br />NONE</center>
    BlacklistingRound --> BlacklistingRound: <center>NO_MAJORITY<br />ROUND_TIMEOUT</center>
    CallCheckpointRound --> PreTxSettlementRound: <center>DONE</center>
    CallCheckpointRound --> ResetAndPauseRound: <center>NEXT_CHECKPOINT_NOT_REACHED_YET<br />SERVICE_NOT_STAKED</center>
    CallCheckpointRound --> CallCheckpointRound: <center>NO_MAJORITY<br />ROUND_TIMEOUT</center>
    CallCheckpointRound --> ServiceEvictedRound: <center>SERVICE_EVICTED</center>
    ChatuiLoadRound --> MechVersionDetectionRound: <center>DONE</center>
    ChatuiLoadRound --> ChatuiLoadRound: <center>NO_MAJORITY<br />FAIL<br />NONE<br />ROUND_TIMEOUT</center>
    CheckBenchmarkingModeRound --> PolymarketWrapCollateralRound: <center>BENCHMARKING_DISABLED</center>
    CheckBenchmarkingModeRound --> BenchmarkingRandomnessRound: <center>BENCHMARKING_ENABLED</center>
    CheckBenchmarkingModeRound --> ImpossibleRound: <center>NONE</center>
    CheckBenchmarkingModeRound --> CheckBenchmarkingModeRound: <center>NO_MAJORITY<br />ROUND_TIMEOUT</center>
    CheckBenchmarkingModeRound --> PolymarketSetApprovalRound: <center>SET_APPROVAL</center>
    CheckLateTxHashesRound --> SynchronizeLateMessagesRound: <center>CHECK_LATE_ARRIVING_MESSAGE</center>
    CheckLateTxHashesRound --> CheckLateTxHashesRound: <center>CHECK_TIMEOUT</center>
    CheckLateTxHashesRound --> PostTxSettlementRound: <center>DONE</center>
    CheckLateTxHashesRound --> HandleFailedTxRound: <center>NEGATIVE<br />NO_MAJORITY<br />NONE</center>
    CheckStopTradingRound --> RandomnessRound: <center>DONE<br />REVIEW_BETS</center>
    CheckStopTradingRound --> CheckStopTradingRound: <center>NO_MAJORITY<br />NONE<br />ROUND_TIMEOUT</center>
    CheckStopTradingRound --> CallCheckpointRound: <center>SKIP_TRADING</center>
    CheckStopTradingRound --> OmenWithdrawRound: <center>WITHDRAW_OMEN</center>
    CheckStopTradingRound --> PolymarketWithdrawRound: <center>WITHDRAW_POLYMARKET</center>
    CheckTransactionHistoryRound --> SynchronizeLateMessagesRound: <center>CHECK_LATE_ARRIVING_MESSAGE</center>
    CheckTransactionHistoryRound --> CheckTransactionHistoryRound: <center>CHECK_TIMEOUT<br />NO_MAJORITY</center>
    CheckTransactionHistoryRound --> PostTxSettlementRound: <center>DONE</center>
    CheckTransactionHistoryRound --> SelectKeeperTransactionSubmissionBRound: <center>NEGATIVE</center>
    CheckTransactionHistoryRound --> HandleFailedTxRound: <center>NONE</center>
    CollectSignatureRound --> FinalizationRound: <center>DONE</center>
    CollectSignatureRound --> ResetRound: <center>NO_MAJORITY</center>
    CollectSignatureRound --> CollectSignatureRound: <center>ROUND_TIMEOUT</center>
    DecisionReceiveRound --> BetPlacementRound: <center>DONE</center>
    DecisionReceiveRound --> PreTxSettlementRound: <center>DONE_NO_SELL</center>
    DecisionReceiveRound --> SellOutcomeTokensRound: <center>DONE_SELL</center>
    DecisionReceiveRound --> BlacklistingRound: <center>MECH_RESPONSE_ERROR<br />TIE<br />UNPROFITABLE</center>
    DecisionReceiveRound --> DecisionReceiveRound: <center>NO_MAJORITY<br />ROUND_TIMEOUT</center>
    DecisionReceiveRound --> PolymarketBetPlacementRound: <center>POLYMARKET_DONE</center>
    DecisionRequestRound --> MechRequestRound: <center>DONE</center>
    DecisionRequestRound --> DecisionReceiveRound: <center>MOCK_MECH_REQUEST</center>
    DecisionRequestRound --> DecisionRequestRound: <center>NO_MAJORITY<br />ROUND_TIMEOUT</center>
    DecisionRequestRound --> BlacklistingRound: <center>SLOTS_UNSUPPORTED_ERROR</center>
    FetchMarketsRouterRound --> UpdateBetsRound: <center>DONE</center>
    FetchMarketsRouterRound --> FetchMarketsRouterRound: <center>NO_MAJORITY<br />NONE</center>
    FetchMarketsRouterRound --> PolymarketFetchMarketRound: <center>POLYMARKET_FETCH_MARKETS</center>
    FetchPerformanceDataRound --> UpdateAchievementsRound: <center>DONE<br />ROUND_TIMEOUT<br />FAIL</center>
    FetchPerformanceDataRound --> FetchPerformanceDataRound: <center>NO_MAJORITY<br />NONE</center>
    FinalizationRound --> CheckTransactionHistoryRound: <center>CHECK_HISTORY</center>
    FinalizationRound --> SynchronizeLateMessagesRound: <center>CHECK_LATE_ARRIVING_MESSAGE</center>
    FinalizationRound --> ValidateTransactionRound: <center>DONE</center>
    FinalizationRound --> SelectKeeperTransactionSubmissionBRound: <center>FINALIZATION_FAILED<br />INSUFFICIENT_FUNDS</center>
    FinalizationRound --> SelectKeeperTransactionSubmissionBAfterTimeoutRound: <center>FINALIZE_TIMEOUT</center>
    HandleFailedTxRound --> BlacklistingRound: <center>BLACKLIST</center>
    HandleFailedTxRound --> HandleFailedTxRound: <center>NO_MAJORITY</center>
    HandleFailedTxRound --> RedeemRound: <center>NO_OP</center>
    MechInformationRound --> CheckBenchmarkingModeRound: <center>DONE</center>
    MechInformationRound --> MechVersionDetectionRound: <center>NONE</center>
    MechInformationRound --> MechInformationRound: <center>NO_MAJORITY<br />ROUND_TIMEOUT</center>
    MechPurchaseSubscriptionRound --> PreTxSettlementRound: <center>DONE</center>
    MechPurchaseSubscriptionRound --> MechPurchaseSubscriptionRound: <center>NO_MAJORITY<br />NONE<br />ROUND_TIMEOUT</center>
    MechRequestRound --> MechPurchaseSubscriptionRound: <center>BUY_SUBSCRIPTION</center>
    MechRequestRound --> PreTxSettlementRound: <center>DONE</center>
    MechRequestRound --> MechRequestRound: <center>NO_MAJORITY<br />ROUND_TIMEOUT</center>
    MechRequestRound --> CallCheckpointRound: <center>SKIP_REQUEST</center>
    MechResponseRound --> DecisionReceiveRound: <center>DONE</center>
    MechResponseRound --> MechResponseRound: <center>NO_MAJORITY</center>
    MechResponseRound --> HandleFailedTxRound: <center>ROUND_TIMEOUT</center>
    MechVersionDetectionRound --> MechVersionDetectionRound: <center>NO_MAJORITY<br />ROUND_TIMEOUT</center>
    MechVersionDetectionRound --> CheckBenchmarkingModeRound: <center>V1<br />NO_MARKETPLACE</center>
    MechVersionDetectionRound --> MechInformationRound: <center>V2</center>
    OmenWithdrawRound --> OmenWithdrawRound: <center>NO_MAJORITY<br />NONE</center>
    OmenWithdrawRound --> PreTxSettlementRound: <center>PREPARE_TX</center>
    OmenWithdrawRound --> ResetAndPauseRound: <center>WITHDRAWAL_DONE<br />WITHDRAWAL_ROUND_TIMEOUT</center>
    PolymarketBetPlacementRound --> CallCheckpointRound: <center>DONE<br />BET_PLACEMENT_DONE<br />MOCK_TX</center>
    PolymarketBetPlacementRound --> PolymarketBetPlacementRound: <center>NO_MAJORITY<br />BET_PLACEMENT_FAILED<br />ROUND_TIMEOUT</center>
    PolymarketBetPlacementRound --> BlacklistingRound: <center>BET_PLACEMENT_IMPOSSIBLE</center>
    PolymarketBetPlacementRound --> ResetAndPauseRound: <center>INSUFFICIENT_BALANCE</center>
    PolymarketBetPlacementRound --> ImpossibleRound: <center>NONE</center>
    PolymarketFetchMarketRound --> RedeemRouterRound: <center>DONE</center>
    PolymarketFetchMarketRound --> ResetAndPauseRound: <center>FETCH_ERROR</center>
    PolymarketFetchMarketRound --> PolymarketFetchMarketRound: <center>NO_MAJORITY<br />ROUND_TIMEOUT</center>
    PolymarketPostSetApprovalRound --> PolymarketSetApprovalRound: <center>APPROVAL_FAILED</center>
    PolymarketPostSetApprovalRound --> PolymarketWrapCollateralRound: <center>DONE</center>
    PolymarketPostSetApprovalRound --> ImpossibleRound: <center>NONE</center>
    PolymarketPostSetApprovalRound --> PolymarketPostSetApprovalRound: <center>NO_MAJORITY<br />ROUND_TIMEOUT</center>
    PolymarketRedeemRound --> CheckStopTradingRound: <center>DONE<br />NO_REDEEMING<br />MOCK_TX</center>
    PolymarketRedeemRound --> PolymarketRedeemRound: <center>NO_MAJORITY<br />NONE</center>
    PolymarketRedeemRound --> PreTxSettlementRound: <center>REDEEM_ROUND_TIMEOUT<br />PREPARE_TX</center>
    PolymarketSetApprovalRound --> PolymarketPostSetApprovalRound: <center>DONE<br />MOCK_TX</center>
    PolymarketSetApprovalRound --> ImpossibleRound: <center>NONE</center>
    PolymarketSetApprovalRound --> PolymarketSetApprovalRound: <center>NO_MAJORITY<br />ROUND_TIMEOUT</center>
    PolymarketSetApprovalRound --> PreTxSettlementRound: <center>PREPARE_TX</center>
    PolymarketSwapUsdcRound --> DecisionRequestRound: <center>DONE<br />NONE<br />MOCK_TX</center>
    PolymarketSwapUsdcRound --> PolymarketSwapUsdcRound: <center>NO_MAJORITY<br />ROUND_TIMEOUT</center>
    PolymarketSwapUsdcRound --> PreTxSettlementRound: <center>PREPARE_TX</center>
    PolymarketWithdrawRound --> PolymarketWithdrawRound: <center>NO_MAJORITY<br />NONE</center>
    PolymarketWithdrawRound --> ResetAndPauseRound: <center>WITHDRAWAL_DONE<br />WITHDRAWAL_ROUND_TIMEOUT</center>
    PolymarketWrapCollateralRound --> FetchMarketsRouterRound: <center>DONE<br />NONE<br />MOCK_TX</center>
    PolymarketWrapCollateralRound --> PolymarketWrapCollateralRound: <center>NO_MAJORITY<br />ROUND_TIMEOUT</center>
    PolymarketWrapCollateralRound --> PreTxSettlementRound: <center>PREPARE_TX</center>
    PostBetUpdateRound --> CallCheckpointRound: <center>DONE</center>
    PostBetUpdateRound --> PostBetUpdateRound: <center>NO_MAJORITY<br />NONE<br />ROUND_TIMEOUT</center>
    PostOmenWithdrawRound --> PostOmenWithdrawRound: <center>NO_MAJORITY<br />NONE<br />WITHDRAWAL_ROUND_TIMEOUT</center>
    PostOmenWithdrawRound --> ResetAndPauseRound: <center>WITHDRAWAL_DONE</center>
    PostTxSettlementRound --> PostBetUpdateRound: <center>BET_PLACEMENT_DONE<br />SELL_OUTCOME_TOKENS_DONE</center>
    PostTxSettlementRound --> MechResponseRound: <center>MECH_REQUESTING_DONE</center>
    PostTxSettlementRound --> CheckStopTradingRound: <center>REDEEMING_DONE</center>
    PostTxSettlementRound --> PostTxSettlementRound: <center>ROUND_TIMEOUT</center>
    PostTxSettlementRound --> PolymarketPostSetApprovalRound: <center>SET_APPROVAL_DONE</center>
    PostTxSettlementRound --> ResetAndPauseRound: <center>STAKING_DONE</center>
    PostTxSettlementRound --> RandomnessRound: <center>SUBSCRIPTION_DONE</center>
    PostTxSettlementRound --> DecisionRequestRound: <center>SWAP_DONE</center>
    PostTxSettlementRound --> FailedMultiplexerRound: <center>UNRECOGNIZED</center>
    PostTxSettlementRound --> PostOmenWithdrawRound: <center>WITHDRAW_OMEN_DONE</center>
    PostTxSettlementRound --> FetchMarketsRouterRound: <center>WRAP_COLLATERAL_DONE</center>
    PreTxSettlementRound --> RandomnessTransactionSubmissionRound: <center>CHECKS_PASSED</center>
    PreTxSettlementRound --> PreTxSettlementRound: <center>NO_MAJORITY<br />REFILL_REQUIRED<br />ROUND_TIMEOUT</center>
    RandomnessRound --> SamplingRound: <center>DONE</center>
    RandomnessRound --> ImpossibleRound: <center>NONE</center>
    RandomnessRound --> RandomnessRound: <center>NO_MAJORITY<br />ROUND_TIMEOUT</center>
    RandomnessTransactionSubmissionRound --> SelectKeeperTransactionSubmissionARound: <center>DONE</center>
    RandomnessTransactionSubmissionRound --> RandomnessTransactionSubmissionRound: <center>NO_MAJORITY<br />NONE<br />ROUND_TIMEOUT</center>
    RedeemRound --> PreTxSettlementRound: <center>DONE</center>
    RedeemRound --> SamplingRound: <center>MOCK_TX</center>
    RedeemRound --> ImpossibleRound: <center>NONE</center>
    RedeemRound --> RedeemRound: <center>NO_MAJORITY</center>
    RedeemRound --> CheckStopTradingRound: <center>REDEEM_ROUND_TIMEOUT<br />NO_REDEEMING</center>
    RedeemRouterRound --> RedeemRound: <center>DONE</center>
    RedeemRouterRound --> RedeemRouterRound: <center>NO_MAJORITY<br />NONE</center>
    RedeemRouterRound --> PolymarketRedeemRound: <center>POLYMARKET_DONE</center>
    ResetAndPauseRound --> FetchPerformanceDataRound: <center>DONE</center>
    ResetAndPauseRound --> ResetAndPauseRound: <center>RESET_AND_PAUSE_TIMEOUT<br />NO_MAJORITY</center>
    ResetRound --> RandomnessTransactionSubmissionRound: <center>DONE</center>
    ResetRound --> HandleFailedTxRound: <center>NO_MAJORITY<br />RESET_TIMEOUT</center>
    SamplingRound --> ToolSelectionRound: <center>DONE<br />BENCHMARKING_ENABLED</center>
    SamplingRound --> ResetAndPauseRound: <center>BENCHMARKING_FINISHED</center>
    SamplingRound --> ImpossibleRound: <center>FETCH_ERROR</center>
    SamplingRound --> SamplingRound: <center>NO_MAJORITY<br />NEW_SIMULATED_RESAMPLE<br />ROUND_TIMEOUT</center>
    SamplingRound --> CallCheckpointRound: <center>NONE</center>
    SelectKeeperTransactionSubmissionARound --> CollectSignatureRound: <center>DONE</center>
    SelectKeeperTransactionSubmissionARound --> HandleFailedTxRound: <center>INCORRECT_SERIALIZATION</center>
    SelectKeeperTransactionSubmissionARound --> ResetRound: <center>NO_MAJORITY</center>
    SelectKeeperTransactionSubmissionARound --> SelectKeeperTransactionSubmissionARound: <center>ROUND_TIMEOUT</center>
    SelectKeeperTransactionSubmissionBAfterTimeoutRound --> CheckTransactionHistoryRound: <center>CHECK_HISTORY</center>
    SelectKeeperTransactionSubmissionBAfterTimeoutRound --> SynchronizeLateMessagesRound: <center>CHECK_LATE_ARRIVING_MESSAGE</center>
    SelectKeeperTransactionSubmissionBAfterTimeoutRound --> FinalizationRound: <center>DONE</center>
    SelectKeeperTransactionSubmissionBAfterTimeoutRound --> HandleFailedTxRound: <center>INCORRECT_SERIALIZATION</center>
    SelectKeeperTransactionSubmissionBAfterTimeoutRound --> ResetRound: <center>NO_MAJORITY</center>
    SelectKeeperTransactionSubmissionBAfterTimeoutRound --> SelectKeeperTransactionSubmissionBAfterTimeoutRound: <center>ROUND_TIMEOUT</center>
    SelectKeeperTransactionSubmissionBRound --> FinalizationRound: <center>DONE</center>
    SelectKeeperTransactionSubmissionBRound --> HandleFailedTxRound: <center>INCORRECT_SERIALIZATION</center>
    SelectKeeperTransactionSubmissionBRound --> ResetRound: <center>NO_MAJORITY</center>
    SelectKeeperTransactionSubmissionBRound --> SelectKeeperTransactionSubmissionBRound: <center>ROUND_TIMEOUT</center>
    SellOutcomeTokensRound --> HandleFailedTxRound: <center>CALC_SELL_AMOUNT_FAILED</center>
    SellOutcomeTokensRound --> PreTxSettlementRound: <center>DONE</center>
    SellOutcomeTokensRound --> BetPlacementRound: <center>MOCK_TX</center>
    SellOutcomeTokensRound --> ImpossibleRound: <center>NONE</center>
    SellOutcomeTokensRound --> SellOutcomeTokensRound: <center>NO_MAJORITY<br />ROUND_TIMEOUT</center>
    SynchronizeLateMessagesRound --> CheckLateTxHashesRound: <center>DONE</center>
    SynchronizeLateMessagesRound --> SelectKeeperTransactionSubmissionBRound: <center>NONE</center>
    SynchronizeLateMessagesRound --> SynchronizeLateMessagesRound: <center>ROUND_TIMEOUT</center>
    SynchronizeLateMessagesRound --> HandleFailedTxRound: <center>SUSPICIOUS_ACTIVITY</center>
    ToolSelectionRound --> PolymarketSwapUsdcRound: <center>DONE</center>
    ToolSelectionRound --> ToolSelectionRound: <center>NO_MAJORITY<br />NONE<br />ROUND_TIMEOUT</center>
    UpdateAchievementsRound --> ChatuiLoadRound: <center>DONE<br />ROUND_TIMEOUT<br />FAIL</center>
    UpdateAchievementsRound --> FetchPerformanceDataRound: <center>NO_MAJORITY<br />NONE</center>
    UpdateBetsRound --> RedeemRouterRound: <center>DONE</center>
    UpdateBetsRound --> ResetAndPauseRound: <center>FETCH_ERROR</center>
    UpdateBetsRound --> UpdateBetsRound: <center>NO_MAJORITY<br />ROUND_TIMEOUT</center>
    ValidateTransactionRound --> PostTxSettlementRound: <center>DONE</center>
    ValidateTransactionRound --> CheckTransactionHistoryRound: <center>NEGATIVE<br />VALIDATE_TIMEOUT</center>
    ValidateTransactionRound --> SelectKeeperTransactionSubmissionBRound: <center>NONE</center>
    ValidateTransactionRound --> ValidateTransactionRound: <center>NO_MAJORITY</center>
