# Board Game Concierge — Autonomous Agent Project Plan

## Context

Board game groups lose the first ~20 minutes of every session re-explaining rules or trying to recall strategy tips from last time. The goal is a Telegram bot — the **Board Game Concierge** — that behaves like a warm, knowledgeable friend who's played everything: on command (e.g. "we're playing Wingspan tonight") it generates a grounded **Pre-Session Report** (rules refresher, common mistakes, strategy tips), answers grounded follow-up questions, and — as the concierge persona matures — helps pick and plan game nights too.

The repo already contains the raw materials: [main.py](main.py), a full BGG rankings dump at [masterlist/boardgames_ranks.csv](masterlist/boardgames_ranks.csv) (~11MB, per-category BGG rank/rating data — useful for fast game-name → BGG ID lookup, and later as a first-pass signal for recommendations), and a [rulebooks/](rulebooks/) folder with 16 real rulebook PDFs (Wingspan, multiple Catan variants, Azul, Ticket to Ride, Terraforming Mars, Hive, Memoir '44, Monopoly, Risk, Sequence, Stratego, Tripoley, 3 Ring Circus, Game of Thrones). These 16 games are the full eventual library, but **v1 deliberately ingests only 2 of them** as a proof of concept before scaling the ingestion pipeline to the rest.

This is a solo, fixed-deadline (1–3 week) bootcamp capstone. Given the full target capability list is much larger than that window supports, **the plan phases deliberately**: v1 ships a lean, grounded, on-command rules digest + basic follow-up Q&A for a 2-game pilot library, in the concierge's voice, on free/no-Docker infrastructure; the richer concierge behaviors (recommendations, night planning, multi-language, confidence scoring, edge-case routing) and the other 14 rulebooks are documented as the target end-state and scheduled into v2/v3 rather than crammed into v1.

## 1. Use Case

- **Description**: A Telegram bot with a consistent "Board Game Concierge" persona (see Section 2's Personality spec) that, v1, teaches the rules of a chosen game via a grounded pre-session digest and follow-up Q&A; v2+, also recommends games and helps plan a game night.
- **Target users**: A specific recurring game group (family/friends) — not a general public product.
- **Verification criteria**: An answer is "correct" if every rules statement traces back to actual text in the game's rulebook PDF, not the LLM's general knowledge or invented detail, and the group actually uses it before or during setup instead of re-deriving rules from memory or guessing at a recommendation.

### Target system capabilities (end-state vision — phased below)

**Can do**
- Answer questions about any game whose rulebook has been imported *(v1: a 2-game pilot from `rulebooks/`; growing to the full 16, then beyond via self-service, is v2)*
- Ground each answer in the imported rulebook text *(v1)*
- Handle follow-up questions in a conversation *(v1: one grounded follow-up per session; deeper multi-turn in v2)*
- Recommend a game for the group/occasion, given a player count and stated preferences *(now in v1 — see Section 3; game-night sequencing/planning beyond a single recommendation is still v2)*
- Detect and respond in 10 languages automatically *(v2)*
- Distinguish between straightforward rules questions and complex edge cases *(v2 — this is what justifies moving from a simple chain to a branching/LangGraph-style flow)*
- Answer counting/enumeration questions ("how many X are there?") from component tables *(v2 — needs a separate structured extraction pass over rulebook component tables)*
- Provide a confidence indicator for every answer *(v2)*

BGG's XML API and Reddit's Data API were originally in scope for community-sourced "common mistakes" and strategy content, but both are **out of consideration entirely** — BGG now requires a registration token we don't have, and Reddit closed self-service Data API app creation and requires manual approval we're not pursuing. Strategy tips instead draw on the LLM's general knowledge, framed the same way as the existing "plays like X" comparison line (an orientation aid, not a grounded/cited claim).

**Cannot do (documented limitation, not a bug — applies for the life of the project)**
- Answer questions about rules not covered in the imported rulebook — say so explicitly, never guess
- Access external websites, publishers' sites, or live errata
- Guarantee 100% accuracy on genuinely ambiguous or contested rules
- Replace official publisher rulings for tournament/competitive play
- Understand house rules or local variants unless they're in an imported document
- Answer questions about games not in the library
- Place orders, process purchases, or complete transactions (per Personality spec's Boundaries)
- Invent details (exact play time, component counts, popularity claims) it isn't confident about

## 2. Technology Stack

### Personality & voice (governs every message the bot sends)

The bot is not a generic Q&A tool — it has a fixed persona that shapes every prompt template from v1 onward:

- **Role**: warm, knowledgeable concierge — "the friend who has played everything."
- **Voice**: short sentences, one idea at a time, light humor welcome, never snobbish about "casual" games, bold game titles (e.g. **Catan**, **Wingspan**).
- **Response shape**: default 2–5 sentences plus an optional short list; match the user's energy (a one-word "hi" gets one warm line, not a paragraph); never end at a dead end — always offer a natural next step.
- **Clarify before recommending**: player count is the one hard requirement for a recommendation; if it's missing from the request, ask for it in one warm, combined question rather than guessing. If weight/time-budget/taste aren't given, proceed anyway rather than over-asking — a deliberate simplification of the original "ask one thing at a time" idea, chosen to avoid building multi-turn session-state tracking for v1.
- **Honesty boundary**: if the bot doesn't recognize a game or isn't confident about a detail, it says so plainly and redirects, rather than bluffing — this is the same principle as the RAG grounding requirement below, just stated as personality rather than architecture.

This persona is implemented as a fixed system prompt prepended to every LLM call (digest generation, follow-up Q&A, and later recommendation/planning calls) — one shared prompt fragment (`app/persona.py`), not duplicated per feature, so tone stays consistent as capabilities grow.

### Technology Selection Framework — answers

| Question | Answer | Implication |
|---|---|---|
| Needs RAG? | **Yes** | Rules answers must be grounded in real rulebook text, not LLM memory |
| Can use LLM knowledge only? | No (for rules teaching) | Recommendation/comparison lines may draw on general knowledge, clearly separated from grounded rules content |
| Interacts with external systems? | **Yes** | Telegram, OpenAI, Pinecone (BGG/Reddit APIs considered and dropped — see Alternatives) |
| Needs tools/integrations? | **Yes** | n8n nodes + Python API clients |
| Needs multi-step reasoning (LangGraph) vs. simple chain? | **No for v1 — simple chain + light memory. Yes for v2.** | v1 is a fixed sequence (retrieve rulebook chunks → one synthesis call, plus short per-chat memory for one follow-up; `/recommend` is a second fixed sequence: extract player count → filter/rank local CSV candidates → one synthesis call) — no branching needed yet. v2 adds real multi-step reasoning: classify simple-vs-edge-case query → route counting questions to structured component-table lookup instead of prose RAG → true multi-turn clarification. That branching/state is what LangGraph is for |
| Needs business-system integration (n8n)? | **Yes** | n8n owns the Telegram trigger + response delivery |
| Needs to be autonomous (scheduling/monitoring)? | **No** | Strictly on-demand, triggered by a Telegram command — no cron/scheduler in v1 |

### Stack

- **Core LLM**: OpenAI GPT — `gpt-4o-mini` for synthesis (cost-appropriate for an on-demand, low-volume bot), upgradeable to `gpt-4o` if digest quality needs it.
- **RAG components**:
  - **Vector DB**: Pinecone (managed, serverless, free tier) — no local server or Docker process to run at all, which fits the no-Docker constraint even better than a self-hosted option: there's nothing to install or keep alive, just an API key. Trade-off vs. the originally-planned Chroma: one more external account/vendor dependency and network calls on every query instead of local disk access, and usage needs to stay within Pinecone's free-tier limits (fine at this scale — a 2-game pilot is on the order of tens of vectors). Index: 1536 dimensions (matching `text-embedding-3-small`), cosine metric, one serverless index (`board-game-concierge`) holding all pilot games with `game_slug` in each vector's metadata so retrieval can filter to the game being asked about.
  - **Embeddings**: OpenAI `text-embedding-3-small` — same vendor as the LLM, avoids a second API key/vendor relationship, cheap enough for a 16-PDF corpus.
  - **Chunking strategy**: Parse PDFs with PyMuPDF. Chunk per page, splitting a page further only if it exceeds ~650 tokens, with ~100-token overlap so a rule doesn't get split mid-explanation. **Every chunk keeps source metadata** so retrieval can stay grounded later. See `app/ingestion/parse_pdf.py`.
  - **Apache Tika — considered, not used for v1**: Tika requires a background JVM (it auto-launches a local Tika server jar), which conflicts with the "no Docker, lightweight native processes" constraint — one more runtime to install and keep alive for a solo, short-deadline project. Its PDF text extraction is also generally coarser on page/layout structure than PyMuPDF, and precise page metadata is exactly what the retrieval pipeline needs. PyMuPDF gives page numbers natively in pure Python with nothing extra to run. Revisit Tika only if v2's "counting from component tables" hits a rulebook where the component table is embedded as an image rather than real text — Tika+Tesseract OCR would be the fallback there, not the default.
  - **Conversation memory (v1, basic)**: a small per-Telegram-chat store (in-memory dict, or one SQLite table keyed by `chat_id`) holding the last few turns, so a follow-up like "what about with 5 players?" resolves against the original digest's game/context. Deliberately simple — full multi-turn planning is v2.
- **Agent framework**: v1 = a simple LangChain retrieval chain + prompt template (with the persona prompt fragment) + the lightweight memory above (not LangGraph). v2 = introduce LangGraph once query classification/routing and recommendation/planning flows are needed.
- **Orchestration**: **n8n Cloud** (revised from the original self-hosted plan — see Alternatives below). n8n owns the Telegram Trigger, light intent parsing (initial request vs. follow-up), an HTTP Request call into the Python RAG service, and formatting/sending the Telegram reply. Because n8n Cloud runs on n8n's own servers rather than your machine, the FastAPI service must be reachable at a **public URL**, not `127.0.0.1` — see Risk Assessment.
- **RAG service runtime**: FastAPI run directly with `uvicorn` (no Docker) — either on your own always-on machine, or deployed to a free-tier PaaS that builds native Python without a Dockerfile (e.g. Render/Railway free web service).
- **Tools/integrations**:
  - Telegram Bot API (n8n Telegram node)
  - `masterlist/boardgames_ranks.csv` — fast game name → BGG ID lookup (`app/clients/game_lookup.py`) and expansion filtering (`is_expansion` column) for recommendations
  - `masterlist/games.csv` (21,925 games: player counts, complexity, age, ratings, category flags) + `masterlist/bgg_db_2018_01.csv` (4,999 games: adds real mechanic/category tags and clean min-max playtime, joined in by BGG id) — the data behind `/recommend` (`app/clients/game_catalog.py`), entirely static/local, no live API
  - OpenAI API — embeddings + chat completion
  - No BGG or Reddit API — both considered and dropped (see Alternatives below); community-sourced "common mistakes"/strategy content was descoped in favor of LLM general knowledge, clearly framed as such

### Alternatives considered / trade-offs

- **All-native-n8n RAG** (n8n's built-in vector store + AI Agent nodes) was considered and rejected in favor of a standalone Python service — trades a bit more setup for finer control over chunking/retrieval quality and a RAG service reusable outside n8n later.
- **Claude vs. GPT**: Claude was the default recommendation for grounded summarization; OpenAI GPT was chosen instead, which is also well-documented and fine for this workload.
- **n8n Cloud vs. self-hosted**: originally planned as self-hosted Community Edition to keep infra cost at $0. **Revised to n8n Cloud** once we discovered you're actually running n8n Cloud, not a local instance — this changes the cost assumption (n8n Cloud is a paid subscription, not $0) and, more importantly, means the FastAPI backend can't be reached via `127.0.0.1` since n8n Cloud executes on n8n's own servers, not your machine (see Risk Assessment).
- **Docker vs. no Docker**: no Docker available, so both n8n and the FastAPI service run as native processes (`n8n start`, `uvicorn`) instead of containers — a supported path for both, just with slightly more manual environment setup instead of one `docker-compose up`.
- **BGG XML API + Reddit Data API vs. dropped entirely**: originally planned as free, no-key/free-tier sources for "common mistakes" and strategy content. Both turned out to require registration/approval we don't have (BGG: registration token as of a 2025 policy change; Reddit: manual Data API app approval since Nov 2025) and aren't pursuing — so rather than keep working around a permanently-blocked dependency, both were removed from the design entirely (code deleted, not just unused). Strategy tips in the report now come from the LLM's general knowledge instead, framed the same way as the existing "plays like X" comparison line.

### Report format decision

The pre-session report is **not** a rulebook excerpt or a wall of retrieved text. In the concierge's voice, the synthesis prompt compresses rulebook retrieval + general knowledge into:
- **5–10 short rule steps** (setup → turn structure → scoring/win condition, whichever matters most for that game), each one sentence
- **1–2 strategy tips**, drawn from the LLM's general knowledge of the game — same framing as the comparison line below (an orientation aid, not a grounded/cited claim), since there's no community-forum data source in scope anymore
- **One "if you've played X" comparison line** to a similar/reference game, to orient players fast (e.g. "plays like a lighter, faster **Ticket to Ride**")

The comparison line draws on the LLM's general knowledge rather than RAG-grounded, since it's an orientation aid rather than a factual rules claim — the rule steps above are the part that must stay grounded and cited. The whole message is written to be read once, quickly, at the table — not a reference document — and follows the Personality spec's response-shape rules (short, warm, never a dead end).

After the initial digest, the same chat can ask one direct follow-up question (e.g. "how does scoring work again?") and get a short, on-persona answer using the memory described above.

## 3. MVP Scope

**v1 (must-have)**
- Telegram command triggers a report for one game per request (e.g. "we're playing Wingspan tonight"), delivered in the concierge persona
- Game name → BGG ID resolution via the existing `masterlist/boardgames_ranks.csv`
- RAG-grounded rules refresher, scoped to a **2-game pilot** selected from the 16 in `rulebooks/`: **Ticket to Ride** (text-dense) and **Catan: Seafarers** (graphics/table-dense), picked to stress-test the parsing/chunking pipeline against both extremes early
- A single, short Telegram message: **5–10 cited rule steps + 1–2 general-knowledge strategy tips + a "plays like X" comparison line** — not a rulebook dump
- **Basic follow-up Q&A**: one grounded follow-up question per session, using short per-chat memory
- **Game recommendations** (`/recommend`): given a player count and free-text preferences, extract player count (simple regex, best-effort — ask for it in one combined question if missing), filter/rank `masterlist/games.csv` (enriched with `bgg_db_2018_01.csv`'s mechanics/playtime data, expansions excluded via `boardgames_ranks.csv`'s `is_expansion` join) by player count and quality, then have the LLM pick ONE confident primary pick + ONE alternative (framed by direction) from that candidate pool — entirely offline, no live API
- English only
- Graceful, explicit, on-persona fallback whenever the answer isn't covered by the imported rulebook, isn't about a game in the library, or otherwise hits a documented "cannot do" limit — say so warmly, don't guess

**v2 (should-have)** — the rest of the target capability list
- Scale the ingestion pipeline from the 2-game v1 pilot to the remaining 14 rulebooks already in `rulebooks/`
- True multi-turn clarification for `/recommend` (ask player count, then weight, then time budget as separate messages) instead of v1's single-message best-effort extraction; broader game-night planning beyond a single recommendation
- Multi-language auto-detect & respond (10 languages)
- Query classification (simple vs. complex/edge-case), routing edge cases to a confidence indicator on the answer
- Counting/enumeration answers from structured extraction of rulebook component tables
- Player-count / expansion-aware rules (the repo already has separate Catan base + Seafarers + Cities & Knights + Explorers & Pirates + Traders & Barbarians rulebooks)
- Deeper multi-turn conversation (beyond v1's single follow-up)
- Basic caching of reports/fetches per game to cut repeat API/LLM cost
- Group-chat support (not just 1:1 DM)
- Self-service: user uploads a new rulebook PDF via Telegram to add a game to the library
- 👍/👎 feedback on answer quality

**v3+ (nice-to-have)**
- Proactive/scheduled game-night reminders (the point autonomy — cron, monitoring — becomes justified)
- Voice input/output
- Web dashboard for library browsing + usage analytics
- Automatic BGG collection sync

**Out of scope for v1**: everything above v2/v3, plus any autonomous/unattended execution and multi-game batch requests.

**Success metrics**
- Correctly generates a grounded report for both v1 pilot games within a reasonable response time (target: under ~30s)
- Spot-check: rule statements are traceable to actual rulebook text (no invented rules, no unsupported details)
- At least one follow-up question per session gets a correctly grounded, on-persona answer
- Responses read as the concierge persona (warm, concise, never a dead end) in a manual review of sample conversations
- Real-world adoption signal: the group actually uses the bot before/at least a few real game nights
- Cost stays near-zero (self-hosted infra + capped OpenAI usage)

## 4. Risk Assessment

**Technical**
- *n8n Cloud can't reach `127.0.0.1`* — **materialized, not hypothetical**: discovered when the n8n workflow's `Call /report API` node failed with `ECONNREFUSED 127.0.0.1:8000`. n8n Cloud executes on n8n's own remote servers, not your machine, so `127.0.0.1` in an n8n Cloud workflow refers to n8n's own server, never your laptop — this only works when n8n is self-hosted on the same host as the backend. Probability: confirmed, Impact: High (blocks every request until fixed). Mitigation (current, temporary): a `cloudflared` quick-tunnel exposes the local FastAPI service at a public HTTPS URL, supervised under `pm2` (`board-game-concierge-tunnel`) alongside the API itself so it restarts if it crashes — but each restart issues a **new** URL (no account, so no fixed subdomain), meaning both HTTP Request nodes' URLs need manual re-entry in the n8n Cloud editor after any tunnel restart. Durable fix (Phase 4): deploy the FastAPI service to a free-tier host with a stable URL (Render/Railway) instead of tunneling from a laptop, or add a Cloudflare account for a named (non-expiring) tunnel.
- ~~*BGG XML API / Reddit Data API auth requirements*~~ — **closed, not open**: both surfaced during Phase 2 testing (BGG now 401s without a registration token; Reddit closed self-service Data API app creation in Nov 2025) and were originally tracked as "degrade gracefully, revisit later" risks. Resolved by removing both from scope entirely rather than continuing to work around them — `app/clients/bgg_client.py` is deleted, no Reddit client was ever built, and strategy tips now come from the LLM's general knowledge instead. No longer an open risk.
- *LLM hallucinating rules despite RAG* — Probability: Medium, Impact: **High** (a wrong rule ruins the game). Mitigation: strict prompt requiring the model to only state what's in retrieved chunks, low temperature, explicit "not found in rulebook" fallback language instead of guessing.
- *Wrong or missing grounding metadata* (chunking/metadata bugs point at the wrong excerpt, or a sentence spans two source chunks) — Probability: Medium, Impact: Medium. Mitigation: keep chunk-to-page mapping simple (one chunk = one page range), spot-check grounding during Phase 2 tests.
- *Genuinely ambiguous/contested rules* — Probability: Medium, Impact: Medium. Mitigation: documented "cannot do"; v1 surfaces uncertainty in plain, on-persona language rather than false confidence; v2's confidence indicator formalizes this.
- *Rulebook PDF parsing quality* (diagrams/tables/icons don't extract cleanly — several PDFs, like the Catan expansions, are large/graphics-heavy) — Probability: High, Impact: Medium. Mitigation: layout-aware parser (PyMuPDF), manual spot-check of chunking output per PDF, tune chunk size for problem files; picking one text-dense and one graphics-dense rulebook for the v1 pilot surfaced this risk immediately (Catan: Seafarers page 16, a hex-tile setup diagram, extracts as mostly numbers/bullets rather than prose).
- *RAG service downtime* — Probability: Low/Medium, Impact: Medium. Mitigation: process restart on crash (`pm2`/systemd instead of a Docker restart policy), health check before n8n calls it, timeout + friendly Telegram fallback message.
- *Free-tier hosting constraints* (no Docker means relying on a native-runtime free web service, which typically sleeps after inactivity and cold-starts) — Probability: Medium, Impact: Low/Medium. Mitigation: keep the FastAPI service lightweight, or run it on your own always-on machine if cold-start latency is a problem on game night.

**Business**
- *Adoption* (bot doesn't actually get used at game night) — Probability: Medium, Impact: Medium. Mitigation: pick the 2 pilot games from ones the group actually plays soon, get feedback after the first few real uses before expanding the library.
- *Scope creep* against a 1–3 week deadline — Probability: **High**, Impact: High. Mitigation: hold the v1 boundary above hard; multi-turn clarification, multi-language, and confidence scoring are explicitly parked in v2/v3, not built now.
- *Cost overrun* — Probability: Low at this volume, Impact: Low/Medium. Mitigation: `gpt-4o-mini`, capped max tokens, OpenAI billing alert.

**Data**
- *Stale CSV data* (`boardgames_ranks.csv`/`games.csv`/`bgg_db_2018_01.csv` rankings/details drift over time — the latter is a 2018 snapshot) — Probability: Medium, Impact: Low. Mitigation: fine for v1's fixed 2-game rulebook pilot and for recommendations at this scale; refresh if the rulebook library grows past 16 or recommendation quality visibly degrades.
- *Rulebook PDFs are copyrighted publisher material* — Impact: Medium (legal/ethical exposure if redistributed). Mitigation: keep this personal/private-group use, never publish `rulebooks/` to a public repo, only quote short grounded snippets in output, not full rulebook text.
- *Telegram usage data* — Probability: Low, Impact: Low. Mitigation: log only chat ID + game requested + timestamp for caching/debugging; no other PII.

## 5. Implementation Plan

**Phase 1 — Setup & data prep (Days 1–3)**
- Register Telegram bot (BotFather), OpenAI API key
- Install n8n Community Edition natively (`npm install -g n8n`, no Docker) locally or on a free-tier host
- Pick the 2 pilot rulebooks (one text-dense, one graphics-dense) and build the PDF → chunk → embed → Pinecone ingestion pipeline for them, **preserving page number in chunk metadata**
- Index `masterlist/boardgames_ranks.csv` for fast name → BGG ID lookup
- Draft the shared persona system-prompt fragment (from Section 2) that every LLM call will use

**Phase 2 — Core RAG service (Days 4–7)** ✅ done
- FastAPI service (via `uvicorn`, no Docker) exposing `/report` (initial digest) and `/ask` (follow-up question) endpoints: Pinecone retrieval + LangChain synthesis chain (persona prompt + retrieved content + general-knowledge strategy tips) → OpenAI
- Lightweight per-chat memory store for follow-ups (in-memory dict, `app/memory.py`)
- Prompt tuning so output stays within the 5–10 step / 1–2 tip / one-comparison / cited / on-persona format, with grounding checks against the 2 pilot rulebooks
- `/recommend` added in the same phase: `app/clients/game_catalog.py` filters/ranks `masterlist/games.csv` (enriched with `bgg_db_2018_01.csv`) by player count and quality, `build_recommendation` in `app/synthesis.py` has the LLM pick one primary + two alternatives from that candidate pool

**Phase 3 — n8n integration & testing (Days 8–10)** ✅ workflow built and verified, live Telegram wiring pending your bot credential
- n8n workflow at `n8n/board-game-concierge.workflow.json`: intent routing is command-based (`/start`/`/help` → static intro, `/ask <question>` → `/ask`, anything else e.g. "we're playing Ticket to Ride tonight" → `/report`), not NLU-classified — deliberately simple per the v1 "simple chain, no LangGraph" decision
- Error handling: HTTP Request nodes retry twice with backoff and fall back to an on-persona "having trouble reaching my rulebook brain" message on failure, rather than breaking the chat
- Verified for real: installed n8n locally, imported the workflow via its CLI, and executed all three routes (help / report / ask) against the live FastAPI server end-to-end — confirmed correct routing, correct request bodies, and correct grounded/cited replies flowing back out. Two real bugs were caught and fixed this way that pure JSON-authoring wouldn't have caught: n8n blocks `$env` access in expressions by default (switched the FastAPI URL from an env-var expression to a plain hardcoded `http://127.0.0.1:8000`), and `localhost` was resolving to IPv6 while `uvicorn` only binds IPv4 (switched to the literal `127.0.0.1`)
- Not yet tested: the actual Telegram Trigger/Send nodes need a real Telegram credential (bot token) to fire against live Telegram — everything upstream of Telegram itself is confirmed working

**Phase 4 — Deploy & monitor (Days 11–14, buffer)**
- Run n8n + FastAPI as native processes on free-tier hosting (or a local always-on machine) — no container step
- Basic logging (requests, errors, latency) + OpenAI budget alert
- Real game-night dry run with the actual group; write up the capstone README

**Dependencies**: Phase 2 depends on Phase 1's ingested vector DB and persona prompt; Phase 3 depends on Phase 2's `/report` and `/ask` endpoints being stable; Phase 4 depends on Phase 3 passing end-to-end tests.

**Milestones**: end of Phase 1 = ingestion pipeline produces sane, source-tagged chunks for both pilot PDFs; end of Phase 2 = `/report` and `/ask` return grounded, on-persona output via curl/Postman; end of Phase 3 = bot works end-to-end in Telegram including follow-ups; end of Phase 4 = used in a real game night.

## 6. Success Metrics

- Both v1 pilot games produce a grounded, on-persona report within ~30s
- Follow-up Q&A correctly resolves against session context at least once per session
- Group uses the bot before real game nights (adoption, not just a demo)
- Infra cost ≈ $0; LLM cost stays within a small capped budget
- Zero rule statements traced to spot-checks that contradict the actual rulebook

## Resources Needed

- **Team**: solo
- **Tools/services**: Node.js (for n8n, no Docker), n8n Community Edition, Python (via the existing `lab` conda environment) + FastAPI + uvicorn, Pinecone account + API key, OpenAI API key, Telegram Bot token (BotFather), a free-tier host (Render/Railway or your own always-on machine) — no BGG or Reddit credentials needed, both dropped from scope
- **Budget**: near-$0 (native/free-tier infra, no paid hosting or containers required); only variable cost is OpenAI usage, capped via billing alert

## Implementation Status

- ✅ Phase 1: project scaffolded (`app/config.py`, `app/persona.py`, `app/ingestion/`, `app/clients/game_lookup.py`), dependencies installed in the `lab` conda environment, PDF chunking pipeline verified against both pilot rulebooks, game-name lookup verified against the masterlist CSV.
- ✅ Ingestion: both pilot rulebooks (42 chunks total) embedded and upserted into the Pinecone index `board-game-concierge` (512-dim, matching the pre-existing index — see `app/config.py`'s `EMBEDDING_DIMENSIONS`).
- ✅ Phase 2: FastAPI service (`app/server.py`) with `/report` and `/ask` built and tested end-to-end via curl for both pilot games — grounded, on-persona output confirmed, including a follow-up question correctly resolving via session memory.
- ✅ BGG/Reddit fully removed: `app/clients/bgg_client.py` deleted, `/report` no longer references BGG at all, Reddit env vars removed from `.env`/`.env.example`. Strategy tips in the report now come from the LLM's general knowledge instead — not a stopgap, the permanent design.
- ✅ `/recommend`: player-count/preference-based recommendation using `masterlist/games.csv` + `masterlist/bgg_db_2018_01.csv` (local CSV data, no live API, expansions excluded via `boardgames_ranks.csv`'s `is_expansion` join) — one primary pick + two alternatives, each framed by direction, per the original persona spec. Verified via curl across several scenarios: complete preferences, missing player count (asks a clarifying question), extreme/zero player count (graceful fallback), and a taste-contrast pair (light vs. heavy request at the same player count) confirmed preferences genuinely change the picks. Two real bugs found and fixed during testing: the LLM mislabeled complexity (called a 3.0-weight game "light") when asked to derive light/medium/heavy from the number itself — fixed by computing that label in Python instead of asking the LLM to; and the "alternative framed by direction" line sometimes said "if you want something lighter" about a game that was actually heavier — fixed by having the prompt explicitly check the direction phrase against the real numbers before writing it.
- ✅ Telegram formatting fixes: removed markdown headings (`#`/`##`/`###`) from all prompts since Telegram's Markdown parse mode doesn't render them (was showing as literal hash characters) — now uses **bold** text instead; added persona-level emoji guidance (light touch, one per key moment); `/report` now opens with a warm, on-persona line naming the game instead of starting cold.
- ✅ Phase 3: n8n installed locally (`npm install -g n8n`, no Docker) and the workflow (`n8n/board-game-concierge.workflow.json`) verified end-to-end against the real running FastAPI server via n8n's own CLI — all four routes (help/report/ask/recommend) confirmed working, including catching and fixing two real n8n runtime gotchas (blocked `$env` access in expressions; `localhost` resolving to IPv6 while `uvicorn` binds IPv4 only) and, separately, an n8n Cloud `127.0.0.1`-unreachable issue solved with a `cloudflared` tunnel (ephemeral URL — needs re-entry into the two... now three HTTP nodes whenever the tunnel restarts).
- ⬜ Not started: Phase 4 (deploy - the tunnel is a testing stopgap, not the durable answer). Also still open: wiring a real Telegram bot credential into the n8n workflow so it fires against live Telegram (only tested against synthetic trigger data so far, since that requires your bot token); an "n8n attribution" footer appearing on real Telegram messages that isn't from our workflow/code, likely an n8n Cloud plan-tier setting to track down separately.
