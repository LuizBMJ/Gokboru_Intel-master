from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Mapping


Loader = Callable[[urllib.request.Request, float], tuple[int, Any]]


ACCOUNT_CATEGORIES = {
    "github.com": "developer_profile",
    "gitlab.com": "developer_profile",
    "bitbucket.org": "developer_profile",
    "linkedin.com": "professional_profile",
    "youtube.com": "video_profile",
    "vimeo.com": "video_profile",
    "twitch.tv": "video_profile",
    "facebook.com": "social_profile",
    "instagram.com": "social_profile",
    "twitter.com": "social_profile",
    "x.com": "social_profile",
    "tiktok.com": "social_profile",
    "pinterest.com": "social_profile",
    "tumblr.com": "social_profile",
    "reddit.com": "social_profile",
    "telegram.org": "social_profile",
    "t.me": "social_profile",
    "mastodon.social": "social_profile",
    "threads.net": "social_profile",
    "snapchat.com": "social_profile",
    "discord.com": "social_profile",
    "spotify.com": "creative_profile",
    "soundcloud.com": "creative_profile",
    "medium.com": "blog_profile",
    "wordpress.com": "blog_profile",
}


def normalize_email(value: str) -> str:
    email = value.strip()
    if "@" not in email:
        raise ValueError("A valid email address is required.")
    local, domain = email.rsplit("@", 1)
    if not local or not domain:
        raise ValueError("A valid email address is required.")
    try:
        domain = domain.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("A valid email address is required.") from exc
    return f"{local.lower()}@{domain.lower()}"


class EmailAccountsClient:
    """Read-only discovery of public profiles linked to an email address."""

    GRAVATAR_URL = "https://gravatar.com/{digest}.json"
    GITHUB_COMMITS_URL = "https://api.github.com/search/commits"
    GITHUB_USER_URL = "https://api.github.com/users/{login}"

    def __init__(
        self,
        *,
        timeout_seconds: float = 20.0,
        token: str | None = None,
        loader: Loader | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Email lookup timeout must be greater than zero.")
        self.timeout_seconds = timeout_seconds
        self.token = (token or os.getenv("GITHUB_TOKEN", "")).strip()
        self.loader = loader or self._load

    def gravatar(self, email: str) -> dict[str, Any]:
        normalized = normalize_email(email)
        digest = hashlib.md5(normalized.encode("utf-8")).hexdigest()
        request = self._request(self.GRAVATAR_URL.format(digest=digest))
        try:
            status, payload = self.loader(request, self.timeout_seconds)
        except urllib.error.HTTPError as exc:
            return self._http_error("gravatar", exc.code)
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            return self._provider_error("gravatar", exc)
        if status == 404:
            return self._not_found("gravatar")
        if status in {401, 403, 429}:
            return {"source": "gravatar", "status": "access_blocked", "profiles": [], "http_status": status}
        if status != 200 or not isinstance(payload, Mapping):
            return self._status_error("gravatar", status)
        entries = payload.get("entry")
        entry = entries[0] if isinstance(entries, list) and entries else None
        if not isinstance(entry, Mapping):
            return self._not_found("gravatar")
        profiles = self._gravatar_profiles(entry)
        if not profiles:
            return self._not_found("gravatar")
        return {
            "source": "gravatar",
            "status": "found",
            "profiles": profiles,
            "gravatar_hash": digest,
        }

    def github_commits(self, email: str, *, limit: int = 20) -> dict[str, Any]:
        normalized = normalize_email(email)
        query = urllib.parse.urlencode({
            "q": f"author-email:{normalized}",
            "per_page": str(min(100, max(1, limit))),
        })
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "Moriarty-V5 email-audit/1.0",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(f"{self.GITHUB_COMMITS_URL}?{query}", headers=headers)
        try:
            status, payload = self.loader(request, self.timeout_seconds)
        except urllib.error.HTTPError as exc:
            return self._http_error("github", exc.code)
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            return self._provider_error("github", exc)
        if status in {401, 403, 429}:
            return {"source": "github", "status": "rate_limited", "profiles": [], "http_status": status}
        if status != 200 or not isinstance(payload, Mapping):
            return self._status_error("github", status)
        items = payload.get("items")
        if not isinstance(items, list) or not items:
            return self._not_found("github")
        grouped: dict[str, dict[str, Any]] = {}
        for item in items:
            if not isinstance(item, Mapping):
                continue
            author = item.get("author") if isinstance(item.get("author"), Mapping) else {}
            commit = item.get("commit") if isinstance(item.get("commit"), Mapping) else {}
            commit_author = commit.get("author") if isinstance(commit.get("author"), Mapping) else {}
            login = str(author.get("login") or "").strip()
            if not login:
                continue
            key = login.casefold()
            entry = grouped.setdefault(key, {
                "login": login,
                "avatar_url": author.get("avatar_url"),
                "html_url": author.get("html_url"),
                "names": [],
                "repositories": [],
                "commit_urls": [],
                "dates": [],
            })
            name = str(commit_author.get("name") or "").strip()
            if name and name not in entry["names"]:
                entry["names"].append(name)
            repository = item.get("repository") if isinstance(item.get("repository"), Mapping) else {}
            repository_name = str(repository.get("full_name") or "").strip()
            if repository_name and repository_name not in entry["repositories"]:
                entry["repositories"].append(repository_name)
            commit_url = str(item.get("html_url") or "").strip()
            if commit_url and commit_url not in entry["commit_urls"]:
                entry["commit_urls"].append(commit_url)
            date = str(commit_author.get("date") or "").strip()
            if date:
                entry["dates"].append(date)
        if not grouped:
            return self._not_found("github")
        profiles: list[dict[str, Any]] = []
        for entry in grouped.values():
            details = self._github_user(entry["login"])
            dates = sorted(entry["dates"])
            profile = self._clean({
                "source": "github",
                "category": "developer_profile",
                "username": entry["login"],
                "name": details.get("name") or (entry["names"][0] if entry["names"] else entry["login"]),
                "bio": details.get("bio"),
                "company": details.get("company"),
                "location": details.get("location"),
                "blog": details.get("blog"),
                "avatar_url": details.get("avatar_url") or entry["avatar_url"],
                "web_url": details.get("html_url") or entry["html_url"] or f"https://github.com/{urllib.parse.quote(entry['login'], safe='')}",
                "email": normalized,
                "account_source": "github_commits",
                "commit_count": len(entry["dates"]),
                "repositories": entry["repositories"][:10],
                "evidence_urls": entry["commit_urls"][:10],
                "first_commit_at": dates[0] if dates else None,
                "last_commit_at": dates[-1] if dates else None,
                "public_repos": details.get("public_repos"),
                "created_at": details.get("created_at"),
                "confidence": 0.9,
                "note": "Public GitHub commit metadata matched the authorized email address.",
            })
            profiles.append(profile)
            twitter = str(details.get("twitter_username") or "").strip()
            if twitter:
                profiles.append(self._clean({
                    "source": "github",
                    "category": "social_profile",
                    "username": twitter,
                    "name": details.get("name") or twitter,
                    "web_url": f"https://x.com/{urllib.parse.quote(twitter, safe='')}",
                    "avatar_url": details.get("avatar_url"),
                    "account_source": "github_profile_link",
                    "confidence": 0.85,
                    "note": "X/Twitter handle published on the matching GitHub profile.",
                }))
        return {
            "source": "github",
            "status": "found",
            "profiles": profiles,
            "match_count": len(items),
            "author_count": len(grouped),
        }

    def _github_user(self, login: str) -> dict[str, Any]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "Moriarty-V5 email-audit/1.0",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(
            self.GITHUB_USER_URL.format(login=urllib.parse.quote(login, safe="")),
            headers=headers,
        )
        try:
            status, payload = self.loader(request, self.timeout_seconds)
        except (urllib.error.HTTPError, OSError, urllib.error.URLError, json.JSONDecodeError):
            return {}
        return payload if status == 200 and isinstance(payload, Mapping) else {}

    @staticmethod
    def _gravatar_profiles(entry: Mapping[str, Any]) -> list[dict[str, Any]]:
        preferred = str(entry.get("preferredUsername") or "").strip()
        profile_url = str(entry.get("profileUrl") or "").strip()
        if not profile_url and preferred:
            profile_url = f"https://gravatar.com/{urllib.parse.quote(preferred, safe='')}"
        photos = entry.get("photos") if isinstance(entry.get("photos"), list) else []
        avatar = photos[0].get("value") if photos and isinstance(photos[0], Mapping) else entry.get("thumbnailUrl")
        urls = [
            str(item.get("value"))
            for item in (entry.get("urls") or [])
            if isinstance(item, Mapping) and item.get("value")
        ]
        profile = EmailAccountsClient._clean({
            "source": "gravatar",
            "category": "identity_profile",
            "username": preferred,
            "name": EmailAccountsClient._display_name(entry),
            "bio": entry.get("aboutMe"),
            "location": entry.get("currentLocation"),
            "avatar_url": avatar,
            "web_url": profile_url,
            "urls": urls,
            "verified": True,
            "account_source": "gravatar_profile",
            "confidence": 0.95,
            "note": "Public Gravatar profile matched the MD5 hash of the authorized email address.",
        })
        profiles = [profile] if profile.get("web_url") else []
        accounts = entry.get("accounts") if isinstance(entry.get("accounts"), list) else []
        for account in accounts:
            if not isinstance(account, Mapping):
                continue
            domain = str(account.get("domain") or account.get("shortname") or "").strip().lower()
            username = str(account.get("username") or "").strip()
            url = str(account.get("url") or "").strip()
            if not url and domain and username:
                url = f"https://{domain}/{urllib.parse.quote(username, safe='')}"
            if not url:
                continue
            item = EmailAccountsClient._clean({
                "source": "gravatar",
                "category": EmailAccountsClient._account_category(domain),
                "username": username,
                "name": account.get("display") or username or domain,
                "web_url": url,
                "avatar_url": None,
                "verified": bool(account.get("verified")),
                "account_domain": domain,
                "account_source": "gravatar_linked_account",
                "confidence": 0.95 if account.get("verified") else 0.8,
                "note": "Linked account published on the matching Gravatar profile.",
            })
            profiles.append(item)
        return profiles

    @staticmethod
    def _display_name(entry: Mapping[str, Any]) -> str | None:
        name = entry.get("displayName")
        if name:
            return str(name)
        structured = entry.get("name") if isinstance(entry.get("name"), Mapping) else {}
        formatted = structured.get("formatted")
        if formatted:
            return str(formatted)
        parts = [structured.get("givenName"), structured.get("familyName")]
        value = " ".join(str(part).strip() for part in parts if part)
        return value or None

    @staticmethod
    def _account_category(domain: str) -> str:
        for candidate, category in ACCOUNT_CATEGORIES.items():
            if domain == candidate or domain.endswith(f".{candidate}"):
                return category
        return "social_profile" if domain else "online_profile"

    @staticmethod
    def _clean(values: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in values.items()
            if value not in (None, "", [], {})
        }

    @staticmethod
    def _request(url: str, accept: str = "application/json") -> urllib.request.Request:
        return urllib.request.Request(url, headers={
            "Accept": accept,
            "User-Agent": "Moriarty-V5 email-audit/1.0",
        })

    @staticmethod
    def _not_found(source: str) -> dict[str, Any]:
        return {"source": source, "status": "not_found", "profiles": []}

    @staticmethod
    def _provider_error(source: str, exc: Exception) -> dict[str, Any]:
        return {
            "source": source,
            "status": "provider_error",
            "profiles": [],
            "note": str(exc) or type(exc).__name__,
        }

    @classmethod
    def _http_error(cls, source: str, status: int) -> dict[str, Any]:
        if status == 404:
            return cls._not_found(source)
        if status in {401, 403, 429}:
            return {
                "source": source,
                "status": "rate_limited" if status == 429 else "access_blocked",
                "profiles": [],
                "http_status": status,
            }
        return cls._status_error(source, status)

    @staticmethod
    def _status_error(source: str, status: int) -> dict[str, Any]:
        return {
            "source": source,
            "status": "provider_error",
            "profiles": [],
            "http_status": status,
        }

    @staticmethod
    def _load(request: urllib.request.Request, timeout: float) -> tuple[int, Any]:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
            return response.status, json.loads(body) if body else None
