import requests
import os
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)

class GithubHistoryAggregator:
    def __init__(self, use_mock: bool = False):
        self.use_mock = use_mock
        self.token = os.environ.get("GITHUB_TOKEN")
        
    def get_recent_commits(self, owner: str, repo: str) -> List[Dict]:
        """
        Fetches the latest commits from the repository.
        """
        if self.use_mock or not self.token:
            return self._get_mock_commits()
            
        try:
            headers = {
                "Authorization": f"token {self.token}",
                "Accept": "application/vnd.github.v3+json"
            }
            response = requests.get(f"https://api.github.com/repos/{owner}/{repo}/commits?per_page=5", headers=headers)
            response.raise_for_status()
            
            commits = []
            for item in response.json():
                commits.append({
                    "sha": item["sha"],
                    "author": item["commit"]["author"]["name"],
                    "message": item["commit"]["message"],
                    "date": item["commit"]["author"]["date"]
                })
            return commits
        except Exception as e:
            logger.error(f"Failed to fetch GitHub commits: {e}")
            return [{"error": str(e)}]

    def _get_mock_commits(self) -> List[Dict]:
        return [
            {
                "sha": "a1b2c3d4e5f6g7h8",
                "author": "dev-engineer",
                "message": "feat: Update database connection pool size from 10 to 100",
                "date": "2026-03-05T19:30:00Z"
            },
            {
                "sha": "j9k8l7m6n5o4p3q2",
                "author": "dev-engineer",
                "message": "fix: Dependency bump",
                "date": "2026-03-05T10:00:00Z"
            }
        ]
