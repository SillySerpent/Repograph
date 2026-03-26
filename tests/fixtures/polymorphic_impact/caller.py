"""OrderManager — explicitly typed against IBroker interface only.

The broker field is typed as IBroker.  The call to broker.submit_order()
resolves to IBroker.submit_order in the call graph (the only known
function matching that name on IBroker).
"""
from __future__ import annotations


class OrderManager:
    """Manages order lifecycle. Depends on IBroker, not LiveBroker directly."""

    def __init__(self, broker) -> None:
        # Type hint is kept as a string to avoid a hard import of IBroker,
        # forcing the call resolver to use the declared type annotation path.
        self._broker = broker  # type: IBroker

    async def submit(self, intent: dict) -> dict:
        """Build and submit an entry order via the broker interface."""
        order = self._build_order(intent)
        # This call targets self._broker whose static type is IBroker.
        # The call graph should link to IBroker.submit_order, not LiveBroker.submit_order.
        ack = await self._broker.submit_order(order)
        return ack

    async def close_position(self, symbol: str, qty: float) -> dict:
        """Submit a closing order for an existing position."""
        order = {"symbol": symbol, "qty": qty, "side": "close"}
        ack = await self._broker.submit_order(order)
        return ack

    async def cancel(self, order_id: str) -> bool:
        """Delegate cancellation to the broker."""
        return await self._broker.cancel_order(order_id)

    def _build_order(self, intent: dict) -> dict:
        return {
            "symbol": intent.get("symbol", "BTC"),
            "qty": intent.get("qty", 0.01),
            "side": intent.get("side", "buy"),
            "type": "market",
        }
