Lessons already paid for
 1. Every HTTP call sends an explicit User-Agent (Upstox's Cloudflare blocks Python's
   default
   urllib User-Agent with HTTP 403 / Error 1010).
 2. The access token is read from a 600-permission file at connect time and re-read once
   on
   401/403. No environment handoffs. Never log or print token values.
 3. Never write to disk inside the websocket receive loop: receive -> bounded queue ->
   batched
   writer thread. (Inline writes caused 70 s lag and 43 disconnects in one session.)
 4. Log the status code and sanitized body of every auth/connect failure.
 5. Preflight HARD gates: token missing/expired, or feed-authorize non-200 after retries.
   Everything else is a SOFT alert. Recording is read-only and never blocked by soft
   checks.
 6. One Upstox websocket client owns the feed. Others use REST or read the recorder's
   output.
 7. NSE holiday calendar respected by every scheduled job.
 8. Timestamps tz-aware, compared in UTC, displayed in Asia/Kolkata.
 9. Every derived value carries an availability timestamp; nothing uses data stamped after it.
   Structures (swings, BOS, FVG, sweeps, exhaustion) exist only after their confirming bars
   close.
10. The live feed is snapshot-based: trade size, aggressor side, delta and footprint are
   ESTIMATES with a confidence field. Bar-based history (VWAP, volume profile) is
   APPROXIMATE.
11. Gaps, resets, duplicates and out-of-order messages are flagged and counted, never
   dropped
   silently.
12. Layers have roles, not votes. A layer stays only if a matched ablation shows it improves
   results on unseen data after costs.


How agents work
   Max 2 attempts or 90 minutes per problem; then docs/stuck/<task>.md and move on.
   Tests first: hand-built sequences with known answers for every metric and structure.
   Truncation test for everything time-based: the value at t is unchanged when data after t
   is removed.
   No network, keys or live calls in Cloud tasks; use the simulators.
   One task per commit ("T##: ..."); docs/ROADMAP.md status updated after each.
   Never weaken or delete a test to make it pass.
