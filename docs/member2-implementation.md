# Member 2 implementation handoff

## Scope implemented in this working branch

The implementation follows `plans/member-2-assignment.md` and consumes the version
manifest written by Member 1. It does not alter Member 1's metadata/version resolver,
Member 3's Semantic Scholar implementation, or Member 4's schemas.

### Source download and extraction

- `src/downloader.py`: explicit versioned-ID validation, arXiv export source endpoint,
  descriptive User-Agent, minimum 3-second pacing, bounded retry, streamed temporary
  output, SHA-256, atomic promotion, and checksum-verified resume.
- `src/extractor.py`: gzip/tar and gzip-single-source detection; `.tex`/`.bib` allowlist;
  regular-file-only extraction; traversal, absolute/drive path and collision checks;
  size/member-count limits; byte-for-byte copy; per-file SHA-256; atomic version folder.
- `src/source_pipeline.py`: consumes `version_tasks.csv`, isolates each version failure,
  and writes one source status record for every selected version.
- `crawl-sources`: CLI command wired into `src/cli.py`.

### First-pass hierarchy parser

- `src/latex_parser.py`: comment/verbatim-aware root detection, transitive input graph,
  deterministic diagnostics for multiple roots/missing files/cycles/repeated includes,
  source-order input expansion, section stack, list components/items, block math,
  figures/tables, references exclusion, acknowledgements inclusion and conservative
  sentence splitting.
- `src/parse_pipeline.py`: processes every source status, retains `no_tex_bib` as an
  empty version record, creates shared per-publication element IDs across versions,
  and writes version-specific hierarchy edges.
- `parse-sources`: CLI command wired into `src/cli.py`.

## Output layout

```text
<data-dir>/
├── raw/arxiv_sources/<arxiv_id>/<versioned_id>/
│   ├── source.archive
│   └── download_status.json
├── corpus/tex/<arxiv_id>/<versioned_id>/
│   └── only .tex and .bib files
├── manifests/
│   ├── source_status.jsonl
│   └── source_summary.json
└── parsed/
    ├── elements.jsonl
    ├── hierarchy.jsonl
    ├── parse_status.jsonl
    └── parse_summary.json
```

## Offline verification

Command:

```bash
python -m pytest -q tests/test_downloader.py tests/test_extractor.py \
  tests/test_latex_parser.py tests/test_parse_pipeline.py
```

Result in the current working runtime: **22 passed**.

The full repository test suite could not be collected in this runtime because
`pyarrow` is not installed and the runtime cannot reach the package index. The repository
already declares `pyarrow` in `requirements.txt`; run the full suite after installing the
project requirements in the intended Python/Colab environment.

## Known limitations / review required before official full-corpus run

This is a working first pass, not a claim that all TeX dialects are handled:

1. LaTeX macro expansion, custom class/package semantics, complex nested brace parsing,
   and some nonstandard include mechanisms are not implemented.
2. The hierarchy parser keeps source-file provenance at the root level; exact per-leaf
   source spans need a follow-up source-map implementation.
3. Sentence splitting uses conservative heuristics. It needs manual spot-checking on a
   representative pilot set before corpus-wide accuracy can be claimed.
4. BibTeX extraction, field unionization, citation-key rewriting and final M2 Parquet
   table export remain a downstream integration task.
5. Live arXiv source download has not been run against the 5,000 assigned publications
   in this environment. Do a small approved pilot first and respect the three-second
   request pacing.

## Branch / Git handoff

Target branch: `member-2/source-parsing`.

The supplied ZIP contains the Member 1 branch snapshot, not a Git working tree with the
remote history. Therefore this deliverable is a source patch/worktree only; it has not
been committed or pushed to GitHub. The branch owner should create/check out the target
branch from the shared remote, copy the changed files, run the full test suite, and open
a pull request for Member 1/M4 review.
