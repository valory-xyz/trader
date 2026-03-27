# Omen Genuinely Graded Agents: 2026-03-20 to 2026-03-26

This report isolates the non-fixed-size Omen agents that look genuinely graded rather than bucketed. The source population is the exact-match dynamic-agent report, and this subset keeps only agents with at least `6` distinct historical bet sizes in the analyzed week.

## What is included

- source report: `reports/omen_dynamic_agents_exact_2026-03-20_2026-03-26`
- subset rule: at least `6` distinct historical bet sizes
- agents in subset: `15`
- exact-matched trades in subset: `237`

## Aggregate

- modeled utility comparison: new better `162`, old better `0`, ties `71`
- bets placed: historical `237`, counterfactual Kelly `221`
- funding deployed: historical `247.27448` xDAI, counterfactual Kelly `426.599751` xDAI
- actual profit / ROI: `12.773425` xDAI / `0.051166`
- counterfactual Kelly profit / ROI: `25.628015` xDAI / `0.059765`

## Main takeaway

For the genuinely graded agents, the current execution-aware Kelly optimizer is still never worse on the modeled log-utility objective. Across `237` exact-matched trades, it improves modeled utility in `162` rows and ties in `71`, with `0` rows where the historical decision is better.

Unlike the broader dynamic-agent cohort, this genuinely graded subset also improves aggregate realized performance. Historically these agents earned about `5.12%` ROI, while the counterfactual Kelly replay earns about `5.98%` ROI despite deploying more capital.

So the genuinely graded subset gives the cleanest positive Omen result:

- better optimizer fidelity
- and better aggregate realized ROI

## On the ties

The `71` ties are not ambiguous-sizing cases. They are all max-size ties:

- historical size at `2.0` xDAI: `71/71`
- counterfactual Kelly size at `2.0` xDAI: `71/71`
- identical historical and Kelly size: `71/71`

So in this subset, ties simply mean the historical trade was already at the Kelly cap.

## Agents

- `0x21876a9459cbd688f06fdc601e7d18be51bdc7b5`: `16` trades, `11` sizes, actual ROI `0.02542`, Kelly ROI `0.217796`
- `0x74c93a79ab31b0570cde0bd4a6172ac1115ae043`: `14` trades, `9` sizes, actual ROI `-0.474467`, Kelly ROI `-0.574928`
- `0xaf79ff71db50d493f24064fee3e8a283907f98ea`: `20` trades, `8` sizes, actual ROI `0.499255`, Kelly ROI `0.564722`
- `0xcc96f5d68a98c7b2af479112d633436497faa64f`: `16` trades, `8` sizes, actual ROI `0.14518`, Kelly ROI `-0.066067`
- `0xf9b972d37f63bf81933abe17195233ca811f8287`: `14` trades, `8` sizes, actual ROI `0.119396`, Kelly ROI `0.111992`
- `0x5461768d1c2ce52e807ff76c793584401300fb80`: `12` trades, `8` sizes, actual ROI `0.519005`, Kelly ROI `0.516372`
- `0xb14e4609cdbea18049c7b01ef00f1ade5a870a6b`: `18` trades, `7` sizes, actual ROI `0.012714`, Kelly ROI `-0.016468`
- `0x78aa375dc9d41eb59af02f1276fbb02ce07cb4d7`: `16` trades, `7` sizes, actual ROI `-0.190712`, Kelly ROI `-0.033164`
- `0x9aeac5414d5fdde84be968a7cf4e43928c484158`: `13` trades, `7` sizes, actual ROI `-0.123416`, Kelly ROI `-0.167349`
- `0x4b914bf678637215dd41ac2941e044dd06cca912`: `29` trades, `6` sizes, actual ROI `-0.129202`, Kelly ROI `-0.055095`
- `0x557f2c2fc1f3b4d68782e171560cc7f39a8de1fc`: `23` trades, `6` sizes, actual ROI `-0.119759`, Kelly ROI `0.18993`
- `0xb636a134b75fabea557e6d4a8187cace39630187`: `14` trades, `6` sizes, actual ROI `-0.352666`, Kelly ROI `-0.038181`
- `0xec456f92b9a1e0a79be63100720483824da85a3d`: `13` trades, `6` sizes, actual ROI `0.463256`, Kelly ROI `0.473882`
- `0x333dd90d00c8a46dde6a0e59569a9a8c25a9e2f4`: `11` trades, `6` sizes, actual ROI `0.004873`, Kelly ROI `-0.14206`
- `0x2060813f352df3a6deff946afaedfa513cdbcf0e`: `8` trades, `6` sizes, actual ROI `-0.388005`, Kelly ROI `-0.419373`

## Files

- `graded_agents_summary.json`: aggregate and per-agent results for the genuinely graded subset
- `graded_agents_rows.json`: per-trade exact-matched rows for the genuinely graded subset
