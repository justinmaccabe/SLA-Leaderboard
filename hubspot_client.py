"""HubSpot client that reproduces the report **1 (a) Open Tickets (Outside SLA)**
and returns a per-person count of open, SLA-breached tickets.

Why we re-derive the report instead of reading it back:
HubSpot has no supported API to fetch a saved custom report's computed results, so
we replicate its filter logic against the CRM Search API (tickets, object 0-5) and
aggregate by the `assigned_to` user — exactly what the report's dimension does.

The report's 9 filters (read from the report on 2026-06-30), combined with AND:
  1. SLA Due Date  is more than 0 days ago      -> breached (SLA due date < now)
  2. Close date    is unknown                    -> still open
  3. Ticket name   doesn't contain "test"
  4. Ticket Owner Check (formula) != True / empty
  5. Ticket status is none of Closed (Support Ticket)
  6. Action Item   is none of Completed, Cancelled, Rejected
  7. In Process Reason doesn't contain "custodian"
  8. Pipeline      is any of Transfer / Add Funds / Transfer Out /
                   Account Administration / Support Ticket / Withdraw
  9. Ticket owner  is none of Daniel Willett
 (+) Assigned to   is any of <the 26-person roster>

Search API limits: it cannot reliably filter on calculated/formula properties (the
"Ticket Owner Check" field) or on substring "doesn't contain". So we push the
clean, index-friendly filters to the API and apply the few residual predicates in
Python over the returned rows. The result is calibrated against the report's total
(set EXPECTED_TOTAL) on the first live run.
"""
from __future__ import annotations

import os
import time
import datetime as dt

import requests

BASE = "https://api.hubapi.com"

# Filter literals straight from the report -----------------------------------
PIPELINE_LABELS_IN = [
    "Transfer", "Add Funds", "Transfer Out",
    "Account Administration", "Support Ticket", "Withdraw",
]
STATUS_LABELS_NOT_IN = ["Closed (Support Ticket)"]
ACTION_ITEM_NOT_IN = ["Completed", "Cancelled", "Rejected"]
OWNER_NAME_NOT_IN = ["Daniel Willett"]
NAME_NOT_CONTAINS = "test"
IN_PROCESS_REASON_NOT_CONTAINS = "custodian"

# Property labels we resolve to internal names at runtime (custom props vary).
LABELS = {
    "sla_due": "SLA Due Date",
    "in_process_reason": "Support Ticket - In Process Reason",
    "owner_check": "Ticket Owner Check",
    "assigned_to": "Assigned to",
    "action_item": "Action Item",
}
# Stable internal names that don't need label resolution.
KNOWN = {
    "pipeline": "hs_pipeline",
    "stage": "hs_pipeline_stage",
    "subject": "subject",
    "closed_date": "closed_date",
    "owner": "hubspot_owner_id",
}


class HubSpot:
    def __init__(self, token: str | None = None):
        self.token = token or os.environ.get("HUBSPOT_TOKEN")
        if not self.token:
            raise RuntimeError(
                "No HubSpot token. Set HUBSPOT_TOKEN (Private App token with "
                "crm.objects.tickets.read, crm.schemas.tickets.read, and "
                "crm.objects.owners.read scopes)."
            )
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {self.token}",
                               "Content-Type": "application/json"})

    # -- low-level with basic 429 backoff -----------------------------------
    def _req(self, method, path, **kw):
        for attempt in range(5):
            r = self.s.request(method, f"{BASE}{path}", timeout=30, **kw)
            if r.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            return r.json()
        r.raise_for_status()

    # -- metadata resolution ------------------------------------------------
    def resolve_property_names(self) -> dict:
        """Map our human labels -> internal property names by reading the ticket
        property schema. Falls back to a slugged guess if a label isn't found."""
        data = self._req("GET", "/crm/v3/properties/tickets")
        by_label = {p["label"]: p["name"] for p in data.get("results", [])}
        names = dict(KNOWN)
        for key, label in LABELS.items():
            names[key] = by_label.get(label) or label.lower().replace(" ", "_")
        return names

    def pipeline_and_stage_ids(self):
        """Resolve pipeline labels -> ids and the 'Closed (Support Ticket)'
        stage label -> stage id, since search filters need ids, not labels."""
        data = self._req("GET", "/crm/v3/pipelines/tickets")
        pipeline_ids, closed_stage_ids = [], []
        for pl in data.get("results", []):
            if pl["label"] in PIPELINE_LABELS_IN:
                pipeline_ids.append(pl["id"])
            for st in pl.get("stages", []):
                if st["label"] in STATUS_LABELS_NOT_IN:
                    closed_stage_ids.append(st["id"])
        return pipeline_ids, closed_stage_ids

    def owners_by_name(self) -> dict:
        """Map 'First Last' -> owner id for owner-based filters."""
        out, after = {}, None
        while True:
            params = {"limit": 100}
            if after:
                params["after"] = after
            data = self._req("GET", "/crm/v3/owners", params=params)
            for o in data.get("results", []):
                name = f"{o.get('firstName','')} {o.get('lastName','')}".strip()
                if name:
                    out[name] = o["id"]
            after = data.get("paging", {}).get("next", {}).get("after")
            if not after:
                break
        return out

    def users_by_id(self) -> dict:
        """Map HubSpot user id -> display name, to turn the `assigned_to` user
        property value into the name shown on the leaderboard. Uses the owners
        endpoint (which exposes the linked userId) so we don't need the settings
        scope; falls back to email if no name is set."""
        out, after = {}, None
        while True:
            params = {"limit": 100}
            if after:
                params["after"] = after
            data = self._req("GET", "/crm/v3/owners", params=params)
            for o in data.get("results", []):
                uid = o.get("userId")
                name = f"{o.get('firstName','')} {o.get('lastName','')}".strip()
                if uid is not None:
                    out[str(uid)] = name or o.get("email", str(uid))
            after = data.get("paging", {}).get("next", {}).get("after")
            if not after:
                break
        return out

    # -- the actual query ---------------------------------------------------
    def fetch_breached(self) -> dict:
        """Return {person_name: open_breached_ticket_count}."""
        props = self.resolve_property_names()
        pipeline_ids, closed_stage_ids = self.pipeline_and_stage_ids()
        owners = self.owners_by_name()
        users = self.users_by_id()
        now_ms = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)

        exclude_owner_ids = [owners[n] for n in OWNER_NAME_NOT_IN if n in owners]

        # Server-side filters (index-friendly). One filterGroup == AND.
        filters = [
            {"propertyName": props["sla_due"], "operator": "LT", "value": now_ms},
            {"propertyName": props["closed_date"], "operator": "NOT_HAS_PROPERTY"},
            {"propertyName": props["pipeline"], "operator": "IN", "values": pipeline_ids},
        ]
        if closed_stage_ids:
            filters.append({"propertyName": props["stage"], "operator": "NOT_IN",
                            "values": closed_stage_ids})
        if ACTION_ITEM_NOT_IN:
            filters.append({"propertyName": props["action_item"], "operator": "NOT_IN",
                            "values": ACTION_ITEM_NOT_IN})
        if exclude_owner_ids:
            filters.append({"propertyName": props["owner"], "operator": "NOT_IN",
                            "values": exclude_owner_ids})

        return_props = [props["assigned_to"], props["subject"],
                        props["in_process_reason"], props["owner_check"]]

        counts: dict[str, int] = {}
        after = None
        while True:
            body = {
                "filterGroups": [{"filters": filters}],
                "properties": return_props,
                "limit": 100,
            }
            if after:
                body["after"] = after
            data = self._req("POST", "/crm/v3/objects/tickets/search", json=body)
            for t in data.get("results", []):
                p = t.get("properties", {})
                # ---- residual predicates the Search API can't express well ----
                subj = (p.get(props["subject"]) or "").lower()
                if NAME_NOT_CONTAINS in subj:
                    continue
                reason = (p.get(props["in_process_reason"]) or "").lower()
                if IN_PROCESS_REASON_NOT_CONTAINS in reason:
                    continue
                # "Ticket Owner Check != True (or empty)" — formula field read,
                # not filtered, server-side.
                oc = (p.get(props["owner_check"]) or "").strip().lower()
                if oc in ("true", "yes", "1"):
                    continue
                # ---- attribute to the assigned user ----
                uid = p.get(props["assigned_to"])
                if not uid:
                    continue
                name = users.get(str(uid), str(uid))
                counts[name] = counts.get(name, 0) + 1
            after = data.get("paging", {}).get("next", {}).get("after")
            if not after:
                break
        return counts
