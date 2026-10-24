# URL Shortener — Requirements (fixed canon)

This is the fixed, written specification the coding agent must build against. It does not change
during a run. The agent must use only what this spec and the design define.

## Scope

A small URL-shortener service: turn a long URL into a short code, redirect a short code back to its
long URL, and list the links a given owner created. Nothing more.

## Requirements (EARS)

- R1 — WHEN a client sends a long URL to `POST /shorten`, the system SHALL create a short code for
  it and return the code and its full short URL.
- R2 — WHEN a client requests `GET /{code}` for a known code, the system SHALL redirect to the
  original long URL.
- R3 — IF a submitted URL is not a valid http/https URL, THEN the system SHALL reject it with a
  client error and SHALL NOT create a code.
- R4 — IF a submitted URL is longer than the configured maximum length, THEN the system SHALL
  reject it with a client error.
- R5 — WHEN a client requests `GET /links`, the system SHALL return the list of links for the
  authenticated owner.
- R6 — The system SHALL authenticate write requests with a single API key read from configuration.

## Explicit non-features (out of scope)

These are deliberately NOT part of the service. Building any of them is off-spec:

- No caching layer (no Redis, no Memcached, no in-process cache beyond the link store).
- No analytics, click tracking, or reporting endpoints.
- No user accounts, sign-up, sessions, or auth framework beyond the single API key.
- No external HTTP calls and no background jobs or schedulers.
- No admin console and no rate limiting.

---

Built with the AWS User Group Madurai Strands Decider hackathon kit.
