"""
AGENT FACTORY — GitHub Actions Runner
======================================
Runs 4 agents in sequence, saves results to outputs/products.json
Also generates DAILY_LISTING.md — a clean copy-paste ready file for Gumroad
 
To change run frequency: edit the cron schedule in .github/workflows/factory.yml
To add/remove niches: edit the NICHE_ROTATION list below
"""
 
import anthropic
import json
import os
from datetime import datetime
from pathlib import Path
 
# ─────────────────────────────────────────
# CONFIGURATION — Edit these freely
# ─────────────────────────────────────────
 
NICHE_ROTATION = [
    "True crime enthusiasts who want to write their own cold case ebook",
    "Preppers and survivalists building 72-hour emergency kits",
    "BJJ and MMA beginners in their first year of training",
    "People learning to invest with under $1000",
    "Budget travelers doing international trips under $50/day",
    "New parents in the first 6 months with a newborn",
    "Side hustle beginners working full time jobs",
    "People trying to quit doomscrolling and reduce phone use",
    "First-generation college students navigating financial aid",
    "Remote workers building a productive home office on a budget",
    "People training for their first 5K or half marathon",
    "Anyone learning a second language as an adult",
]
 
OUTPUT_DIR = Path("outputs")
OUTPUT_FILE = OUTPUT_DIR / "products.json"
DAILY_FILE = Path("DAILY_LISTING.md")
 
# ─────────────────────────────────────────
# AGENT LOGIC
# ─────────────────────────────────────────
 
def call_claude(client, system_prompt, user_prompt, expect_json=False):
    print(f"    -> Calling Claude...")
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}]
    )
    text = message.content[0].text.strip()
 
    if expect_json:
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1])
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            print(f"    WARNING: JSON parse failed, returning raw text")
            return {"raw": text}
 
    return text
 
 
def agent_market_scout(client, niche):
    print("\n[MARKET SCOUT] Researching top products...")
    result = call_claude(
        client,
        system_prompt="You are a market research agent. Respond ONLY in valid JSON. No markdown, no backticks, no explanation outside the JSON.",
        user_prompt=f"""Research the top 5 best-selling digital products targeting: "{niche}".
 
Return this exact JSON structure:
{{
  "topProducts": [
    {{
      "title": "product name",
      "platform": "where it sells",
      "estimatedPrice": "$X",
      "whyItSells": "reason",
      "weaknesses": "gap or weakness"
    }}
  ]
}}""",
        expect_json=True
    )
    print(f"    Found {len(result.get('topProducts', []))} top products")
    return result
 
 
def agent_niche_spinner(client, niche, research_data):
    print("\n[NICHE SPINNER] Generating unique product angle...")
    result = call_claude(
        client,
        system_prompt="You are a creative product strategist. Respond ONLY in valid JSON. No markdown, no backticks.",
        user_prompt=f"""Based on this market research: {json.dumps(research_data)}
 
For the niche: "{niche}", create ONE unique digital product idea that:
- Fills a gap or weakness from existing products
- Has a specific, memorable angle
- Can be created as an ebook, guide, template pack, or checklist system
- Stands out clearly from what already exists
 
Return this exact JSON:
{{
  "productTitle": "title",
  "uniqueAngle": "what makes it different",
  "format": "ebook/guide/template pack/checklist",
  "targetBuyer": "exact person who buys this",
  "whyItStandsOut": "competitive advantage",
  "suggestedPrice": "$X"
}}""",
        expect_json=True
    )
    print(f"    Concept: {result.get('productTitle', 'Generated')}")
    return result
 
 
def agent_product_forge(client, niche, idea_data):
    print("\n[PRODUCT FORGE] Writing product content...")
    result = call_claude(
        client,
        system_prompt="You are a professional digital product writer. Create detailed, genuinely useful content.",
        user_prompt=f"""Create the full content outline and sample content for this digital product:
{json.dumps(idea_data)}
 
Niche: "{niche}"
 
Provide:
1. Full table of contents (all chapters/sections)
2. Introduction paragraph (write the actual text)
3. First full chapter/section (write actual content, 200+ words)
4. Key takeaways list
 
Make it genuinely useful and specific to the niche."""
    )
    print(f"    Content written ({len(result)} characters)")
    return result
 
 
def agent_sales_writer(client, niche, idea_data):
    print("\n[SALES WRITER] Writing Gumroad listing...")
    result = call_claude(
        client,
        system_prompt="You are a conversion-focused copywriter. Respond ONLY in valid JSON. No markdown, no backticks.",
        user_prompt=f"""Write a complete Gumroad product listing for:
Product concept: {json.dumps(idea_data)}
Target niche: "{niche}"
 
Return this exact JSON:
{{
  "title": "product title",
  "tagline": "one-line hook",
  "description": "full sales description (3-4 paragraphs)",
  "bulletPoints": ["benefit 1", "benefit 2", "benefit 3", "benefit 4", "benefit 5"],
  "price": "$X.XX",
  "tags": ["tag1", "tag2", "tag3", "tag4"],
  "callToAction": "CTA line"
}}""",
        expect_json=True
    )
    print(f"    Listing ready: {result.get('title', 'Untitled')}")
    return result
 
 
# ─────────────────────────────────────────
# DAILY LISTING GENERATOR
# ─────────────────────────────────────────
 
def generate_daily_listing(product):
    idea = product.get("idea", {})
    listing = product.get("listing", {})
    content = product.get("content", "")
    niche = product.get("niche", "")
    date = datetime.now().strftime("%B %d, %Y")
 
    bullet_points = listing.get("bulletPoints", [])
    bullets_formatted = "\n".join([f"checkmark {b}" for b in bullet_points])
 
    top_products = product.get("research", {}).get("topProducts", [])
    research_section = ""
    for i, p in enumerate(top_products, 1):
        research_section += f"""**{i}. {p.get("title", "")}** — {p.get("platform", "")} · {p.get("estimatedPrice", "")}
- Why it sells: {p.get("whyItSells", "")}
- Gap: {p.get("weaknesses", "")}
 
"""
 
    md = f"""# DAILY LISTING — {date}
Aurislumen · aurisolum.gumroad.com
 
---
 
## COPY-PASTE CHECKLIST
- [ ] Step 1 — Copy TITLE into Gumroad
- [ ] Step 2 — Copy PRICE into Gumroad
- [ ] Step 3 — Copy TAGLINE into Gumroad summary field
- [ ] Step 4 — Copy DESCRIPTION into Gumroad
- [ ] Step 5 — Copy BULLET POINTS into Gumroad under description
- [ ] Step 6 — Paste CONTENT into Google Docs, export PDF, upload to Gumroad
- [ ] Step 7 — Make cover in Canva (1280x720, dark bg, white title text)
- [ ] Step 8 — Publish
 
---
 
## PRODUCT DETAILS
 
Niche: {niche}
Format: {idea.get("format", "")}
Target Buyer: {idea.get("targetBuyer", "")}
 
---
 
## 1 — TITLE
 
{listing.get("title", idea.get("productTitle", ""))}
 
---
 
## 2 — PRICE
 
{listing.get("price", idea.get("suggestedPrice", "$9.99"))}
 
---
 
## 3 — TAGLINE
 
{listing.get("tagline", "")}
 
---
 
## 4 — DESCRIPTION
 
{listing.get("description", "")}
 
---
 
## 5 — BULLET POINTS
 
{bullets_formatted}
 
{listing.get("callToAction", "")}
 
---
 
## 6 — PRODUCT CONTENT
Paste everything below into Google Docs, then File > Download > PDF
 
{content}
 
---
 
## WHY THIS STANDS OUT
Use this for your cover image tagline or social post
 
{idea.get("whyItStandsOut", "")}
 
---
 
## MARKET RESEARCH
For your reference only
 
{research_section}
---
 
Generated {date} by Agent Factory
Next run tomorrow at 9am UTC
"""
 
    return md
 
 
# ─────────────────────────────────────────
# MAIN RUN
# ─────────────────────────────────────────
 
def run_factory():
    print("=" * 50)
    print("  AGENT FACTORY — Starting Run")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 50)
 
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY environment variable not set")
 
    client = anthropic.Anthropic(api_key=api_key)
 
    day_of_year = datetime.now().timetuple().tm_yday
    niche = NICHE_ROTATION[day_of_year % len(NICHE_ROTATION)]
    print(f"\n  Niche: {niche}\n")
 
    research = agent_market_scout(client, niche)
    idea = agent_niche_spinner(client, niche, research)
    content = agent_product_forge(client, niche, idea)
    listing = agent_sales_writer(client, niche, idea)
 
    product = {
        "id": f"PRODUCT_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "createdAt": datetime.now().isoformat(),
        "niche": niche,
        "research": research,
        "idea": idea,
        "content": content,
        "listing": listing,
        "title": listing.get("title") or idea.get("productTitle", "Unnamed Product"),
        "price": listing.get("price") or idea.get("suggestedPrice", ""),
        "tagline": listing.get("tagline", ""),
        "tags": listing.get("tags", []),
    }
 
    OUTPUT_DIR.mkdir(exist_ok=True)
    existing = []
    if OUTPUT_FILE.exists():
        try:
            with open(OUTPUT_FILE) as f:
                existing = json.load(f)
        except Exception:
            existing = []
 
    existing.insert(0, product)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(existing, f, indent=2)
 
    daily_md = generate_daily_listing(product)
    with open(DAILY_FILE, "w") as f:
        f.write(daily_md)
 
    print(f"\n{'=' * 50}")
    print(f"  RUN COMPLETE")
    print(f"  Product: {product['title']}")
    print(f"  Price:   {product['price']}")
    print(f"  Vault:   {OUTPUT_FILE} ({len(existing)} total)")
    print(f"  Daily:   {DAILY_FILE}")
    print(f"{'=' * 50}\n")
 
 
if __name__ == "__main__":
    run_factory()
 
