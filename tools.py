"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
"""

import os
import re

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()

# Default Groq chat model. Swap here to change it everywhere.
MODEL = "llama-3.3-70b-versatile"


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


def _chat(prompt: str, temperature: float = 0.7) -> str:
    """
    Send a single user prompt to the LLM and return the reply text.

    Raises on client/API errors — callers are responsible for catching these
    and returning a graceful fallback string (tools never raise).
    """
    client = _get_groq_client()
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    return response.choices[0].message.content.strip()


def _format_item(item: dict) -> str:
    """
    Render a listing dict or a wardrobe-item dict as a compact one-line
    description for use inside an LLM prompt. Tolerates missing fields.
    """
    # Listings use 'title'; wardrobe items use 'name'.
    label = item.get("title") or item.get("name") or "item"
    parts = [label]

    colors = item.get("colors")
    if colors:
        parts.append(f"colors: {', '.join(colors)}")

    tags = item.get("style_tags")
    if tags:
        parts.append(f"style: {', '.join(tags)}")

    if item.get("category"):
        parts.append(f"category: {item['category']}")
    if item.get("brand"):
        parts.append(f"brand: {item['brand']}")
    if item.get("notes"):
        parts.append(f"notes: {item['notes']}")

    return " — ".join(parts)


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match first).
        Returns an empty list if nothing matches — does NOT raise an exception.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform

    TODO:
        1. Load all listings with load_listings().
        2. Filter by max_price and size (if provided).
        3. Score each remaining listing by keyword overlap with `description`.
        4. Drop any listings with a score of 0 (no relevant matches).
        5. Sort by score, highest first, and return the listing dicts.

    Before writing code, fill in the Tool 1 section of planning.md.
    """
    listings = load_listings()

    # Tokenize the search keywords (lowercase, alphanumeric words only).
    keywords = set(re.findall(r"[a-z0-9]+", description.lower()))

    size_filter = size.lower() if size else None

    scored: list[tuple[int, dict]] = []
    for listing in listings:
        # Step 2a: price ceiling (inclusive).
        if max_price is not None and listing["price"] > max_price:
            continue

        # Step 2b: size filter (case-insensitive substring match, so
        # "M" matches "S/M" and "m" matches "Medium").
        if size_filter is not None and size_filter not in listing["size"].lower():
            continue

        # Step 3: score by keyword overlap across the listing's text fields.
        haystack = " ".join(
            [
                listing["title"],
                listing["description"],
                listing["category"],
                listing.get("brand") or "",
                " ".join(listing["style_tags"]),
                " ".join(listing["colors"]),
            ]
        ).lower()
        listing_words = set(re.findall(r"[a-z0-9]+", haystack))
        score = len(keywords & listing_words)

        # Step 4: drop listings with no keyword overlap.
        if score > 0:
            scored.append((score, listing))

    # Step 5: sort by score, highest first (stable sort preserves dataset order
    # for ties), and return just the listing dicts.
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [listing for _, listing in scored]


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handle this gracefully.

    Returns:
        A non-empty string with outfit suggestions.
        If the wardrobe is empty, offer general styling advice for the item
        rather than raising an exception or returning an empty string.

    TODO:
        1. Check whether wardrobe['items'] is empty.
        2. If empty: call the LLM with a prompt for general styling ideas
           (what kinds of items pair well, what vibe it suits, etc.).
        3. If not empty: format the wardrobe items into a prompt and ask
           the LLM to suggest specific outfit combinations using the new item
           and named pieces from the wardrobe.
        4. Return the LLM's response as a string.

    Before writing code, fill in the Tool 2 section of planning.md.
    """
    # Describe the thrifted item for the prompt (shared by both branches).
    item_desc = _format_item(new_item)

    items = (wardrobe or {}).get("items", [])

    if not items:
        # Step 2: empty wardrobe → general styling advice, no specific pieces.
        prompt = (
            "You are a thrift-fashion stylist. A shopper is considering this "
            f"second-hand find:\n\n{item_desc}\n\n"
            "They haven't told you what's already in their closet. Suggest how "
            "to style this piece in general terms: what kinds of items pair "
            "well with it, what occasions or vibe it suits, and 1–2 example "
            "outfit ideas using common wardrobe staples. Keep it friendly and "
            "concrete — about 3–5 sentences."
        )
    else:
        # Step 3: populated wardrobe → outfits using specific named pieces.
        wardrobe_lines = "\n".join(f"- {_format_item(it)}" for it in items)
        prompt = (
            "You are a thrift-fashion stylist. A shopper is considering this "
            f"second-hand find:\n\n{item_desc}\n\n"
            "Here is what they already own:\n"
            f"{wardrobe_lines}\n\n"
            "Suggest 1–2 complete outfits that pair the new find with specific "
            "pieces from their wardrobe. Refer to the wardrobe pieces by name. "
            "For each outfit, briefly explain why it works and what vibe it "
            "gives. Keep it friendly and concrete."
        )

    # Step 4: call the LLM; never raise — fall back to advice the agent can use.
    try:
        return _chat(prompt, temperature=0.7)
    except Exception as exc:  # noqa: BLE001 — tools surface errors as text
        name = new_item.get("title") or new_item.get("name") or "this piece"
        return (
            f"Couldn't reach the styling assistant ({exc}). As a starting "
            f"point, {name} is versatile — try pairing it with neutral basics "
            "and one statement piece to build a balanced look."
        )


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2–4 sentence string usable as an Instagram/TikTok caption.
        If outfit is empty or missing, return a descriptive error message
        string — do NOT raise an exception.

    The caption should:
    - Feel casual and authentic (like a real OOTD post, not a product description)
    - Mention the item name, price, and platform naturally (once each)
    - Capture the outfit vibe in specific terms
    - Sound different each time for different inputs (use higher LLM temperature)

    TODO:
        1. Guard against an empty or whitespace-only outfit string.
        2. Build a prompt that gives the LLM the item details and the outfit,
           and asks for a caption matching the style guidelines above.
        3. Call the LLM and return the response.

    Before writing code, fill in the Tool 3 section of planning.md.
    """
    # Step 1: guard against an empty/whitespace outfit — return an error
    # string, never raise (the agent decides what to do with it).
    if not outfit or not outfit.strip():
        return (
            "Can't write a caption yet — no outfit suggestion was provided. "
            "Run suggest_outfit() first, then pass its result here."
        )

    # Pull the details the caption should mention naturally (once each).
    name = new_item.get("title") or new_item.get("name") or "this thrifted find"
    price = new_item.get("price")
    price_str = f"${price:g}" if isinstance(price, (int, float)) else "a steal"
    platform = new_item.get("platform") or "secondhand"

    # Step 2: build the prompt.
    prompt = (
        "Write a short, shareable Instagram/TikTok-style OOTD caption for a "
        "thrifted find. Use this info:\n"
        f"- Item: {name}\n"
        f"- Price: {price_str}\n"
        f"- Platform: {platform}\n"
        f"- The outfit: {outfit}\n\n"
        "Guidelines:\n"
        "- 2–4 sentences, casual and authentic — like a real person posting "
        "their fit, NOT a product description.\n"
        f"- Mention the item name, the price ({price_str}), and the platform "
        f"({platform}) naturally, once each.\n"
        "- Capture the outfit's vibe in specific terms.\n"
        "- Return only the caption text (emojis/hashtags welcome), nothing else."
    )

    # Step 3: call the LLM with higher temperature so captions vary. Never
    # raise — fall back to a simple caption the agent can still use.
    try:
        return _chat(prompt, temperature=0.95)
    except Exception as exc:  # noqa: BLE001 — tools surface errors as text
        return (
            f"(Caption generator unavailable: {exc}) Thrifted {name} for "
            f"{price_str} on {platform} and styled it up — obsessed with this look. 🧵"
        )
