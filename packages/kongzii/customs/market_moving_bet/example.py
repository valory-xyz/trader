from market_moving_bet import run, MovingBet


def main() -> None:
    # Calculate the required bet and on which outcome to place it, if we want to move the market from 91% to 85%.
    assert run(
        amounts=(58775075539429832141, 601869234248985448743),
        target_p_yes=0.85,
        verbose=True,
    ) == MovingBet(
        bet_amount=20161264336804665553,
        bet_outcome_index=1,
        error=None,
    )

    print("---")

    # Calculate the required bet and on which outcome to place it, if we want to move the market from 91% to 95%.
    assert run(
        amounts=(58775075539429832141, 601869234248985448743),
        target_p_yes=0.95,
        verbose=True,
    ) == MovingBet(
        bet_amount=258064183511099719095,
        bet_outcome_index=0,
        error=None,
    )


if __name__ == "__main__":
    main()
