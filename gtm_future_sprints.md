# MVP Go-Live Sprints

These are the remaining launch-readiness sprints needed before the MVP can be used by real users at game night.

## Sprint 1 - Stable Core Flows

- Goal: make the main Telegram commands work consistently end to end.
- Target user/buyer: the host of a recurring game night.
- Channel or motion: direct testing in the real Telegram chat.
- Key deliverable: reliable `/help`, `/ask`, `/tips`, `/recommend`, `/games`, and `/reset` flows with clear fallback behavior.
- Success metric: no broken command paths in several consecutive real chat sessions.

## Sprint 2 - Context and Clarification

- Goal: make the bot follow the current game context correctly.
- Target user/buyer: the same game-night host and players who ask follow-up questions.
- Channel or motion: in-chat usage during actual game conversations.
- Key deliverable: session memory that keeps the active game stable, plus clarification when a different game is mentioned.
- Success metric: follow-up commands keep the right game context and ambiguous cases trigger clarification instead of wrong answers.

## Sprint 3 - Launch Packaging

- Goal: make the MVP understandable and easy to adopt.
- Target user/buyer: first-time users in the host's group.
- Channel or motion: a simple onboarding message, README, and n8n workflow setup.
- Key deliverable: clear setup docs, stable backend URL handling, and a predictable first-use experience.
- Success metric: a new user can start using the bot without direct developer help.
