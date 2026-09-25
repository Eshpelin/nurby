from services.perception.usage import combine_perception_usage, perception_budget_decision


def test_perception_budget_combines_rule_and_enrichment_ledgers():
    assert combine_perception_usage(7, 100, 5, 40) == (12, 140)


def test_perception_budget_ignores_invalid_negative_ledger_values():
    assert combine_perception_usage(-1, 20, 3, -4) == (3, 20)


def test_perception_budget_allows_below_limit():
    result = perception_budget_decision(
        used_cost_cents=10, used_tokens=100, estimated_cost_cents=2,
        estimated_tokens=20, cost_limit_cents=20, token_limit=200,
    )
    assert result.allowed is True
    assert result.stage == "normal"


def test_perception_budget_warns_before_blocking():
    result = perception_budget_decision(
        used_cost_cents=15, used_tokens=0, estimated_cost_cents=1,
        estimated_tokens=1, cost_limit_cents=20, token_limit=0,
    )
    assert result.allowed is True
    assert result.stage == "warn"


def test_perception_budget_blocks_the_call_that_would_cross_limit():
    result = perception_budget_decision(
        used_cost_cents=19, used_tokens=0, estimated_cost_cents=2,
        estimated_tokens=1, cost_limit_cents=20, token_limit=0,
    )
    assert result.allowed is False
    assert result.stage == "blocked"
    assert "cost budget" in result.reason


def test_perception_budget_zero_limits_are_disabled():
    result = perception_budget_decision(
        used_cost_cents=999, used_tokens=999, estimated_cost_cents=5,
        estimated_tokens=5,
    )
    assert result.allowed is True
    assert result.stage == "normal"
