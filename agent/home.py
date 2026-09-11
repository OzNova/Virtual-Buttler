"""Home Assistant bridge (Phase 4). Opt-in, local-only, REST via urllib.

Env: HASS_URL (e.g. http://homeassistant.local:8123), HASS_TOKEN (long-lived).
No MQTT dep in Phase 4 (documented for later). All calls time out fast and
degrade to {hint} when unconfigured — never crash the agent.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request

logger = logging.getLogger("butler-agent.home")


def configured() -> bool:
    return bool(os.getenv("HASS_URL") and os.getenv("HASS_TOKEN"))


def _req(method: str, path: str, body: dict | None = None, timeout: float = 10.0):
    base = (os.getenv("HASS_URL") or "").rstrip("/")
    token = os.getenv("HASS_TOKEN", "")
    if not (base and token):
        raise RuntimeError("Set HASS_URL and HASS_TOKEN to use smart home.")
    data = json.dumps(body or {}).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Authorization": f"Bearer {token}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode()
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        return {}


def get_state(entity_id: str) -> dict:
    try:
        data = _req("GET", f"/api/states/{entity_id}")
        return {"ok": True, "state": data.get("state"), "attributes": data.get("attributes", {})}
    except RuntimeError as e:
        return {"ok": False, "hint": str(e)}
    except Exception:
        logger.debug("HASS state failed", exc_info=True)
        return {"ok": False, "error": "home assistant request failed"}


def call_service(domain: str, service: str, data: dict | None = None) -> dict:
    try:
        _req("POST", f"/api/services/{domain}/{service}", {"entity_id": (data or {}).get("entity_id"),
                                                           **{k: v for k, v in (data or {}).items()
                                                              if k != "entity_id"}})
        return {"ok": True}
    except RuntimeError as e:
        return {"ok": False, "hint": str(e)}
    except Exception:
        logger.debug("HASS service failed", exc_info=True)
        return {"ok": False, "error": "home assistant request failed"}
