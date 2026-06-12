# Security

This tool makes read-only GET requests to public sources (RSS feeds, Apple lookup, Podcast Index) and writes local files. The main things worth protecting are your optional Podcast Index credentials, which are read from the environment and never written to output, and safe handling of untrusted feed XML.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting: open the **Security** tab on this repo and click **Report a vulnerability**. Do not open a public issue for security problems.

I aim to respond within a week. Credit goes to the reporter in the fix notes unless you prefer otherwise.
