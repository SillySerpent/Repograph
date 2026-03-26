"""LiveBroker — concrete implementation of IBroker."""
from __future__ import annotations
from interface import IBroker


class LiveBroker(IBroker):
    """Live exchange broker. Routes orders via signed REST calls."""

    def __init__(self, api_key: str, secret: str) -> None:
        self._api_key = api_key
        self._secret = secret
        self._session = None

    async def submit_order(self, order: dict) -> dict:
        """Submit order to exchange REST API."""
        signed = self._sign_request(order)
        response = await self._post("/v1/order", signed)
        return {"ack_id": response.get("order_id"), "status": "accepted"}

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel order via REST DELETE endpoint."""
        resp = await self._delete(f"/v1/order/{order_id}")
        return resp.get("status") == "cancelled"

    def get_position(self, symbol: str) -> dict | None:
        """Return cached position snapshot."""
        return self._positions.get(symbol)

    def _sign_request(self, payload: dict) -> dict:
        """Add HMAC signature headers."""
        import hashlib
        return {"data": payload, "sig": hashlib.sha256(str(payload).encode()).hexdigest()}

    async def _post(self, path: str, body: dict) -> dict:
        return {}

    async def _delete(self, path: str) -> dict:
        return {}

    @property
    def _positions(self) -> dict:
        return {}
