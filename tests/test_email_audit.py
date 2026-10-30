from __future__ import annotations

import hashlib

import pytest

from moriarty.providers.email_accounts import EmailAccountsClient, normalize_email
from moriarty.providers.email_localpart import EmailLocalpartClient
from moriarty.services.email_audit import EmailAuditCore, compact_email_audit, render_email_audit_text


def test_normalize_email_lowercases_local_and_domain() -> None:
    assert normalize_email(" Jane.Doe@Example.COM ") == "jane.doe@example.com"
    with pytest.raises(ValueError):
        normalize_email("not-an-email")


def test_gravatar_parses_profile_and_linked_social_accounts() -> None:
    def loader(request, timeout):
        assert hashlib.md5(b"jane@example.com").hexdigest() in request.full_url
        return 200, {
            "entry": [{
                "preferredUsername": "janedoe",
                "displayName": "Jane Doe",
                "profileUrl": "https://gravatar.com/janedoe",
                "accounts": [
                    {"domain": "github.com", "username": "janedoe", "url": "https://github.com/janedoe", "verified": True},
                    {"domain": "instagram.com", "username": "jane.doe", "url": "https://instagram.com/jane.doe"},
                ],
            }]
        }

    result = EmailAccountsClient(loader=loader).gravatar("jane@example.com")

    assert result["status"] == "found"
    assert result["profiles"][0]["category"] == "identity_profile"
    assert [item["category"] for item in result["profiles"][1:]] == ["developer_profile", "social_profile"]
    assert result["profiles"][2]["confidence"] == 0.8


def test_github_commits_groups_authors_and_adds_profile_links() -> None:
    def loader(request, timeout):
        if "/search/commits" in request.full_url:
            return 200, {
                "items": [
                    {
                        "author": {"login": "janedoe", "html_url": "https://github.com/janedoe"},
                        "commit": {"author": {"name": "Jane Doe", "date": "2025-01-01T00:00:00Z"}},
                        "repository": {"full_name": "acme/repo"},
                        "html_url": "https://github.com/acme/repo/commit/abc",
                    },
                    {
                        "author": {"login": "janedoe"},
                        "commit": {"author": {"name": "Jane Doe", "date": "2025-02-01T00:00:00Z"}},
                        "repository": {"full_name": "acme/other"},
                        "html_url": "https://github.com/acme/other/commit/def",
                    },
                ]
            }
        assert "/users/janedoe" in request.full_url
        return 200, {"login": "janedoe", "name": "Jane Doe", "twitter_username": "jane_x"}

    result = EmailAccountsClient(loader=loader).github_commits("jane@example.com")

    assert result["status"] == "found"
    assert result["author_count"] == 1
    assert result["profiles"][0]["commit_count"] == 2
    assert result["profiles"][0]["account_source"] == "github_commits"
    assert result["profiles"][1]["category"] == "social_profile"
    assert result["profiles"][1]["web_url"] == "https://x.com/jane_x"


def test_localpart_candidates_are_bounded_public_usernames() -> None:
    assert EmailLocalpartClient.candidates("Jane.Doe+tag@example.com") == ["jane.doe", "janedoe"]
    assert EmailLocalpartClient.candidates("a@example.com") == []


def test_email_audit_combines_authoritative_and_heuristic_profiles() -> None:
    runners = {
        "validation": lambda: {"source": "validation", "status": "found", "validation": {"syntax_valid": True}},
        "gravatar": lambda: {"source": "gravatar", "status": "found", "profiles": [{
            "name": "Jane Doe", "username": "janedoe", "web_url": "https://gravatar.com/janedoe",
            "category": "identity_profile", "source": "gravatar", "confidence": 1.0,
        }]},
        "github": lambda: {"source": "github", "status": "found", "profiles": [{
            "name": "Jane Doe", "username": "janedoe", "web_url": "https://github.com/janedoe",
            "category": "developer_profile", "source": "github", "confidence": 1.0,
        }]},
        "localpart": lambda: {"source": "localpart", "status": "found", "profiles": [{
            "name": "Jane Doe", "username": "janedoe", "web_url": "https://instagram.com/janedoe",
            "category": "social_profile", "source": "localpart", "confidence": 0.45,
            "heuristic": True,
        }]},
    }

    result = EmailAuditCore().run(
        "Jane.Doe@example.com",
        ("validation", "gravatar", "github", "localpart"),
        runners,
    )

    assert result["status"] == "completed"
    assert result["email"] == "jane.doe@example.com"
    assert result["summary"]["profiles_found"] == 3
    assert result["summary"]["confirmed_profiles"] == 2
    assert result["summary"]["unverified_profiles"] == 1
    assert result["summary"]["social_accounts"] == 1
    assert len(result["relationships"]) == 3
    statuses = {item["url"]: item["status"] for item in result["correlated_profiles"]}
    assert statuses["https://github.com/janedoe"] == "confirmed"
    assert statuses["https://instagram.com/janedoe"] == "unverified"


def test_compact_email_audit_removes_graph_internals() -> None:
    result = EmailAuditCore().run("jane@example.com", ("gravatar",), {
        "gravatar": lambda: {"source": "gravatar", "status": "found", "profiles": [{
            "username": "jane", "web_url": "https://gravatar.com/jane",
            "category": "identity_profile", "source": "gravatar", "confidence": 0.95,
        }]},
    })
    compact = compact_email_audit(result)

    assert compact["schema_version"] == "1.0-compact"
    assert "entities" not in compact
    assert compact["findings"]["profiles"][0]["url"] == "https://gravatar.com/jane"
    assert "EMAIL REPORT" in render_email_audit_text(compact, "en")
    assert "E-POSTA RAPORU" in render_email_audit_text(compact, "tr")


def test_email_audit_rejects_invalid_inputs() -> None:
    core = EmailAuditCore()
    with pytest.raises(ValueError):
        core.run("invalid", ("gravatar",), {})
    with pytest.raises(ValueError):
        core.run("jane@example.com", ("unknown",), {})
    with pytest.raises(ValueError):
        core.run("jane@example.com", (), {})
