"""Logging configuration using loguru."""

import sys

from loguru import logger

from aegis.config import settings


def setup_logging() -> None:
    """Configure loguru for the application.

    Local: human-readable colored output.
    Production: JSON-serialized for log aggregation.
    """
    logger.remove()

    if settings.is_production:
        logger.add(sys.stderr, serialize=True, level=settings.log_level)
    else:
        logger.add(
            sys.stderr,
            level=settings.log_level,
            format=(
                "<green>{time:YYYY-MM-DDTHH:mm:ss}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{name}</cyan>:<cyan>{function}</cyan> | "
                "{extra} | "
                "<level>{message}</level>"
            ),
        )


# Pricing per 1M tokens (Claude Sonnet 4)
ANTHROPIC_INPUT_COST_PER_M = 3.00
ANTHROPIC_OUTPUT_COST_PER_M = 15.00


def estimate_cost(input_tokens: int, output_tokens: int) -> float:
    """Estimate USD cost for an Anthropic API call."""
    input_cost = (input_tokens / 1_000_000) * ANTHROPIC_INPUT_COST_PER_M
    output_cost = (output_tokens / 1_000_000) * ANTHROPIC_OUTPUT_COST_PER_M
    return round(input_cost + output_cost, 6)
