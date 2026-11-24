#!/usr/bin/env python3
"""Interactive terminal tool for Milestone 3 manual reference labeling (MS3-M4-T01).

Enforces:
- Candidates are strictly scoped to the same publication's `references` rows.
- Every BibTeX entry of each selected publication is labeled (normalized ref_arxiv_id or None).
- Preserves existing labels across different `--paper` runs (never silently drops saved papers).
- Atomic checkpoint save after each edit; supports resume, review when 100% done,
  Enter-to-keep existing label, Back (`b`), ShowAll (`a`), Notes (`n`), and Quit (`q`).
- Built-in quota & integrity validation (`--verify-only` or automatically at finish).

Usage:
    python scripts/label_tool.py --data-dir D:/code/nmkhdl-project-1-data-member-4 --member member-4
    python scripts/label_tool.py --data-dir D:/code/nmkhdl-project-1-data-member-2 --member member-2 --list-candidates
    python scripts/label_tool.py --data-dir D:/code/nmkhdl-project-1-data-member-2 --member member-2
    python scripts/label_tool.py --data-dir D:/code/nmkhdl-project-1-data-member-2 --member member-2 --verify-only
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.model import HeuristicRanker
from src.normalize import normalize_arxiv_id
from src.storage import BIBTEX_SCHEMA, PAPERS_SCHEMA, REFERENCES_SCHEMA, read_sharded_parquet


DEFAULT_MEMBER4_PAPERS = [
    "2409.16241",
    "2409.13701",
    "2409.15283",
    "2409.14143",
    "2409.15869",
]


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _load_existing(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"selected_papers": [], "labels": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_labeled_papers(payload: dict[str, Any]) -> set[str]:
    papers: set[str] = set()
    for raw in payload.get("selected_papers") or []:
        if norm := normalize_arxiv_id(raw):
            papers.add(norm)
    for rec in payload.get("labels") or []:
        if norm := normalize_arxiv_id(rec.get("arxiv_id")):
            papers.add(norm)
    return papers


def _load_excluded_papers(exclude_paths: list[Path]) -> tuple[set[str], str | None]:
    excluded: set[str] = set()
    for raw_path in exclude_paths:
        path = raw_path.expanduser().resolve()
        if not path.is_file():
            return set(), f"--exclude-labels file not found: {path}"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return set(), f"Failed to read --exclude-labels file {path}: {exc}"
        excluded.update(_extract_labeled_papers(payload))
    return excluded, None


def _select_candidate_papers(
    *,
    bib_by_pub: dict[str, list[dict[str, Any]]],
    ref_by_pub: dict[str, list[dict[str, Any]]],
    excluded_papers: set[str],
    min_entries: int,
    min_refs: int,
) -> list[str]:
    eligible: list[tuple[int, int, str]] = []
    for aid, entries in bib_by_pub.items():
        if aid in excluded_papers or len(entries) < min_entries:
            continue
        ref_count = len(ref_by_pub.get(aid, []))
        if ref_count < min_refs:
            continue
        eligible.append((len(entries), -ref_count, aid))
    eligible.sort()
    return [aid for _, _, aid in eligible]


def _format_authors(authors: list[str] | None, limit: int = 4) -> str:
    if not authors:
        return "(none)"
    if len(authors) <= limit:
        return ", ".join(authors)
    return ", ".join(authors[:limit]) + f" (+{len(authors) - limit} more)"


def _rank_candidates_with_info(
    entry: dict[str, Any],
    refs: list[dict[str, Any]],
    ranker: HeuristicRanker,
) -> list[tuple[dict[str, Any], float]]:
    scored = []
    for ref in refs:
        score = ranker.score_pair(entry, ref)
        scored.append((ref, score))
    scored.sort(key=lambda item: (-item[1], normalize_arxiv_id(item[0].get("ref_arxiv_id")) or ""))
    return scored


def _dedupe_bibtex_rows(rows: list[dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], int]:
    bib_by_pub: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_pairs: set[tuple[str, str]] = set()
    dup_count = 0
    for r in rows:
        aid = normalize_arxiv_id(r.get("arxiv_id"))
        ckey = str(r.get("citation_key", ""))
        if not aid:
            continue
        if (aid, ckey) in seen_pairs:
            dup_count += 1
            continue
        seen_pairs.add((aid, ckey))
        bib_by_pub[aid].append(r)
    return bib_by_pub, dup_count


def _dedupe_reference_rows(rows: list[dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], int]:
    ref_by_pub: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_pairs: set[tuple[str, str]] = set()
    dup_count = 0
    for r in rows:
        aid = normalize_arxiv_id(r.get("arxiv_id"))
        rid = normalize_arxiv_id(r.get("ref_arxiv_id"))
        if not aid or not rid:
            continue
        if (aid, rid) in seen_pairs:
            dup_count += 1
            continue
        seen_pairs.add((aid, rid))
        ref_by_pub[aid].append(r)
    return ref_by_pub, dup_count


def _collect_used_refs(
    records_by_pair: dict[tuple[str, str], dict[str, Any]],
    aid: str,
    current_ckey: str,
) -> dict[str, list[str]]:
    used_refs: dict[str, list[str]] = defaultdict(list)
    for (a, k), rec in sorted(records_by_pair.items()):
        norm_gt = normalize_arxiv_id(rec.get("groundtruth_arxiv_id"))
        if a == aid and k != current_ckey and norm_gt:
            used_refs[norm_gt].append(k)
    return used_refs


def verify_labels(
    *,
    payload: dict[str, Any],
    selected_papers: list[str],
    bib_by_pub: dict[str, list[dict[str, Any]]],
    ref_by_pub: dict[str, list[dict[str, Any]]],
) -> tuple[bool, list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    labels = payload.get("labels", [])
    by_pair = {(normalize_arxiv_id(r.get("arxiv_id")), str(r.get("citation_key", ""))): r for r in labels}

    unique_papers = list(dict.fromkeys(normalize_arxiv_id(p) for p in selected_papers if normalize_arxiv_id(p)))
    if len(unique_papers) < 5:
        errors.append(f"Selected {len(unique_papers)} papers, expected at least 5.")

    total_entries = 0
    for aid in unique_papers:
        entries = bib_by_pub.get(aid, [])
        if len(entries) < 20:
            errors.append(f"Paper {aid} has only {len(entries)} BibTeX entries (requires >= 20).")
        valid_refs = {
            norm
            for r in ref_by_pub.get(aid, [])
            if (norm := normalize_arxiv_id(r.get("ref_arxiv_id")))
        }
        assigned_refs: dict[str, list[str]] = defaultdict(list)
        missing_keys = []
        for e in entries:
            ckey = str(e["citation_key"])
            rec = by_pair.get((aid, ckey))
            if rec is None:
                missing_keys.append(ckey)
                continue
            total_entries += 1
            raw_gt = rec.get("groundtruth_arxiv_id")
            if raw_gt is not None and str(raw_gt).strip() != "":
                gt = normalize_arxiv_id(raw_gt)
                if not gt:
                    errors.append(f"Paper {aid} key '{ckey}': malformed groundtruth_arxiv_id {raw_gt!r}.")
                elif gt not in valid_refs:
                    errors.append(f"Paper {aid} key '{ckey}': groundtruth '{gt}' not in same-paper references.")
                else:
                    assigned_refs[gt].append(ckey)
        if missing_keys:
            errors.append(f"Paper {aid}: {len(missing_keys)} unlabeled entries (e.g. {missing_keys[:3]}).")
        for gt, keys in assigned_refs.items():
            if len(keys) > 1:
                warnings.append(f"Paper {aid}: ref '{gt}' assigned to multiple keys {keys}.")

    if total_entries < 100:
        errors.append(f"Total labeled entries is {total_entries}, expected >= 100.")

    return len(errors) == 0, errors, warnings


def _build_payload(
    *,
    member: str,
    all_papers: list[str],
    records_by_pair: dict[tuple[str, str], dict[str, Any]],
    bib_by_pub: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    ordered_papers = list(dict.fromkeys(normalize_arxiv_id(p) for p in all_papers if normalize_arxiv_id(p)))
    ordered_labels: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()
    pub_summary = []

    for aid in ordered_papers:
        entries = sorted(bib_by_pub.get(aid, []), key=lambda r: str(r["citation_key"]))
        labeled_in_pub = 0
        matched_in_pub = 0
        for e in entries:
            ckey = str(e["citation_key"])
            rec = records_by_pair.get((aid, ckey))
            if rec is not None:
                ordered_labels.append(rec)
                seen_pairs.add((aid, ckey))
                labeled_in_pub += 1
                if rec.get("groundtruth_arxiv_id"):
                    matched_in_pub += 1
        pub_summary.append({
            "arxiv_id": aid,
            "method": "manual",
            "labeled_by": member,
            "entries_count": len(entries),
            "labeled_count": labeled_in_pub,
            "matched_count": matched_in_pub,
        })

    # Preserve any stray existing labels not in ordered_papers so nothing is silently lost
    for pair in sorted(records_by_pair.keys() - seen_pairs):
        ordered_labels.append(records_by_pair[pair])

    return {
        "member_id": member,
        "selected_papers": ordered_papers,
        "updated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "publications": pub_summary,
        "labels": ordered_labels,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Interactive M3 manual labeling tool.")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--member", default="member-4")
    parser.add_argument("--paper", action="append", default=[], help="Specify paper ID (repeatable).")
    parser.add_argument("--num-papers", type=int, default=5, help="Number of papers to auto-pick (default: 5).")
    parser.add_argument("--min-entries", type=int, default=20, help="Min BibTeX entries per auto-picked paper (default: 20).")
    parser.add_argument("--min-refs", type=int, default=5, help="Min arXiv references per auto-picked paper (default: 5).")
    parser.add_argument(
        "--auto-pick",
        action="store_true",
        help="Auto-pick new unlabeled eligible papers even if output already has papers.",
    )
    parser.add_argument(
        "--exclude-labels",
        action="append",
        type=Path,
        default=[],
        help="Existing manual_labels JSON file(s) whose papers should be excluded (repeatable).",
    )
    parser.add_argument(
        "--list-candidates",
        action="store_true",
        help="List eligible unlabeled candidate papers in --data-dir and exit.",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()

    if args.num_papers < 1:
        print(f"[ERROR] --num-papers must be >= 1, got {args.num_papers}", file=sys.stderr)
        return 2
    if args.min_entries < 1 or args.min_refs < 0:
        print(
            f"[ERROR] Invalid thresholds: --min-entries={args.min_entries}, --min-refs={args.min_refs}",
            file=sys.stderr,
        )
        return 2

    excluded_from_files, exclude_err = _load_excluded_papers(args.exclude_labels)
    if exclude_err:
        print(f"[ERROR] {exclude_err}", file=sys.stderr)
        return 2

    data_dir = args.data_dir.expanduser().resolve()
    output_path = (args.output or (data_dir / "matching" / "manual_labels.json")).expanduser().resolve()

    existing = _load_existing(output_path)
    existing_papers = [
        norm for p in (existing.get("selected_papers") or []) if (norm := normalize_arxiv_id(p))
    ]
    existing_labeled = _extract_labeled_papers(existing)

    if args.verify_only and not args.list_candidates and not args.paper and not existing_papers:
        print(f"[ERROR] No existing labels found at {output_path}", file=sys.stderr)
        return 1

    print("Loading tables (papers, bibtex, references)...", flush=True)
    papers_map = {
        normalize_arxiv_id(r["arxiv_id"]): (r.get("title") or "")
        for r in read_sharded_parquet(data_dir / "tables" / "papers", PAPERS_SCHEMA).to_pylist()
        if normalize_arxiv_id(r.get("arxiv_id"))
    }
    bib_by_pub, dup_bib_count = _dedupe_bibtex_rows(
        read_sharded_parquet(data_dir / "tables" / "bibtex", BIBTEX_SCHEMA).to_pylist()
    )
    if dup_bib_count:
        print(
            f"[WARN] Deduplicated {dup_bib_count} duplicate (arxiv_id, citation_key) row(s) in tables/bibtex.",
            file=sys.stderr,
        )
    ref_by_pub, dup_ref_count = _dedupe_reference_rows(
        read_sharded_parquet(data_dir / "tables" / "references", REFERENCES_SCHEMA).to_pylist()
    )
    if dup_ref_count:
        print(
            f"[WARN] Deduplicated {dup_ref_count} duplicate (arxiv_id, ref_arxiv_id) row(s) in tables/references.",
            file=sys.stderr,
        )

    if args.list_candidates:
        pool_excluded = excluded_from_files | existing_labeled
        candidates = _select_candidate_papers(
            bib_by_pub=bib_by_pub,
            ref_by_pub=ref_by_pub,
            excluded_papers=pool_excluded,
            min_entries=args.min_entries,
            min_refs=args.min_refs,
        )
        show_n = max(20, args.num_papers)
        print(
            f"Found {len(candidates)} eligible unlabeled paper(s) in {data_dir} "
            f"(min_entries={args.min_entries}, min_refs={args.min_refs}, excluded={len(pool_excluded)}):"
        )
        for aid in candidates[:show_n]:
            title = (papers_map.get(aid) or "")[:60]
            print(f"  {aid} | bib={len(bib_by_pub[aid]):3d} | refs={len(ref_by_pub.get(aid, [])):3d} | {title}")
        return 0

    if args.paper:
        invalid_papers = [p for p in args.paper if not normalize_arxiv_id(p)]
        if invalid_papers:
            print(f"[ERROR] Invalid --paper ID(s): {invalid_papers}", file=sys.stderr)
            return 2
        active_papers = list(dict.fromkeys(
            norm for p in args.paper if (norm := normalize_arxiv_id(p))
        ))
        overlap_excluded = [p for p in active_papers if p in excluded_from_files]
        if overlap_excluded:
            print(
                f"[ERROR] Paper ID(s) already present in --exclude-labels: {overlap_excluded}",
                file=sys.stderr,
            )
            return 2
    elif not args.auto_pick and existing_papers:
        active_papers = existing_papers
    elif (
        not args.auto_pick
        and args.member == "member-4"
        and all(bib_by_pub.get(p) for p in DEFAULT_MEMBER4_PAPERS)
        and not (set(DEFAULT_MEMBER4_PAPERS) & excluded_from_files)
    ):
        active_papers = list(DEFAULT_MEMBER4_PAPERS)
    else:
        pool_excluded = excluded_from_files | existing_labeled
        candidates = _select_candidate_papers(
            bib_by_pub=bib_by_pub,
            ref_by_pub=ref_by_pub,
            excluded_papers=pool_excluded,
            min_entries=args.min_entries,
            min_refs=args.min_refs,
        )
        if len(candidates) < args.num_papers:
            print(
                f"[ERROR] Found only {len(candidates)} eligible unlabeled paper(s) in {data_dir} "
                f"(need {args.num_papers}; min_entries={args.min_entries}, min_refs={args.min_refs}, "
                f"excluded={len(pool_excluded)}).",
                file=sys.stderr,
            )
            return 2
        active_papers = candidates[:args.num_papers]
        print(f"[AUTO-PICK] Selected {len(active_papers)} paper(s) for {args.member}: {active_papers}", flush=True)

    missing_in_bibtex = [p for p in active_papers if not bib_by_pub.get(p)]
    if missing_in_bibtex:
        print(
            f"[ERROR] Paper ID(s) not found or have 0 entries in tables/bibtex: {missing_in_bibtex}",
            file=sys.stderr,
        )
        return 2

    all_papers = list(dict.fromkeys([*existing_papers, *active_papers]))
    records_by_pair: dict[tuple[str, str], dict[str, Any]] = {
        (normalize_arxiv_id(r["arxiv_id"]), str(r["citation_key"])): r
        for r in existing.get("labels", [])
        if normalize_arxiv_id(r.get("arxiv_id"))
    }

    if args.verify_only:
        payload = _build_payload(
            member=args.member,
            all_papers=all_papers,
            records_by_pair=records_by_pair,
            bib_by_pub=bib_by_pub,
        )
        ok, errs, warns = verify_labels(
            payload=payload,
            selected_papers=all_papers,
            bib_by_pub=bib_by_pub,
            ref_by_pub=ref_by_pub,
        )
        print(json.dumps({
            "is_valid": ok,
            "output": str(output_path),
            "publications": payload["publications"],
            "errors": errs,
            "warnings": warns,
        }, ensure_ascii=False, indent=2))
        return 0 if ok else 1

    # Flatten ordered task list across active_papers
    tasks: list[tuple[int, int, dict[str, Any]]] = []
    for p_idx, aid in enumerate(active_papers, start=1):
        entries = sorted(bib_by_pub.get(aid, []), key=lambda r: str(r["citation_key"]))
        for e_idx, entry in enumerate(entries, start=1):
            tasks.append((p_idx, e_idx, entry))

    ranker = HeuristicRanker()
    idx = 0
    while idx < len(tasks):
        _, _, e = tasks[idx]
        if (normalize_arxiv_id(e["arxiv_id"]), str(e["citation_key"])) not in records_by_pair:
            break
        idx += 1

    if idx == len(tasks):
        print(f"All {len(tasks)} entries across {len(active_papers)} active paper(s) are already labeled.")
        cmd = input("Press [r] to review from #1, [e] to jump to entry #, or Enter/[q] to exit: ").strip().lower()
        if cmd == "r":
            idx = 0
        elif cmd == "e":
            raw_num = input(f"Enter entry index [1..{len(tasks)}]: ").strip()
            if raw_num.isdigit() and 1 <= int(raw_num) <= len(tasks):
                idx = int(raw_num) - 1
            else:
                print("Invalid index. Exiting without changes.")
                return 0
        else:
            return 0
    else:
        print(f"Resuming at entry {idx + 1}/{len(tasks)}. Output: {output_path}")

    modified = False
    while idx < len(tasks):
        p_idx, e_idx, entry = tasks[idx]
        aid = normalize_arxiv_id(entry["arxiv_id"])
        ckey = str(entry["citation_key"])
        pub_entries = bib_by_pub[aid]
        refs = ref_by_pub.get(aid, [])
        scored = _rank_candidates_with_info(entry, refs, ranker)

        used_refs = _collect_used_refs(records_by_pair, aid, ckey)
        current_rec = records_by_pair.get((aid, ckey))
        pending_note: str | None = current_rec.get("notes") if current_rec else None
        show_all = False

        while True:
            done_in_scope = sum(
                1 for _, _, e in tasks
                if (normalize_arxiv_id(e["arxiv_id"]), str(e["citation_key"])) in records_by_pair
            )
            paper_title = (papers_map.get(aid) or "")[:55]
            print("\n" + "=" * 88)
            print(
                f"Paper {p_idx}/{len(active_papers)}: {aid} ({paper_title}...) | "
                f"Entry {e_idx}/{len(pub_entries)} | Scope done: {done_in_scope}/{len(tasks)}"
            )
            print("-" * 88)
            print(f"[BibTeX] key={ckey} | type={entry.get('entry_type')} | year={entry.get('year')}")
            print(f"  Title:   {entry.get('title')}")
            print(f"  Authors: {_format_authors(entry.get('authors'))}")
            if entry.get("journal") or entry.get("doi") or entry.get("url"):
                print(f"  Extra:   journal={entry.get('journal')} | doi={entry.get('doi')} | url={entry.get('url')}")
            if current_rec is not None:
                print(f"  [Current saved label]: {current_rec.get('groundtruth_arxiv_id') or 'NONE (no arXiv match)'}")
            if pending_note:
                print(f"  [Note]: {pending_note}")
            print("-" * 88)

            display_list = scored if show_all else scored[:5]
            header = f"ALL {len(scored)} arXiv references" if show_all else f"Top {len(display_list)}/{len(scored)} candidates"
            print(f"[{header} in {aid}]")
            for c_idx, (ref, score) in enumerate(display_list, start=1):
                rid_raw = ref.get("ref_arxiv_id")
                rid_norm = normalize_arxiv_id(rid_raw)
                used_tag = f" [USED by {', '.join(used_refs[rid_norm])}]" if rid_norm in used_refs else ""
                print(
                    f"  [{c_idx}] {rid_norm or rid_raw} (sim={score:.2f}) | date={ref.get('ref_submission_date')}{used_tag}\n"
                    f"      Title:   {ref.get('ref_title')}\n"
                    f"      Authors: {_format_authors(ref.get('ref_authors'))}"
                )

            print("-" * 88)
            pick_part = f"[1..{len(display_list)}], " if display_list else ""
            enter_part = "Enter=Keep, " if current_rec is not None else ""
            prompt = f"Pick {pick_part}0=No-Match, {enter_part}a=ShowAll, b=Back, n=EditNote, q=Save&Quit: "
            choice = input(prompt).strip()

            if choice.lower() == "q":
                if modified or not output_path.is_file():
                    payload = _build_payload(
                        member=args.member,
                        all_papers=all_papers,
                        records_by_pair=records_by_pair,
                        bib_by_pub=bib_by_pub,
                    )
                    _atomic_write_json(output_path, payload)
                print(f"Saved {len(records_by_pair)} total labels to {output_path}. Bye!")
                return 0
            if choice.lower() == "a":
                show_all = True
                continue
            if choice.lower() == "b":
                if idx > 0:
                    idx -= 1
                    break
                print("Already at the first entry.")
                continue
            if choice.lower() == "n":
                entered = input("Enter note (leave blank to clear): ").strip()
                pending_note = entered or None
                continue
            if choice == "" and current_rec is not None:
                gt_id = normalize_arxiv_id(current_rec.get("groundtruth_arxiv_id")) or None
            elif choice == "0":
                gt_id = None
            elif display_list and choice.isdigit() and 1 <= int(choice) <= len(display_list):
                raw_picked = display_list[int(choice) - 1][0].get("ref_arxiv_id")
                gt_id = normalize_arxiv_id(raw_picked)
                if not gt_id:
                    print(f"[ERROR] Invalid ref_arxiv_id in candidate: {raw_picked!r}")
                    continue
            else:
                print("Invalid input.")
                continue

            records_by_pair[(aid, ckey)] = {
                "arxiv_id": aid,
                "citation_key": ckey,
                "groundtruth_arxiv_id": gt_id,
                "method": "manual",
                "labeled_by": args.member,
                "notes": pending_note,
                "labeled_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            modified = True
            payload = _build_payload(
                member=args.member,
                all_papers=all_papers,
                records_by_pair=records_by_pair,
                bib_by_pub=bib_by_pub,
            )
            _atomic_write_json(output_path, payload)
            idx += 1
            break

    payload = _build_payload(
        member=args.member,
        all_papers=all_papers,
        records_by_pair=records_by_pair,
        bib_by_pub=bib_by_pub,
    )
    if modified or not output_path.is_file():
        _atomic_write_json(output_path, payload)
    ok, errs, warns = verify_labels(
        payload=payload,
        selected_papers=all_papers,
        bib_by_pub=bib_by_pub,
        ref_by_pub=ref_by_pub,
    )
    print("\n" + "=" * 88)
    print(f"FINISHED! Saved {len(payload['labels'])} manual labels to: {output_path}")
    print(f"Validation: is_valid={ok} | errors={errs} | warnings={warns}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
