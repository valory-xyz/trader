stateDiagram-v2
    CallCheckpointRound --> CheckpointCallPreparedRound: <center>DONE</center>
    CallCheckpointRound --> FinishedStakingRound: <center>NEXT_CHECKPOINT_NOT_REACHED_YET<br />SERVICE_NOT_STAKED</center>
    CallCheckpointRound --> CallCheckpointRound: <center>NO_MAJORITY<br />ROUND_TIMEOUT</center>
    CallCheckpointRound --> ServiceEvictedRound: <center>SERVICE_EVICTED</center>
