stateDiagram-v2
    FetchMarketsRouterRound --> UpdateBetsRound: <center>DONE</center>
    FetchMarketsRouterRound --> FetchMarketsRouterRound: <center>NONE<br />NO_MAJORITY</center>
    FetchMarketsRouterRound --> PolymarketFetchMarketRound: <center>POLYMARKET_FETCH_MARKETS</center>
    UpdateBetsRound --> FinishedMarketManagerRound: <center>DONE</center>
    UpdateBetsRound --> FailedMarketManagerRound: <center>FETCH_ERROR</center>
    UpdateBetsRound --> UpdateBetsRound: <center>NO_MAJORITY<br />ROUND_TIMEOUT</center>
    PolymarketFetchMarketRound --> FinishedPolymarketFetchMarketRound: <center>DONE</center>
    PolymarketFetchMarketRound --> FailedMarketManagerRound: <center>FETCH_ERROR</center>
    PolymarketFetchMarketRound --> PolymarketFetchMarketRound: <center>NO_MAJORITY<br />ROUND_TIMEOUT</center>
