# Trader Agent

This agent uses `trader_abci` skill, which:
1. Searches for new questions on the supported prediction markets
2. Selects a question to investigate its answer
3. Predicts the answer for the selected question
4. Decides whether answering this question is profitable
5. Submits the answer if it is profitable, otherwise temporarily blacklists the question
