"""Convert approved complete aggregates to the unchanged original classifier."""

from monthly_recap import CoreMetrics, build_type_section, classify_savings_type


def author_type_title(story: dict) -> str:
    metrics = story["author_previous_month"]
    if "metrics_version" not in metrics:
        return story["type_title"]
    # Request validation has already enforced the closed complete branch. Do not
    # invent missing values or alter the frozen request before digest validation.
    core = CoreMetrics(
        save_count=metrics["deposit_count"], total_savings=metrics["total_savings"],
        avg_amount=metrics["avg_amount"], regularity_std=metrics["regularity_std"],
        pace_bias=metrics["pace_bias"], abandon_count=metrics["abandon_count"],
        transfer_count=metrics["transfer_count"], visit_count=metrics["visit_count"],
    )
    return build_type_section(classify_savings_type(core))["type_title"]
