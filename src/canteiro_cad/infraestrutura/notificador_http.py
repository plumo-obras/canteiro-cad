"""Callback HTTP: avisa a URL de quem pediu quando a tradução termina, assinado com HMAC-SHA256 se houver segredo."""

from __future__ import annotations

import hashlib
import hmac
import json

import httpx


class NotificadorHttp:
    def __init__(self, segredo: bytes = b"", timeout: float = 10):
        self.segredo, self.timeout = segredo, timeout

    async def avisar(self, url: str, corpo: dict) -> None:
        bruto = json.dumps(corpo, ensure_ascii=False).encode()
        cab = {"Content-Type": "application/json"}
        if self.segredo:
            cab["X-Tradutor-Assinatura"] = "sha256=" + hmac.new(self.segredo, bruto, hashlib.sha256).hexdigest()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as c:
                await c.post(url, content=bruto, headers=cab)
        except httpx.HTTPError:
            pass  # o cliente ainda pode consultar o status
