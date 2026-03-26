"""IBroker interface — callers reference only this type, never the concrete class."""
from __future__ import annotations
from abc import ABC, abstractmethod


class IBroker(ABC):
    """Abstract broker interface used throughout order management."""

    @abstractmethod
    async def submit_order(self, order: dict) -> dict:
        """Submit an order to the exchange.  Returns an acknowledgement dict."""

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order.  Returns True on success."""

    @abstractmethod
    def get_position(self, symbol: str) -> dict | None:
        """Return the current open position for a symbol, or None."""
