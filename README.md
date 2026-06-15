# FitFindr 🛍️

FitFindr is an agentic app that finds secondhand clothing listings matching a
natural-language request and styles them against the user's existing wardrobe.
The user types something like *"vintage graphic tee under $30, size M"*, and the
agent returns three things: the top matching listing, an outfit idea built from
that listing plus the user's wardrobe, and a shareable OOTD "fit card" caption.

The agent runs a fixed, ordered planning loop over three tools, passing state
between them through a single per-interaction session dict. See
[planning.md](planning.md) for the original spec and architecture diagram.

## Setup

```bash
pip install -r requirements.txt
```

Set your Groq API key in a `.env` file in the project root (get a free key at
[console.groq.com](https://console.groq.com)):

```
GROQ_API_KEY=your_key_here
```

## Running

**Web UI (Gradio):**

```bash
python app.py
```

Then open the localhost URL shown in your terminal (usually
http://127.0.0.1:7860).

**CLI smoke test (runs a happy path + a no-results path):**

```bash
python agent.py
```

## Project Layout

```
ai201-project2-fitfindr-starter/
├── agent.py                   # Planning loop: _parse_query, _new_session, run_agent
├── tools.py                   # The three tools + Groq client helpers
├── app.py                     # Gradio UI (handle_query → run_agent)
├── data/
│   ├── listings.json          # 40 mock secondhand listings
│   └── wardrobe_schema.json   # Wardrobe format + example/empty wardrobes
├── utils/data_loader.py       # load_listings, get_example_wardrobe, get_empty_wardrobe
├── planning.md                # Design doc (spec, loop, state, architecture)
└── requirements.txt
```

---

## Tool Inventory

The agent uses three tools, defined in [tools.py](tools.py). Tool 1 is pure
Python (deterministic keyword search over the mock dataset); Tools 2 and 3 call
the Groq LLM (`llama-3.3-70b-versatile`).

### Tool 1 — `search_listings`

[tools.py:86](tools.py#L86)

- **Purpose:** Find listings in the mock dataset that match the user's
  description, filtered by optional size and price ceiling, ranked by keyword
  relevance. This is the only tool that gates the rest of the loop — if it finds
  nothing, the agent stops.
- **Inputs:**
  - `description` (`str`) — keywords describing the item (e.g. `"vintage graphic tee"`).
  - `size` (`str | None`) — size to filter by; case-insensitive substring match, so `"M"` matches `"S/M"`. `None` skips size filtering.
  - `max_price` (`float | None`) — inclusive price ceiling. `None` skips price filtering.
- **Output:** `list[dict]` — matching listing dicts sorted by relevance score
  (highest first), ties preserving dataset order. Empty list if nothing matches
  (it never raises). Each listing dict contains: `id`, `title`, `description`,
  `category`, `style_tags` (list), `size`, `condition`, `price` (float),
  `colors` (list), `brand`, `platform`.

### Tool 2 — `suggest_outfit`

[tools.py:163](tools.py#L163)

- **Purpose:** Given the selected secondhand item and the user's wardrobe, ask
  the LLM for 1–2 complete outfit ideas that pair the new item with specific
  named wardrobe pieces (or general styling advice if the wardrobe is empty).
- **Inputs:**
  - `new_item` (`dict`) — the selected listing dict (the item being considered).
  - `wardrobe` (`dict`) — wardrobe dict with an `items` key holding a list of wardrobe-item dicts; may be empty.
- **Output:** `str` — a non-empty outfit-suggestion paragraph. Populated
  wardrobe → outfits referencing pieces by name; empty wardrobe → general
  styling advice using common staples. Never returns empty and never raises.

### Tool 3 — `create_fit_card`

[tools.py:232](tools.py#L232)

- **Purpose:** Turn the outfit suggestion into a short, casual, shareable
  Instagram/TikTok-style OOTD caption that names the item, price, and platform
  naturally.
- **Inputs:**
  - `outfit` (`str`) — the outfit suggestion string from `suggest_outfit()`.
  - `new_item` (`dict`) — the selected listing dict (supplies item name, price, platform for the caption).
- **Output:** `str` — a 2–4 sentence caption. Generated at higher temperature
  (`0.95`) so captions vary across runs. Returns a descriptive error string if
  `outfit` is empty/whitespace; never raises.

### Internal helpers (not tools)

- `_parse_query(query)` — regex extraction of `description` / `size` / `max_price` from the raw query.
- `_chat(prompt, temperature)` — single-prompt Groq call shared by Tools 2 & 3.
- `_format_item(item)` — renders a listing or wardrobe item as a one-line string for prompts.
- `_get_groq_client()` — builds the Groq client; raises `ValueError` if `GROQ_API_KEY` is unset.

---

## Planning Loop

The agent does **not** do free-form LLM tool selection. `run_agent(query, wardrobe)`
([agent.py:98](agent.py#L98)) runs a **fixed, ordered pipeline with one branch
point**, and decides each next step by reading the current session state:

1. **Initialize** — `_new_session(query, wardrobe)` creates the session dict.
2. **Parse** — `_parse_query()` pulls `description`, `size`, `max_price` out of
   the query (regex for `size M`, and `under $30` / bare `$30`), stripping those
   phrases out of the description so they don't dilute keyword matching. Stored
   in `session["parsed"]`.
3. **Search** — `search_listings(description, size, max_price)` → `session["search_results"]`.
4. **Branch on the search result (the one real decision):**
   - **Empty results →** set `session["error"]` to a helpful "no listings found,
     try a different filter" message and **return immediately**. No LLM call is
     made, because there is no item to style.
   - **Non-empty →** select the top (most relevant) listing as
     `session["selected_item"]` and continue.
5. **Suggest outfit** — `suggest_outfit(selected_item, wardrobe)` → `session["outfit_suggestion"]`.
6. **Create fit card** — `create_fit_card(outfit_suggestion, selected_item)` → `session["fit_card"]`.
7. **Return** the completed session.

**How it knows it's done:** the loop ends either by returning early on the
empty-search branch (error set, other outputs `None`) or by reaching step 7 with
all three outputs populated. The caller checks `session["error"]` first — `None`
means success. Because the two LLM tools never raise (they return fallback
strings on failure), once search succeeds the pipeline always runs to completion.

```
parse → search ─┬─ empty ─→ set error, RETURN early
                └─ found ─→ select top → suggest_outfit → create_fit_card → RETURN
```

---

## State Management

All information for a single interaction lives in **one session dict**, created
by `_new_session()` ([agent.py:74](agent.py#L74)) at the start of every
`run_agent()` call. It is the single source of truth: each step reads what it
needs from the session and writes its result back, so **no tool talks to another
tool directly** — the output of one tool becomes the input to the next *through*
the session.

| Key | Set by | Consumed by |
|-----|--------|-------------|
| `query` | `_new_session` (raw user text) | parsing |
| `parsed` | Step 2 — `_parse_query()` → `{description, size, max_price}` | `search_listings` |
| `search_results` | Step 3 — `search_listings()` output | branch check + item selection |
| `selected_item` | Step 4 — `search_results[0]` | `suggest_outfit`, `create_fit_card` |
| `wardrobe` | `_new_session` (passed in by the UI) | `suggest_outfit` |
| `outfit_suggestion` | Step 5 — `suggest_outfit()` output | `create_fit_card` |
| `fit_card` | Step 6 — `create_fit_card()` output | final UI output |
| `error` | Set only on the empty-search branch | UI (decides which panels to show) |

**Flow example:** `search_listings` writes `search_results`; step 4 reads it and
writes `selected_item`; `suggest_outfit` reads `selected_item` + `wardrobe` and
writes `outfit_suggestion`; `create_fit_card` reads `outfit_suggestion` +
`selected_item` and writes `fit_card`. The UI ([app.py](app.py)) then maps
`selected_item` → 🛍️ panel, `outfit_suggestion` → 👗 panel, `fit_card` → ✨
panel — or, if `error` is set, shows the error in the first panel and blanks the
other two.

The session is **per-interaction** — a fresh dict is built on every
`run_agent()` call, so there is no shared state between separate queries.

---

## Error Handling

The agent is built so that **tools never raise** — they return `[]`, an error
string, or a graceful fallback. That guarantees the loop always finishes and the
UI always receives three panels. Each tool's failure mode is handled as follows.

### `search_listings` — no results match (hard stop)

If the filtered, scored search returns an empty list, the planning loop sets
`session["error"]` and **returns before any LLM call** — there's no point
styling an item that was never found. The error message tells the user exactly
which filters were applied and what to relax.

> **Concrete example (from testing).** Query: `"designer ballgown size XXS under $5"`.
> `_parse_query` produced `{'description': 'designer ballgown', 'size': 'XXS', 'max_price': 5.0}`.
> No listing matched, so `run_agent` returned early with:
>
> ```
> error           = "No listings found for 'designer ballgown' in size XXS under $5.
>                     Try removing a filter (size or price) or using different keywords."
> outfit_suggestion = None
> fit_card          = None
> ```
>
> The UI shows that message in the 🛍️ panel and leaves 👗 and ✨ blank.

### `suggest_outfit` — empty wardrobe *and* LLM/API failure

Two failure modes are covered:

1. **Empty wardrobe** — instead of returning nothing, it prompts the LLM for
   general styling advice (pairing ideas + example outfits with common staples).
2. **LLM/API failure** — the Groq call is wrapped in `try/except`; on any
   exception it returns a friendly fallback string rather than raising.

> **Concrete example (from testing).** Forcing the API failure path (unset
> `GROQ_API_KEY`) with item *"90s Band Tee"* and an empty wardrobe returned:
>
> ```
> Couldn't reach the styling assistant (GROQ_API_KEY not set. Add it to a .env
> file in the project root.). As a starting point, 90s Band Tee is versatile —
> try pairing it with neutral basics and one statement piece to build a
> balanced look.
> ```
>
> The agent keeps running and the fit card can still be generated.

### `create_fit_card` — missing/empty outfit input (+ LLM fallback)

Before calling the LLM it guards against an empty or whitespace-only `outfit`
string and returns a descriptive error string. The LLM call itself is also
wrapped, falling back to a simple templated caption on API failure.

> **Concrete example (from testing).** Calling `create_fit_card("   ", item)`
> with a whitespace-only outfit returned:
>
> ```
> Can't write a caption yet — no outfit suggestion was provided. Run
> suggest_outfit() first, then pass its result here.
> ```

The UI layer adds one more guard: `handle_query` ([app.py:46](app.py#L46))
returns a prompt to the user if the query box is empty, before the agent ever
runs.

---

## AI Usage

Per the AI Tool Plan in [planning.md](planning.md), I used AI coding assistants
(Claude and Copilot) to generate implementation from my spec, then reviewed and
overrode the output before committing. Specific instances:

### Instance 1 — Generating the three tools from the Tool Inventory spec

- **What I gave it:** The **Tools** section of [planning.md](planning.md) (the
  Tool 1–3 blocks: each tool's purpose, input parameters with types, return
  value, and failure mode), plus the signature stubs and docstrings in
  [tools.py](tools.py) and the `load_listings()` / wardrobe helpers in
  `utils/data_loader.py`.
- **What it produced:** Working bodies for `search_listings`, `suggest_outfit`,
  and `create_fit_card` — keyword-overlap scoring for search, and two Groq
  prompts (empty-wardrobe vs. populated-wardrobe) for the styling tool.
- **What I changed/overrode before using it:**
  - My spec said search returns *"3 top relevant items,"* but the generated code
    capped results at 3. I **removed the cap** and return the full ranked list,
    letting the loop pick `search_results[0]` — the cap was pointless since only
    the top item is used downstream.
  - The spec described searching *"the internet."* I **overrode that** to search
    the local mock `listings.json` via `load_listings()`, since that's the
    project's actual dataset — no live API.
  - The first draft had `create_fit_card` take only `outfit` (as my Tool 3 block
    listed). I **added `new_item`** as a second input so the caption could name
    the item, price, and platform, and bumped its temperature to `0.95` so
    captions vary. I verified the empty/whitespace-outfit guard returns a string
    instead of raising before trusting it.

### Instance 2 — Generating the planning loop and state model from the loop/state/architecture spec

- **What I gave it:** The **Planning Loop**, **State Management**, and
  **Architecture** (ASCII diagram) sections of [planning.md](planning.md) — the
  ordered pipeline, the session-dict state table, and the diagram showing the
  empty-search branch and how state flows between tools.
- **What it produced:** `run_agent()` in [agent.py](agent.py) wiring the three
  tools together through the session dict, including the early-return on empty
  search results, plus `_parse_query()` and `_new_session()`.
- **What I changed/overrode before using it:**
  - The starter left query parsing open (regex vs. LLM). The assistant initially
    leaned toward an LLM parse; I **overrode it to deterministic regex** in
    `_parse_query`, stripping the size/price phrases out of the description so
    they don't dilute keyword matching — predictable and no extra LLM call.
  - I tightened the no-results behavior to match my diagram's hard stop:
    `run_agent` must set `session["error"]` and **return before any LLM call**.
    I tested this with `"designer ballgown size XXS under $5"` to confirm
    `outfit_suggestion` / `fit_card` stay `None` and no Groq request is made.
  - I confirmed the generated tools matched my "tools never raise" rule by
    forcing an API failure (unset `GROQ_API_KEY`) and checking that
    `suggest_outfit` returned a fallback string rather than crashing the loop.

## Spec Reflection

How the built agent compares to the original design in
[planning.md](planning.md):

**What matched the spec.** The three-tool inventory, the fixed-pipeline planning
loop with a single branch on the search result, and the single-session-dict
state model were all implemented as planned. The "tools never raise" principle
and the empty-search hard stop (no LLM call when there's nothing to style)
carried over directly from the architecture diagram. The full happy path was
verified end-to-end — e.g. `"vintage graphic tee under $30"` selects the
*Y2K Baby Tee — Butterfly Print* ($18), produces a multi-sentence outfit idea,
and generates a varied caption.

**What changed or got more specific than the original plan.**

- **Search returns *all* matches, not "top 3."** The Tool 1 spec said it returns
  "3 top relevant items," but the implementation returns the full ranked list
  and the loop selects `search_results[0]`. Capping at 3 was unnecessary since
  only the top item is used downstream; the UI shows a single listing.
- **No real internet search.** The plan described searching "the internet," but
  the tool searches the local mock `listings.json` via keyword overlap scoring —
  matching the project's actual dataset rather than a live API.
- **Query parsing is regex, not the LLM.** The starter left this open; I chose
  deterministic regex in `_parse_query` (size/price phrases stripped from the
  description) so search inputs are predictable and don't cost an LLM call.
- **`create_fit_card` takes two inputs, not one.** The planning-doc Tool 3 block
  listed only `outfit`; the implementation also takes `new_item` so the caption
  can name the item, price, and platform — needed to meet the caption
  requirements.
- **Error handling got richer than the table implied.** Beyond the planned
  failure modes, both LLM tools also degrade gracefully on API failure (verified
  by forcing an unset key), and the UI guards the empty-query case. The
  wardrobe-empty case became "general styling advice" rather than a user-facing
  error, which is a better experience for new users.

**What I'd do next.** Surface more than one listing in the UI so the user can
pick which item to style, and add a lightweight retry/backoff around the Groq
calls so transient API errors recover instead of immediately falling back.
