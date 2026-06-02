"""
KURAPIKA — Problem Solver / Pain Point Scout
=============================================
HxH Character: Kurapika (methodical, evidence-driven, laser-focused on real suffering)

What Kurapika does:
  1. Scans Reddit public JSON endpoints for recurring pain points
  2. Hits Google Autocomplete API for what people are searching
  3. Scores and clusters pain points by mention frequency
  4. Filters out saturated niches (too much existing product supply)
  5. Outputs ranked pain_points.json
  6. Writes the top validated niche to niche_queue.json for Killua to consume

No Reddit API key needed — uses public .json endpoints with a proper User-Agent.
No Google API key needed — uses the free autocomplete endpoint.

Usage:
    python3 kurapika.py

    Or add to cron (runs before factory.py):
    30 8 * * * python3 /home/lip/AiFactory/kurapika.py

Outputs:
    outputs/pain_points.json   — full ranked list of validated pain points
    niche_queue.json           — top niche ready for Killua to consume
"""

import anthropic
import json
import os
import re
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime
from pathlib import Path


# ─────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────

# Subreddits to scan for pain points
# Mix of high-traffic general subs + niche-specific ones
TARGET_SUBREDDITS = [
    "nosurf",
    "personalfinance",
    "Frugal",
    "digitalnomad",
    "WorkOnline",
    "Entrepreneur",
    "smallbusiness",
    "sidehustle",
    "passive_income",
    "learnprogramming",
    "ITCareerQuestions",
    "cybersecurity",
    "homeoffice",
    "productivity",
    "getdisciplined",
    "Parenting",
    "beyondthebump",
    "Fitness",
    "loseit",
    "LifeAdvice",
    "selfimprovement",
]

# Google Autocomplete seed queries — Kurapika asks these to surface what people search
AUTOCOMPLETE_SEEDS = [
    "how to stop",
    "how to deal with",
    "why can't I",
    "I keep struggling with",
    "best way to",
    "I hate that I",
    "how do I fix",
    "I wish there was",
    "template for",
    "checklist for",
    "guide for beginners",
    "I can't afford",
    "I don't know how to",
]

# Pain point scoring thresholds
MIN_SCORE_TO_QUALIFY = 3       # Minimum weighted score to include in output
MIN_MENTIONS_TO_QUALIFY = 5    # Minimum raw Reddit post hits to qualify

# Output files
OUTPUT_DIR = Path("outputs")
PAIN_POINTS_FILE = OUTPUT_DIR / "pain_points.json"
NICHE_QUEUE_FILE = Path("niche_queue.json")

# User-Agent for all HTTP requests (Reddit requires a descriptive UA)
USER_AGENT = "AiFactory/1.0 (kurapika pain-point scanner; contact: agent-factory-bot)"


# ─────────────────────────────────────────
# HTTP HELPER
# ─────────────────────────────────────────

def extract_json_from_response(raw: str, context: str = "") -> dict:
    """
    Robustly extract a JSON object from a Claude response.

    Handles all real-world response shapes:
      - Bare JSON                          {"key": ...}
      - Fenced with lang tag + newline     ```json\\n{...}\\n```\\n
      - Fenced without lang tag            ```\\n{...}\\n```
      - Fenced, no trailing newline        ```json\\n{...}\\n```
      - Preamble text before the fence     "Here is...\\n```json\\n{...}\\n```"
      - Inline JSON after explanatory text "Analysis: {...}"

    Raises json.JSONDecodeError on genuine parse failure after all
    strategies are exhausted, so the caller can decide how to recover.
    Logs the raw response on failure to make debugging easy.
    """
    # 1. Try direct parse first (bare JSON, most efficient)
    stripped = raw.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    # 2. Extract content from fenced block (handles trailing newlines, lang tags)
    fence_match = re.search(r"```(?:json|JSON)?\s*\n(.*?)\n?```", stripped, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 3. Find the outermost {...} block (handles preamble / postamble text)
    brace_match = re.search(r"\{.*\}", stripped, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    # All strategies failed — log and raise so the caller sees exactly what Claude sent
    label = f" [{context}]" if context else ""
    print(f"\n    [JSON PARSE FAILED{label}] Raw Claude response ({len(raw)} chars):")
    for i, line in enumerate(raw.splitlines()[:20], 1):
        print(f"      {i:02d}| {line}")
    if len(raw.splitlines()) > 20:
        print(f"      ... ({len(raw.splitlines()) - 20} more lines)")
    raise json.JSONDecodeError(
        f"Could not parse JSON from Claude response{label}", raw, 0
    )


def fetch_url(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        if e.code == 429:
            print(f"    [rate limited] {url[:60]}... waiting 5s")
            time.sleep(5)
        else:
            print(f"    [HTTP {e.code}] {url[:60]}...")
        return None
    except Exception as e:
        print(f"    [fetch error] {url[:60]}... {e}")
        return None


# ─────────────────────────────────────────
# REDDIT SCANNER
# ─────────────────────────────────────────

def scan_reddit_subreddit(subreddit, limit=25):
    """
    Fetch top posts from a subreddit using the public JSON endpoint.
    Returns a list of (title, score, num_comments) tuples.
    """
    url = f"https://www.reddit.com/r/{subreddit}/top.json?t=month&limit={limit}"
    data = fetch_url(url)
    if not data:
        return []

    posts = []
    try:
        children = data["data"]["children"]
        for child in children:
            post = child["data"]
            title = post.get("title", "")
            score = post.get("score", 0)
            comments = post.get("num_comments", 0)
            posts.append((title, score, comments))
    except (KeyError, TypeError):
        pass

    time.sleep(1.2)  # Polite delay between Reddit requests
    return posts


def search_reddit(query, limit=10):
    """
    Search Reddit for a query using the public search JSON endpoint.
    Returns a list of (title, score, num_comments) tuples.
    """
    encoded = urllib.parse.quote(query)
    url = f"https://www.reddit.com/search.json?q={encoded}&sort=relevance&t=year&limit={limit}"
    data = fetch_url(url)
    if not data:
        return []

    posts = []
    try:
        children = data["data"]["children"]
        for child in children:
            post = child["data"]
            title = post.get("title", "")
            score = post.get("score", 0)
            comments = post.get("num_comments", 0)
            posts.append((title, score, comments))
    except (KeyError, TypeError):
        pass

    time.sleep(1.2)
    return posts


# ─────────────────────────────────────────
# GOOGLE AUTOCOMPLETE SCANNER
# ─────────────────────────────────────────

def get_autocomplete(seed):
    """
    Hit the Google Autocomplete API for a seed query.
    Returns a list of autocomplete suggestion strings.
    """
    encoded = urllib.parse.quote(seed)
    url = f"https://suggestqueries.google.com/complete/search?client=firefox&q={encoded}"
    data = fetch_url(url)
    if not data or not isinstance(data, list) or len(data) < 2:
        return []

    suggestions = data[1] if isinstance(data[1], list) else []
    time.sleep(0.5)
    return suggestions


# ─────────────────────────────────────────
# PAIN POINT EXTRACTOR (Claude-powered)
# ─────────────────────────────────────────

def extract_pain_points(client, raw_titles, autocomplete_suggestions):
    """
    Feed raw Reddit titles + Google autocomplete suggestions to Claude.
    Claude extracts, clusters, and scores genuine pain points.
    Returns a list of pain point dicts.
    """
    print("\n[KURAPIKA] Sending data to Claude for pain point extraction...")

    titles_text = "\n".join(f"- {t}" for t in raw_titles[:60])
    autocomplete_text = "\n".join(f"- {s}" for s in autocomplete_suggestions[:40])

    try:
        result_raw = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=(
                "You are a market research analyst specializing in finding validated consumer pain points. "
                "You ONLY respond in valid JSON. No markdown, no backticks, no explanation outside the JSON."
            ),
            messages=[{
                "role": "user",
                "content": f"""Analyze these Reddit post titles and Google search suggestions to identify the strongest pain points.

REDDIT TITLES (real posts, sorted by engagement):
{titles_text}

GOOGLE AUTOCOMPLETE (what people actually search):
{autocomplete_text}

Extract the top 10 most promising pain points. For each one:
- It must represent a REAL, recurring problem that affects many people
- It must be solvable with a digital product (ebook, guide, template, checklist, course)
- It must NOT be dominated by huge existing solutions (avoid: lose weight, learn coding, manage money generically)
- It SHOULD be specific enough to build a focused product around

Return this exact JSON structure:
{{
  "painPoints": [
    {{
      "problem": "clear 1-sentence description of the pain point",
      "nicheStatement": "exact phrasing to use as a factory niche input (e.g. 'Remote workers who struggle to focus during back-to-back Zoom calls')",
      "evidenceCount": 12,
      "severity": "high/medium/low",
      "productFormat": "ebook/guide/template pack/checklist/prompt pack",
      "suggestedPrice": "$9.99",
      "competitionLevel": "low/medium/high",
      "score": 8,
      "reasoning": "why this is a strong opportunity"
    }}
  ]
}}

Replace evidenceCount with an integer estimate of how many times this theme appeared in the data.
Replace score with an integer from 1-10 (higher = better opportunity).
Score higher for: high severity + low competition + specific niche + clear digital product fit.
Score lower for: generic problems, high competition, problems needing human services."""
            }]
        ).content[0].text.strip()

        parsed = extract_json_from_response(result_raw, context="extract_pain_points")
        pain_points = parsed.get("painPoints", [])
        if not isinstance(pain_points, list):
            print("    [WARNING] 'painPoints' is not a list in Claude response")
            return []
        return pain_points
    except anthropic.RateLimitError as e:
        print(f"    [ERROR] Rate limit hit during pain point extraction: {e}")
        print("    Tip: reduce input size or wait a minute before retrying.")
        return []
    except json.JSONDecodeError:
        # extract_json_from_response already printed the raw response
        return []


# ─────────────────────────────────────────
# SATURATION CHECKER (Claude-powered)
# ─────────────────────────────────────────

def filter_saturated(client, pain_points):
    """
    Ask Claude to flag which pain points already have saturated product supply.
    Returns filtered list with only the non-saturated ones.
    """
    if not pain_points:
        return []

    print("\n[KURAPIKA] Checking for market saturation...")

    points_text = json.dumps([{
        "problem": p.get("problem"),
        "nicheStatement": p.get("nicheStatement"),
        "competitionLevel": p.get("competitionLevel")
    } for p in pain_points], indent=2)

    result_raw = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        system=(
            "You are a market saturation analyst for digital products. "
            "You ONLY respond in valid JSON. No markdown, no backticks."
        ),
        messages=[{
            "role": "user",
            "content": f"""Review these pain points and flag which ones are OVERSATURATED with existing digital products on Gumroad, Etsy, Amazon KDP, and Udemy.

Pain points to review:
{points_text}

A pain point is OVERSATURATED if:
- There are already dozens of high-quality, well-reviewed products solving it exactly
- Big brands or publishers dominate the space
- Price compression has driven typical products below $3

Return this exact JSON:
{{
  "keep": ["nicheStatement1", "nicheStatement2"],
  "skip": ["nicheStatement3"],
  "reasoning": "brief explanation of any skips"
}}

When in doubt, KEEP it — a slightly competitive niche is fine. Only skip truly dominated ones."""
        }]
    ).content[0].text.strip()

    try:
        parsed = extract_json_from_response(result_raw, context="filter_saturated")
        keep_set = set(parsed.get("keep", []))
        skipped = parsed.get("skip", [])
        if skipped:
            print(f"    Filtered out {len(skipped)} saturated niche(s): {skipped}")
        return [p for p in pain_points if p.get("nicheStatement") in keep_set]
    except json.JSONDecodeError:
        print("    [WARNING] Saturation check parse failed — keeping all")
        return pain_points


# ─────────────────────────────────────────
# MAIN KURAPIKA RUN
# ─────────────────────────────────────────

def run_kurapika():
    print("=" * 50)
    print("  KURAPIKA — Pain Point Scanner")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY environment variable not set")

    client = anthropic.Anthropic(api_key=api_key)

    # ── Step 1: Scan Reddit subreddits ──
    print(f"\n[KURAPIKA] Scanning {len(TARGET_SUBREDDITS)} subreddits...")
    all_titles = []
    for i, sub in enumerate(TARGET_SUBREDDITS):
        print(f"    [{i+1}/{len(TARGET_SUBREDDITS)}] r/{sub}")
        posts = scan_reddit_subreddit(sub, limit=20)
        titles = [t for t, s, c in posts if s > 5]  # Filter low-engagement posts
        all_titles.extend(titles)

    print(f"    Collected {len(all_titles)} Reddit post titles")

    # ── Step 2: Google Autocomplete ──
    print(f"\n[KURAPIKA] Running {len(AUTOCOMPLETE_SEEDS)} Google autocomplete queries...")
    all_suggestions = []
    for seed in AUTOCOMPLETE_SEEDS:
        suggestions = get_autocomplete(seed)
        all_suggestions.extend(suggestions)
        print(f"    '{seed}' → {len(suggestions)} suggestions")

    print(f"    Collected {len(all_suggestions)} autocomplete suggestions")

    # ── Step 3: Extract pain points with Claude ──
    pain_points = extract_pain_points(client, all_titles, all_suggestions)
    print(f"    Extracted {len(pain_points)} pain points")

    if not pain_points:
        print("\n[KURAPIKA] No pain points extracted. Exiting.")
        return

    # ── Step 4: Filter saturated niches ──
    qualified = filter_saturated(client, pain_points)
    print(f"    {len(qualified)} pain points passed saturation filter")

    if not qualified:
        print("\n[KURAPIKA] All niches filtered as saturated. Using top unfiltered.")
        qualified = sorted(pain_points, key=lambda x: x.get("score", 0), reverse=True)[:3]

    # ── Step 5: Sort by score ──
    qualified.sort(key=lambda x: x.get("score", 0), reverse=True)

    # ── Step 6: Save pain_points.json ──
    OUTPUT_DIR.mkdir(exist_ok=True)

    output = {
        "generatedAt": datetime.now().isoformat(),
        "totalScanned": {
            "redditTitles": len(all_titles),
            "autocompleteResults": len(all_suggestions)
        },
        "painPoints": qualified
    }

    with open(PAIN_POINTS_FILE, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n    Saved {len(qualified)} pain points to {PAIN_POINTS_FILE}")

    # ── Step 7: Write top niche to niche_queue.json ──
    top = qualified[0]
    niche_queue = {
        "generatedAt": datetime.now().isoformat(),
        "source": "kurapika",
        "niche": top.get("nicheStatement"),
        "problem": top.get("problem"),
        "score": top.get("score"),
        "productFormat": top.get("productFormat"),
        "suggestedPrice": top.get("suggestedPrice"),
        "reasoning": top.get("reasoning"),
        "consumed": False   # Killua sets this to True after using it
    }

    with open(NICHE_QUEUE_FILE, "w") as f:
        json.dump(niche_queue, f, indent=2)

    # ── Summary ──
    print(f"\n{'=' * 50}")
    print(f"  KURAPIKA RUN COMPLETE")
    print(f"  Pain points found:  {len(qualified)}")
    print(f"  Top niche:          {top.get('nicheStatement', 'N/A')}")
    print(f"  Score:              {top.get('score', 'N/A')}/10")
    print(f"  Format:             {top.get('productFormat', 'N/A')}")
    print(f"  Price:              {top.get('suggestedPrice', 'N/A')}")
    print(f"  Queued for Killua:  {NICHE_QUEUE_FILE}")
    print(f"{'=' * 50}\n")

    # Print top 3 for quick review
    print("TOP 3 PAIN POINTS:")
    for i, p in enumerate(qualified[:3], 1):
        print(f"\n  {i}. {p.get('problem', '')}")
        print(f"     Niche: {p.get('nicheStatement', '')}")
        print(f"     Score: {p.get('score', '')}/10 | Competition: {p.get('competitionLevel', '')} | Format: {p.get('productFormat', '')}")


if __name__ == "__main__":
    run_kurapika()
