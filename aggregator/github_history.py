"""GitHub history aggregator — fetches recent commits or mock."""

import os
import requests
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)


class GithubHistoryAggregator:
    def __init__(self, use_mock: bool = True):
        self.use_mock = use_mock
        self.token = os.environ.get("GITHUB_TOKEN")

    def get_recent_commits(self, owner: str = "acme", repo: str = "payment-service") -> List[Dict]:
        if self.use_mock or not self.token:
            return self._get_mock_commits()

        try:
            headers = {
                "Authorization": f"token {self.token}",
                "Accept": "application/vnd.github.v3+json",
            }
            response = requests.get(
                f"https://api.github.com/repos/{owner}/{repo}/commits?per_page=5",
                headers=headers,
                timeout=10,
            )
            response.raise_for_status()

            return [
                {
                    "sha": item["sha"][:12],
                    "author": item["commit"]["author"]["name"],
                    "message": item["commit"]["message"],
                    "date": item["commit"]["author"]["date"],
                }
                for item in response.json()
            ]
        except Exception as e:
            logger.error(f"GitHub fetch failed: {e}")
            return self._get_mock_commits()

    def _get_mock_commits(self) -> List[Dict]:
        return [
            {
                "sha": "a1b2c3d4e5f6",
                "author": "dev-engineer",
                "message": "feat: Update database connection pool size from 10 to 100",
                "date": "2026-03-07T09:30:00Z",
            },
            {
                "sha": "j9k8l7m6n5o4",
                "author": "dev-engineer",
                "message": "fix: Bump memory-hungry dependency to latest",
                "date": "2026-03-07T08:00:00Z",
            },
        ]
