# RAG design: corpus, chunking, embeddings, retrieval

## The corpus is designed, not scraped

13 markdown files: company.md plus one per service line, each with YAML
frontmatter carrying service_line, and a consistent section structure
(Overview, Services & pricing, Process, FAQs, Notes). Two authoring decisions
paid off downstream:

- Cross-service links were planted deliberately (ice dams in the gutters FAQ
  point at insulation; roofing notes mention the solar bundle). Retrieval can
  only surface connections that exist in the text.
- Sections were written to land near the chunk-size target, which is what
  makes the simple chunking strategy correct here.

## Chunking: structure-aware, and why not fancier

The ladder, simplest to most complex: fixed-size with overlap, recursive
splitting, structure-aware (chosen), semantic chunking, LLM-based chunking.

We split at markdown `##` headings with a ~1,200-character cap (about 300
tokens), subsplitting long sections at paragraph breaks. No overlap needed:
sections are self-contained because an author made them so. Semantic chunking
exists to find meaning boundaries in documents that do not declare them
(transcripts, scraped pages); paying for it on authored markdown is buying a
metal detector to find a fence you built yourself. On a messy client corpus
this decision flips, and that is the first thing to re-examine.

One trick with outsized effect: every chunk's stored text is prefixed with
its document title and section heading. "Diagnostic: $89" is ambiguous;
"Water Heaters | Services & pricing: Diagnostic: $89" embeds better and
answers better when retrieved alone.

## Embeddings

BAAI/bge-small-en-v1.5 via FastEmbed: local, free, 384 dimensions, plenty for
a 70-chunk corpus. Two API details that silently degrade quality if missed:

- Documents embed with passage_embed, queries with query_embed. bge models
  were trained with a query prefix and query_embed applies it; using plain
  embed for queries does not error, it just quietly worsens ranking.
- Batch the embedding calls. FastEmbed batches internally; per-chunk loops
  are 10x slower for nothing.

Upgrade path when corpus or quality demands grow: a larger open model or a
hosted embedding API, plus a re-ranker on the top 20. Neither earned its cost
at this scale.

## Qdrant configuration

One collection, cosine distance, 384-d vectors, and a keyword payload index
on service_line, which is what makes filtered search indexed rather than
scanned. Filtering uses MatchAny over the routed service line PLUS company,
because financing, membership, hours, and service-area facts live in
company.md and legitimately answer questions asked "about" any trade. A
strict single-line filter blinds the bot to its own policies; this was
caught in testing when "can I finance that?" needed the FlexPay chunk.

## The score-threshold finding (read this before trusting thresholds)

Measured on this corpus: legitimate hits scored 0.52 to 0.79; irrelevant hits
for an out-of-scope question (swimming pools) scored 0.60 to 0.61. The ranges
overlap. No absolute cutoff can both keep the FlexPay chunk (0.609) and drop
the pool noise (0.614). bge-small compresses everything into a narrow score
band, and this is typical of embedding models generally.

Consequence: MIN_SCORE (0.45) is a coarse floor, knowingly weak, and the
system's honesty rests on three layers instead:

1. The router classifies out-of-scope before retrieval ever runs.
2. Retrieval returns an empty list rather than junk when nothing clears the
   floor, and skips entirely for chitchat and out-of-scope intents.
3. The answer prompt forbids answering beyond the provided context and
   offers a human instead.

## Refresh strategy: full rebuild, on purpose

ingest.py drops and recreates the collection every run. At 13 files this
takes seconds and is guaranteed correct. The alternative (incremental upsert
with deterministic IDs) is the right answer at scale but carries the stale
chunk trap: edit a doc from 10 chunks down to 7 and the orphaned 3 keep
answering questions forever unless you delete by source first. Every RAG
system that mysteriously answers from old docs has this bug. We chose the
strategy that cannot have it.

## Verification

The ingest script ends with two checks that gate P0: a filtered query must
return only the target service line with the pricing section on top, and an
unfiltered paraphrase with no shared keywords ("my sink is leaking") must
rank the right trade first on pure semantic similarity.
