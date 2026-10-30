from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Mapping

from moriarty.providers.public_username_profiles import PublicUsernameProfilesClient
from moriarty.providers.social_username_profiles import SocialUsernameProfilesClient
from moriarty.providers.web_username_probe import WEB_PROFILE_SPECS, WebUsernameProbe


USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
WEB_SOURCE_NAMES = {"facebook", "instagram", "twitter", "tiktok", "pinterest", "tumblr", "twitch"}
API_SOURCES = {
    "reddit": "social_profile",
    "bluesky": "social_profile",
    "telegram": "social_profile",
}


class EmailLocalpartClient:
    """Heuristic checks that reuse the email local-part as a public username."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 20.0,
        public_profiles: PublicUsernameProfilesClient | None = None,
        social_profiles: SocialUsernameProfilesClient | None = None,
        web_probe: WebUsernameProbe | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Email local-part timeout must be greater than zero.")
        self.timeout_seconds = timeout_seconds
        self.public_profiles = public_profiles or PublicUsernameProfilesClient(timeout_seconds=timeout_seconds)
        self.social_profiles = social_profiles or SocialUsernameProfilesClient(timeout_seconds=timeout_seconds)
        self.web_probe = web_probe or WebUsernameProbe(timeout_seconds=timeout_seconds)

    def lookup(self, email: str, *, limit: int = 20) -> dict[str, Any]:
        candidates = self.candidates(email)
        if not candidates:
            return {
                "source": "localpart",
                "status": "not_found",
                "profiles": [],
                "note": "The email local-part is not a valid public username.",
            }
        specs = [spec for spec in WEB_PROFILE_SPECS if spec.name in WEB_SOURCE_NAMES and not spec.retired]
        profiles: list[dict[str, Any]] = []
        checked = 0
        with ThreadPoolExecutor(max_workers=8, thread_name_prefix="email-localpart") as executor:
            jobs: list[tuple[str, Any, Any]] = []
            for username in candidates:
                for spec in specs:
                    jobs.append((username, spec, executor.submit(self.web_probe.lookup, spec, username)))
                jobs.append((username, None, executor.submit(self.public_profiles.reddit, username)))
                jobs.append((username, None, executor.submit(self.social_profiles.bluesky, username)))
                jobs.append((username, None, executor.submit(self.social_profiles.telegram, username)))
            for username, spec, future in jobs:
                checked += 1
                try:
                    result = future.result()
                except Exception:
                    continue
                if not isinstance(result, Mapping) or result.get("status") != "found":
                    continue
                profile = result.get("profile")
                if not isinstance(profile, Mapping):
                    continue
                api_source = str(result.get("source") or "")
                category = str(getattr(spec, "category", "") or API_SOURCES.get(api_source) or "social_profile")
                item = {
                    **dict(profile),
                    "source": "localpart",
                    "category": category,
                    "account_source": api_source or "unknown",
                    "confidence": 0.45,
                    "heuristic": True,
                    "note": (
                        f"Matched the email local-part '{username}' on {api_source or 'a public site'}. "
                        "This is a heuristic signal; account ownership must be verified manually."
                    ),
                }
                profiles.append({key: value for key, value in item.items() if value not in (None, "", [], {})})
        unique: dict[str, dict[str, Any]] = {}
        for profile in profiles:
            key = "|".join(str(value) for value in (
                profile.get("account_source"),
                profile.get("web_url") or profile.get("url"),
                profile.get("username"),
            ) if value)
            unique.setdefault(key, profile)
        output = list(unique.values())[:max(1, limit)]
        return {
            "source": "localpart",
            "status": "found" if output else "not_found",
            "profiles": output,
            "checked_count": checked,
            "found_count": len(output),
            "candidate_usernames": candidates,
        }

    @staticmethod
    def candidates(email: str) -> list[str]:
        local = email.strip().split("@", 1)[0].lower()
        local = local.split("+", 1)[0]
        values = [local]
        if "." in local:
            values.append(local.replace(".", ""))
        output: list[str] = []
        for value in values:
            if value and USERNAME_RE.fullmatch(value) and value not in output:
                output.append(value)
        return output[:2]
