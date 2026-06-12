<div align="center">

# podcast-benchmark

Benchmark any podcast against a peer set using only public data. No download estimates, no scraping, no guesses.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11+-blue?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Podcast](https://img.shields.io/badge/Podcast-Chain_of_Thought-purple?style=flat-square)](https://chainofthought.show)
[![X](https://img.shields.io/badge/X-@ConorBronsdon-black?style=flat-square&logo=x)](https://x.com/ConorBronsdon)

</div>

---


A command-line tool that compares a podcast against a set of peers using only public data. It produces two files: a `benchmark.json` with every raw number and fetch timestamp, and a `report.md` with ranked comparison tables and a short findings section.

It was built to generate the data half of a citable benchmark report for the [Chain of Thought](https://chainofthought.show) podcast, but it works for any show. Point it at a config that lists your podcast and a peer set, and it does the rest. If you run a podcast and want an honest read on where you stand, this is for you.

## What it measures

All of these come from public sources. None of them are estimated or invented.

- Catalog depth: total episode count (Apple `trackCount`, falling back to Podcast Index `episodeCount`).
- Publishing cadence: episodes per month over the trailing six months, computed from the live RSS feed. Future-dated items are excluded (and warned about), and feeds whose oldest item falls inside the window are flagged as possibly truncated and left out of the cadence ranking.
- Average episode duration: mean minutes across episodes that report a duration in the feed.
- Transcript availability: percent of in-feed episodes that carry a `podcast:transcript` tag (any of the namespace URI variants seen in the wild).
- Feed hygiene: a four-point checklist read from the RSS channel: artwork (`itunes:image` or `image`), at least one `itunes:category`, a `podcast:funding` tag, and `podcast:locked` with the value `yes`. N/A when the feed could not be fetched or parsed.
- Days since last episode: recency, from the newest non-future feed pubdate.
- Apple rating count and average: read if Apple exposes them. See the limitations section. Today they come back as N/A.

## What it deliberately does NOT do

- It does not estimate or report download numbers. Downloads are private data. No public source has them, and guessing would make the report worthless.
- It does not scrape Apple Podcasts charts or Spotify. That is brittle and against their terms. Chart rank is out of scope.
- It does not rank a metric where some shows lack data. Those shows are marked N/A and excluded from that one ranking, and the exclusion is stated in the report.

The report leads with a sentence saying it benchmarks public signals, not downloads, so a reader is never misled about what the numbers mean.

## Install

Requires Python 3.11 or newer.

```bash
pip install -r requirements.txt
```

`requests` is the only hard dependency. RSS parsing uses the standard library. Config parsing uses a small built-in YAML reader, so PyYAML is optional. Install it (`pip install PyYAML`) if you want a more robust parser.

## Usage

```bash
python -m podcast_benchmark.cli config.example.yaml -o output
```

This writes `output/benchmark.json` and `output/report.md`. Any source that fails for a show degrades to N/A and is listed in a warnings section, never dropped silently.

### Regenerating the report from cached data

`benchmark.json` contains everything the report needs, so `report.md` can be re-rendered without touching the network:

```bash
python -m podcast_benchmark.cli --from-json output/benchmark.json -o output
```

This is the reproducibility path: anyone holding the JSON can regenerate the exact report, and rendering changes can be re-applied to old runs without refetching.

### Podcast Index (optional)

Podcast Index corroborates episode counts and categories, and helps for peers whose Apple ID you do not have. Set two environment variables to enable it:

```bash
export PODCASTINDEX_API_KEY=your-key
export PODCASTINDEX_API_SECRET=your-secret
```

On Windows PowerShell:

```powershell
$env:PODCASTINDEX_API_KEY = "your-key"
$env:PODCASTINDEX_API_SECRET = "your-secret"
```

Get a free key at api.podcastindex.org. Without these the tool still runs and falls back to Apple plus the raw RSS feed.

## Config format

A small YAML file with one subject and a list of peers. Each show needs a name and a feed URL. An Apple ID is optional but unlocks catalog depth and genre.

```yaml
subject:
  name: Chain of Thought
  feed_url: https://feeds.transistor.fm/chain-of-thought
  apple_id: 1776879655

peers:
  - name: Latent Space
    feed_url: https://api.substack.com/feed/podcast/1084089.rss
    apple_id: 1674008350
  - name: Practical AI
    feed_url: https://feeds.transistor.fm/practical-ai-machine-learning-data-science-llm
    apple_id: 1406537385
```

See `config.example.yaml` for the full peer set used in `example-output/`.

## Example output

`example-output/` holds a real run against `config.example.yaml`. It was generated with read-only public GETs and committed so you can see actual results without running anything. It was produced without Podcast Index credentials, which is what a fresh clone gets, so the warnings show the graceful fallback.

Here is the overview table from that run, an AI podcast peer set benchmarked against Chain of Thought:

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

The full run adds per-metric rankings, a findings section, the warnings list, and a methodology block with source URLs and fetch timestamps. See [`example-output/report.md`](example-output/report.md).

## How this feeds a /reports page

The JSON is the source of record. A reports page can read `benchmark.json` directly to render tables, or embed `report.md` as-is. Because every number carries a source and a fetch timestamp, the page can show "data as of" dates and stay honest. Re-run the tool quarterly and the report regenerates with fresh numbers and new timestamps, so the page stays current without manual edits.

## Limitations worth knowing

- Apple's public lookup API no longer returns rating counts or averages. The tool reads those fields and reports N/A when absent, which is the current reality for every show. Ratings ranking is therefore omitted unless Apple restores the data.
- Cadence, duration, and transcript percentages are computed from the episodes a feed actually serves. Some hosts cap the feed to the most recent items. When every episode in a feed falls inside the six-month window, the cadence value is flagged with an asterisk and excluded from the cadence ranking, because the true rate may be higher than what the window shows.
- Transcript availability reflects the `podcast:transcript` RSS tag only. A show can publish transcripts on its website without emitting the tag, in which case it reads as 0 percent here. The metric measures feed-declared transcripts, not all transcripts that exist.
- Catalog depth from different sources can differ by a few episodes depending on trailers and crawl timing. The tool prefers Apple and records which source it used in the JSON.

## Tests

```bash
python -m pytest
```

Tests mock all network access. They cover cadence and duration computation from a fixture feed, ranking with N/A handling, config parsing, and an end-to-end report build.

## Contributing

Issues and pull requests are welcome. If you hit a feed format the parser mishandles, or a public metric worth adding, open an issue with the feed URL and what you expected. Keep the bar the tool sets for itself: public sources only, no estimates, no scraping, and every number traceable to where it came from.

## About

Built and maintained by [Conor Bronsdon](https://github.com/conorbronsdon). I host the [Chain of Thought](https://chainofthought.show) podcast, which covers AI infrastructure, developer tools, and how practitioners actually use this stuff. This tool came out of the show's growth work: I wanted an honest, repeatable way to see where Chain of Thought stands against its peers without leaning on numbers nobody can verify.

Companion tools:

- [op3-mcp](https://github.com/conorbronsdon/op3-mcp): your own download, geography, and app analytics through OP3, the part this benchmark deliberately leaves out.
- [podcastindex-mcp](https://github.com/conorbronsdon/podcastindex-mcp): the Podcast Index MCP server, the same API this tool uses to corroborate episode counts.
- [ai-tools-for-creators](https://github.com/conorbronsdon/ai-tools-for-creators): a curated list of AI skills and MCP servers for people who ship ideas for a living.

More at [chainofthought.show](https://chainofthought.show) and on [X](https://x.com/ConorBronsdon).

---

## Disclaimer

*All views, opinions, and statements expressed on this account are solely my own and are made in my personal capacity. They do not reflect, and should not be construed as reflecting, the views, positions, or policies of Modular. This account is not affiliated with, authorized by, or endorsed by Modular in any way.*

## License

MIT
