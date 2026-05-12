stateDiagram-v2
    FetchPerformanceDataRound --> UpdateAchievementsRound: <center>DONE<br />ROUND_TIMEOUT<br />FAIL</center>
    FetchPerformanceDataRound --> FetchPerformanceDataRound: <center>NONE<br />NO_MAJORITY</center>
    UpdateAchievementsRound --> FinishedFetchPerformanceDataRound: <center>DONE<br />ROUND_TIMEOUT<br />FAIL</center>
    UpdateAchievementsRound --> FetchPerformanceDataRound: <center>NONE<br />NO_MAJORITY</center>
