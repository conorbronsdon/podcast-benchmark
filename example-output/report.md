# Podcast Benchmark: Chain of Thought vs peers

Generated 2026-06-11T07:26:39Z by podcast-benchmark v0.1.0.

This report benchmarks PUBLIC signals only: catalog depth, publishing cadence, episode duration, transcript availability, and feed hygiene. It does not estimate downloads or chart rank. Those are private or ToS-restricted and are out of scope by design.

## Overview

| Show | Catalog eps | Eps/month (6mo) | Avg min | Transcripts % | Days since last | Hygiene /4 | Apple rating |
| ---- | ---- | ---- | ---- | ---- | ---- | ---- | ---- |
| Chain of Thought (subject) | 62 | 2.62 | 45.4 | 98.4 | 7 | 3/4 | N/A |
| Latent Space | 207 | 8.85 | 71.1 | 0.0 | 6 | 2/4 | N/A |
| Practical AI | 361 | 3.28 | 46.4 | 15.2 | 6 | 2/4 | N/A |
| The TWIML AI Podcast | 787 | 1.8 | 46.3 | 0.0 | 1 | 2/4 | N/A |
| Gradient Dissent | 137 | 1.15 | 53.6 | 0.0 | 15 | 2/4 | N/A |
| AI Engineering Podcast | 79 | 1.31 | 53.8 | 93.7 | 106 | 3/4 | N/A |
| No Priors | 166 | 3.77 | 38.6 | 0.0 | 0 | 2/4 | N/A |
| The Cognitive Revolution | 349 | 8.03 | 98.0 | 0.0 | 0 | 2/4 | N/A |

`*` cadence computed from a feed window that may be truncated by the host (every episode in the feed falls inside the 6-month window), so the true rate may be higher. These values are reported but excluded from cadence ranking.

## Rankings

### Catalog depth (episodes)

| Rank | Show | Value |
| ---- | ---- | ----- |
| 1 | The TWIML AI Podcast | 787 |
| 2 | Practical AI | 361 |
| 3 | The Cognitive Revolution | 349 |
| 4 | Latent Space | 207 |
| 5 | No Priors | 166 |
| 6 | Gradient Dissent | 137 |
| 7 | AI Engineering Podcast | 79 |
| 8 | Chain of Thought (subject) | 62 |

### Publishing cadence (episodes/month, trailing 6 months)

| Rank | Show | Value |
| ---- | ---- | ----- |
| 1 | Latent Space | 8.85 |
| 2 | The Cognitive Revolution | 8.03 |
| 3 | No Priors | 3.77 |
| 4 | Practical AI | 3.28 |
| 5 | Chain of Thought (subject) | 2.62 |
| 6 | The TWIML AI Podcast | 1.8 |
| 7 | AI Engineering Podcast | 1.31 |
| 8 | Gradient Dissent | 1.15 |

### Transcript availability

| Rank | Show | Value |
| ---- | ---- | ----- |
| 1 | Chain of Thought (subject) | 98.4% |
| 2 | AI Engineering Podcast | 93.7% |
| 3 | Practical AI | 15.2% |
| 4 | Latent Space | 0.0% |
| 5 | The TWIML AI Podcast | 0.0% |
| 6 | Gradient Dissent | 0.0% |
| 7 | No Priors | 0.0% |
| 8 | The Cognitive Revolution | 0.0% |

### Feed hygiene

| Rank | Show | Value |
| ---- | ---- | ----- |
| 1 | Chain of Thought (subject) | 3/4 |
| 2 | AI Engineering Podcast | 3/4 |
| 3 | Latent Space | 2/4 |
| 4 | Practical AI | 2/4 |
| 5 | The TWIML AI Podcast | 2/4 |
| 6 | Gradient Dissent | 2/4 |
| 7 | No Priors | 2/4 |
| 8 | The Cognitive Revolution | 2/4 |

### Apple ratings count

No show had data for this metric. Ranking omitted.

## Findings

- Catalog depth: 62 episodes, ranked 8 of 8 shows with data.
- Publishing cadence: 2.62 episodes/month over the trailing 6 months, ranked 5 of 8 shows with non-truncated feed windows.
- Transcript availability: 98.4% of in-feed episodes, ranked 1 of 8.
- Feed hygiene: 3/4 signals present (artwork, categories, locked_tag; missing: funding_tag), ranked 1 of 8.
- Average episode duration in the feed window: 45.4 minutes.
- Days since last episode: 7.
- Apple ratings: N/A for all shows (Apple's public API does not expose ratings counts).

## Warnings

- [Chain of Thought] apple: ratings not exposed by public API for id 1776879655 (expected)
- [Chain of Thought] podcastindex: skipped (PODCASTINDEX_API_KEY / PODCASTINDEX_API_SECRET unset)
- [Latent Space] apple: ratings not exposed by public API for id 1674008350 (expected)
- [Latent Space] podcastindex: skipped (PODCASTINDEX_API_KEY / PODCASTINDEX_API_SECRET unset)
- [Practical AI] apple: ratings not exposed by public API for id 1406537385 (expected)
- [Practical AI] podcastindex: skipped (PODCASTINDEX_API_KEY / PODCASTINDEX_API_SECRET unset)
- [The TWIML AI Podcast] apple: ratings not exposed by public API for id 1116303051 (expected)
- [The TWIML AI Podcast] podcastindex: skipped (PODCASTINDEX_API_KEY / PODCASTINDEX_API_SECRET unset)
- [Gradient Dissent] apple: ratings not exposed by public API for id 1504567418 (expected)
- [Gradient Dissent] podcastindex: skipped (PODCASTINDEX_API_KEY / PODCASTINDEX_API_SECRET unset)
- [AI Engineering Podcast] apple: ratings not exposed by public API for id 1626358243 (expected)
- [AI Engineering Podcast] podcastindex: skipped (PODCASTINDEX_API_KEY / PODCASTINDEX_API_SECRET unset)
- [No Priors] apple: ratings not exposed by public API for id 1668002688 (expected)
- [No Priors] podcastindex: skipped (PODCASTINDEX_API_KEY / PODCASTINDEX_API_SECRET unset)
- [The Cognitive Revolution] apple: ratings not exposed by public API for id 1669813431 (expected)
- [The Cognitive Revolution] podcastindex: skipped (PODCASTINDEX_API_KEY / PODCASTINDEX_API_SECRET unset)

## Methodology

Sources, fetched at the timestamps recorded in benchmark.json:
- Apple iTunes lookup API (https://itunes.apple.com/lookup)
- Podcast Index API (https://api.podcastindex.org)
- Direct RSS feed fetch

Cadence window: trailing 183 days.

- Apple's public lookup API does not expose ratings; rating fields are N/A unless Apple restores them.
- Cadence, duration, and transcript percentages are computed from the episodes present in the live RSS feed window.
- Catalog depth uses Apple trackCount, falling back to Podcast Index episodeCount.
- Downloads and chart positions are private/ToS-restricted and are deliberately not collected.
