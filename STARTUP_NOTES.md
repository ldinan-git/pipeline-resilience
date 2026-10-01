# Startup Notes — Pipeline Resilience

## The Idea

AI-assisted data pipeline resilience. When pipelines break, the system
diagnoses the failure, applies a fix automatically if it's seen it before,
and escalates to a human if it hasn't. Every resolved incident makes the
system smarter.

## The Real Value Prop

Not "AI data quality" — that's too generic. The specific thing:
**accumulated organizational knowledge about data failures, made actionable automatically.**

When pipeline B breaks at 2am, the fix that someone applied to pipeline A
six months ago is applied automatically. No escalation, no on-call wake-up.

At LPL, 30 people were doing work that 2 people could do with the right system.
The gap was institutional knowledge living in people's heads, not in tooling.

## Why This Is Defensible

The corpus IS the moat. Not the embedding logic, not the tiered architecture —
those are just engineering. The moat is having seen 10,000 incidents that
competitors haven't seen.

General LLMs don't have:
- Org-specific context
- Cross-pipeline history within your org
- Vendor-specific error patterns (Protegrity license expiry, Informatica,
  custodian mainframe feeds)
- The fix that worked last time for THIS type of pipeline

## The Tiered Architecture

```
Tier 1 — Pipeline history    your own pipeline remembers its past
Tier 2 — Data analysis       LLM reads the actual failing rows
Tier 3 — Org knowledge       any pipeline in your org that saw this
Tier 4 — Cross-org corpus    anonymized patterns from other companies
Tier 5 — General LLM         fallback when nothing matches
```

Value concentrates at Tier 3 for the first sale.
Tier 4 is the long-term moat.

## Go-To-Market

**McKinsey is the path to the first 10 customers.**
Every data transformation engagement is an incident corpus entry.
You're inside F500 companies watching pipelines fail. Document everything.
By the time you leave you have two years of real enterprise incidents
that no competitor can replicate.

Early customers get free/discounted access in exchange for contributing
their resolved incidents to the shared corpus. Explicit trade, explicit
anonymization — they see exactly what leaves their environment.

## How to Build the Corpus

1. **Seed with your own knowledge** — 50-100 incidents from LPL you already
   know. Protegrity license expiry. Custodian encoding mismatches. Acquisition
   schema conflicts. Write them down structured. This is the demo.

2. **McKinsey generates it** — two years inside enterprise data environments.
   Document every incident privately, in your own system.

3. **Customers contribute in exchange for value** — first 5 customers get
   free access, their resolved incidents go into the shared corpus.
   Anonymization must be real and visible to earn trust in financial services.

## The Real Risk

dbt, Airflow, Databricks will add this as a feature once it proves out.
The window is: get design partners, build the corpus, become the standard
before the platforms get there.

The corpus built from real incidents is the thing they can't just copy.

## Competitive Landscape

- Monte Carlo, Bigeye — data observability, tell you WHAT is wrong, not WHY
- Great Expectations, dbt tests — rules-based, manual, no cross-org learning
- General LLMs — no org context, no incident history, no vendor-specific knowledge

None of them have the incident corpus + cross-org knowledge propagation.

## The Pitch (one sentence)

When your pipeline breaks at 2am, instead of waking up the senior engineer
who fixed this six months ago on a different pipeline, the system already
knows the fix — because it remembers everything your org has ever resolved.

## Technical Architecture (built so far)

- Pre-pipeline validation gate: raw data split into clean + quarantine
  before the pipeline runs. Pipeline always succeeds on clean data.
- LLM learns rules from known-good sample data (column stats → validation rules)
- Embedding similarity (nomic-embed-text) for cross-pipeline matching
- Tier 3 auto-applies fixes at cosine similarity > 0.92
- Corpus contributions anonymized: specific values stripped, structural
  error pattern preserved
- Local dev: SQLite + numpy similarity. Production path: pgvector + central API

## Timing

Second year MBA at Booth. McKinsey offer starts in ~8 months.
Plan: take McKinsey, use engagements to build corpus and validate,
leave in 2 years with seed corpus + network + savings runway.

Don't turn down McKinsey. Use it.
