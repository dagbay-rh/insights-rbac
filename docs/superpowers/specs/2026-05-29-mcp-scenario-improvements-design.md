# MCP Scenario Improvements Design

Addresses the top 3 improvement priorities identified in LLM evaluation of RBAC MCP chatbot scenarios.

## Problem Statement

LLM evaluation of 10 RBAC MCP scenarios revealed three critical gaps:

1. **Scenario 7 — Offboarding (score 5/100):** All 4 runs return "I can't answer that." No tool description mentions offboarding as a use case, so the LLM doesn't know which tools to chain.
2. **Scenario 5 — User lookup (score 50/100):** `guide_user_access_delegation` does exact username match only. When given a display name like "Joe", it fails 3/4 runs. Only succeeds when the LLM independently resolves the username first.
3. **Scenarios 9-10 — Cross-account (scores 60-65/100):** Tools return correct data but responses are too thin. No lifecycle explanation, no audience-specific formatting, no proactive checks when results are empty.

## Target Scores

- Scenario 7: 5 → 70+
- Scenario 5: 50 → 85+
- Scenarios 9-10: 60-65 → 80+

## All Changes in One File

Every change is in `rbac/management/mcp_views.py`. No new models, endpoints, or files needed.

---

## Change 1: Offboarding Discovery (Scenario 7)

### Root Cause

The `get_user_state` tool already returns everything needed for an offboarding report (groups, roles, permissions, audit history by and on the user). But its description doesn't mention offboarding, so the LLM never discovers it for this use case.

### Changes

**1a. `get_user_state` description (~line 2774):**

Add offboarding as a named scenario with trigger keywords:

```
SCENARIO: 'Contractor X is being offboarded, I need their RBAC activity and current access' →
call get_user_state(username='X') to get groups, permissions, and audit trail in one call.
USE WHEN: 'offboard', 'offboarding', 'leaving the company', 'contractor leaving',
'deprovisioning', 'compliance report', 'activity summary for records'.
AFTER ANALYSIS: Present numbered options:
(1) remove the user from all their group(s),
(2) generate a formatted compliance report for records,
(3) both.
Format as 'Reply 1, 2, or 3 -- or no'.
Note: Deactivating the user account itself is handled in the IT/account portal, not the RBAC API.
```

**Note:** Init instructions (`_MCP_INSTRUCTIONS_*`) are not supported by the runtime. All guidance
goes into per-tool descriptions only — no changes to `_MCP_INSTRUCTIONS_REMEDIATION`.

---

## Change 2: Fuzzy User Lookup in Delegation Tool (Scenario 5)

### Root Cause

`guide_user_access_delegation` takes a `username` parameter and does `list_principals(usernames=username, match_criteria='exact')`. When the LLM passes a display name like "Joe", it gets 0 results and reports failure. No fallback to display-name search.

### Changes

**2a. Add fuzzy fallback in `guide_user_access_delegation` (~line 4232-4246):**

After the exact username lookup returns 0 results, try `_list_principals_by_name()`:

```python
# Current: exact match only
principals_raw = list_principals(request, usernames=username, match_criteria="exact", limit=1)
principals_data = json.loads(principals_raw)
if principals_data.get("data"):
    # ... use it
else:
    result["user_info"] = {"error": f"User '{username}' not found"}

# New: add fuzzy fallback
if not principals_data.get("data"):
    # Try display name search
    name_raw = _list_principals_by_name(request, username, limit=5, offset=0,
                                         sort_order="asc", status="enabled")
    name_data = json.loads(name_raw)
    candidates = name_data.get("data", [])
    if len(candidates) == 1:
        # Exactly one match — use it automatically
        user_data = candidates[0]
        username = user_data.get("username")  # Update for downstream lookups
        result["user_info"] = {
            "username": user_data.get("username"),
            "is_org_admin": user_data.get("is_org_admin", False),
            "is_active": user_data.get("is_active", True),
            "resolved_from": f"display name '{username}' matched to '{user_data.get('username')}'",
        }
    elif len(candidates) > 1:
        # Multiple matches — return candidates for disambiguation
        result["user_info"] = {
            "error": f"Multiple users match '{username}'",
            "candidates": [
                {"username": c.get("username"),
                 "name": f"{c.get('first_name', '')} {c.get('last_name', '')}".strip()}
                for c in candidates
            ],
            "hint": "Re-call with the exact username from the candidates list.",
        }
    else:
        result["user_info"] = {"error": f"User '{username}' not found"}
```

**2b. Update tool description (~line 4184):**

Change the username parameter context in the description to:
```
"Accepts username (e.g., 'doejoe') or display name (e.g., 'Joe Doe'). "
"If a display name is given, the tool resolves it automatically. "
"If multiple users match, candidates are returned for disambiguation."
```

---

## Change 3: Richer Cross-Account Responses (Scenarios 9-10)

### Root Cause

`investigate_tam_access` and `audit_redhat_access` return correct data but:
- Empty results get a one-liner instead of proactive follow-up
- No lifecycle explanation for cross-account requests
- No audience-specific formatting guidance (CISO briefing)

### Changes

**3a. `investigate_tam_access` — Enrich empty-result response (~line 1793):**

When no approved requests are found, automatically query pending and expired counts:

```python
if not requests_list:
    # Proactively check other statuses
    pending_count = CrossAccountRequest.objects.filter(
        target_org=org_id, status="pending"
    ).count()
    expired_count = CrossAccountRequest.objects.filter(
        target_org=org_id, status="expired"
    ).count()

    return json.dumps({
        "requests": [],
        "analysis": {
            "total_active_requests": 0,
            "message": f"No {status} cross-account requests found.",
            "other_statuses": {
                "pending": pending_count,
                "expired": expired_count,
            },
            "lifecycle": (
                "Cross-account request lifecycle: "
                "create → pending (awaits org admin approval) → approved (active access) → expired. "
                "A request can also be denied or cancelled at any stage."
            ),
            "hint": (
                f"There are {pending_count} pending and {expired_count} expired request(s). "
                "Use investigate_tam_access(status='pending') or status='expired' to inspect them."
                if pending_count or expired_count
                else "No requests of any status exist for this organization."
            ),
        },
    })
```

**3b. `investigate_tam_access` — Update description (~line 1740):**

Add formatting and lifecycle guidance:
```
"When no approved requests are found, the tool proactively checks for pending/expired "
"requests and explains the cross-account request lifecycle. "
"RESPONSE FORMAT: Present results as a table: "
"requester name | roles granted | specific permissions | expiration | status. "
"Explain the lifecycle: create → pending → approved → active → expired."
```

**3c. `audit_redhat_access` — Enrich empty-result response (~line 2002):**

When no active access exists, include a CISO briefing template and monitoring suggestion:

```python
if not requests_list:
    # Check other statuses for context
    pending_count = CrossAccountRequest.objects.filter(
        target_org=org_id, status="pending"
    ).count()
    expired_count = CrossAccountRequest.objects.filter(
        target_org=org_id, status="expired"
    ).count()

    return json.dumps({
        "active_access": [],
        "summary": {
            "total_users": 0,
            "expiring_soon": 0,
            "unused_access": 0,
            "pending_requests": pending_count,
            "expired_requests": expired_count,
            "message": "No active Red Hat cross-account access found for this organization.",
            "ciso_briefing": (
                "CISO Summary: Zero Red Hat personnel currently have active access to this "
                "organization's console.redhat.com environment. "
                + (f"There are {pending_count} pending request(s) awaiting approval. "
                   if pending_count else "")
                + (f"There are {expired_count} previously expired access grant(s) on record."
                   if expired_count else "")
            ),
            "briefing_template": (
                "If active access existed, the report would include for each Red Hat user: "
                "name, email, roles granted, permission scope, access start/end dates, "
                "days remaining, and RBAC audit activity (actions performed during the access window)."
            ),
            "monitoring": (
                "To monitor future cross-account requests, periodically call "
                "audit_redhat_access() or list_cross_account_requests(query_by='target_org', "
                "status='pending') to catch new requests before they are approved."
            ),
        },
    })
```

**3d. `audit_redhat_access` — Update description (~line 1950):**

Add CISO formatting guidance:
```
"FORMAT FOR CISO BRIEFING: Present as a table with columns: "
"Red Hat user | roles | access scope | expiration | approved by | recent activity. "
"When no active access exists, still present a summary stating zero access, "
"note any pending/expired requests, and provide a monitoring recommendation."
```

**Note:** All cross-account formatting/lifecycle guidance is embedded in the per-tool descriptions
(3b and 3d above). No changes to `_MCP_INSTRUCTIONS_REMEDIATION` since init instructions are
not supported by the runtime.

---

## Testing

Update `tests/management/test_mcp_views.py` with:

1. **Offboarding:** Verify `get_user_state` description contains offboarding keywords.
2. **Fuzzy lookup:** Test `guide_user_access_delegation` with a display name that resolves to exactly 1 user, multiple users, and zero users.
3. **Cross-account empty results:** Verify `investigate_tam_access` and `audit_redhat_access` return enriched responses with pending/expired counts when no approved requests exist.

---

## Out of Scope

- New MCP tools (decision: enhance existing tools)
- Changes to V1/V2 API endpoints
- Changes to models or database schema
- Frontend changes
