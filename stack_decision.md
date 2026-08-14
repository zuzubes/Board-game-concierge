# Stack Decision

## Primary Stack

**n8n** for workflow orchestration
**telegram** for user interface to interact with the application
**search api** for getting tips and strategies


## Why n8n fits this problem

This product is a Telegram-first concierge with a simple operational flow:

- receive a chat command
- parse the intent
- call one backend endpoint
- send the reply back

That is exactly the kind of integration-heavy, event-driven workflow n8n handles well. It keeps the Telegram routing visible, makes retries and fallbacks easy to manage, and lets us ship quickly without building a custom orchestrator.

For this MVP, the problem is not complex agent reasoning. It is orchestration, external API handling, and predictable delivery into Telegram. n8n fits that shape better than a heavier agent framework.

## Why Telegram fits the product

Telegram is the right user surface for this MVP because the bot is meant for a real game table, not a general consumer app.

- It is already where the chat happens.
- Slash commands make the interaction model simple.
- It supports fast back-and-forth during game setup and play.
- It avoids building a separate web UI before the product proves value.

## Why Pinecone fits the product

Pinecone is the retrieval layer because the concierge needs fast, managed vector search over imported rulebooks.

- It stores rulebook chunks with metadata cleanly.
- It removes the need to run a separate vector database locally.
- It fits the small-to-medium corpus size of this MVP.
- It supports the grounding requirement without extra infra overhead.

## Why the search APIs fit the product

The strategy-tip feature uses SerpApi, Serper, and Tavily because external search providers were the practical alternative once the original community-data plan stopped being viable.

- BGG XML API required admin/registration approval that was not available for this project.
- Reddit changed how developers access community threads, so that path was no longer a dependable source for strategy discussion.
- Search APIs provide a fallback chain and keep the tip feature usable even if one provider fails.
- They also let the bot remain lightweight: the tips feature can fail over without adding more bespoke scraping or API-specific logic.

## Why LangGraph is secondary for this MVP

**LangGraph** is the better choice when the product needs deeper branching, multi-step planning, structured agent state, or conditional tool routing.

That is useful later for:

- richer multi-turn conversations
- more advanced recommendation flows
- confidence-based routing
- query classification across several decision steps

But those needs are not the main bottleneck in this MVP. Adding LangGraph now would increase complexity before the product has proven its core Telegram workflow.

## MVP Decision

- **Primary:** n8n
- **Secondary:** LangGraph

We keep the MVP on n8n because it is simpler, faster to operate, and a better fit for Telegram orchestration.
We keep LangGraph as the later-stage upgrade path once the concierge needs more agentic branching than this MVP requires.
