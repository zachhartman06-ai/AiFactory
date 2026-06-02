"""
LEORIO PARADINIGHT — Volume Generator
======================================
HxH Character: Leorio (loud, hard-working, practical, never stops grinding)

What Leorio does:
  1. Pulls the top validated niche from Kurapika's pain_points.json (if available)
     OR falls back to his own evergreen niche list
  2. Generates 3-5 micro-products per run — checklists, cheat sheets,
     prompt packs, micro-templates, one-page reference guides
  3. Keeps each product under 2000 words — hyper-focused, no padding
  4. Prices everything at $3.99 or $4.99 flat
  5. Writes all products to outputs/products.json with "posted": false
     so Bisky can loop through and list them all in one session

Leorio runs separately from Killua (factory.py).
Suggested cron: 3x per week (Mon/Wed/Fri) at 10am

Usage:
    python3 leorio.py

Outputs:
    outputs/products.json  — appends new micro-products (same schema as factory.py)
    LEORIO_BATCH.md        — copy-paste ready summary of all products from this run
"""

import anthropic
import json
import os
import time
from datetime import datetime
from pathlib import Path

from pdf_agent import generate_pdf


# ─────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────

# Leorio's own evergreen niche list — no demand threshold needed
# These are timeless problems that always sell
EVERGREEN_NICHES = [
    "Adults who can't stick to a morning routine no matter how many times they try",
    "Freelancers who struggle to price their services without undercharging",
    "People who want to start journaling but don't know what to write",
    "Job seekers writing cover letters who don't know how to stand out",
    "New remote workers who can't separate work from home life",
    "People trying to build an emergency fund on a tight budget",
    "Anyone learning to cook simple healthy meals for one person",
    "Students who highlight everything and still can't retain information",
    "People who want to read more books but never finish what they start",
    "Anyone trying to declutter their home without feeling overwhelmed",
    "People who want to start meditating but find it too abstract",
    "Freelancers managing multiple clients who lose track of deadlines",
    "Anyone trying to build a habit and breaking it within two weeks",
    "People who want to negotiate a raise but don't know how to start",
    "New pet owners who don't know what they actually need to buy",
    "Anyone trying to meal prep for the week without getting bored",
    "People who want to improve their posture from sitting all day",
    "Anyone trying to quit caffeine or reduce their coffee intake",
    "People who want to start investing but are afraid of losing money",
    "New parents trying to build a sleep schedule for their baby",
]

# Micro-product formats Leorio specializes in
MICRO_FORMATS = [
    "checklist",
    "cheat sheet",
    "prompt pack",
    "micro-template pack",
    "one-page reference guide",
    "swipe file",
    "action plan",
    "script template",
]

# Pricing — always flat, always charm pricing
PRICES = ["$3.99", "$4.99"]

# Output files
OUTPUT_DIR = Path("outputs")
OUTPUT_FILE = OUTPUT_DIR / "products.json"
BATCH_FILE = Path("LEORIO_BATCH.md")
PAIN_POINTS_FILE = OUTPUT_DIR / "pain_points.json"

# How many micro-products to generate per run
PRODUCTS_PER_RUN = 2


# ─────────────────────────────────────────
# NICHE SELECTION
# ─────────────────────────────────────────

def get_niche():
    """
    Kurapika-first niche selection.
    Uses the highest-scored unprocessed pain point from pain_points.json.
    Falls back to Leorio's own evergreen list if nothing available.
    """
    if PAIN_POINTS_FILE.exists():
        try:
            with open(PAIN_POINTS_FILE) as f:
                data = json.load(f)

            pain_points = data.get("painPoints", [])
            # Find highest scored point not yet consumed by Leorio
            for point in sorted(pain_points, key=lambda x: x.get("score", 0), reverse=True):
                if not point.get("leorioConsumed", False):
                    niche = point.get("nicheStatement")
                    if niche:
                        # Mark as consumed
                        point["leorioConsumed"] = True
                        point["leorioConsumedAt"] = datetime.now().isoformat()
                        with open(PAIN_POINTS_FILE, "w") as f:
                            json.dump(data, f, indent=2)
                        print(f"  [KURAPIKA] Using validated pain point (score: {point.get('score', '?')}/10)")
                        print(f"  Niche: {niche}")
                        return niche, "kurapika"
        except Exception as e:
            print(f"  [WARNING] Could not read pain_points.json: {e}")

    # Fallback: evergreen rotation
    day_of_year = datetime.now().timetuple().tm_yday
    niche = EVERGREEN_NICHES[day_of_year % len(EVERGREEN_NICHES)]
    print(f"  [EVERGREEN] Using rotation niche")
    print(f"  Niche: {niche}")
    return niche, "evergreen"


# ─────────────────────────────────────────
# AGENT FUNCTIONS
# ─────────────────────────────────────────

def call_claude(client, system_prompt, user_prompt, expect_json=False):
    """Call Claude and return text or parsed JSON."""
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}]
    )
    text = message.content[0].text.strip()

    if expect_json:
        # Strip markdown fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            # Find closing fence
            end = len(lines) - 1
            while end > 0 and lines[end].strip() in ("```", ""):
                end -= 1
            text = "\n".join(lines[1:end+1])

        # Try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try extracting outermost JSON object
        import re
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        print(f"    [WARNING] JSON parse failed. Raw response (first 300 chars):")
        print(f"    {text[:300]}")
        return {}

    return text


def generate_product_concepts(client, niche):
    """
    Generate 4-5 distinct micro-product concepts for a niche.
    Returns a list of concept dicts.
    """
    print(f"\n[LEORIO] Generating {PRODUCTS_PER_RUN} micro-product concepts...")

    result = call_claude(
        client,
        system_prompt=(
            "You are a digital product strategist specializing in high-volume micro-products. "
            "You ONLY respond in valid JSON. No markdown, no backticks, no explanation outside the JSON."
        ),
        user_prompt=f"""Generate exactly {PRODUCTS_PER_RUN} distinct micro-product concepts for this niche:

"{niche}"

Each product must be:
- A SHORT, focused digital product (checklist, cheat sheet, prompt pack, template, reference guide, swipe file, script, action plan)
- Completable in under 2000 words
- Priced at $3.99 or $4.99
- Instantly useful — the buyer gets value in under 10 minutes of reading
- Distinct from the others — no overlap in what they solve

Return this exact JSON:
{{
  "concepts": [
    {{
      "title": "product title",
      "format": "checklist/cheat sheet/prompt pack/template pack/reference guide/swipe file/action plan/script template",
      "tagline": "one-line hook",
      "price": "$3.99 or $4.99",
      "whatItSolves": "the specific micro-problem this fixes",
      "keyPoints": ["point 1", "point 2", "point 3", "point 4", "point 5"],
      "targetBuyer": "exact person who buys this"
    }}
  ]
}}""",
        expect_json=True
    )

    concepts = result.get("concepts", [])
    print(f"    Generated {len(concepts)} concepts")
    return concepts


def generate_product_content(client, concept, niche):
    """
    Write the full content for a single micro-product.
    Returns the content as a string.
    """
    fmt = concept.get('format', '').lower()

    # Format-specific depth requirements injected into the prompt
    depth_rules = {
        "checklist":        "15-25 checkbox items minimum. Each item must be a specific, concrete action — not a vague category. Include a brief (1-sentence) explanation under any item that needs context. Group items into 3-5 logical sections with ## headers.",
        "cheat sheet":      "8-12 dense sections minimum. Each section needs a ## header and 4-8 bullet points of specific, immediately usable information. Include exact numbers, formulas, commands, or thresholds wherever possible — not just descriptions.",
        "prompt pack":      "10-15 ready-to-use prompts minimum. Each prompt must be a complete, copy-paste-ready prompt written in the second person, specific enough to produce a useful output without editing. Number each prompt. Group by use case with ## headers.",
        "micro-template pack": "8-12 distinct template sections minimum. Each template must be fully written out — actual text with [FILL IN] placeholders, not a description of what to write. Include usage instructions for each.",
        "template pack":    "8-12 distinct template sections minimum. Each template must be fully written out — actual text with [FILL IN] placeholders, not a description of what to write. Include usage instructions for each.",
        "template":         "8-12 distinct template sections minimum. Each template must be fully written out — actual text with [FILL IN] placeholders, not a description of what to write. Include usage instructions for each.",
        "action plan":      "Full day-by-day or week-by-week breakdown minimum 20-30 individual action steps. Each step must name exactly what to do, how long it takes, and what done looks like. Use numbered steps under ## Week/Phase headers.",
        "reference guide":  "10-15 detailed sections minimum. Each section needs a ## header, a 2-3 sentence explanation of why it matters, and 5-8 specific bullet points with concrete details, examples, or numbers. No vague generalities.",
        "swipe file":       "12-20 ready-to-use examples minimum. Each swipe must be complete and copy-paste ready. Group by situation or type with ## headers. Include a one-line note on when to use each.",
        "one-page reference guide": "10-15 sections minimum. Dense and scannable. Every section needs a ## header and 4-6 tight bullet points with specific, usable information — numbers, steps, examples.",
    }
    depth = depth_rules.get(fmt, "Minimum 15 distinct, specific, actionable items or sections. Each must give the reader something concrete and usable — not a description of what they should figure out themselves.")

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=(
            "You are a professional digital product writer with a decade of experience "
            "creating high-converting, genuinely useful products that buyers recommend to others. "
            "Your rule: the buyer paid real money for this. They deserve a product that saves them "
            "hours, not a skeleton they have to fill in themselves. Write everything out fully. "
            "No filler. No padding. No generic advice that applies to everyone and therefore helps no one. "
            "Every sentence must earn its place by giving the reader something specific and actionable."
        ),
        messages=[{
            "role": "user",
            "content": f"""Write the COMPLETE, FULL content for this digital product. Do not write an outline or a plan — write the actual product a customer will read and use.

PRODUCT DETAILS:
Title: {concept.get('title')}
Format: {concept.get('format')}
Niche: {niche}
Target buyer: {concept.get('targetBuyer')}
What it solves: {concept.get('whatItSolves')}
Key areas to cover: {json.dumps(concept.get('keyPoints', []))}

FORMAT REQUIREMENTS FOR THIS PRODUCT TYPE ({fmt.upper()}):
{depth}

UNIVERSAL REQUIREMENTS (non-negotiable):
- Minimum 800 words of actual content — not counting headers or whitespace
- Every piece of advice must be specific to the exact niche above, not generic life advice
- Use concrete numbers, timeframes, and examples — not vague guidance like "be consistent"
- Write for someone doing this TODAY, not someone planning to start someday
- Use proper markdown: # for the title, ## for main sections, ### for sub-sections, - [ ] for checklist items, numbered lists for steps, - for bullets
- Separate sections with ---
- The buyer paid money for this. They deserve genuinely useful content, not a skeleton.

Begin writing the product now. Write the complete product from title to last item:"""
        }]
    )
    return message.content[0].text.strip()


def generate_listing_copy(client, concept, niche):
    """
    Write Gumroad/Payhip listing copy for a micro-product.
    Returns a dict with title, description, bullets, tags.
    """
    result = call_claude(
        client,
        system_prompt=(
            "You are a conversion copywriter for digital products. "
            "You ONLY respond in valid JSON. No markdown, no backticks."
        ),
        user_prompt=f"""Write a complete product listing for:

Title: {concept.get('title')}
Format: {concept.get('format')}
Price: {concept.get('price')}
Target buyer: {concept.get('targetBuyer')}
What it solves: {concept.get('whatItSolves')}
Niche: {niche}

Return this exact JSON:
{{
  "title": "final product title",
  "tagline": "one-line hook (under 100 chars)",
  "description": "2-3 paragraph sales description — problem-aware, benefit-focused, ends with CTA",
  "bulletPoints": ["benefit 1", "benefit 2", "benefit 3", "benefit 4"],
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"],
  "callToAction": "CTA line"
}}""",
        expect_json=True
    )
    return result


# ─────────────────────────────────────────
# BATCH SUMMARY GENERATOR
# ─────────────────────────────────────────

def generate_batch_summary(products, niche, niche_source):
    """Generate a clean markdown summary of all products from this run."""
    date = datetime.now().strftime("%B %d, %Y")

    md = f"""# LEORIO BATCH — {date}
Niche: {niche}
Source: {niche_source}
Products generated: {len(products)}

---

## PRODUCTS THIS RUN

"""
    for i, p in enumerate(products, 1):
        listing = p.get("listing", {})
        concept = p.get("concept", {})
        md += f"""### {i}. {listing.get('title', concept.get('title', 'Untitled'))}
- **Price:** {p.get('price', '')}
- **Format:** {concept.get('format', '')}
- **Tagline:** {listing.get('tagline', '')}
- **Solves:** {concept.get('whatItSolves', '')}
- **PDF:** {p.get('pdf_path') or '❌ not generated'}
- **Status:** ⏳ Pending Bisky listing

**Description:**
{listing.get('description', '')}

**Bullet Points:**
"""
        for b in listing.get('bulletPoints', []):
            md += f"- {b}\n"

        md += f"""
**Tags:** {', '.join(listing.get('tags', []))}

---

"""

    md += f"""## NEXT STEPS
1. Run Bisky to list all unposted products: `python3 lister.py --all`
2. Review LEORIO_BATCH.md for any products to skip
3. Check outputs/products.json — all products have "posted": false until Bisky runs

Generated {date} by Leorio
"""
    return md


# ─────────────────────────────────────────
# MAIN LEORIO RUN
# ─────────────────────────────────────────

def run_leorio():
    print("=" * 50)
    print("  LEORIO — Volume Generator")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY environment variable not set")

    client = anthropic.Anthropic(api_key=api_key)

    # ── Step 1: Get niche ──
    print("\n[LEORIO] Selecting niche...")
    niche, niche_source = get_niche()

    # ── Step 2: Generate product concepts ──
    concepts = generate_product_concepts(client, niche)
    if not concepts:
        print("\n[LEORIO] No concepts generated. Exiting.")
        return

    # ── Step 3: Generate content + listing for each concept ──
    products = []
    for i, concept in enumerate(concepts[:PRODUCTS_PER_RUN], 1):
        print(f"\n[LEORIO] Building product {i}/{min(len(concepts), PRODUCTS_PER_RUN)}: {concept.get('title', 'Untitled')}")

        print(f"    Writing content...")
        content = generate_product_content(client, concept, niche)
        print(f"    Content: {len(content)} characters")

        print(f"    Writing listing copy...")
        listing = generate_listing_copy(client, concept, niche)
        print(f"    Listing: {listing.get('title', 'Untitled')}")

        product = {
            "id": f"LEORIO_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{i}",
            "createdAt": datetime.now().isoformat(),
            "agent": "leorio",
            "niche": niche,
            "nicheSource": niche_source,
            "concept": concept,
            "content": content,
            "listing": listing,
            "title": listing.get("title") or concept.get("title", "Untitled"),
            "price": concept.get("price", "$3.99"),
            "tagline": listing.get("tagline", ""),
            "tags": listing.get("tags", []),
            "posted": False,      # Bisky sets this to True after listing
            "postedAt": None,
            "platform": None,
        }

        # Generate PDF immediately after building the product
        print(f"    Generating PDF...")
        pdf_path = generate_pdf(product)
        if pdf_path:
            product["pdf_path"] = str(pdf_path)
        else:
            product["pdf_path"] = None

        products.append(product)

        # 30-second pause between products to stay under the
        # 30k input tokens/minute rate limit
        if i < min(len(concepts), PRODUCTS_PER_RUN):
            print(f"    Pausing 30s before next product...")
            time.sleep(30)

    # ── Step 4: Save to products.json ──
    OUTPUT_DIR.mkdir(exist_ok=True)
    existing = []
    if OUTPUT_FILE.exists():
        try:
            with open(OUTPUT_FILE) as f:
                existing = json.load(f)
        except Exception:
            existing = []

    # Prepend new products
    for p in reversed(products):
        existing.insert(0, p)

    with open(OUTPUT_FILE, "w") as f:
        json.dump(existing, f, indent=2)

    print(f"\n    Saved {len(products)} products to {OUTPUT_FILE}")

    # ── Step 5: Generate batch summary ──
    batch_md = generate_batch_summary(products, niche, niche_source)
    with open(BATCH_FILE, "w") as f:
        f.write(batch_md)

    # ── Summary ──
    print(f"\n{'=' * 50}")
    print(f"  LEORIO RUN COMPLETE")
    print(f"  Products generated: {len(products)}")
    print(f"  Niche: {niche[:50]}...")
    print(f"  Source: {niche_source}")
    print(f"  Vault: {OUTPUT_FILE} ({len(existing)} total)")
    print(f"  Batch: {BATCH_FILE}")
    print(f"  All products marked posted: False — run Bisky to list")
    print(f"{'=' * 50}\n")

    print("PRODUCTS THIS RUN:")
    for i, p in enumerate(products, 1):
        print(f"  {i}. {p['title']} — {p['price']}")


if __name__ == "__main__":
    run_leorio()
