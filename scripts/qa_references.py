"""MS1-M3-T07 manual QA: compare Semantic Scholar references with what the source really cites.

Usage: python scripts/qa_references.py <data-dir> [n_sample] [seed]
Needs raw/s2/ (crawl-references) and parsed/bibtex*.jsonl (run-parsing) in <data-dir>.
"""
import json
import os
import random
import re
import statistics
import sys
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher


def norm(text):
    return re.sub(r"[^a-z0-9 ]", "", unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()).strip()


def same_title(a, b):
    if not a or not b:
        return False
    if min(len(a), len(b)) >= 20 and (a in b or b in a):
        return True
    return SequenceMatcher(None, a, b).ratio() >= 0.9


def main(data_dir, n_sample=10, seed=18):
    s2 = {}
    for name in os.listdir(f"{data_dir}/raw/s2"):
        record = json.load(open(f"{data_dir}/raw/s2/{name}"))
        s2[record["status"]["arxiv_id"]] = record

    # canonical keys cited by the latest version = what the paper really cites
    cites = defaultdict(dict)
    for line in open(f"{data_dir}/parsed/bibtex_citations.jsonl"):
        c = json.loads(line)
        cites[c["arxiv_id"]].setdefault(c["version"], set()).add((c["cited_key"], c["canonical_key"]))
    latest = {a: v[max(v)] for a, v in cites.items()}

    ok = [a for a, r in s2.items() if r["status"]["status"] == "ok"]
    ratios = [s2[a]["status"]["response_reference_count"] / len(latest[a]) for a in ok if latest.get(a)]
    print("S2 ok:", len(ok), "| ok nhưng 0 reference:", sum(s2[a]["status"]["response_reference_count"] == 0 for a in ok))
    print("Bài có \\cite trong source:", len(ratios), "| median S2 refs / số key được cite:", round(statistics.median(ratios), 2),
          "| S2 < 50%:", sum(x < 0.5 for x in ratios), "| S2 > 150%:", sum(x > 1.5 for x in ratios))

    sample = sorted(random.Random(seed).sample(sorted(s2), n_sample))
    bib = defaultdict(dict)
    for line in open(f"{data_dir}/parsed/bibtex.jsonl"):
        entry = json.loads(line)
        if entry["arxiv_id"] in sample:
            bib[entry["arxiv_id"]][entry["citation_key"]] = entry

    print("\n| arxiv_id | S2 status | S2 refs | eligible arXiv | \\cite trong source | cite có BibTeX | cite có trong S2 | arXiv ID khớp source |")
    print("|---|---|---|---|---|---|---|---|")
    total_cited = total_found = id_checked = id_same = 0
    for a in sample:
        refs = s2[a]["references"]
        s2_titles = [norm((x.get("s2") or {}).get("title")) for x in refs]
        cited = [bib[a][k] for k in {k for _, k in latest.get(a, set())} if k in bib[a]]
        found = sum(any(same_title(norm(e["title"]), t) for t in s2_titles) for e in cited)
        checked = same = 0
        for x in refs:  # eligible arXiv ID vs the arXiv ID written in the source entry
            if not x.get("ref_arxiv_id"):
                continue
            for e in bib[a].values():
                m = re.search(r"(\d{4}\.\d{4,5})", f"{e.get('url') or ''} {e.get('journal') or ''}")
                if m and same_title(norm(e["title"]), norm(x["s2"].get("title"))):
                    checked += 1
                    same += m.group(1) == x["ref_arxiv_id"]
                    break
        st = s2[a]["status"]
        print(f"| {a} | {st['status']} | {st['response_reference_count']} | {st['eligible_reference_count']} "
              f"| {len(latest.get(a, set()))} | {len(cited)} | {found} | {same}/{checked} |")
        total_cited += len(cited); total_found += found; id_checked += checked; id_same += same
    print(f"\nRecall S2 so với \\cite có BibTeX: {total_found}/{total_cited} = {total_found / max(1, total_cited):.3f}")
    print(f"arXiv ID eligible khớp source: {id_same}/{id_checked}")


if __name__ == "__main__":
    main(sys.argv[1], *(int(x) for x in sys.argv[2:4]))
