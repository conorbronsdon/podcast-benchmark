# podcast-benchmark

A command-line tool that compares a podcast against a set of peers using only
public data. It produces two files: a `benchmark.json` with every raw number
and fetch timestamp, and a `report.md` with ranked comparison tables and a
short findings section.

It was built to generate the data half of a citable benchmark report for the
Chain of Thought podcast, but it works for any show. Point it at a config that
lists your podcast and a peer set, and it does the rest.

## What it measures

All of these come from public sources. None of them are estimated or invented.

- Catalog depth: total episode count (Apple `trackCount`, falling back to
  Podcast Index `episodeCount`).
- Publishing cadence: episodes per month over the trailing six months,
  computed from the live RSS feed.
- Average episode duration: mean minutes across episodes that report a
  duration in the feed.
- Transcript availability: percent of in-feed episodes that carry a
  `podcast:transcript` tag.
- Feed hygiene: a four-point checklist (artwork, categories, funding tag,
  locked tag) read from the RSS channel.
- Days since last episode: recency, from the newest feed pubdate.
- Apple rating count and average: read if Apple exposes them. See the
  limitations section. Today they come back as N/A.

## What it deliberately does NOT do

- It does not estimate or report download numbers. Downloads are private data.
  No public source has them, and guessing would make the report worthless.
- It does not scrape Apple Podcasts charts or Spotify. That is brittle and
  against their terms. Chart rank is out of scope.
- It does not rank a metric where some shows lack data. Those shows are marked
  N/A and excluded from that one ranking, and the exclusion is stated in the
  report.

The report leads with a sentence saying it benchmarks public signals, not
downloads, so a reader is never misled about what the numbers mean.

## Install

Requires Python 3.11 or newer.

```bash
pip install -r requirements.txt
```

`requests` is the only hard dependency. RSS parsing uses the standard library.
Config parsing uses a small built-in YAML reader, so PyYAML is optional. Install
it (`pip install PyYAML`) if you want a more robust parser.

## Usage

```bash
python -m podcast_benchmark.cli config.example.yaml -o output
```

This writes `output/benchmark.json` and `output/report.md`. Any source that
fails for a show degrades to N/A and is listed in a warnings section, never
dropped silently.

### Podcast Index (optional)

Podcast Index corroborates episode counts and categories, and helps for peers
whose Apple ID you do not have. Set two environment variables to enable it:

```bash
export PODCASTINDEX_API_KEY=your-key
export PODCASTINDEX_API_SECRET=your-secret
```

On Windows PowerShell:

```powershell
$env:PODCASTINDEX_API_KEY = "your-key"
$env:PODCASTINDEX_API_SECRET = "your-secret"
```

Get a free key at api.podcastindex.org. Without these the tool still runs and
falls back to Apple plus the raw RSS feed.

## Config format

A small YAML file with one subject and a list of peers. Each show needs a name
and a feed URL. An Apple ID is optional but unlocks catalog depth and genre.

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

`example-output/` holds a real run against `config.example.yaml`. It was
generated with read-only public GETs and committed so you can see actual
results without running anything. It was produced without Podcast Index
credentials, which is what a fresh clone gets, so the warnings show the
graceful fallback.

## How this feeds a /reports page

The JSON is the source of record. A reports page can read `benchmark.json`
directly to render tables, or embed `report.md` as-is. Because every number
carries a source and a fetch timestamp, the page can show "data as of" dates
and stay honest. Re-run the tool quarterly and the report regenerates with
fresh numbers and new timestamps, so the page stays current without manual
edits.

## Limitations worth knowing

- Apple's public lookup API no longer returns rating counts or averages. The
  tool reads those fields and reports N/A when absent, which is the current
  reality for every show. Ratings ranking is therefore omitted unless Apple
  restores the data.
- Cadence, duration, and transcript percentages are computed from the
  episodes a feed actually serves. Some hosts cap the feed to the most recent
  items. When every episode in a feed falls inside the six-month window, the
  cadence value is flagged with an asterisk and excluded from the cadence
  ranking, because the true rate may be higher than what the window shows.
- Transcript availability reflects the `podcast:transcript` RSS tag only. A
  show can publish transcripts on its website without emitting the tag, in
  which case it reads as 0 percent here. The metric measures feed-declared
  transcripts, not all transcripts that exist.
- Catalog depth from different sources can differ by a few episodes depending
  on trailers and crawl timing. The tool prefers Apple and records which
  source it used in the JSON.

## Tests

```bash
python -m pytest
```

Tests mock all network access. They cover cadence and duration computation
from a fixture feed, ranking with N/A handling, config parsing, and an
end-to-end report build.

## License

MIT.
