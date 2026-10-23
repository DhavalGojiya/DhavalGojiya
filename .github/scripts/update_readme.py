"""Refresh the generated parts of README.md.

Pull request counts and the latest merged pull requests come from the GitHub
search API, articles from the Hashnode blog's RSS feed. Each generated part sits
between marker comments, so the hand-written text around it is never touched.
"""

import html
import json
import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

USER = "DhavalGojiya"
FEED_URL = "https://dhavalgojiya.hashnode.dev/rss.xml"
README = Path(__file__).resolve().parents[2] / "README.md"
LATEST_PRS = 5
LATEST_ARTICLES = 3
# Hashnode's CDN resizes on request; one fixed crop keeps every card the same height.
COVER_PARAMS = "?w=600&h=315&fit=crop&crop=entropy&auto=compress,format&format=webp"


def fetch(url: str, headers: dict[str, str] | None = None) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER, **(headers or {})})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def merged_prs() -> list[dict]:
    """Merged PRs authored in repositories the user does not own, newest merge first."""
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token := os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    query = f"author:{USER} type:pr is:merged -user:{USER}"
    items: list[dict] = []
    page = 1
    while True:
        params = urllib.parse.urlencode({"q": query, "per_page": 100, "page": page})
        data = json.loads(fetch(f"https://api.github.com/search/issues?{params}", headers))
        # A timed-out search returns a partial page, which would shrink every count.
        if data["incomplete_results"]:
            raise SystemExit("GitHub search returned incomplete results")
        items += data["items"]
        if not data["items"] or len(items) >= data["total_count"]:
            break
        page += 1
    return sorted(items, key=lambda pr: pr["pull_request"]["merged_at"], reverse=True)


def articles() -> list[dict]:
    """Blog posts from the RSS feed, newest first."""
    channel = ET.fromstring(fetch(FEED_URL)).find("channel")
    posts = []
    for item in channel.findall("item"):
        enclosure = item.find("enclosure")
        posts.append(
            {
                "title": item.findtext("title", "").strip(),
                "url": item.findtext("link", "").strip(),
                "date": parsedate_to_datetime(item.findtext("pubDate")),
                "cover": enclosure.get("url") if enclosure is not None else None,
            }
        )
    return sorted(posts, key=lambda post: post["date"], reverse=True)


def repo_name(pr: dict) -> str:
    return pr["repository_url"].rsplit("/repos/", 1)[1]


def day(value: datetime) -> str:
    return f"{value:%b} {value.day}, {value.year}"


def markdown_text(text: str) -> str:
    # Backticks stay unescaped so `code` in a PR title still renders as code.
    return re.sub(r"([\\*_\[\]<>])", r"\\\1", text)


def pr_line(pr: dict) -> str:
    repo = repo_name(pr)
    merged = datetime.fromisoformat(pr["pull_request"]["merged_at"].replace("Z", "+00:00"))
    return (
        f"- [{markdown_text(pr['title'])}]({pr['html_url']}) "
        f"in [{markdown_text(repo)}](https://github.com/{repo}) · {day(merged)}"
    )


def article_cards(posts: list[dict]) -> str:
    cells = []
    for post in posts:
        url = html.escape(post["url"])
        cover = ""
        if post["cover"]:
            src = html.escape(post["cover"] + COVER_PARAMS)
            cover = f'<a href="{url}"><img src="{src}" alt="" width="100%" /></a><br/>\n      '
        cells.append(
            f'    <td width="{100 // len(posts)}%" valign="top">\n'
            f"      {cover}"
            f'<a href="{url}"><b>{html.escape(post["title"])}</b></a><br/>\n'
            f"      <sub>{day(post['date'])}</sub>\n"
            "    </td>"
        )
    return "<table>\n  <tr>\n" + "\n".join(cells) + "\n  </tr>\n</table>"


def replace_block(text: str, name: str, body: str) -> str:
    pattern = re.compile(rf"(<!-- {name}:start -->).*?(<!-- {name}:end -->)", re.DOTALL)
    if not pattern.search(text):
        raise SystemExit(f"README.md has no {name} block")
    return pattern.sub(lambda match: f"{match[1]}\n\n{body}\n\n{match[2]}", text)


def replace_counts(text: str, counts: dict[str, int]) -> str:
    def fill(match: re.Match) -> str:
        if match[2] not in counts:
            raise SystemExit(f"README.md asks for an unknown count: {match[2]}")
        return f"{match[1]}{counts[match[2]]}{match[3]}"

    return re.sub(r"(<!-- count:(\S+) -->).*?(<!-- /count -->)", fill, text)


def main() -> None:
    prs = merged_prs()
    posts = articles()[:LATEST_ARTICLES]
    if not posts:
        raise SystemExit(f"{FEED_URL} has no articles")
    per_repo = Counter(repo_name(pr) for pr in prs)

    text = README.read_text()
    text = replace_counts(text, {"total": len(prs), "projects": len(per_repo), **per_repo})
    text = replace_block(text, "recent-prs", "\n".join(pr_line(pr) for pr in prs[:LATEST_PRS]))
    text = replace_block(text, "articles", article_cards(posts))
    README.write_text(text)


if __name__ == "__main__":
    main()
