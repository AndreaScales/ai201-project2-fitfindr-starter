# FitFindr — planning.md

> Complete this document before writing any implementation code.
> Your spec and agent diagram are what you'll use to direct AI tools (Claude, Copilot, etc.) to generate your implementation — the more specific they are, the more useful the generated code will be.
> Your planning.md will be reviewed as part of your submission.
> Update it before starting any stretch features.

---

## Tools

List every tool your agent will use. For each tool, fill in all four fields.
You must have at least 3 tools. The three required tools are listed — add any additional tools below them.

### Tool 1: search_listings

**What it does:**
<!-- Describe what this tool does in 1–2 sentences -->
The tool searches the internet for listings of the sought after thrifted item. It returns a list of 3 top relevant items and the input parameter details.
**Input parameters:**
<!-- List each parameter, its type, and what it represents -->
- `description` (str): A description of the item that is being searched (i.e., vintage graphic tee)
- `size` (str): The size of the item you are searching for (i.e., size=M)
- `max_price` (float): The maximum price you are wanting to pay for said item (i.e., max_price=30.0)

**What it returns:**
<!-- Describe the return value — what fields does a result contain? -->
It returns the most relevant search option based off of the input parameters.

**What happens if it fails or returns nothing:**
<!-- What should the agent do if no listings match? -->
If the items fail or returns nothing, the program will tell the user what to input differently and stop.

---

### Tool 2: suggest_outfit

**What it does:**
<!-- Describe what this tool does in 1–2 sentences -->
This tool suggests an outfit of clothes based off of the finding you found in the 

**Input parameters:**
<!-- List each parameter, its type, and what it represents -->
- `new_item` (dict): a listing in the wardrobe
- `wardrobe` (dict): a collection of listings that the user has. 

**What it returns:**
<!-- Describe the return value -->
It returns a suggested outfit based off of what's in the wardrobe and what the user searched in the listing. 

**What happens if it fails or returns nothing:**
<!-- What should the agent do if the wardrobe is empty or no outfit can be suggested? -->
If the wardrobe is empty, the program offers general styling advice for the item (pairing ideas and example outfits using common staples) instead of returning nothing. If the LLM call itself fails, it returns a friendly fallback string rather than raising an exception.
---

### Tool 3: create_fit_card

**What it does:**
<!-- Describe what this tool does in 1–2 sentences -->
- Creates a 2-3 sentence caption that includes the parameter descriptions,

**Input parameters:**
<!-- List each parameter, its type, and what it represents -->
- `outfit` (str): outfit suggestion based off of new item and wardrobe parameters.

**What it returns:**
<!-- Describe the return value -->
'outfit' returns a string statement that offers an outfit suggestion to the user based off of the wardrobe items 

**What happens if it fails or returns nothing:**
<!-- What should the agent do if the outfit data is incomplete? -->
If it fails (there are no items in wardrobe) or it returns nothing, then it will print an error message and prompt the user

---

### Additional Tools (if any)

<!-- Copy the block above for any tools beyond the required three -->

---

## Planning Loop

**How does your agent decide which tool to call next?**
<!-- Describe the logic your planning loop uses. What does it look at? What conditions change its behavior? How does it know when it's done? -->
The agent decides which tool to call next based off of the stored session state. It runs as a fixed, ordered pipeline with one branch point, rather than free-form tool selection:

1. **Parse the query** — `_parse_query()` extracts `description`, `size`, and `max_price` from the user's text (regex: `size M`, `under $30`/bare `$30`) and stores them in `session["parsed"]`.
2. **Search** — calls `search_listings(description, size, max_price)` and stores the list in `session["search_results"]`.
3. **Branch on the search result** — this is the key decision:
   - If `search_results` is **empty**, the agent sets `session["error"]` to a helpful "no listings found / try a different filter" message and **returns immediately**. It does *not* call the LLM tools, because there is no item to style.
   - If `search_results` has items, it picks the top (most relevant) one as `session["selected_item"]` and continues.
4. **Suggest an outfit** — calls `suggest_outfit(selected_item, wardrobe)` and stores the result in `session["outfit_suggestion"]`.
5. **Create a fit card** — calls `create_fit_card(outfit_suggestion, selected_item)` and stores it in `session["fit_card"]`.

**How it knows it's done:** the loop is finished when it either returns early on the empty-search branch (error set, other outputs `None`) or reaches the end with all three output fields populated. The caller checks `session["error"]` first — if it's `None`, the run succeeded. The two LLM tools never raise (they return fallback strings on failure), so once search succeeds the pipeline always runs to completion.

---

## State Management

**How does information from one tool get passed to the next?**
<!-- Describe how your agent stores and accesses state within a session. What data is tracked? How is it passed between tool calls? -->

All information for a single interaction lives in one **session dict**, created by `_new_session(query, wardrobe)` at the start of `run_agent()`. This dict is the single source of truth — every step reads what it needs from the session and writes its result back into the session, so no tool talks to another tool directly. Output of one tool becomes input to the next *through* the session.

**What's tracked in the session:**

| Key | Set by | Used by |
|-----|--------|---------|
| `query` | `_new_session` (original user text) | parsing |
| `parsed` | Step 2 — `_parse_query()` → `{description, size, max_price}` | `search_listings` |
| `search_results` | Step 3 — `search_listings()` output | branch check + item selection |
| `selected_item` | Step 4 — top result (`search_results[0]`) | `suggest_outfit`, `create_fit_card` |
| `wardrobe` | `_new_session` (passed in by the UI) | `suggest_outfit` |
| `outfit_suggestion` | Step 5 — `suggest_outfit()` output | `create_fit_card` |
| `fit_card` | Step 6 — `create_fit_card()` output | final UI output |
| `error` | set only on the empty-search branch | UI (decides which panels to show) |

**How it passes between tool calls:** for example, `search_listings` writes `search_results`; Step 4 reads that and writes `selected_item`; `suggest_outfit` reads `selected_item` (+ `wardrobe`) and writes `outfit_suggestion`; `create_fit_card` reads `outfit_suggestion` and `selected_item` and writes `fit_card`. The fully-populated session is then returned to the UI, which maps `selected_item`, `outfit_suggestion`, and `fit_card` to the three output panels — or, if `error` is set, shows the error in the first panel and leaves the other two blank. The session is per-interaction (a fresh one is built on every `run_agent()` call), so there is no shared state between separate queries.

---

## Error Handling

For each tool, describe the specific failure mode you're handling and what the agent does in response.

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| search_listings | No results match the query | Tells the user what to try differently and stops, doesn't return 'suggest_outfit' |
| suggest_outfit | Wardrobe is empty | Tells the user that the wardrobe is empty, and runs a suggestion based on the users style suggestions, offers to return to search_listing|
| create_fit_card | Outfit input is missing or incomplete | Tells the user that the outfit isn't there and what to try differently, and stops, offers to search for another listing |

---

## Architecture

<!-- Draw a diagram of your agent showing how the components connect:
     User input → Planning Loop → Tools (search_listings, suggest_outfit, create_fit_card)
                                                                          ↕
                                                                   State / Session
     Show what triggers each tool, how state flows between them, and where error paths branch off.
     ASCII art, a Mermaid diagram (https://mermaid.js.org/syntax/flowchart.html), or an embedded
     sketch are all fine. You'll share this diagram with an AI tool when asking it to implement
     the planning loop and each individual tool. -->

UI LAYER (app.py)
  User types query + picks wardrobe (Example / Empty)
            │
            ▼
  handle_query(user_query, wardrobe_choice)
            │  calls run_agent(query, wardrobe)
            ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ PLANNING LOOP (agent.py → run_agent)                                       │
│                                                                            │
│  Step 1: session = _new_session(query, wardrobe)   ──┐  reads/writes       │
│                                                      │  every step         │
│  Step 2: parse query → description, size, max_price  │                     │
│          session["parsed"] = {...}                   ▼                     │
│                                              ┌────────────────────────┐    │
│  Step 3: search_listings(desc, size, price)  │  SESSION / STATE       │    │
│          │                                   │  (single dict, the     │    │
│          ├─ results == []  ──► set           │   source of truth)     │    │
│          │   session["error"]                │                        │    │
│          │   = "No listings found…"  ───────►│  query                 │    │
│          │   RETURN early  ✗                 │  parsed                │    │
│          │                                   │  search_results        │    │
│          ▼ results = [item, …]               │  selected_item         │    │
│  Step 4: session["selected_item"]            │  wardrobe              │    │
│          = results[0]  ─────────────────────►│  outfit_suggestion     │    │
│          │                                   │  fit_card              │    │
│  Step 5: suggest_outfit(selected_item,       │  error                 │    │
│          │              wardrobe)            └────────────────────────┘    │
│          │   wardrobe empty → general advice  ▲         ▲                  │
│          │   LLM error      → fallback string │         │                  │
│          ▼   session["outfit_suggestion"] ────┘         │                  │
│  Step 6: create_fit_card(outfit, selected_item)         │                  │
│          │   empty outfit → error-string guard          │                  │
│          │   LLM error    → fallback caption            │                  │
│          ▼   session["fit_card"] ───────────────────────┘                  │
│                                                                            │
│  Step 7: RETURN session  ✓                                                 │
└──────────────────────────────────────────────────────────────────────────┘
            │
            ▼
  handle_query reads the session:
    error set?  → show error in panel 1, blanks in panels 2 & 3
    else        → map selected_item → 🛍️ Top listing
                      outfit_suggestion → 👗 Outfit idea
                      fit_card          → ✨ Fit card

NOTES
  • Tools never raise — they return [] / error-strings / fallback strings,
    so the loop always finishes and the UI always gets three panels.
  • search_listings is the only hard stop: empty results short-circuit the
    loop before any LLM call (no point styling an item that wasn't found).
  • suggest_outfit & create_fit_card call the Groq LLM
    (llama-3.3-70b-versatile); both degrade gracefully on empty input or
    API failure rather than crashing the agent.

---

## AI Tool Plan

I plan to use both Claude and Copilot to assist with the implementation of the program. I will give the planning.md document, specifically the Tools, Planning Loop, State Management, Error Handling and Architecture as a guide to the AI tool on how to develop the tools to fit the program. After giving AI the tool document portion, I expect it to return implementation for the three tools, 'search_listings', 'suggest_outfit' and 'create_fit_card'.  I also would like it to test it with at least two different queries before trusting and committing. I would give AI the Planning Loop and State Management portion of planning.md to handle state management tracking within the program so that the program is aware of if and when to move between the three different tools. For error handling, I would expect the AI to prepare error messages if and when tools come back empty or fail. I would create the architecture to further emphasize what triggers each tool, how state flows between them and where error paths branch off.  I'll verify that the output matches my spec with query tests as well as coding chunks at a time to check input and output thoroughly. 
<!-- For each part of the implementation below, describe:
     - Which AI tool you plan to use (Claude, Copilot, ChatGPT, etc.)
     - What you'll give it as input (which sections of this planning.md, your agent diagram)
     - What you expect it to produce
     - How you'll verify the output matches your spec before moving on

     "I'll use AI to help me code" is not a plan.
     "I'll give Claude my Tool 1 spec (inputs, return value, failure mode) and ask it to implement
     search_listings() using load_listings() from the data loader — then test it against 3 queries
     before trusting it" is a plan. -->

**Milestone 3 — Individual tool implementations:**

**Milestone 4 — Planning loop and state management:**

---

## A Complete Interaction (Step by Step)

Write out what a full user interaction looks like from start to finish — tool call by tool call. Use a specific example query.

**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"

**Step 1:**
<!-- What does the agent do first? Which tool is called? With what input? -->
The agent will first search for a vintage graphic tee under $30, calling the tool 'search_listings' (search_listings("vintage graphic tee", max_price=30.0)). It will return 3 top options, sorted by relevance. It will then pick the top result from these options. 

**Step 2:**
<!-- What happens next? What was returned from step 1? What tool is called now? -->
Next, the after the top thrifted option is returned, the tool 'suggest_outfit' is used to create an outfit for the user based off of what's in the user's wardrobe. The Groq LLM is used to suggest 1-2 complete outfit combinations. If the wardrobe is empty, it will give general styling advice instead.

**Step 3:**
<!-- Continue until the full interaction is complete -->
In this step, a caption is generated (a 2-4 sentence statement) mentioning the item, price and platform naturally. 


**Final output to user:**
<!-- What does the user actually see at the end? -->
In the end the user see an interface with a top listing found, an outfit idea and a fit card as a three output panel. 
