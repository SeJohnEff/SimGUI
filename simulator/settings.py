"""Simulator settings."""

from dataclasses import dataclass


@dataclass
class SimulatorSettings:
    """Configuration for the SIM programmer simulator."""

    delay_ms: int = 500
    error_rate: float = 0.0
    num_cards: int = 10
