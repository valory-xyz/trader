# Omen Dynamic-Size Agents Exact Check: 2026-03-20 to 2026-03-26

This report covers only Omen agents whose historical sizing in the morning replay was not the fixed `0.025` xDAI pattern.

The morning replay identified `37` non-fixed-size agents in this 1-week window. Exact mech matching produced usable replay rows for `31` of them, which is the population summarized below.

## Aggregate

- agents with usable exact matches: `31`
- trades with exact mech match: `441`
- modeled utility comparison: new better `283`, old better `0`, ties `151`
- bets placed: historical `441`, counterfactual Kelly `422`
- funding deployed: historical `474.614531` xDAI, counterfactual Kelly `826.252707` xDAI
- actual profit / ROI: `3.002074` xDAI / `0.006267`
- counterfactual Kelly profit / ROI: `-46.945417` xDAI / `-0.056529`

## Conclusion

For the non-fixed-size Omen agents, the current execution-aware Kelly optimizer is almost never worse on its intended objective. Across the `441` exact-matched trades, it improves modeled log utility in `283` rows and ties in `151`, with `0` rows where the historical decision is better under the same modeled objective.

That optimizer advantage does not translate into better aggregate realized performance for this cohort. Historically, these agents earned about `+0.63%` ROI on `474.61` xDAI of deployed capital, while the counterfactual Kelly replay would have deployed `826.25` xDAI and finished at about `-5.65%` ROI. So the dynamic-agent-only picture is materially different from the fixed-size subset: optimizer fidelity improves, but ex post ROI worsens in aggregate.

## Per Agent

- `0x4b914bf678637215dd41ac2941e044dd06cca912`
  old vs new bets: `29` vs `24`
  old vs new funding: `23.032803` vs `45.015732` xDAI
  optimizer comparison: new better `19`, old better `0`, ties `8`
  actual ROI `-0.129202`, counterfactual Kelly ROI `-0.055095`
- `0x557f2c2fc1f3b4d68782e171560cc7f39a8de1fc`
  old vs new bets: `23` vs `21`
  old vs new funding: `9.163994` vs `40.080411` xDAI
  optimizer comparison: new better `23`, old better `0`, ties `0`
  actual ROI `-0.119759`, counterfactual Kelly ROI `0.18993`
- `0xaf79ff71db50d493f24064fee3e8a283907f98ea`
  old vs new bets: `20` vs `18`
  old vs new funding: `35.660174` vs `35.481513` xDAI
  optimizer comparison: new better `7`, old better `0`, ties `12`
  actual ROI `0.499255`, counterfactual Kelly ROI `0.564722`
- `0x12208e338e809f83094c8d1cf81999e83fdcbf90`
  old vs new bets: `20` vs `20`
  old vs new funding: `32.1` vs `39.817936` xDAI
  optimizer comparison: new better `5`, old better `0`, ties `15`
  actual ROI `0.165511`, counterfactual Kelly ROI `-0.059272`
- `0xb14e4609cdbea18049c7b01ef00f1ade5a870a6b`
  old vs new bets: `18` vs `17`
  old vs new funding: `23.704022` vs `32.452455` xDAI
  optimizer comparison: new better `9`, old better `0`, ties `8`
  actual ROI `0.012714`, counterfactual Kelly ROI `-0.016468`
- `0x78aa375dc9d41eb59af02f1276fbb02ce07cb4d7`
  old vs new bets: `16` vs `16`
  old vs new funding: `23.769146` vs `32.0` xDAI
  optimizer comparison: new better `7`, old better `0`, ties `9`
  actual ROI `-0.190712`, counterfactual Kelly ROI `-0.033164`
- `0x21876a9459cbd688f06fdc601e7d18be51bdc7b5`
  old vs new bets: `16` vs `14`
  old vs new funding: `13.901749` vs `25.249249` xDAI
  optimizer comparison: new better `14`, old better `0`, ties `2`
  actual ROI `0.02542`, counterfactual Kelly ROI `0.217796`
- `0x2fd67a6c8741bf9388e6682916cf60d21fcfae27`
  old vs new bets: `16` vs `16`
  old vs new funding: `10.580075` vs `32.0` xDAI
  optimizer comparison: new better `12`, old better `0`, ties `4`
  actual ROI `0.472723`, counterfactual Kelly ROI `-0.281049`
- `0xcc96f5d68a98c7b2af479112d633436497faa64f`
  old vs new bets: `16` vs `16`
  old vs new funding: `8.017086` vs `30.618687` xDAI
  optimizer comparison: new better `16`, old better `0`, ties `0`
  actual ROI `0.14518`, counterfactual Kelly ROI `-0.066067`
- `0x347e4ef0ff34cf39d1c7e08bc07c68c41a4836d6`
  old vs new bets: `16` vs `15`
  old vs new funding: `7.830417` vs `30.0` xDAI
  optimizer comparison: new better `15`, old better `0`, ties `0`
  actual ROI `-0.377119`, counterfactual Kelly ROI `-0.371355`
- `0x7469eecd46cf671a1f627715bfa84385e476c4db`
  old vs new bets: `16` vs `16`
  old vs new funding: `5.15` vs `32.0` xDAI
  optimizer comparison: new better `16`, old better `0`, ties `0`
  actual ROI `-0.546596`, counterfactual Kelly ROI `-0.244394`
- `0x2b00ebb18be2224d60fc55ae52df5cf6177f8fb7`
  old vs new bets: `15` vs `15`
  old vs new funding: `28.44971` vs `30.0` xDAI
  optimizer comparison: new better `4`, old better `0`, ties `11`
  actual ROI `-0.016327`, counterfactual Kelly ROI `-0.031924`
- `0x20ce19cb2cac1dc09d93d2f3697660a7480cd579`
  old vs new bets: `14` vs `14`
  old vs new funding: `23.889712` vs `28.0` xDAI
  optimizer comparison: new better `3`, old better `0`, ties `11`
  actual ROI `-0.21991`, counterfactual Kelly ROI `-0.235829`
- `0xf9b972d37f63bf81933abe17195233ca811f8287`
  old vs new bets: `14` vs `13`
  old vs new funding: `17.534063` vs `24.662224` xDAI
  optimizer comparison: new better `7`, old better `0`, ties `7`
  actual ROI `0.119396`, counterfactual Kelly ROI `0.111992`
- `0x74c93a79ab31b0570cde0bd4a6172ac1115ae043`
  old vs new bets: `14` vs `13`
  old vs new funding: `14.106188` vs `26.0` xDAI
  optimizer comparison: new better `10`, old better `0`, ties `4`
  actual ROI `-0.474467`, counterfactual Kelly ROI `-0.574928`
- `0xb636a134b75fabea557e6d4a8187cace39630187`
  old vs new bets: `14` vs `13`
  old vs new funding: `11.529596` vs `25.485471` xDAI
  optimizer comparison: new better `10`, old better `0`, ties `4`
  actual ROI `-0.352666`, counterfactual Kelly ROI `-0.038181`
- `0xf33e3a63b060a475e238b93663363eff3334a1e0`
  old vs new bets: `14` vs `14`
  old vs new funding: `2.51927` vs `27.465681` xDAI
  optimizer comparison: new better `14`, old better `0`, ties `0`
  actual ROI `0.540638`, counterfactual Kelly ROI `-0.493659`
- `0x9560b50ab878da86c79a61bc713c71b185c99fd9`
  old vs new bets: `14` vs `12`
  old vs new funding: `1.717799` vs `23.358818` xDAI
  optimizer comparison: new better `12`, old better `0`, ties `0`
  actual ROI `-0.151381`, counterfactual Kelly ROI `0.015611`
- `0x9aeac5414d5fdde84be968a7cf4e43928c484158`
  old vs new bets: `13` vs `13`
  old vs new funding: `13.392755` vs `26.0` xDAI
  optimizer comparison: new better `9`, old better `0`, ties `4`
  actual ROI `-0.123416`, counterfactual Kelly ROI `-0.167349`
- `0x2bc48750cb6c1f2a11401cc3c0cf06064e095ebf`
  old vs new bets: `13` vs `13`
  old vs new funding: `13.0` vs `26.0` xDAI
  optimizer comparison: new better `13`, old better `0`, ties `0`
  actual ROI `-0.156942`, counterfactual Kelly ROI `-0.195274`
- `0xec456f92b9a1e0a79be63100720483824da85a3d`
  old vs new bets: `13` vs `13`
  old vs new funding: `11.032306` vs `25.869389` xDAI
  optimizer comparison: new better `13`, old better `0`, ties `0`
  actual ROI `0.463256`, counterfactual Kelly ROI `0.473882`
- `0x2ad146e33b27933241dd68eeb18e77d860ba361d`
  old vs new bets: `12` vs `12`
  old vs new funding: `20.947403` vs `23.580461` xDAI
  optimizer comparison: new better `4`, old better `0`, ties `8`
  actual ROI `-0.029504`, counterfactual Kelly ROI `-0.074178`
- `0x5461768d1c2ce52e807ff76c793584401300fb80`
  old vs new bets: `12` vs `12`
  old vs new funding: `18.138967` vs `23.370692` xDAI
  optimizer comparison: new better `7`, old better `0`, ties `5`
  actual ROI `0.519005`, counterfactual Kelly ROI `0.516372`
- `0xccd5f5b251f16436a56ca65bbb8401d782cbbd97`
  old vs new bets: `12` vs `12`
  old vs new funding: `9.031001` vs `24.0` xDAI
  optimizer comparison: new better `12`, old better `0`, ties `0`
  actual ROI `-0.409448`, counterfactual Kelly ROI `-0.594993`
- `0x1a6d44ebddd2070f0df58b388c3d13eb98b6543c`
  old vs new bets: `11` vs `11`
  old vs new funding: `20.025` vs `22.0` xDAI
  optimizer comparison: new better `1`, old better `0`, ties `10`
  actual ROI `-0.434211`, counterfactual Kelly ROI `-0.484751`
- `0x333dd90d00c8a46dde6a0e59569a9a8c25a9e2f4`
  old vs new bets: `11` vs `11`
  old vs new funding: `17.729551` vs `21.707114` xDAI
  optimizer comparison: new better `5`, old better `0`, ties `6`
  actual ROI `0.004873`, counterfactual Kelly ROI `-0.14206`
- `0xf3305893eea9b7e64f7bc910d463602b18c742dc`
  old vs new bets: `9` vs `9`
  old vs new funding: `17.434969` vs `18.0` xDAI
  optimizer comparison: new better `2`, old better `0`, ties `7`
  actual ROI `-0.117308`, counterfactual Kelly ROI `-0.101016`
- `0x387621395906631c3737b16bf4a41cac22dc4240`
  old vs new bets: `8` vs `8`
  old vs new funding: `14.820251` vs `15.43006` xDAI
  optimizer comparison: new better `2`, old better `0`, ties `6`
  actual ROI `0.294503`, counterfactual Kelly ROI `0.244565`
- `0xd7f52526ef848f113b9043c98e6124206a8a67af`
  old vs new bets: `8` vs `8`
  old vs new funding: `14.151127` vs `16.0` xDAI
  optimizer comparison: new better `2`, old better `0`, ties `6`
  actual ROI `0.150343`, counterfactual Kelly ROI `0.138318`
- `0x2060813f352df3a6deff946afaedfa513cdbcf0e`
  old vs new bets: `8` vs `7`
  old vs new funding: `6.56208` vs `12.606814` xDAI
  optimizer comparison: new better `6`, old better `0`, ties `2`
  actual ROI `-0.388005`, counterfactual Kelly ROI `-0.419373`
- `0xc45cca9d465efc6883d07ec4b5a8ee25e1519570`
  old vs new bets: `6` vs `6`
  old vs new funding: `5.693317` vs `12.0` xDAI
  optimizer comparison: new better `4`, old better `0`, ties `2`
  actual ROI `0.176628`, counterfactual Kelly ROI `0.538369`

## Files

- `dynamic_agents_summary.json`: aggregate and per-agent exact results for non-fixed-size agents
- `dynamic_agents_rows.json`: per-trade exact mech-matched rows for non-fixed-size agents
