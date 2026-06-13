"""
tests/test_tools.py

Unit tests for the three FitFindr tools, with at least one test per
failure mode:

    search_listings  → returns [] when nothing matches (no exception)
    suggest_outfit   → handles an empty wardrobe; never raises on LLM error
    create_fit_card  → returns an error string for empty/missing outfit

The LLM-backed tools (suggest_outfit, create_fit_card) are tested with the
network call mocked out via monkeypatch, so the suite is fast, deterministic,
and free — it exercises the real branching/guard/fallback logic without
hitting the Groq API. A couple of opt-in live tests are included at the
bottom (skipped unless GROQ_API_KEY is set and RUN_LIVE_LLM=1).
"""

import os

import pytest

import tools
from tools import search_listings, suggest_outfit, create_fit_card

from utils.data_loader import get_example_wardrobe, get_empty_wardrobe


# ── search_listings ───────────────────────────────────────────────────────────

def test_search_returns_results():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0


def test_search_empty_results():
    # Failure mode: nothing matches → empty list, not an exception.
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []


def test_search_price_filter():
    results = search_listings("jacket", size=None, max_price=10)
    assert all(item["price"] <= 10 for item in results)


def test_search_size_filter_case_insensitive():
    # "m" should match sizes like "M", "S/M", "M/L" regardless of case.
    results = search_listings("vintage", size="m", max_price=None)
    assert all("m" in item["size"].lower() for item in results)


def test_search_results_sorted_by_relevance():
    # Scores are non-increasing: best match first.
    results = search_listings("vintage denim jeans", size=None, max_price=None)
    assert len(results) > 1  # need at least two to compare ordering
    keywords = {"vintage", "denim", "jeans"}

    def score(item):
        hay = " ".join(
            [item["title"], item["description"], " ".join(item["style_tags"])]
        ).lower()
        return len(keywords & set(hay.split()))

    scores = [score(item) for item in results]
    assert scores == sorted(scores, reverse=True)


# ── suggest_outfit ──────────────────────────────────────────────────────────

@pytest.fixture
def sample_item():
    return {
        "title": "Vintage Levi's 501 Jeans",
        "category": "bottoms",
        "colors": ["blue"],
        "style_tags": ["vintage", "denim"],
        "price": 38.0,
        "platform": "depop",
    }


def test_suggest_outfit_empty_wardrobe(monkeypatch, sample_item):
    # Failure mode: empty wardrobe must NOT crash — it should fall back to
    # general styling advice. We capture the prompt to confirm the
    # general-advice branch was taken.
    captured = {}

    def fake_chat(prompt, temperature=0.7):
        captured["prompt"] = prompt
        return "General styling advice goes here."

    monkeypatch.setattr(tools, "_chat", fake_chat)

    result = suggest_outfit(sample_item, get_empty_wardrobe())
    assert isinstance(result, str)
    assert result.strip()  # non-empty
    # General-advice branch doesn't list specific owned pieces.
    assert "what they already own" not in captured["prompt"].lower()


def test_suggest_outfit_none_wardrobe(monkeypatch, sample_item):
    # Defensive: a None wardrobe should be treated like an empty one, not crash.
    monkeypatch.setattr(tools, "_chat", lambda p, temperature=0.7: "advice")
    result = suggest_outfit(sample_item, None)
    assert isinstance(result, str) and result.strip()


def test_suggest_outfit_populated_wardrobe(monkeypatch, sample_item):
    captured = {}

    def fake_chat(prompt, temperature=0.7):
        captured["prompt"] = prompt
        return "Outfit 1: ..."

    monkeypatch.setattr(tools, "_chat", fake_chat)

    result = suggest_outfit(sample_item, get_example_wardrobe())
    assert isinstance(result, str) and result.strip()
    # Populated branch lists the owned pieces in the prompt.
    assert "what they already own" in captured["prompt"].lower()


def test_suggest_outfit_llm_error_does_not_raise(monkeypatch, sample_item):
    # Failure mode: LLM call fails → return a fallback string, never raise.
    def boom(prompt, temperature=0.7):
        raise RuntimeError("API down")

    monkeypatch.setattr(tools, "_chat", boom)

    result = suggest_outfit(sample_item, get_example_wardrobe())
    assert isinstance(result, str) and result.strip()


# ── create_fit_card ───────────────────────────────────────────────────────────

def test_create_fit_card_empty_outfit(sample_item):
    # Failure mode: empty outfit → descriptive error string, no exception.
    result = create_fit_card("", sample_item)
    assert isinstance(result, str)
    assert result.strip()


def test_create_fit_card_whitespace_outfit(sample_item):
    # Whitespace-only counts as empty.
    result = create_fit_card("   \n  ", sample_item)
    assert isinstance(result, str) and result.strip()


def test_create_fit_card_does_not_call_llm_when_empty(monkeypatch, sample_item):
    # The empty-outfit guard should short-circuit before the LLM call.
    def boom(prompt, temperature=0.7):
        raise AssertionError("_chat should not be called for an empty outfit")

    monkeypatch.setattr(tools, "_chat", boom)
    result = create_fit_card("", sample_item)
    assert isinstance(result, str) and result.strip()


def test_create_fit_card_llm_error_does_not_raise(monkeypatch, sample_item):
    # Failure mode: LLM call fails → fallback caption string, never raise.
    monkeypatch.setattr(
        tools, "_chat", lambda p, temperature=0.95: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    result = create_fit_card("white tee + chunky sneakers", sample_item)
    assert isinstance(result, str) and result.strip()


def test_create_fit_card_returns_caption(monkeypatch, sample_item):
    monkeypatch.setattr(
        tools, "_chat", lambda p, temperature=0.95: "Thrifted gold ✨ #ootd"
    )
    result = create_fit_card("white tee + chunky sneakers", sample_item)
    assert result == "Thrifted gold ✨ #ootd"


# ── opt-in live LLM tests (skipped by default) ─────────────────────────────────

_RUN_LIVE = os.environ.get("RUN_LIVE_LLM") == "1" and os.environ.get("GROQ_API_KEY")


@pytest.mark.skipif(not _RUN_LIVE, reason="set RUN_LIVE_LLM=1 and GROQ_API_KEY to run")
def test_create_fit_card_outputs_vary_live(sample_item):
    outfit = "Levi 501s with a cropped white tee and chunky black sneakers."
    outs = {create_fit_card(outfit, sample_item) for _ in range(3)}
    assert len(outs) > 1  # high temperature → varied captions
