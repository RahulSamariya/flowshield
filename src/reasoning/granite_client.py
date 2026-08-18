"""GraniteClient — thin HTTP wrapper for IBM Granite text generation.

Responsibilities
----------------
- POST to the Granite /v1/text/generation endpoint.
- Raise GraniteUnavailable on any network, timeout, or HTTP error.
- Never interpret the response — return raw generated text to the caller.
- Read credentials from environment variables so no secrets appear in code.

Environment variables
---------------------
GRANITE_API_URL   Base URL, e.g. https://us-south.ml.cloud.ibm.com
GRANITE_API_KEY   IBM Cloud API key (Bearer token)
GRANITE_MODEL_ID  Model ID (default: ibm/granite-3-8b-instruct)

The client is intentionally minimal.  All prompt engineering lives in
``prompt_templates.py``, not here.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field


class GraniteUnavailable(RuntimeError):
    """Raised when Granite cannot be reached or returns a non-200 response.

    Callers should catch this and activate the deterministic fallback path.
    """


@dataclass
class GraniteConfig:
    """Runtime configuration for the Granite client.

    Reads from environment variables by default so secrets never appear in
    source code.  Pass explicit values only in tests.
    """

    api_url: str = field(
        default_factory=lambda: os.getenv(
            "GRANITE_API_URL", "https://us-south.ml.cloud.ibm.com"
        )
    )
    api_key: str = field(
        default_factory=lambda: os.getenv("GRANITE_API_KEY", "")
    )
    model_id: str = field(
        default_factory=lambda: os.getenv(
            "GRANITE_MODEL_ID", "ibm/granite-3-8b-instruct"
        )
    )
    timeout_seconds: int = 30
    max_new_tokens: int = 512
    temperature: float = 0.0   # deterministic output — no sampling


class GraniteClient:
    """HTTP client for IBM Granite text generation.

    Usage::

        client = GraniteClient()                    # reads from env
        client = GraniteClient(GraniteConfig(       # explicit config for tests
            api_url="http://mock", api_key="test"
        ))

        text = client.generate(prompt)              # raises GraniteUnavailable on error
    """

    def __init__(self, config: GraniteConfig | None = None) -> None:
        self._cfg = config or GraniteConfig()

    def generate(self, prompt: str) -> str:
        """Send ``prompt`` to Granite and return the generated text.

        Raises
        ------
        GraniteUnavailable
            On any network error, timeout, missing API key, or non-200 HTTP status.
        """
        if not self._cfg.api_key:
            raise GraniteUnavailable(
                "GRANITE_API_KEY is not set. "
                "Set the environment variable or pass GraniteConfig explicitly."
            )

        url = (
            f"{self._cfg.api_url.rstrip('/')}"
            f"/ml/v1/text/generation?version=2023-05-29"
        )
        body = json.dumps({
            "model_id": self._cfg.model_id,
            "input": prompt,
            "parameters": {
                "decoding_method": "greedy",
                "max_new_tokens": self._cfg.max_new_tokens,
                "temperature": self._cfg.temperature,
                "stop_sequences": ["<|end|>"],
            },
        }).encode()

        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._cfg.api_key}",
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self._cfg.timeout_seconds) as resp:
                raw = resp.read().decode()
        except urllib.error.HTTPError as exc:
            raise GraniteUnavailable(
                f"Granite returned HTTP {exc.code}: {exc.reason}"
            ) from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise GraniteUnavailable(
                f"Granite unreachable: {exc}"
            ) from exc

        try:
            payload = json.loads(raw)
            return payload["results"][0]["generated_text"].strip()
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            raise GraniteUnavailable(
                f"Unexpected Granite response format: {raw[:200]}"
            ) from exc
