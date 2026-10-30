from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from time import monotonic
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4

from moriarty.domain.intelligence_graph import IntelligenceEntity, IntelligenceRelationship
from moriarty.services.username_audit import correlate_username_profiles


EMAIL_RE = re.compile(
    r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?"
    r"(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+$",
    re.IGNORECASE,
)
SOCIAL_CATEGORY_RE = re.compile(r"^(?:social|professional|video|creative|community|blog)")


def _is_social_category(value: Any) -> bool:
    return bool(SOCIAL_CATEGORY_RE.match(str(value or "")))


@dataclass(frozen=True, slots=True)
class EmailSource:
    name: str
    category: str
    description: str
    requires_configuration: tuple[str, ...] = ()


DEFAULT_EMAIL_SOURCES = (
    EmailSource(
        "validation",
        "email_identity",
        "Email syntax, DNS, MX, domain and disposable-provider validation without sending mail.",
    ),
    EmailSource(
        "gravatar",
        "identity_profile",
        "Gravatar profile and its verified linked social accounts, matched by email hash.",
    ),
    EmailSource(
        "github",
        "developer_profile",
        "Public GitHub commits authored with the email address, enriched with GitHub profile links.",
        ("GITHUB_TOKEN (optional)",),
    ),
    EmailSource(
        "localpart",
        "social_profile",
        "Heuristic exact-username checks across social platforms using the email local-part.",
    ),
)


class EmailAuditCore:
    def __init__(self, catalog: Sequence[EmailSource] = DEFAULT_EMAIL_SOURCES) -> None:
        self.catalog = tuple(catalog)
        self._known = {item.name for item in catalog}
        self._categories = {item.name: item.category for item in catalog}

    def run(
        self,
        email: str,
        selected_sources: Sequence[str],
        runners: Mapping[str, Callable[[], Mapping[str, Any]]],
    ) -> dict[str, Any]:
        email = email.strip()
        if not EMAIL_RE.fullmatch(email):
            raise ValueError("A valid email address is required.")
        normalized = email.lower()
        selected = tuple(dict.fromkeys(item.strip().lower() for item in selected_sources if item.strip()))
        unknown = tuple(item for item in selected if item not in self._known)
        if unknown:
            raise ValueError(f"Unknown email-audit source(s): {', '.join(unknown)}")
        if not selected:
            raise ValueError("Select at least one email-audit source.")

        started_at = datetime.now(timezone.utc)
        started = monotonic()
        target = IntelligenceEntity("email", normalized, normalized, "target", {"normalized": normalized})
        entities = [target]
        relationships: list[IntelligenceRelationship] = []

        def run_source(source: str) -> dict[str, Any]:
            source_started = monotonic()
            try:
                item = dict(runners[source]())
            except Exception as exc:
                item = {
                    "source": source,
                    "status": "provider_error",
                    "profiles": [],
                    "note": str(exc) or type(exc).__name__,
                }
            verification_status = str(item.get("status") or "provider_error")
            item["verification_status"] = verification_status
            item["display_status"] = (
                "found" if verification_status == "found"
                else "not_found" if verification_status == "not_found"
                else "failed"
            )
            item["duration_ms"] = max(0, round((monotonic() - source_started) * 1000))
            return item

        with ThreadPoolExecutor(max_workers=min(8, len(selected)), thread_name_prefix="email-audit") as executor:
            results = list(executor.map(run_source, selected))

        validation: dict[str, Any] | None = None
        for source, item in zip(selected, results, strict=True):
            if isinstance(item.get("validation"), Mapping):
                validation = dict(item["validation"])
            raw_profiles = item.get("profiles")
            if not isinstance(raw_profiles, list):
                raw_profiles = [item["profile"]] if isinstance(item.get("profile"), Mapping) else []
            for profile in raw_profiles:
                if not isinstance(profile, Mapping):
                    continue
                url = str(profile.get("web_url") or profile.get("url") or "").strip()
                if not url:
                    continue
                profile_source = str(profile.get("source") or source)
                username = str(profile.get("username") or profile.get("name") or "").strip()
                label = str(profile.get("name") or username or profile_source)
                confidence = float(profile.get("confidence", item.get("confidence", 1.0)))
                properties = {
                    **dict(profile),
                    "email": normalized,
                    "display_status": "found",
                    "verification_status": "heuristic" if profile.get("heuristic") else "found",
                    "category": str(profile.get("category") or self._categories.get(source, "online_profile")),
                }
                entity = IntelligenceEntity(
                    "online_profile",
                    url,
                    label,
                    profile_source,
                    properties,
                    min(max(confidence, 0.0), 1.0),
                )
                entities.append(entity)
                relationships.append(
                    IntelligenceRelationship(target.id, entity.id, "registered_with", profile_source, {
                        "email": normalized,
                        "account_source": profile.get("account_source") or profile_source,
                    })
                )

        correlated = correlate_username_profiles([entity.to_dict() for entity in entities])
        completed = sum(item.get("verification_status") in {"found", "not_found"} for item in results)
        found_sources = sum(item.get("verification_status") == "found" for item in results)
        unverified = len(results) - completed
        completed_at = datetime.now(timezone.utc)
        summary = {
            "requested": len(results),
            "completed": completed,
            "found": found_sources,
            "not_found": sum(item.get("verification_status") == "not_found" for item in results),
            "unverified": unverified,
            "failed_or_blocked": unverified,
            "profiles_found": len(correlated),
            "social_accounts": sum(_is_social_category(item.get("category")) for item in correlated),
            "confirmed_profiles": sum(item.get("status") == "confirmed" for item in correlated),
            "probable_profiles": sum(item.get("status") == "probable" for item in correlated),
            "unverified_profiles": sum(item.get("status") == "unverified" for item in correlated),
        }
        return {
            "schema_version": "1.0",
            "audit_type": "email",
            "audit_id": str(uuid4()),
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "duration_ms": max(0, round((monotonic() - started) * 1000)),
            "email": normalized,
            "status": "completed" if completed == len(results) else "partial" if completed else "failed",
            "validation": validation,
            "summary": summary,
            "checks": [
                {
                    "source": item.get("source"),
                    "status": item.get("display_status"),
                    "verification_status": item.get("verification_status"),
                    "profile_count": len(item.get("profiles") or []) if isinstance(item.get("profiles"), list) else 0,
                }
                for item in results
            ],
            "sources": results,
            "entities": [entity.to_dict() for entity in entities],
            "relationships": [relation.to_dict() for relation in relationships],
            "correlated_profiles": correlated,
        }


def compact_email_audit(result: Mapping[str, Any]) -> dict[str, Any]:
    profiles = result.get("correlated_profiles")
    profiles = [dict(item) for item in profiles if isinstance(item, Mapping)] if isinstance(profiles, list) else []
    diagnostics: list[dict[str, Any]] = []
    for item in result.get("sources", []):
        if not isinstance(item, Mapping):
            continue
        status = item.get("verification_status") or item.get("status")
        if status in {"found", "not_found"}:
            continue
        diagnostics.append({
            key: value
            for key, value in {
                "source": item.get("source"),
                "status": status,
                "note": item.get("note"),
            }.items()
            if value
        })
    social = [item for item in profiles if _is_social_category(item.get("category"))]
    summary = dict(result.get("summary") or {})
    summary["profiles_found"] = len(profiles)
    summary["social_accounts"] = len(social)
    summary["confirmed_profiles"] = sum(item.get("status") == "confirmed" for item in profiles)
    summary["probable_profiles"] = sum(item.get("status") == "probable" for item in profiles)
    summary["unverified_profiles"] = sum(item.get("status") == "unverified" for item in profiles)
    return {
        "schema_version": "1.0-compact",
        "audit_id": result.get("audit_id"),
        "email": result.get("email"),
        "status": result.get("status"),
        "validation": result.get("validation"),
        "summary": summary,
        "findings": {"profiles": profiles, "social_accounts": social},
        "diagnostics": diagnostics,
    }


def render_email_audit_text(result: Mapping[str, Any], language: str = "en") -> str:
    tr = language != "en"
    summary = result.get("summary") if isinstance(result.get("summary"), Mapping) else {}
    findings = result.get("findings") if isinstance(result.get("findings"), Mapping) else {}
    profiles = findings.get("profiles") if isinstance(findings.get("profiles"), list) else []
    diagnostics = result.get("diagnostics") if isinstance(result.get("diagnostics"), list) else []
    validation = result.get("validation") if isinstance(result.get("validation"), Mapping) else {}
    lines = [
        "=" * 72,
        f"  GOKBORU INTELLIGENCE - {'E-POSTA RAPORU' if tr else 'EMAIL REPORT'}",
        "=" * 72,
        f"  {'Hedef' if tr else 'Target'}       : {result.get('email', '-')}",
        f"  {'Durum' if tr else 'Status'}       : {result.get('status', '-')}",
        f"  {'Kaynaklar' if tr else 'Sources'}     : {summary.get('completed', 0)}/{summary.get('requested', 0)}",
        f"  {'Profil' if tr else 'Profiles'}      : {summary.get('profiles_found', len(profiles))}",
        f"  {'Sosyal hesap' if tr else 'Social accounts'}: {summary.get('social_accounts', 0)}",
    ]
    if validation:
        syntax_valid = bool(validation.get("syntax_valid"))
        mx_valid = bool(validation.get("mx_configured"))
        lines.extend([
            f"  {'Sintaks' if tr else 'Syntax'}       : {('gecerli' if syntax_valid else 'gecersiz') if tr else ('valid' if syntax_valid else 'invalid')}",
            f"  MX           : {('var' if mx_valid else 'yok') if tr else ('yes' if mx_valid else 'no')}",
        ])

    lines.extend(["", "-" * 72, f"  {'PROFILLER' if tr else 'PROFILES'}", "-" * 72])
    if not profiles:
        lines.append("  " + ("Eslesen profil bulunamadi." if tr else "No matching profiles found."))
    for index, profile in enumerate(profiles[:100], 1):
        if not isinstance(profile, Mapping):
            continue
        url = profile.get("url") or profile.get("web_url") or profile.get("canonical_url") or "-"
        sources = ", ".join(str(value) for value in profile.get("evidence_sources", []) if value) or "-"
        lines.extend([
            f"  [{index:02}] {profile.get('name') or profile.get('username') or 'Profile'}",
            f"       URL        : {url}",
            f"       {'Kategori' if tr else 'Category'}   : {profile.get('category') or 'unknown'}",
            f"       {'Guven' if tr else 'Confidence'}  : {profile.get('status', 'unverified')} ({round(float(profile.get('confidence') or 0) * 100)}%)",
            f"       {'Kanit' if tr else 'Evidence'}    : {sources}",
        ])

    if diagnostics:
        lines.extend(["", "-" * 72, f"  {'KAYNAK DURUMLARI' if tr else 'SOURCE STATUSES'}", "-" * 72])
        for item in diagnostics[:50]:
            if isinstance(item, Mapping):
                lines.append(
                    f"  - {item.get('source', 'source')}: {item.get('status', 'unverified')} - "
                    f"{item.get('note') or item.get('error') or '-'}"
                )
    return "\n".join(lines)
