#!/usr/bin/env python3
"""
analyse_elixir_citations.py

Analyzes citation metrics for the ELIXIR software tools collection relative to the
broader bio.tools catalogue, using the enriched dataset (e.g. `biotools_publications_elixir_incl.json`).

Key Deliverables & Analyses:
  1. 3-Tier Categorization:
     Categorizes all tools into 'Top 1%', 'Top 10%', and 'Average' based on total citations.
  2. CSV Exports:
     - Ranked CSV of all bio.tools with category, percentile rank, is_elixir, and firstPublication.
     - Ranked CSV of ELIXIR tools only with elixir_rank, global_rank, category, and firstPublication.
  3. Yearly Histograms:
     - Citations per year (All bio.tools vs. ELIXIR tools).
     - Number of tools per year (All bio.tools vs. ELIXIR tools).
  4. Pie Charts:
     - Category breakdown of All bio.tools across Top 1%, Top 10%, and Average.
     - Category breakdown of ELIXIR tools across Top 1%, Top 10%, and Average.
  5. Overall & Non-Zero Citation Proportions:
     Comprehensive summary statistics and distribution metrics.
"""

import argparse
import csv
import html
import json
import math
import os
import re
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple


def compute_statistics(values: List[int]) -> Dict[str, Any]:
    """Computes basic distribution metrics for a list of non-negative integers."""
    if not values:
        return {"count": 0, "sum": 0, "mean": 0.0, "median": 0.0, "max": 0, "min": 0}
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    total = sum(sorted_vals)
    mean = total / n
    mid = n // 2
    median = (sorted_vals[mid] + sorted_vals[~mid]) / 2.0
    return {
        "count": n,
        "sum": total,
        "mean": mean,
        "median": median,
        "max": sorted_vals[-1],
        "min": sorted_vals[0],
    }


def categorize_tools(
    tools: List[Dict],
    citation_key: str = "total_citations",
    category_attr: str = "category",
    rank_attr: str = "global_rank",
    percentile_attr: str = "percentile_rank",
) -> Tuple[List[Dict], Dict[str, Any]]:
    """
    Ranks all tools by `citation_key` descending and assigns each tool to one of
    three mutually exclusive categories:
      - 'Top 1%': Ranks 1 to cutoff_1%
      - 'Top 10%': Ranks (cutoff_1% + 1) to cutoff_10%
      - 'Average': Ranks (cutoff_10% + 1) to N
    """
    total_tools = len(tools)
    if total_tools == 0:
        return [], {}

    # Sort descending by citation_key (None -> 0)
    sorted_tools = sorted(
        tools,
        key=lambda t: (t.get(citation_key) or 0),
        reverse=True,
    )

    cutoff_1 = max(1, math.ceil(total_tools * 0.01))
    cutoff_10 = max(1, math.ceil(total_tools * 0.10))

    threshold_top1 = sorted_tools[cutoff_1 - 1].get(citation_key) or 0
    threshold_top10 = sorted_tools[cutoff_10 - 1].get(citation_key) or 0

    enriched_tools = []
    category_counts_all = {"Top 1%": 0, "Top 10%": 0, "Average": 0}
    category_counts_elixir = {"Top 1%": 0, "Top 10%": 0, "Average": 0}

    for rank, tool in enumerate(sorted_tools, 1):
        if rank <= cutoff_1:
            cat = "Top 1%"
        elif rank <= cutoff_10:
            cat = "Top 10%"
        else:
            cat = "Average"

        pct_rank = (rank / total_tools) * 100.0
        is_el = bool(tool.get("is_elixir"))

        item = dict(tool)
        item[rank_attr] = rank
        item[category_attr] = cat
        item[percentile_attr] = pct_rank
        enriched_tools.append(item)

        category_counts_all[cat] += 1
        if is_el:
            category_counts_elixir[cat] += 1

    metadata = {
        "citation_key": citation_key,
        "category_attr": category_attr,
        "rank_attr": rank_attr,
        "total_tools": total_tools,
        "cutoff_top1": cutoff_1,
        "cutoff_top10": cutoff_10,
        "threshold_top1": threshold_top1,
        "threshold_top10": threshold_top10,
        "category_counts_all": category_counts_all,
        "category_counts_elixir": category_counts_elixir,
    }

    return enriched_tools, metadata


def analyze_tool_percentiles(
    enriched_tools: List[Dict],
    metadata: Dict[str, Any],
    max_print_per_tier: int = 25,
    title_suffix: str = "Ranked by Total Citations",
) -> None:
    """Prints tool-level representation across Top 1%, Top 10%, and Average categories."""
    total_tools = metadata["total_tools"]
    elixir_tools = [t for t in enriched_tools if t.get("is_elixir")]
    total_elixir = len(elixir_tools)

    cat_attr = metadata.get("category_attr", "category")
    rank_attr = metadata.get("rank_attr", "global_rank")
    cit_key = metadata.get("citation_key", "total_citations")

    counts_all = metadata["category_counts_all"]
    counts_elixir = metadata["category_counts_elixir"]

    print("\n" + "=" * 76)
    print(f"       TOOL-LEVEL CATEGORIZATION ANALYSIS ({title_suffix})")
    print("=" * 76)
    print(f"Categories: Top 1% (Ranks 1–{metadata['cutoff_top1']:,}), "
          f"Top 10% (Ranks {metadata['cutoff_top1'] + 1:,}–{metadata['cutoff_top10']:,}), "
          f"Average (Ranks {metadata['cutoff_top10'] + 1:,}–{total_tools:,})")
    print("-" * 76)

    # 1. Top 1%
    top1_elixir = [t for t in enriched_tools if t.get(cat_attr) == "Top 1%" and t.get("is_elixir")]
    pct_top1_all = (counts_all["Top 1%"] / total_tools) * 100.0
    pct_top1_el = (counts_elixir["Top 1%"] / total_elixir) * 100.0 if total_elixir > 0 else 0.0
    pct_of_tier_1 = (counts_elixir["Top 1%"] / counts_all["Top 1%"]) * 100.0 if counts_all["Top 1%"] > 0 else 0.0
    enrichment_1 = (pct_top1_el / pct_top1_all) if pct_top1_all > 0 else 0.0

    print(f"\n--- Category: Top 1% (Top {counts_all['Top 1%']:,} tools | Threshold: >={metadata['threshold_top1']:,} citations) ---")
    print(f"  * All bio.tools in category:           {counts_all['Top 1%']:,} ({pct_top1_all:.2f}%)")
    print(f"  * ELIXIR tools in category:            {counts_elixir['Top 1%']:,} / {total_elixir:,} ({pct_top1_el:.2f}% of ELIXIR collection)")
    print(f"  * Representation in category:          {pct_of_tier_1:.2f}% of this category is ELIXIR")
    print(f"  * Representation enrichment:           {enrichment_1:.2f}x {'(Over-represented)' if enrichment_1 > 1.0 else '(Under-represented)'}")

    if top1_elixir:
        print(f"  * Top ELIXIR tools in Top 1% (showing up to {max_print_per_tier}):")
        for idx, t in enumerate(top1_elixir[:max_print_per_tier], 1):
            cites = t.get(cit_key) or 0
            fp = t.get("first_primary_publication") if cit_key == "primary_citations" else (t.get("firstPublication") or "N/A")
            if not fp:
                fp = t.get("firstPublication") or "N/A"
            print(f"      {idx:2d}. Rank #{t.get(rank_attr, idx):,}: {t['name']} ({t['biotools_id']}) - {cites:,} citations (First pub: {fp})")
        if len(top1_elixir) > max_print_per_tier:
            print(f"      ... and {len(top1_elixir) - max_print_per_tier} more")

    # 2. Top 10% (non-overlapping tier: ranks 345..3440)
    top10_elixir = [t for t in enriched_tools if t.get(cat_attr) == "Top 10%" and t.get("is_elixir")]
    pct_top10_all = (counts_all["Top 10%"] / total_tools) * 100.0
    pct_top10_el = (counts_elixir["Top 10%"] / total_elixir) * 100.0 if total_elixir > 0 else 0.0
    pct_of_tier_10 = (counts_elixir["Top 10%"] / counts_all["Top 10%"]) * 100.0 if counts_all["Top 10%"] > 0 else 0.0
    enrichment_10 = (pct_top10_el / pct_top10_all) if pct_top10_all > 0 else 0.0

    print(f"\n--- Category: Top 10% (Ranks {metadata['cutoff_top1'] + 1:,}–{metadata['cutoff_top10']:,} | {counts_all['Top 10%']:,} tools | Threshold: >={metadata['threshold_top10']:,} citations) ---")
    print(f"  * All bio.tools in category:           {counts_all['Top 10%']:,} ({pct_top10_all:.2f}%)")
    print(f"  * ELIXIR tools in category:            {counts_elixir['Top 10%']:,} / {total_elixir:,} ({pct_top10_el:.2f}% of ELIXIR collection)")
    print(f"  * Representation in category:          {pct_of_tier_10:.2f}% of this category is ELIXIR")
    print(f"  * Representation enrichment:           {enrichment_10:.2f}x {'(Over-represented)' if enrichment_10 > 1.0 else '(Under-represented)'}")

    # Cumulative Top 10% summary (Top 1% + Top 10%)
    cum_elixir = counts_elixir["Top 1%"] + counts_elixir["Top 10%"]
    cum_all = counts_all["Top 1%"] + counts_all["Top 10%"]
    cum_pct_el = (cum_elixir / total_elixir) * 100.0 if total_elixir > 0 else 0.0
    print(f"  [Note: Cumulative Top 10% (Top 1% + Top 10% combined): {cum_elixir:,} / {total_elixir:,} ELIXIR tools ({cum_pct_el:.2f}%), {(cum_pct_el/10.0):.2f}x enrichment]")

    if top10_elixir:
        print(f"  * Sample ELIXIR tools in Top 10% (showing up to {max_print_per_tier}):")
        for idx, t in enumerate(top10_elixir[:max_print_per_tier], 1):
            cites = t.get(cit_key) or 0
            fp = t.get("first_primary_publication") if cit_key == "primary_citations" else (t.get("firstPublication") or "N/A")
            if not fp:
                fp = t.get("firstPublication") or "N/A"
            print(f"      {idx:2d}. Rank #{t.get(rank_attr, idx):,}: {t['name']} ({t['biotools_id']}) - {cites:,} citations (First pub: {fp})")
        if len(top10_elixir) > max_print_per_tier:
            print(f"      ... and {len(top10_elixir) - max_print_per_tier} more")

    # 3. Average
    pct_avg_all = (counts_all["Average"] / total_tools) * 100.0
    pct_avg_el = (counts_elixir["Average"] / total_elixir) * 100.0 if total_elixir > 0 else 0.0
    pct_of_tier_avg = (counts_elixir["Average"] / counts_all["Average"]) * 100.0 if counts_all["Average"] > 0 else 0.0
    enrichment_avg = (pct_avg_el / pct_avg_all) if pct_avg_all > 0 else 0.0

    print(f"\n--- Category: Average (Remaining {counts_all['Average']:,} tools | <{metadata['threshold_top10']:,} citations) ---")
    print(f"  * All bio.tools in category:           {counts_all['Average']:,} ({pct_avg_all:.2f}%)")
    print(f"  * ELIXIR tools in category:            {counts_elixir['Average']:,} / {total_elixir:,} ({pct_avg_el:.2f}% of ELIXIR collection)")
    print(f"  * Representation in category:          {pct_of_tier_avg:.2f}% of this category is ELIXIR")
    print(f"  * Representation enrichment:           {enrichment_avg:.2f}x {'(Over-represented)' if enrichment_avg > 1.0 else '(Under-represented)'}")


def analyze_publication_percentiles(
    tools: List[Dict],
    tiers: List[Tuple[str, float]],
    print_pubs: bool = True,
    max_print_per_tier: int = 10,
) -> List[Dict]:
    """
    Collects all publications across all tools, ranks them by citation count descending,
    and analyzes the representation of ELIXIR publications.
    """
    all_publications = []
    for tool in tools:
        is_el = bool(tool.get("is_elixir"))
        bt_id = tool.get("biotools_id")
        t_name = tool.get("name")

        for pub in tool.get("publications", []):
            all_publications.append({
                "tool_id": bt_id,
                "tool_name": t_name,
                "is_elixir": is_el,
                "pub_id": pub.get("id"),
                "pub_type": pub.get("type"),
                "doi": pub.get("doi"),
                "citations": pub.get("citations") or 0,
            })

    total_pubs = len(all_publications)
    elixir_pubs = [p for p in all_publications if p["is_elixir"]]
    total_elixir_pubs = len(elixir_pubs)

    if total_pubs == 0:
        print("\nNo publications available for publication-level analysis.")
        return []

    sorted_pubs = sorted(all_publications, key=lambda p: p["citations"], reverse=True)

    results = []
    print("\n" + "=" * 76)
    print("   PUBLICATION-LEVEL PERCENTILE ANALYSIS (Ranked by Paper Citations)")
    print("=" * 76)

    for label, pct in tiers:
        cutoff = max(1, math.ceil(total_pubs * pct))
        top_slice = sorted_pubs[:cutoff]
        threshold = top_slice[-1]["citations"]

        elixir_in_tier = [p for p in top_slice if p["is_elixir"]]
        elixir_count = len(elixir_in_tier)

        pct_of_tier = (elixir_count / cutoff) * 100.0 if cutoff > 0 else 0.0
        pct_of_all_elixir = (elixir_count / total_elixir_pubs) * 100.0 if total_elixir_pubs > 0 else 0.0

        distinct_tools = len({p["tool_id"] for p in elixir_in_tier})

        tier_info = {
            "tier": label,
            "pub_cutoff": cutoff,
            "threshold_citations": threshold,
            "elixir_count": elixir_count,
            "pct_of_tier": pct_of_tier,
            "pct_of_all_elixir": pct_of_all_elixir,
            "distinct_tools": distinct_tools,
        }
        results.append(tier_info)

        print(f"\n--- {label} (Top {cutoff:,} publications | Threshold: >={threshold:,} citations) ---")
        print(f"  * ELIXIR publications in tier:        {elixir_count:,} / {cutoff:,} ({pct_of_tier:.2f}% of this tier)")
        print(f"  * Percentage of all ELIXIR papers:    {pct_of_all_elixir:.2f}% ({elixir_count:,} of {total_elixir_pubs:,})")
        print(f"  * Distinct ELIXIR tools represented:  {distinct_tools:,}")

        if print_pubs and elixir_in_tier:
            print(f"  * Sample ELIXIR papers in tier (up to {max_print_per_tier}):")
            for idx, p in enumerate(elixir_in_tier[:max_print_per_tier], 1):
                doi_or_id = p["doi"] or p["pub_id"] or "N/A"
                print(f"      {idx:2d}. {p['tool_name']} [{doi_or_id}]: {p['citations']:,} citations")
            if len(elixir_in_tier) > max_print_per_tier:
                print(f"      ... and {len(elixir_in_tier) - max_print_per_tier} more")

    return results


# =====================================================================
# Yearly Analysis (citations & tools by firstPublication year)
# =====================================================================

def analyze_citations_by_year(
    tools: List[Dict],
    start_year: int = 1990,
    export_csv: Optional[str] = None,
    citation_key: str = "total_citations",
    date_key: str = "firstPublication",
    title_label: str = "All Related Publications",
) -> List[Dict[str, Any]]:
    """
    Calculates citations and tool counts grouped by publication year
    separately for all bio.tools and ELIXIR tools.
    """
    by_year: Dict[int, Dict[str, int]] = {}
    unknown_all = {"cits": 0, "count": 0}
    unknown_elixir = {"cits": 0, "count": 0}

    for t in tools:
        cits = t.get(citation_key) or 0
        is_el = bool(t.get("is_elixir"))

        if citation_key == "primary_citations":
            # Primary case: only count tools that have primary publications
            has_primary = (t.get("primary_publication_count") or 0) > 0 or any(
                p.get("is_primary") for p in t.get("publications", [])
            )
            if not has_primary:
                continue

            fp = t.get(date_key) or t.get("first_primary_publication")
            if not fp:
                prim_dates = [
                    p.get("date") for p in t.get("publications", [])
                    if p.get("is_primary") and p.get("date") and isinstance(p["date"], str)
                ]
                fp = min(prim_dates) if prim_dates else None
        elif citation_key in ("pmo_citations", "primary_method_other_citations", "total_pmo_citations"):
            # PMO case: only count tools that have Primary, Method, or Other publications
            has_pmo = (t.get("pmo_publication_count") or 0) > 0 or any(
                p.get("is_pmo") for p in t.get("publications", [])
            )
            if not has_pmo:
                continue

            fp = t.get(date_key) or t.get("first_pmo_publication")
            if not fp:
                pmo_dates = [
                    p.get("date") for p in t.get("publications", [])
                    if p.get("is_pmo") and p.get("date") and isinstance(p["date"], str)
                ]
                fp = min(pmo_dates) if pmo_dates else None
        else:
            fp = t.get(date_key) or t.get("firstPublication")

        year = None
        if fp:
            m = re.search(r"(\d{4})", str(fp))
            if m:
                val = int(m.group(1))
                if 1950 <= val <= 2030:
                    year = val

        if year is None:
            unknown_all["cits"] += cits
            unknown_all["count"] += 1
            if is_el:
                unknown_elixir["cits"] += cits
                unknown_elixir["count"] += 1
        else:
            if year not in by_year:
                by_year[year] = {
                    "all_cits": 0,
                    "all_tools": 0,
                    "elixir_cits": 0,
                    "elixir_tools": 0,
                }
            by_year[year]["all_cits"] += cits
            by_year[year]["all_tools"] += 1
            if is_el:
                by_year[year]["elixir_cits"] += cits
                by_year[year]["elixir_tools"] += 1

    sorted_years = sorted(by_year.keys())
    yearly_records = []
    for y in sorted_years:
        data = by_year[y]
        pct_elixir_cit = (
            (data["elixir_cits"] / data["all_cits"]) * 100.0
            if data["all_cits"] > 0
            else 0.0
        )
        pct_elixir_tools = (
            (data["elixir_tools"] / data["all_tools"]) * 100.0
            if data["all_tools"] > 0
            else 0.0
        )
        yearly_records.append({
            "year": y,
            "all_cits": data["all_cits"],
            "all_tools": data["all_tools"],
            "elixir_cits": data["elixir_cits"],
            "elixir_tools": data["elixir_tools"],
            "pct_elixir_cit": pct_elixir_cit,
            "pct_elixir_tools": pct_elixir_tools,
        })

    # Print Table Report
    print("\n" + "=" * 88)
    print(f"        CITATIONS & TOOLS BY PUBLICATION YEAR ({title_label})")
    print("=" * 88)
    header = f"{'Year':^6} | {'All Citations':>14} | {'All Tools':>9} | {'ELIXIR Cit.':>12} | {'ELIXIR Tools':>12} | {'% ELIXIR Cit.':>13} | {'% EL Tools':>10}"
    print(header)
    print("-" * len(header))

    for r in yearly_records:
        if r["year"] >= start_year or r["all_cits"] > 0 or r["elixir_cits"] > 0:
            print(
                f"{r['year']:^6} | "
                f"{r['all_cits']:>14,d} | "
                f"{r['all_tools']:>9,d} | "
                f"{r['elixir_cits']:>12,d} | "
                f"{r['elixir_tools']:>12,d} | "
                f"{r['pct_elixir_cit']:>12.2f}% | "
                f"{r['pct_elixir_tools']:>9.2f}%"
            )

    print("-" * len(header))
    pct_unknown_cit = (
        (unknown_elixir["cits"] / unknown_all["cits"]) * 100.0
        if unknown_all["cits"] > 0
        else 0.0
    )
    pct_unknown_tools = (
        (unknown_elixir["count"] / unknown_all["count"]) * 100.0
        if unknown_all["count"] > 0
        else 0.0
    )
    print(
        f"{'N/A*':^6} | "
        f"{unknown_all['cits']:>14,d} | "
        f"{unknown_all['count']:>9,d} | "
        f"{unknown_elixir['cits']:>12,d} | "
        f"{unknown_elixir['count']:>12,d} | "
        f"{pct_unknown_cit:>12.2f}% | "
        f"{pct_unknown_tools:>9.2f}%"
    )
    print("-" * len(header))
    print("  * 'N/A' represents tools with missing/unparsed publication dates.")

    # Peak years summary
    if yearly_records:
        peak_all_cits = max(yearly_records, key=lambda x: x["all_cits"])
        peak_elixir_cits = max(yearly_records, key=lambda x: x["elixir_cits"])
        peak_all_tools = max(yearly_records, key=lambda x: x["all_tools"])
        peak_elixir_tools = max(yearly_records, key=lambda x: x["elixir_tools"])
        print(f"\n  Peak citations (All bio.tools): {peak_all_cits['year']} with {peak_all_cits['all_cits']:,} citations ({peak_all_tools['all_tools']:,} tools)")
        print(f"  Peak citations (ELIXIR tools):  {peak_elixir_cits['year']} with {peak_elixir_cits['elixir_cits']:,} citations ({peak_elixir_tools['elixir_tools']:,} tools)")
        print(f"  Peak tool count (All bio.tools): {peak_all_tools['year']} with {peak_all_tools['all_tools']:,} tools ({peak_all_tools['all_cits']:,} citations)")
        print(f"  Peak tool count (ELIXIR tools):  {peak_elixir_tools['year']} with {peak_elixir_tools['elixir_tools']:,} tools ({peak_elixir_tools['elixir_cits']:,} citations)")

    # Optional CSV export
    if export_csv:
        out_dir = os.path.dirname(os.path.abspath(export_csv))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(export_csv, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "year",
                "all_tools_citations",
                "all_tools_count",
                "elixir_tools_citations",
                "elixir_tools_count",
                "percentage_elixir_citations",
                "percentage_elixir_tools",
            ])
            for r in yearly_records:
                writer.writerow([
                    r["year"],
                    r["all_cits"],
                    r["all_tools"],
                    r["elixir_cits"],
                    r["elixir_tools"],
                    f"{r['pct_elixir_cit']:.2f}",
                    f"{r['pct_elixir_tools']:.2f}",
                ])
            writer.writerow([
                "Unknown",
                unknown_all["cits"],
                unknown_all["count"],
                unknown_elixir["cits"],
                unknown_elixir["count"],
                f"{pct_unknown_cit:.2f}",
                f"{pct_unknown_tools:.2f}",
            ])
        print(f"\nExported yearly breakdown to '{export_csv}'.")

    return yearly_records


# =====================================================================
# SVG Histogram Helper Functions
# =====================================================================

def get_nice_max(val: int) -> int:
    """Rounds up integer val to clean graphical tick intervals."""
    if val <= 0:
        return 10
    order = 10 ** int(math.floor(math.log10(val)))
    lead = val / order
    if lead <= 1.2:
        return int(1.25 * order)
    elif lead <= 2.5:
        return int(2.5 * order)
    elif lead <= 5.0:
        return int(5.0 * order)
    else:
        return int(10.0 * order)


def export_svg_and_png(
    svg_content: str,
    output_path: str,
    enable_png: bool = True,
    zoom: float = 2.0,
    figure_desc: str = "figure",
) -> None:
    """
    Saves an SVG string to `output_path` and, if enabled, renders and saves a
    high-resolution companion PNG file.
    """
    out_dir = os.path.dirname(os.path.abspath(output_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(svg_content)
    print(f"\nGenerated {figure_desc} (SVG): '{output_path}'")

    if not enable_png:
        return

    png_path = (
        output_path[:-4] + ".png"
        if output_path.lower().endswith(".svg")
        else output_path + ".png"
    )

    png_success = False

    # Option 1: resvg_py (Rust-backed, fastest, highest fidelity)
    try:
        import resvg_py

        png_bytes = resvg_py.svg_to_bytes(svg_string=svg_content, zoom=zoom)
        with open(png_path, "wb") as f:
            f.write(png_bytes)
        png_success = True
    except ImportError:
        pass
    except Exception as e:
        print(f"Warning: resvg-py encountered an issue converting '{output_path}' to PNG: {e}")

    # Option 2: cairosvg
    if not png_success:
        try:
            import cairosvg

            cairosvg.svg2png(bytestring=svg_content.encode("utf-8"), write_to=png_path, scale=zoom)
            png_success = True
        except ImportError:
            pass
        except Exception:
            pass

    # Option 3: Python virtual environment fallback
    if not png_success:
        venv_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".venv", "bin", "python3")
        if os.path.isfile(venv_py):
            try:
                proc = subprocess.run(
                    [
                        venv_py,
                        "-c",
                        "import resvg_py, sys; sys.stdout.buffer.write(resvg_py.svg_to_bytes(svg_string=sys.stdin.read(), zoom=2.0))",
                    ],
                    input=svg_content,
                    text=True,
                    capture_output=True,
                    check=True,
                )
                if proc.stdout:
                    with open(png_path, "wb") as f:
                        f.write(proc.stdout)
                    png_success = True
            except Exception:
                pass

    if png_success:
        print(f"Generated {figure_desc} (PNG): '{png_path}'")
    else:
        print(
            f"Note: PNG conversion skipped for '{png_path}'. "
            "To generate PNG copies, install resvg-py (`pip install resvg-py`)."
        )


def generate_citations_histogram(
    yearly_data: List[Dict[str, Any]],
    output_path: str,
    start_year: int = 1990,
    enable_png: bool = True,
    title: Optional[str] = None,
    subtitle: Optional[str] = None,
    panel1_title: Optional[str] = None,
    panel2_title: Optional[str] = None,
    y_axis_label: str = "Total Citations",
) -> None:
    """
    Generates a publication-grade vector figure (SVG) comparing citations by
    publication year for All bio.tools vs ELIXIR tools.
    """
    filtered = [d for d in yearly_data if d["year"] >= start_year]
    if not filtered:
        print("No yearly citation data available to plot within the specified range.")
        return

    main_title = title or "Distribution of Total Citations by Tool's First Publication Year"
    sub_title = (
        subtitle
        if subtitle is not None
        else f"Sum of citations across bio.tools (top) and ELIXIR software tools (bottom) | Years {filtered[0]['year']}–{filtered[-1]['year']}"
    )
    p1_title = panel1_title or "■ All bio.tools (Total Citations)"
    p2_title = panel2_title or "■ ELIXIR Europe Tools (Total Citations)"

    width = 1100
    height = 740
    margin_left = 110
    margin_right = 40
    margin_top = 85
    margin_bottom = 75
    gap_between = 70

    plot_width = width - margin_left - margin_right
    total_plot_height = height - margin_top - margin_bottom - gap_between
    panel_height = total_plot_height / 2.0

    y_panel1_top = margin_top
    y_panel1_bottom = y_panel1_top + panel_height

    y_panel2_top = y_panel1_bottom + gap_between
    y_panel2_bottom = y_panel2_top + panel_height

    n_years = len(filtered)
    slot_width = plot_width / n_years
    bar_width = max(3.0, slot_width * 0.72)
    bar_offset = (slot_width - bar_width) / 2.0

    max_all = max(d["all_cits"] for d in filtered) if filtered else 1
    max_elixir = max(d["elixir_cits"] for d in filtered) if filtered else 1

    scale_all_max = get_nice_max(max_all)
    scale_elixir_max = get_nice_max(max_elixir)

    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="100%" height="auto" style="background:#ffffff; font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif;">',
        '<defs>',
        '  <style>',
        '    .chart-title { font-size: 17px; font-weight: bold; fill: #1a202c; }',
        '    .chart-subtitle { font-size: 12px; fill: #718096; }',
        '    .panel-title { font-size: 13px; font-weight: bold; }',
        '    .gridline { stroke: #e2e8f0; stroke-width: 1; stroke-dasharray: 3 3; }',
        '    .axis-line { stroke: #718096; stroke-width: 1.2; }',
        '    .tick-label { font-size: 10px; fill: #4a5568; }',
        '    .x-label { font-size: 10px; fill: #4a5568; text-anchor: end; }',
        '    .bar-all { fill: #2b6cb0; transition: fill 0.15s; }',
        '    .bar-all:hover { fill: #3182ce; }',
        '    .bar-elixir { fill: #dd6b20; transition: fill 0.15s; }',
        '    .bar-elixir:hover { fill: #ed8936; }',
        '    .axis-title { font-size: 11px; font-weight: 600; fill: #2d3748; }',
        '  </style>',
        '</defs>',
    ]

    # Overall Titles
    svg_parts.append(
        f'<text x="{width / 2}" y="32" class="chart-title" text-anchor="middle">'
        f"{main_title}</text>"
    )
    svg_parts.append(
        f'<text x="{width / 2}" y="52" class="chart-subtitle" text-anchor="middle">'
        f"{sub_title}</text>"
    )

    # ------------------ PANEL 1: All bio.tools ------------------
    svg_parts.append(
        f'<text x="{margin_left}" y="{y_panel1_top - 12}" class="panel-title" fill="#2b6cb0">'
        f"{p1_title}</text>"
    )

    n_ticks = 5
    for i in range(n_ticks + 1):
        frac = i / n_ticks
        val = int(scale_all_max * frac)
        y_pos = y_panel1_bottom - (panel_height * frac)
        svg_parts.append(f'<line x1="{margin_left}" y1="{y_pos:.1f}" x2="{margin_left + plot_width}" y2="{y_pos:.1f}" class="gridline"/>')
        val_str = f"{val / 1_000_000:.1f}M" if val >= 1_000_000 else (f"{val // 1_000}k" if val > 0 else "0")
        svg_parts.append(f'<text x="{margin_left - 10}" y="{y_pos + 3.5:.1f}" class="tick-label" text-anchor="end">{val_str}</text>')

    mid_y1 = (y_panel1_top + y_panel1_bottom) / 2
    svg_parts.append(
        f'<text x="25" y="{mid_y1}" class="axis-title" text-anchor="middle" '
        f'transform="rotate(-90 25 {mid_y1})">{y_axis_label}</text>'
    )

    for idx, d in enumerate(filtered):
        x = margin_left + (idx * slot_width) + bar_offset
        c = d["all_cits"]
        bar_h = (c / scale_all_max) * panel_height if scale_all_max > 0 else 0
        y = y_panel1_bottom - bar_h
        svg_parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width:.1f}" height="{bar_h:.1f}" rx="2" class="bar-all">'
            f'<title>Year {d["year"]}: {c:,} citations ({d["all_tools"]:,} tools)</title></rect>'
        )

    svg_parts.append(f'<line x1="{margin_left}" y1="{y_panel1_bottom}" x2="{margin_left + plot_width}" y2="{y_panel1_bottom}" class="axis-line"/>')

    # ------------------ PANEL 2: ELIXIR Tools ------------------
    svg_parts.append(
        f'<text x="{margin_left}" y="{y_panel2_top - 12}" class="panel-title" fill="#dd6b20">'
        f"{p2_title}</text>"
    )

    for i in range(n_ticks + 1):
        frac = i / n_ticks
        val = int(scale_elixir_max * frac)
        y_pos = y_panel2_bottom - (panel_height * frac)
        svg_parts.append(f'<line x1="{margin_left}" y1="{y_pos:.1f}" x2="{margin_left + plot_width}" y2="{y_pos:.1f}" class="gridline"/>')
        val_str = f"{val // 1_000}k" if val > 0 else "0"
        svg_parts.append(f'<text x="{margin_left - 10}" y="{y_pos + 3.5:.1f}" class="tick-label" text-anchor="end">{val_str}</text>')

    mid_y2 = (y_panel2_top + y_panel2_bottom) / 2
    svg_parts.append(
        f'<text x="25" y="{mid_y2}" class="axis-title" text-anchor="middle" '
        f'transform="rotate(-90 25 {mid_y2})">{y_axis_label}</text>'
    )

    for idx, d in enumerate(filtered):
        x = margin_left + (idx * slot_width) + bar_offset
        c = d["elixir_cits"]
        bar_h = (c / scale_elixir_max) * panel_height if scale_elixir_max > 0 else 0
        y = y_panel2_bottom - bar_h
        svg_parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width:.1f}" height="{bar_h:.1f}" rx="2" class="bar-elixir">'
            f'<title>Year {d["year"]}: {c:,} citations ({d["elixir_tools"]:,} tools)</title></rect>'
        )

    svg_parts.append(f'<line x1="{margin_left}" y1="{y_panel2_bottom}" x2="{margin_left + plot_width}" y2="{y_panel2_bottom}" class="axis-line"/>')

    # Shared X-axis Labels below Panel 2
    for idx, d in enumerate(filtered):
        center_x = margin_left + (idx * slot_width) + (slot_width / 2.0)
        svg_parts.append(f'<line x1="{center_x:.1f}" y1="{y_panel2_bottom}" x2="{center_x:.1f}" y2="{y_panel2_bottom + 5}" class="axis-line"/>')
        svg_parts.append(
            f'<text x="{center_x + 3:.1f}" y="{y_panel2_bottom + 16:.1f}" class="x-label" '
            f'transform="rotate(-45 {center_x + 3:.1f} {y_panel2_bottom + 16:.1f})">{d["year"]}</text>'
        )

    svg_parts.append(
        f'<text x="{margin_left + (plot_width / 2)}" y="{height - 12}" class="axis-title" text-anchor="middle">'
        f"Tool First Publication Year</text>"
    )

    svg_parts.append("</svg>")

    export_svg_and_png(
        svg_content="\n".join(svg_parts),
        output_path=output_path,
        enable_png=enable_png,
        figure_desc="citations histogram figure",
    )


def generate_tools_histogram(
    yearly_data: List[Dict[str, Any]],
    output_path: str,
    start_year: int = 1990,
    enable_png: bool = True,
    title: Optional[str] = None,
    subtitle: Optional[str] = None,
    panel1_title: Optional[str] = None,
    panel2_title: Optional[str] = None,
) -> None:
    """
    Generates a publication-grade vector figure (SVG) comparing tool counts by
    tool publication year for All bio.tools vs ELIXIR tools.
    """
    filtered = [d for d in yearly_data if d["year"] >= start_year]
    if not filtered:
        print("No yearly tool data available to plot within the specified range.")
        return

    main_title = title or "Distribution of Tool Counts by First Publication Year"
    sub_title = (
        subtitle
        if subtitle is not None
        else f"Number of tools published per year: bio.tools (top) and ELIXIR software tools (bottom) | Years {filtered[0]['year']}–{filtered[-1]['year']}"
    )
    p1_title = panel1_title or "■ All bio.tools (Tool Count)"
    p2_title = panel2_title or "■ ELIXIR Europe Tools (Tool Count)"

    width = 1100
    height = 740
    margin_left = 90
    margin_right = 40
    margin_top = 85
    margin_bottom = 75
    gap_between = 70

    plot_width = width - margin_left - margin_right
    total_plot_height = height - margin_top - margin_bottom - gap_between
    panel_height = total_plot_height / 2.0

    y_panel1_top = margin_top
    y_panel1_bottom = y_panel1_top + panel_height

    y_panel2_top = y_panel1_bottom + gap_between
    y_panel2_bottom = y_panel2_top + panel_height

    n_years = len(filtered)
    slot_width = plot_width / n_years
    bar_width = max(3.0, slot_width * 0.72)
    bar_offset = (slot_width - bar_width) / 2.0

    max_all_tools = max(d["all_tools"] for d in filtered) if filtered else 1
    max_elixir_tools = max(d["elixir_tools"] for d in filtered) if filtered else 1

    scale_all_max = get_nice_max(max_all_tools)
    scale_elixir_max = get_nice_max(max_elixir_tools)

    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="100%" height="auto" style="background:#ffffff; font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif;">',
        '<defs>',
        '  <style>',
        '    .chart-title { font-size: 17px; font-weight: bold; fill: #1a202c; }',
        '    .chart-subtitle { font-size: 12px; fill: #718096; }',
        '    .panel-title { font-size: 13px; font-weight: bold; }',
        '    .gridline { stroke: #e2e8f0; stroke-width: 1; stroke-dasharray: 3 3; }',
        '    .axis-line { stroke: #718096; stroke-width: 1.2; }',
        '    .tick-label { font-size: 10px; fill: #4a5568; }',
        '    .x-label { font-size: 10px; fill: #4a5568; text-anchor: end; }',
        '    .bar-all { fill: #0d9488; transition: fill 0.15s; }',
        '    .bar-all:hover { fill: #14b8a6; }',
        '    .bar-elixir { fill: #7c3aed; transition: fill 0.15s; }',
        '    .bar-elixir:hover { fill: #8b5cf6; }',
        '    .axis-title { font-size: 11px; font-weight: 600; fill: #2d3748; }',
        '  </style>',
        '</defs>',
    ]

    # Overall Titles
    svg_parts.append(
        f'<text x="{width / 2}" y="32" class="chart-title" text-anchor="middle">'
        f"{main_title}</text>"
    )
    svg_parts.append(
        f'<text x="{width / 2}" y="52" class="chart-subtitle" text-anchor="middle">'
        f"{sub_title}</text>"
    )

    # ------------------ PANEL 1: All bio.tools ------------------
    svg_parts.append(
        f'<text x="{margin_left}" y="{y_panel1_top - 12}" class="panel-title" fill="#0d9488">'
        f"{p1_title}</text>"
    )

    n_ticks = 5
    for i in range(n_ticks + 1):
        frac = i / n_ticks
        val = int(scale_all_max * frac)
        y_pos = y_panel1_bottom - (panel_height * frac)
        svg_parts.append(f'<line x1="{margin_left}" y1="{y_pos:.1f}" x2="{margin_left + plot_width}" y2="{y_pos:.1f}" class="gridline"/>')
        val_str = f"{val:,}"
        svg_parts.append(f'<text x="{margin_left - 10}" y="{y_pos + 3.5:.1f}" class="tick-label" text-anchor="end">{val_str}</text>')

    mid_y1 = (y_panel1_top + y_panel1_bottom) / 2
    svg_parts.append(
        f'<text x="25" y="{mid_y1}" class="axis-title" text-anchor="middle" '
        f'transform="rotate(-90 25 {mid_y1})">Number of Tools</text>'
    )

    for idx, d in enumerate(filtered):
        x = margin_left + (idx * slot_width) + bar_offset
        cnt = d["all_tools"]
        bar_h = (cnt / scale_all_max) * panel_height if scale_all_max > 0 else 0
        y = y_panel1_bottom - bar_h
        svg_parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width:.1f}" height="{bar_h:.1f}" rx="2" class="bar-all">'
            f'<title>Year {d["year"]}: {cnt:,} tools ({d["all_cits"]:,} citations)</title></rect>'
        )

    svg_parts.append(f'<line x1="{margin_left}" y1="{y_panel1_bottom}" x2="{margin_left + plot_width}" y2="{y_panel1_bottom}" class="axis-line"/>')

    # ------------------ PANEL 2: ELIXIR Tools ------------------
    svg_parts.append(
        f'<text x="{margin_left}" y="{y_panel2_top - 12}" class="panel-title" fill="#7c3aed">'
        f"{p2_title}</text>"
    )

    for i in range(n_ticks + 1):
        frac = i / n_ticks
        val = int(scale_elixir_max * frac)
        y_pos = y_panel2_bottom - (panel_height * frac)
        svg_parts.append(f'<line x1="{margin_left}" y1="{y_pos:.1f}" x2="{margin_left + plot_width}" y2="{y_pos:.1f}" class="gridline"/>')
        val_str = f"{val:,}"
        svg_parts.append(f'<text x="{margin_left - 10}" y="{y_pos + 3.5:.1f}" class="tick-label" text-anchor="end">{val_str}</text>')

    mid_y2 = (y_panel2_top + y_panel2_bottom) / 2
    svg_parts.append(
        f'<text x="25" y="{mid_y2}" class="axis-title" text-anchor="middle" '
        f'transform="rotate(-90 25 {mid_y2})">Number of Tools</text>'
    )

    for idx, d in enumerate(filtered):
        x = margin_left + (idx * slot_width) + bar_offset
        cnt = d["elixir_tools"]
        bar_h = (cnt / scale_elixir_max) * panel_height if scale_elixir_max > 0 else 0
        y = y_panel2_bottom - bar_h
        svg_parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width:.1f}" height="{bar_h:.1f}" rx="2" class="bar-elixir">'
            f'<title>Year {d["year"]}: {cnt:,} tools ({d["elixir_cits"]:,} citations)</title></rect>'
        )

    svg_parts.append(f'<line x1="{margin_left}" y1="{y_panel2_bottom}" x2="{margin_left + plot_width}" y2="{y_panel2_bottom}" class="axis-line"/>')

    # Shared X-axis Labels below Panel 2
    for idx, d in enumerate(filtered):
        center_x = margin_left + (idx * slot_width) + (slot_width / 2.0)
        svg_parts.append(f'<line x1="{center_x:.1f}" y1="{y_panel2_bottom}" x2="{center_x:.1f}" y2="{y_panel2_bottom + 5}" class="axis-line"/>')
        svg_parts.append(
            f'<text x="{center_x + 3:.1f}" y="{y_panel2_bottom + 16:.1f}" class="x-label" '
            f'transform="rotate(-45 {center_x + 3:.1f} {y_panel2_bottom + 16:.1f})">{d["year"]}</text>'
        )

    svg_parts.append(
        f'<text x="{margin_left + (plot_width / 2)}" y="{height - 12}" class="axis-title" text-anchor="middle">'
        f"Tool First Publication Year</text>"
    )

    svg_parts.append("</svg>")

    export_svg_and_png(
        svg_content="\n".join(svg_parts),
        output_path=output_path,
        enable_png=enable_png,
        figure_desc="tools histogram figure",
    )


# =====================================================================
# SVG & PNG Pie Chart Generation
# =====================================================================

def generate_pie_chart_svg(
    slices: List[Dict[str, Any]],
    title: str,
    subtitle: str,
    output_path: str,
    enable_png: bool = True,
) -> None:
    """
    Generates a publication-grade vector pie/donut chart (SVG) visualizing category breakdown.
    Each entry in `slices` is a dict with: 'label', 'count', 'color'.
    """
    total = sum(s["count"] for s in slices)
    if total == 0:
        print(f"No data available to generate pie chart for '{output_path}'.")
        return

    width = 620
    height = 380
    cx = 195
    cy = 205
    radius = 125
    inner_radius = 58  # Donut hole for modern look and central metric

    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="100%" height="auto" style="background:#ffffff; font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif;">',
        '<defs>',
        '  <style>',
        '    .chart-title { font-size: 16px; font-weight: bold; fill: #1a202c; }',
        '    .chart-subtitle { font-size: 11.5px; fill: #718096; }',
        '    .legend-title { font-size: 12px; font-weight: bold; fill: #2d3748; }',
        '    .legend-label { font-size: 12px; font-weight: 600; fill: #1a202c; }',
        '    .legend-sub { font-size: 11px; fill: #718096; }',
        '    .donut-center-num { font-size: 18px; font-weight: bold; fill: #1a202c; text-anchor: middle; }',
        '    .donut-center-lbl { font-size: 10px; fill: #718096; text-anchor: middle; text-transform: uppercase; letter-spacing: 0.5px; }',
        '    .pie-slice { transition: opacity 0.15s, transform 0.15s; cursor: pointer; }',
        '    .pie-slice:hover { opacity: 0.88; }',
        '  </style>',
        '</defs>',
    ]

    # Titles
    svg_parts.append(
        f'<text x="{width / 2}" y="30" class="chart-title" text-anchor="middle">{title}</text>'
    )
    svg_parts.append(
        f'<text x="{width / 2}" y="50" class="chart-subtitle" text-anchor="middle">{subtitle}</text>'
    )

    # Donut Slices
    start_angle = -math.pi / 2.0
    for s in slices:
        cnt = s["count"]
        pct = (cnt / total) * 100.0
        angle = (cnt / total) * 2.0 * math.pi
        end_angle = start_angle + angle

        x1_outer = cx + radius * math.cos(start_angle)
        y1_outer = cy + radius * math.sin(start_angle)
        x2_outer = cx + radius * math.cos(end_angle)
        y2_outer = cy + radius * math.sin(end_angle)

        x1_inner = cx + inner_radius * math.cos(end_angle)
        y1_inner = cy + inner_radius * math.sin(end_angle)
        x2_inner = cx + inner_radius * math.cos(start_angle)
        y2_inner = cy + inner_radius * math.sin(start_angle)

        large_arc = 1 if angle > math.pi else 0

        # Donut sector path
        path_d = (
            f"M {x1_outer:.2f} {y1_outer:.2f} "
            f"A {radius} {radius} 0 {large_arc} 1 {x2_outer:.2f} {y2_outer:.2f} "
            f"L {x1_inner:.2f} {y1_inner:.2f} "
            f"A {inner_radius} {inner_radius} 0 {large_arc} 0 {x2_inner:.2f} {y2_inner:.2f} Z"
        )

        svg_parts.append(
            f'<path d="{path_d}" fill="{s["color"]}" stroke="#ffffff" stroke-width="2" class="pie-slice">'
            f'<title>{s["label"]}: {cnt:,} tools ({pct:.2f}%)</title>'
            f'</path>'
        )

        start_angle = end_angle

    # Center label in donut hole
    svg_parts.append(f'<text x="{cx}" y="{cy - 2}" class="donut-center-num">{total:,}</text>')
    svg_parts.append(f'<text x="{cx}" y="{cy + 15}" class="donut-center-lbl">Tools</text>')

    # Legend Card on the right
    leg_x = 360
    leg_y_start = 120
    box_w = 230
    box_h = len(slices) * 60 + 30

    svg_parts.append(
        f'<rect x="{leg_x - 12}" y="{leg_y_start - 24}" width="{box_w}" height="{box_h}" '
        f'rx="8" fill="#f8fafc" stroke="#e2e8f0" stroke-width="1"/>'
    )
    svg_parts.append(
        f'<text x="{leg_x}" y="{leg_y_start - 6}" class="legend-title">Citation Categories</text>'
    )

    for i, s in enumerate(slices):
        cnt = s["count"]
        pct = (cnt / total) * 100.0
        row_y = leg_y_start + 20 + (i * 56)

        # Color square
        svg_parts.append(
            f'<rect x="{leg_x}" y="{row_y}" width="14" height="14" rx="3" fill="{s["color"]}"/>'
        )
        # Category Name & Percentage
        svg_parts.append(
            f'<text x="{leg_x + 24}" y="{row_y + 11}" class="legend-label">'
            f'{s["label"]} <tspan fill="{s["color"]}">({pct:.1f}%)</tspan></text>'
        )
        # Tool count
        svg_parts.append(
            f'<text x="{leg_x + 24}" y="{row_y + 27}" class="legend-sub">'
            f'{cnt:,} tools</text>'
        )

    svg_parts.append("</svg>")

    export_svg_and_png(
        svg_content="\n".join(svg_parts),
        output_path=output_path,
        enable_png=enable_png,
        figure_desc="pie chart figure",
    )


# =====================================================================
# Top Tools Side-by-Side Comparison SVG Generator
# =====================================================================

def generate_top_tools_comparison_svg(
    enriched_tools: List[Dict],
    output_path: str,
    only_elixir: bool = False,
    top_n: int = 30,
    enable_png: bool = True,
) -> None:
    """
    Generates a publication-grade vector figure (SVG and companion PNG) displaying
    the top N tools side by side across three citation rankings:
      1. All Related Publications (total_citations)
      2. Primary Publications Only (primary_citations)
      3. Primary, Method, or Other Publications (pmo_citations)
    """
    if only_elixir:
        candidates = [t for t in enriched_tools if t.get("is_elixir")]
        main_title = f"Top {top_n} ELIXIR Europe Tools Across Three Citation Rankings"
        sub_title = (
            f"Comparison of top {top_n} ELIXIR software tools by citation count across rankings | "
            "Pills display global bio.tools rank"
        )
    else:
        candidates = enriched_tools
        main_title = f"Top {top_n} bio.tools Across Three Citation Rankings"
        sub_title = (
            f"Comparison of top {top_n} tools in bio.tools across three citation rankings | "
            "Orange badge highlights ELIXIR Europe tools"
        )

    columns = [
        {
            "title": "All Related Publications",
            "subtitle": "Total citations across all linked papers",
            "cit_key": "total_citations",
            "rank_attr": "global_rank",
            "color": "#2563eb",       # Blue
        },
        {
            "title": "Primary Publications Only",
            "subtitle": "Citations strictly from Primary papers",
            "cit_key": "primary_citations",
            "rank_attr": "primary_rank",
            "color": "#7c3aed",       # Purple
        },
        {
            "title": "Primary, Method, or Other",
            "subtitle": "Citations from Primary, Method, or Other papers",
            "cit_key": "pmo_citations",
            "rank_attr": "pmo_rank",
            "color": "#0d9488",       # Teal
        },
    ]

    width = 1470
    margin_top = 80
    margin_left = 30
    col_gap = 25
    col_width = 450
    header_h = 54
    row_h = 36
    height = margin_top + header_h + 8 + (top_n * row_h) + 30

    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="100%" height="auto" style="background:#ffffff; font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif;">',
        '<defs>',
        '  <style>',
        '    .main-title { font-size: 19px; font-weight: bold; fill: #0f172a; }',
        '    .sub-title { font-size: 12px; fill: #64748b; }',
        '    .col-header-title { font-size: 13.5px; font-weight: bold; fill: #ffffff; }',
        '    .col-header-sub { font-size: 10.5px; fill: rgba(255, 255, 255, 0.88); }',
        '    .rank-text { font-size: 9.5px; font-weight: bold; text-anchor: middle; }',
        '    .tool-name { font-size: 11.5px; font-weight: 600; fill: #0f172a; }',
        '    .tool-id { font-size: 9px; fill: #64748b; }',
        '    .cit-num { font-size: 11.5px; font-weight: bold; fill: #0f172a; text-anchor: end; }',
        '    .row-card { transition: opacity 0.1s; }',
        '    .row-card:hover { opacity: 0.92; }',
        '    .badge-elixir-pill { fill: #ffedd5; stroke: #fed7aa; stroke-width: 1; rx: 4px; }',
        '    .badge-elixir-text { font-size: 9px; font-weight: 700; fill: #c2410c; text-anchor: middle; }',
        '    .badge-global-pill { fill: #f1f5f9; stroke: #cbd5e1; stroke-width: 1; rx: 4px; }',
        '    .badge-global-text { font-size: 8.5px; font-weight: 600; fill: #475569; text-anchor: middle; }',
        '  </style>',
        '</defs>',
    ]

    # Main Titles
    svg_parts.append(
        f'<text x="{width / 2}" y="32" class="main-title" text-anchor="middle">{html.escape(main_title)}</text>'
    )
    svg_parts.append(
        f'<text x="{width / 2}" y="52" class="sub-title" text-anchor="middle">{html.escape(sub_title)}</text>'
    )

    # Legend at Top Right for Plot 1
    if not only_elixir:
        leg_x = width - margin_left - 150
        leg_y = 22
        svg_parts.append(
            f'<rect x="{leg_x}" y="{leg_y}" width="150" height="26" rx="6" fill="#f8fafc" stroke="#e2e8f0" stroke-width="1"/>'
        )
        svg_parts.append(
            f'<rect x="{leg_x + 8}" y="{leg_y + 5}" width="46" height="16" rx="3" fill="#ffedd5" stroke="#fed7aa" stroke-width="1"/>'
        )
        svg_parts.append(
            f'<text x="{leg_x + 31}" y="{leg_y + 16.5}" fill="#c2410c" font-size="8.5" font-weight="bold" text-anchor="middle">ELIXIR</text>'
        )
        svg_parts.append(
            f'<text x="{leg_x + 60}" y="{leg_y + 17}" fill="#475569" font-size="10" font-weight="500">= ELIXIR tool</text>'
        )

    # Render 3 Columns
    for col_idx, col in enumerate(columns):
        col_x = margin_left + col_idx * (col_width + col_gap)
        top_tools = sorted(
            candidates,
            key=lambda t: (t.get(col["cit_key"]) or 0),
            reverse=True,
        )[:top_n]
        max_cits = (top_tools[0].get(col["cit_key"]) or 1) if top_tools else 1

        # Column Header Card
        svg_parts.append(
            f'<rect x="{col_x}" y="{margin_top}" width="{col_width}" height="{header_h}" '
            f'rx="8" fill="{col["color"]}"/>'
        )
        svg_parts.append(
            f'<text x="{col_x + 14}" y="{margin_top + 22}" class="col-header-title">{col["title"]}</text>'
        )
        svg_parts.append(
            f'<text x="{col_x + 14}" y="{margin_top + 40}" class="col-header-sub">{col["subtitle"]}</text>'
        )

        # Rows
        for i in range(top_n):
            row_y = margin_top + header_h + 8 + (i * row_h)
            if i < len(top_tools):
                t = top_tools[i]
                rank = i + 1
                cits = t.get(col["cit_key"]) or 0
                is_el = bool(t.get("is_elixir"))
                name = t.get("name") or t.get("biotools_id")
                bt_id = t.get("biotools_id")

                # Truncate strings
                max_name_len = 19 if (not only_elixir and is_el) or only_elixir else 24
                disp_name = (name[:max_name_len - 1] + "…") if len(name) > max_name_len else name
                disp_id = (bt_id[:22] + "…") if len(bt_id) > 23 else bt_id

                # Row background
                if not only_elixir and is_el:
                    row_bg = "#fff7ed"  # soft orange
                    border_color = "#fed7aa"
                    accent_left = f'<line x1="{col_x}" y1="{row_y}" x2="{col_x}" y2="{row_y + row_h - 2}" stroke="#ea580c" stroke-width="3.5"/>'
                else:
                    row_bg = "#ffffff" if (i % 2 == 0) else "#f8fafc"
                    border_color = "#e2e8f0"
                    accent_left = ""

                svg_parts.append('<g class="row-card">')
                svg_parts.append(
                    f'<title>#{rank} {html.escape(name)} ({html.escape(bt_id)})\n{cits:,} citations\n{"ELIXIR tool" if is_el else "bio.tools entry"}</title>'
                )
                svg_parts.append(
                    f'<rect x="{col_x}" y="{row_y}" width="{col_width}" height="{row_h - 2}" '
                    f'rx="5" fill="{row_bg}" stroke="{border_color}" stroke-width="1"/>'
                )
                if accent_left:
                    svg_parts.append(accent_left)

                # Rank pill
                if rank == 1:
                    rp_bg, rp_fg = "#fef3c7", "#92400e"
                elif rank == 2:
                    rp_bg, rp_fg = "#f1f5f9", "#334155"
                elif rank == 3:
                    rp_bg, rp_fg = "#ffedd5", "#9a3412"
                else:
                    rp_bg, rp_fg = "#f1f5f9", "#64748b"

                svg_parts.append(
                    f'<rect x="{col_x + 6}" y="{row_y + 7}" width="26" height="20" rx="3" fill="{rp_bg}"/>'
                )
                svg_parts.append(
                    f'<text x="{col_x + 19}" y="{row_y + 21}" class="rank-text" fill="{rp_fg}">#{rank}</text>'
                )

                # Tool Name and ID
                svg_parts.append(
                    f'<text x="{col_x + 38}" y="{row_y + 15}" class="tool-name">{html.escape(disp_name)}</text>'
                )
                svg_parts.append(
                    f'<text x="{col_x + 38}" y="{row_y + 28}" class="tool-id">{html.escape(disp_id)}</text>'
                )

                # Badge
                if not only_elixir and is_el:
                    # ELIXIR Badge
                    badge_x = col_x + 208
                    svg_parts.append(
                        f'<rect x="{badge_x}" y="{row_y + 8}" width="44" height="17" class="badge-elixir-pill"/>'
                    )
                    svg_parts.append(
                        f'<text x="{badge_x + 22}" y="{row_y + 20}" class="badge-elixir-text">ELIXIR</text>'
                    )
                elif only_elixir:
                    # Global Rank Badge
                    g_rank = t.get(col["rank_attr"])
                    g_str = f"Global #{g_rank:,}" if g_rank else "N/A"
                    badge_x = col_x + 186
                    svg_parts.append(
                        f'<rect x="{badge_x}" y="{row_y + 8}" width="66" height="17" class="badge-global-pill"/>'
                    )
                    svg_parts.append(
                        f'<text x="{badge_x + 33}" y="{row_y + 20}" class="badge-global-text">{g_str}</text>'
                    )

                # Citation Count
                svg_parts.append(
                    f'<text x="{col_x + col_width - 10}" y="{row_y + 16}" class="cit-num">{cits:,}</text>'
                )

                # Citation Mini-bar
                bar_max_w = 65.0
                bar_w = max(2.0, (cits / max_cits) * bar_max_w) if max_cits > 0 else 0
                bar_x = col_x + col_width - 10 - bar_max_w
                svg_parts.append(
                    f'<rect x="{bar_x}" y="{row_y + 22}" width="{bar_max_w}" height="3.5" rx="1.75" fill="#e2e8f0"/>'
                )
                svg_parts.append(
                    f'<rect x="{col_x + col_width - 10 - bar_w}" y="{row_y + 22}" width="{bar_w}" height="3.5" rx="1.75" fill="{col["color"]}"/>'
                )

                svg_parts.append('</g>')

    svg_parts.append("</svg>")

    export_svg_and_png(
        svg_content="\n".join(svg_parts),
        output_path=output_path,
        enable_png=enable_png,
        figure_desc="top tools comparison figure",
    )


# =====================================================================
# Complete Tool Ranking Export
# =====================================================================

def export_ranked_csvs(
    enriched_tools: List[Dict],
    all_csv_path: Optional[str] = None,
    elixir_csv_path: Optional[str] = None,
    primary_all_csv_path: Optional[str] = None,
    primary_elixir_csv_path: Optional[str] = None,
    pmo_all_csv_path: Optional[str] = None,
    pmo_elixir_csv_path: Optional[str] = None,
) -> None:
    """
    Exports CSV rankings:
      1. all_csv_path: All bio.tools ranked by total citations with category,
         percentile rank, is_elixir flag, total, primary, and PMO citation metrics.
      2. elixir_csv_path: ELIXIR tools only ranked by citations.
      3. primary_all_csv_path: All bio.tools ranked by primary publication citations.
      4. primary_elixir_csv_path: ELIXIR tools only ranked by primary publication citations.
      5. pmo_all_csv_path: All bio.tools ranked by Primary, Method, or Other publication citations.
      6. pmo_elixir_csv_path: ELIXIR tools only ranked by Primary, Method, or Other publication citations.
    """
    if all_csv_path:
        out_dir = os.path.dirname(os.path.abspath(all_csv_path))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        sorted_all = sorted(enriched_tools, key=lambda t: t.get("global_rank", 999999))
        with open(all_csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "rank",
                "category",
                "percentile_rank",
                "primary_rank",
                "category_primary",
                "pmo_rank",
                "category_pmo",
                "biotools_id",
                "name",
                "is_elixir",
                "firstPublication",
                "first_primary_publication",
                "first_pmo_publication",
                "total_citations",
                "primary_citations",
                "pmo_citations",
                "publication_count",
                "primary_publication_count",
                "pmo_publication_count",
                "additionDate",
                "repository_url",
                "bio_tools_url",
            ])
            for t in sorted_all:
                writer.writerow([
                    t.get("global_rank"),
                    t.get("category"),
                    f"{t.get('percentile_rank', 0.0):.4f}",
                    t.get("primary_rank") or "",
                    t.get("category_primary") or "",
                    t.get("pmo_rank") or "",
                    t.get("category_pmo") or "",
                    t.get("biotools_id"),
                    t.get("name"),
                    t.get("is_elixir", False),
                    t.get("firstPublication") or "",
                    t.get("first_primary_publication") or "",
                    t.get("first_pmo_publication") or "",
                    t.get("total_citations") or 0,
                    t.get("primary_citations") or 0,
                    t.get("pmo_citations") or 0,
                    t.get("publication_count", 0),
                    t.get("primary_publication_count", 0),
                    t.get("pmo_publication_count", 0),
                    t.get("additionDate") or "",
                    t.get("repository_url") or "",
                    t.get("bio_tools_url") or "",
                ])
        print(f"\nExported complete ranked bio.tools catalogue to '{all_csv_path}'.")

    if elixir_csv_path:
        out_dir = os.path.dirname(os.path.abspath(elixir_csv_path))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        elixir_tools = [t for t in enriched_tools if t.get("is_elixir")]
        elixir_sorted = sorted(elixir_tools, key=lambda t: t.get("global_rank", 999999))
        with open(elixir_csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "elixir_rank",
                "global_rank",
                "category",
                "percentile_rank",
                "primary_rank",
                "category_primary",
                "pmo_rank",
                "category_pmo",
                "biotools_id",
                "name",
                "is_elixir",
                "firstPublication",
                "first_primary_publication",
                "first_pmo_publication",
                "total_citations",
                "primary_citations",
                "pmo_citations",
                "publication_count",
                "primary_publication_count",
                "pmo_publication_count",
                "additionDate",
                "repository_url",
                "bio_tools_url",
            ])
            for el_rank, t in enumerate(elixir_sorted, 1):
                writer.writerow([
                    el_rank,
                    t.get("global_rank"),
                    t.get("category"),
                    f"{t.get('percentile_rank', 0.0):.4f}",
                    t.get("primary_rank") or "",
                    t.get("category_primary") or "",
                    t.get("pmo_rank") or "",
                    t.get("category_pmo") or "",
                    t.get("biotools_id"),
                    t.get("name"),
                    t.get("is_elixir", False),
                    t.get("firstPublication") or "",
                    t.get("first_primary_publication") or "",
                    t.get("first_pmo_publication") or "",
                    t.get("total_citations") or 0,
                    t.get("primary_citations") or 0,
                    t.get("pmo_citations") or 0,
                    t.get("publication_count", 0),
                    t.get("primary_publication_count", 0),
                    t.get("pmo_publication_count", 0),
                    t.get("additionDate") or "",
                    t.get("repository_url") or "",
                    t.get("bio_tools_url") or "",
                ])
        print(f"Exported ELIXIR-only ranked catalogue to '{elixir_csv_path}'.")

    if primary_all_csv_path:
        out_dir = os.path.dirname(os.path.abspath(primary_all_csv_path))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        sorted_prim = sorted(enriched_tools, key=lambda t: t.get("primary_rank", 999999))
        with open(primary_all_csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "primary_rank",
                "category_primary",
                "primary_percentile_rank",
                "total_citations_rank",
                "category_all",
                "pmo_rank",
                "category_pmo",
                "biotools_id",
                "name",
                "is_elixir",
                "first_primary_publication",
                "firstPublication",
                "first_pmo_publication",
                "primary_citations",
                "total_citations",
                "pmo_citations",
                "primary_publication_count",
                "publication_count",
                "pmo_publication_count",
                "additionDate",
                "repository_url",
                "bio_tools_url",
            ])
            for t in sorted_prim:
                writer.writerow([
                    t.get("primary_rank"),
                    t.get("category_primary"),
                    f"{t.get('primary_percentile_rank', 0.0):.4f}" if t.get("primary_percentile_rank") is not None else "",
                    t.get("global_rank"),
                    t.get("category"),
                    t.get("pmo_rank") or "",
                    t.get("category_pmo") or "",
                    t.get("biotools_id"),
                    t.get("name"),
                    t.get("is_elixir", False),
                    t.get("first_primary_publication") or "",
                    t.get("firstPublication") or "",
                    t.get("first_pmo_publication") or "",
                    t.get("primary_citations") or 0,
                    t.get("total_citations") or 0,
                    t.get("pmo_citations") or 0,
                    t.get("primary_publication_count", 0),
                    t.get("publication_count", 0),
                    t.get("pmo_publication_count", 0),
                    t.get("additionDate") or "",
                    t.get("repository_url") or "",
                    t.get("bio_tools_url") or "",
                ])
        print(f"Exported complete ranked bio.tools catalogue (by primary citations) to '{primary_all_csv_path}'.")

    if primary_elixir_csv_path:
        out_dir = os.path.dirname(os.path.abspath(primary_elixir_csv_path))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        elixir_prim = [t for t in enriched_tools if t.get("is_elixir")]
        elixir_prim_sorted = sorted(elixir_prim, key=lambda t: t.get("primary_rank", 999999))
        with open(primary_elixir_csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "elixir_primary_rank",
                "primary_rank",
                "category_primary",
                "primary_percentile_rank",
                "global_rank",
                "category_all",
                "pmo_rank",
                "category_pmo",
                "biotools_id",
                "name",
                "is_elixir",
                "first_primary_publication",
                "firstPublication",
                "first_pmo_publication",
                "primary_citations",
                "total_citations",
                "pmo_citations",
                "primary_publication_count",
                "publication_count",
                "pmo_publication_count",
                "additionDate",
                "repository_url",
                "bio_tools_url",
            ])
            for el_rank, t in enumerate(elixir_prim_sorted, 1):
                writer.writerow([
                    el_rank,
                    t.get("primary_rank"),
                    t.get("category_primary"),
                    f"{t.get('primary_percentile_rank', 0.0):.4f}" if t.get("primary_percentile_rank") is not None else "",
                    t.get("global_rank"),
                    t.get("category"),
                    t.get("pmo_rank") or "",
                    t.get("category_pmo") or "",
                    t.get("biotools_id"),
                    t.get("name"),
                    t.get("is_elixir", False),
                    t.get("first_primary_publication") or "",
                    t.get("firstPublication") or "",
                    t.get("first_pmo_publication") or "",
                    t.get("primary_citations") or 0,
                    t.get("total_citations") or 0,
                    t.get("pmo_citations") or 0,
                    t.get("primary_publication_count", 0),
                    t.get("publication_count", 0),
                    t.get("pmo_publication_count", 0),
                    t.get("additionDate") or "",
                    t.get("repository_url") or "",
                    t.get("bio_tools_url") or "",
                ])
        print(f"Exported ELIXIR-only ranked catalogue (by primary citations) to '{primary_elixir_csv_path}'.")

    if pmo_all_csv_path:
        out_dir = os.path.dirname(os.path.abspath(pmo_all_csv_path))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        sorted_pmo = sorted(enriched_tools, key=lambda t: t.get("pmo_rank", 999999))
        with open(pmo_all_csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "pmo_rank",
                "category_pmo",
                "pmo_percentile_rank",
                "total_citations_rank",
                "category_all",
                "primary_rank",
                "category_primary",
                "biotools_id",
                "name",
                "is_elixir",
                "first_pmo_publication",
                "first_primary_publication",
                "firstPublication",
                "pmo_citations",
                "primary_citations",
                "total_citations",
                "pmo_publication_count",
                "primary_publication_count",
                "publication_count",
                "additionDate",
                "repository_url",
                "bio_tools_url",
            ])
            for t in sorted_pmo:
                writer.writerow([
                    t.get("pmo_rank"),
                    t.get("category_pmo"),
                    f"{t.get('pmo_percentile_rank', 0.0):.4f}" if t.get("pmo_percentile_rank") is not None else "",
                    t.get("global_rank"),
                    t.get("category"),
                    t.get("primary_rank") or "",
                    t.get("category_primary") or "",
                    t.get("biotools_id"),
                    t.get("name"),
                    t.get("is_elixir", False),
                    t.get("first_pmo_publication") or "",
                    t.get("first_primary_publication") or "",
                    t.get("firstPublication") or "",
                    t.get("pmo_citations") or 0,
                    t.get("primary_citations") or 0,
                    t.get("total_citations") or 0,
                    t.get("pmo_publication_count", 0),
                    t.get("primary_publication_count", 0),
                    t.get("publication_count", 0),
                    t.get("additionDate") or "",
                    t.get("repository_url") or "",
                    t.get("bio_tools_url") or "",
                ])
        print(f"Exported complete ranked bio.tools catalogue (by Primary/Method/Other citations) to '{pmo_all_csv_path}'.")

    if pmo_elixir_csv_path:
        out_dir = os.path.dirname(os.path.abspath(pmo_elixir_csv_path))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        elixir_pmo = [t for t in enriched_tools if t.get("is_elixir")]
        elixir_pmo_sorted = sorted(elixir_pmo, key=lambda t: t.get("pmo_rank", 999999))
        with open(pmo_elixir_csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "elixir_pmo_rank",
                "pmo_rank",
                "category_pmo",
                "pmo_percentile_rank",
                "global_rank",
                "category_all",
                "primary_rank",
                "category_primary",
                "biotools_id",
                "name",
                "is_elixir",
                "first_pmo_publication",
                "first_primary_publication",
                "firstPublication",
                "pmo_citations",
                "primary_citations",
                "total_citations",
                "pmo_publication_count",
                "primary_publication_count",
                "publication_count",
                "additionDate",
                "repository_url",
                "bio_tools_url",
            ])
            for el_rank, t in enumerate(elixir_pmo_sorted, 1):
                writer.writerow([
                    el_rank,
                    t.get("pmo_rank"),
                    t.get("category_pmo"),
                    f"{t.get('pmo_percentile_rank', 0.0):.4f}" if t.get("pmo_percentile_rank") is not None else "",
                    t.get("global_rank"),
                    t.get("category"),
                    t.get("primary_rank") or "",
                    t.get("category_primary") or "",
                    t.get("biotools_id"),
                    t.get("name"),
                    t.get("is_elixir", False),
                    t.get("first_pmo_publication") or "",
                    t.get("first_primary_publication") or "",
                    t.get("firstPublication") or "",
                    t.get("pmo_citations") or 0,
                    t.get("primary_citations") or 0,
                    t.get("total_citations") or 0,
                    t.get("pmo_publication_count", 0),
                    t.get("primary_publication_count", 0),
                    t.get("publication_count", 0),
                    t.get("additionDate") or "",
                    t.get("repository_url") or "",
                    t.get("bio_tools_url") or "",
                ])
        print(f"Exported ELIXIR-only ranked catalogue (by Primary/Method/Other citations) to '{pmo_elixir_csv_path}'.")


def main():
    parser = argparse.ArgumentParser(
        description="Analyze citation percentiles, yearly distributions, and metrics for ELIXIR tools in the bio.tools dataset."
    )
    parser.add_argument(
        "--input-json",
        "-i",
        default="outputs/json/biotools_publications_elixir_incl.json",
        help="Path to input enriched JSON file (default: outputs/json/biotools_publications_elixir_incl.json).",
    )
    parser.add_argument(
        "--export-all-csv",
        "--export-csv",
        dest="export_all_csv",
        default="outputs/csv/all_biotools_ranked.csv",
        help="Path to export ranked CSV of all bio.tools with categories (default: outputs/csv/all_biotools_ranked.csv).",
    )
    parser.add_argument(
        "--export-elixir-csv",
        default="outputs/csv/elixir_tools_ranked.csv",
        help="Path to export ranked CSV of ELIXIR tools only (default: outputs/csv/elixir_tools_ranked.csv).",
    )
    parser.add_argument(
        "--export-all-primary-csv",
        default="outputs/csv/all_biotools_primary_ranked.csv",
        help="Path to export ranked CSV of all bio.tools ranked by primary citations (default: outputs/csv/all_biotools_primary_ranked.csv).",
    )
    parser.add_argument(
        "--export-elixir-primary-csv",
        default="outputs/csv/elixir_tools_primary_ranked.csv",
        help="Path to export ranked CSV of ELIXIR tools ranked by primary citations (default: outputs/csv/elixir_tools_primary_ranked.csv).",
    )
    parser.add_argument(
        "--export-all-pmo-csv",
        default="outputs/csv/all_biotools_pmo_ranked.csv",
        help="Path to export ranked CSV of all bio.tools ranked by Primary, Method, or Other citations (default: outputs/csv/all_biotools_pmo_ranked.csv).",
    )
    parser.add_argument(
        "--export-elixir-pmo-csv",
        default="outputs/csv/elixir_tools_pmo_ranked.csv",
        help="Path to export ranked CSV of ELIXIR tools ranked by Primary, Method, or Other citations (default: outputs/csv/elixir_tools_pmo_ranked.csv).",
    )
    parser.add_argument(
        "--export-year-csv",
        help="Optional path to export yearly citation sums and tool counts to CSV (all publications).",
    )
    parser.add_argument(
        "--export-year-primary-csv",
        help="Optional path to export yearly citation sums and tool counts to CSV (primary publications only).",
    )
    parser.add_argument(
        "--export-year-pmo-csv",
        help="Optional path to export yearly citation sums and tool counts to CSV (Primary, Method, or Other publications).",
    )
    parser.add_argument(
        "--plot-citations-file",
        "--plot-file",
        dest="plot_citations_file",
        default="outputs/plots/citations_by_year.svg",
        help="Path to save citations per year histogram figure for all publications (default: outputs/plots/citations_by_year.svg). Use 'none' to skip.",
    )
    parser.add_argument(
        "--plot-citations-primary-file",
        default="outputs/plots/citations_primary_by_year.svg",
        help="Path to save citations per year histogram figure for primary publications only (default: outputs/plots/citations_primary_by_year.svg). Use 'none' to skip.",
    )
    parser.add_argument(
        "--plot-citations-pmo-file",
        default="outputs/plots/citations_pmo_by_year.svg",
        help="Path to save citations per year histogram figure for Primary, Method, or Other publications (default: outputs/plots/citations_pmo_by_year.svg). Use 'none' to skip.",
    )
    parser.add_argument(
        "--plot-tools-file",
        default="outputs/plots/tools_by_year.svg",
        help="Path to save tools per year histogram figure for all tools (default: outputs/plots/tools_by_year.svg). Use 'none' to skip.",
    )
    parser.add_argument(
        "--plot-tools-primary-file",
        default="outputs/plots/tools_primary_by_year.svg",
        help="Path to save tools per year histogram figure for tools with primary publications (default: outputs/plots/tools_primary_by_year.svg). Use 'none' to skip.",
    )
    parser.add_argument(
        "--plot-tools-pmo-file",
        default="outputs/plots/tools_pmo_by_year.svg",
        help="Path to save tools per year histogram figure for tools with Primary, Method, or Other publications (default: outputs/plots/tools_pmo_by_year.svg). Use 'none' to skip.",
    )
    parser.add_argument(
        "--plot-biotools-pie",
        default="outputs/plots/biotools_categories_pie.svg",
        help="Path to save all bio.tools category breakdown pie chart (all publications) (default: outputs/plots/biotools_categories_pie.svg). Use 'none' to skip.",
    )
    parser.add_argument(
        "--plot-biotools-pie-primary",
        default="outputs/plots/biotools_categories_pie_primary.svg",
        help="Path to save all bio.tools category breakdown pie chart (primary publications only) (default: outputs/plots/biotools_categories_pie_primary.svg). Use 'none' to skip.",
    )
    parser.add_argument(
        "--plot-biotools-pie-pmo",
        default="outputs/plots/biotools_categories_pie_pmo.svg",
        help="Path to save all bio.tools category breakdown pie chart (Primary, Method, or Other publications) (default: outputs/plots/biotools_categories_pie_pmo.svg). Use 'none' to skip.",
    )
    parser.add_argument(
        "--plot-elixir-pie",
        default="outputs/plots/elixir_categories_pie.svg",
        help="Path to save ELIXIR tools category breakdown pie chart (all publications) (default: outputs/plots/elixir_categories_pie.svg). Use 'none' to skip.",
    )
    parser.add_argument(
        "--plot-elixir-pie-primary",
        default="outputs/plots/elixir_categories_pie_primary.svg",
        help="Path to save ELIXIR tools category breakdown pie chart (primary publications only) (default: outputs/plots/elixir_categories_pie_primary.svg). Use 'none' to skip.",
    )
    parser.add_argument(
        "--plot-elixir-pie-pmo",
        default="outputs/plots/elixir_categories_pie_pmo.svg",
        help="Path to save ELIXIR tools category breakdown pie chart (Primary, Method, or Other publications) (default: outputs/plots/elixir_categories_pie_pmo.svg). Use 'none' to skip.",
    )
    parser.add_argument(
        "--plot-top30-all-file",
        "--plot-top20-all-file",
        dest="plot_top30_all_file",
        default="outputs/plots/top30_biotools_rankings.svg",
        help="Path to save top N bio.tools across three rankings comparison figure (default: outputs/plots/top30_biotools_rankings.svg). Use 'none' to skip.",
    )
    parser.add_argument(
        "--plot-top30-elixir-file",
        "--plot-top20-elixir-file",
        dest="plot_top30_elixir_file",
        default="outputs/plots/top30_elixir_rankings.svg",
        help="Path to save top N ELIXIR tools across three rankings comparison figure (default: outputs/plots/top30_elixir_rankings.svg). Use 'none' to skip.",
    )
    parser.add_argument(
        "--top-tools-n",
        type=int,
        default=30,
        help="Number of tools to show in top tools ranking comparison figures (default: 30).",
    )
    parser.add_argument(
        "--plot-start-year",
        type=int,
        default=1990,
        help="Earliest publication year to include on histogram charts (default: 1990).",
    )
    parser.add_argument(
        "--no-png",
        action="store_true",
        default=False,
        help="Disable automatic generation of raster PNG copies alongside SVG figures.",
    )
    parser.add_argument(
        "--max-tools-print",
        type=int,
        default=25,
        help="Maximum number of tools to list under each tier in stdout (default: 25).",
    )

    args = parser.parse_args()

    # Auto-fallback to legacy root directory paths if new directory structure is not used
    if not os.path.isfile(args.input_json) and os.path.isfile("biotools_publications_elixir_incl.json"):
        args.input_json = "biotools_publications_elixir_incl.json"

    if not os.path.isfile(args.input_json):
        print(f"Error: Input file '{args.input_json}' not found.", file=sys.stderr)
        sys.exit(1)

    print(f"Loading dataset from '{args.input_json}'...")
    with open(args.input_json, "r", encoding="utf-8") as f:
        tools = json.load(f)

    total_tools = len(tools)
    elixir_tools = [t for t in tools if t.get("is_elixir")]
    non_elixir_tools = [t for t in tools if not t.get("is_elixir")]
    total_elixir = len(elixir_tools)

    # Citation counts: Total vs Primary vs PMO (normalized None -> 0)
    all_citations = [(t.get("total_citations") or 0) for t in tools]
    elixir_citations = [(t.get("total_citations") or 0) for t in elixir_tools]
    non_elixir_citations = [(t.get("total_citations") or 0) for t in non_elixir_tools]

    all_primary_citations = [(t.get("primary_citations") or 0) for t in tools]
    elixir_primary_citations = [(t.get("primary_citations") or 0) for t in elixir_tools]
    non_elixir_primary_citations = [(t.get("primary_citations") or 0) for t in non_elixir_tools]

    all_pmo_citations = [(t.get("pmo_citations") or 0) for t in tools]
    elixir_pmo_citations = [(t.get("pmo_citations") or 0) for t in elixir_tools]
    non_elixir_pmo_citations = [(t.get("pmo_citations") or 0) for t in non_elixir_tools]

    # Non-zero counts
    non_zero_all = sum(1 for c in all_citations if c > 0)
    non_zero_elixir = sum(1 for c in elixir_citations if c > 0)
    non_zero_non_elixir = sum(1 for c in non_elixir_citations if c > 0)

    non_zero_prim_all = sum(1 for c in all_primary_citations if c > 0)
    non_zero_prim_elixir = sum(1 for c in elixir_primary_citations if c > 0)
    non_zero_prim_non_elixir = sum(1 for c in non_elixir_primary_citations if c > 0)

    non_zero_pmo_all = sum(1 for c in all_pmo_citations if c > 0)
    non_zero_pmo_elixir = sum(1 for c in elixir_pmo_citations if c > 0)
    non_zero_pmo_non_elixir = sum(1 for c in non_elixir_pmo_citations if c > 0)

    # Zero counts
    zero_all = total_tools - non_zero_all
    zero_elixir = total_elixir - non_zero_elixir
    zero_prim_all = total_tools - non_zero_prim_all
    zero_prim_elixir = total_elixir - non_zero_prim_elixir
    zero_pmo_all = total_tools - non_zero_pmo_all
    zero_pmo_elixir = total_elixir - non_zero_pmo_elixir

    # Summary distributions
    stats_all = compute_statistics(all_citations)
    stats_elixir = compute_statistics(elixir_citations)
    stats_prim_all = compute_statistics(all_primary_citations)
    stats_prim_elixir = compute_statistics(elixir_primary_citations)
    stats_pmo_all = compute_statistics(all_pmo_citations)
    stats_pmo_elixir = compute_statistics(elixir_pmo_citations)

    # Print Non-zero & General Statistics Report: Total Citations (All Publications)
    print("\n" + "=" * 76)
    print("      OVERALL CITATION STATISTICS: ALL RELATED PUBLICATIONS")
    print("=" * 76)
    print(f"Total bio.tools entries:                 {total_tools:,}")
    print(f"  - ELIXIR tools:                        {total_elixir:,} ({total_elixir/total_tools*100:.2f}%)")
    print(f"  - Non-ELIXIR tools:                    {len(non_elixir_tools):,} ({len(non_elixir_tools)/total_tools*100:.2f}%)")
    print("-" * 76)
    print("NON-ZERO CITATION PROPORTIONS (All Related Publications):")
    print(f"  * All bio.tools (incl. ELIXIR):        {non_zero_all:,} / {total_tools:,} ({non_zero_all/total_tools*100:.2f}%)")
    print(f"  * ELIXIR tools:                        {non_zero_elixir:,} / {total_elixir:,} ({non_zero_elixir/total_elixir*100:.2f}%)")
    print(f"  * Non-ELIXIR tools:                    {non_zero_non_elixir:,} / {len(non_elixir_tools):,} ({non_zero_non_elixir/len(non_elixir_tools)*100:.2f}%)")
    print("-" * 76)
    print("ZERO CITATION PROPORTIONS (All Related Publications):")
    print(f"  * All bio.tools (0 citations):         {zero_all:,} ({zero_all/total_tools*100:.2f}%)")
    print(f"  * ELIXIR tools (0 citations):          {zero_elixir:,} ({zero_elixir/total_elixir*100:.2f}%)")
    print("-" * 76)
    print("CITATION DISTRIBUTION METRICS (All Related Publications):")
    print(f"  * Total citations across ALL tools:    {stats_all['sum']:,}")
    print(f"  * Total citations across ELIXIR tools: {stats_elixir['sum']:,} ({stats_elixir['sum']/stats_all['sum']*100:.2f}% of all citations)" if stats_all['sum'] else "")
    print(f"  * Mean citations per tool:             ALL: {stats_all['mean']:.1f} | ELIXIR: {stats_elixir['mean']:.1f}")
    print(f"  * Median citations per tool:           ALL: {stats_all['median']:.1f} | ELIXIR: {stats_elixir['median']:.1f}")
    print(f"  * Maximum citations for a tool:        ALL: {stats_all['max']:,} | ELIXIR: {stats_elixir['max']:,}")

    # Print Non-zero & General Statistics Report: Primary Publications Only
    print("\n" + "=" * 76)
    print("      OVERALL CITATION STATISTICS: PRIMARY PUBLICATIONS ONLY")
    print("=" * 76)
    print("NON-ZERO CITATION PROPORTIONS (Primary Publications Only):")
    print(f"  * All bio.tools (incl. ELIXIR):        {non_zero_prim_all:,} / {total_tools:,} ({non_zero_prim_all/total_tools*100:.2f}%)")
    print(f"  * ELIXIR tools:                        {non_zero_prim_elixir:,} / {total_elixir:,} ({non_zero_prim_elixir/total_elixir*100:.2f}%)")
    print(f"  * Non-ELIXIR tools:                    {non_zero_prim_non_elixir:,} / {len(non_elixir_tools):,} ({non_zero_prim_non_elixir/len(non_elixir_tools)*100:.2f}%)")
    print("-" * 76)
    print("ZERO CITATION PROPORTIONS (Primary Publications Only):")
    print(f"  * All bio.tools (0 citations):         {zero_prim_all:,} ({zero_prim_all/total_tools*100:.2f}%)")
    print(f"  * ELIXIR tools (0 citations):          {zero_prim_elixir:,} ({zero_prim_elixir/total_elixir*100:.2f}%)")
    print("-" * 76)
    print("CITATION DISTRIBUTION METRICS (Primary Publications Only):")
    print(f"  * Total citations across ALL tools:    {stats_prim_all['sum']:,}")
    print(f"  * Total citations across ELIXIR tools: {stats_prim_elixir['sum']:,} ({stats_prim_elixir['sum']/stats_prim_all['sum']*100:.2f}% of all citations)" if stats_prim_all['sum'] else "")
    print(f"  * Mean citations per tool:             ALL: {stats_prim_all['mean']:.1f} | ELIXIR: {stats_prim_elixir['mean']:.1f}")
    print(f"  * Median citations per tool:           ALL: {stats_prim_all['median']:.1f} | ELIXIR: {stats_prim_elixir['median']:.1f}")
    print(f"  * Maximum citations for a tool:        ALL: {stats_prim_all['max']:,} | ELIXIR: {stats_prim_elixir['max']:,}")

    # Print Non-zero & General Statistics Report: Primary, Method, or Other Publications
    print("\n" + "=" * 76)
    print("  OVERALL CITATION STATISTICS: PRIMARY, METHOD, OR OTHER PUBLICATIONS")
    print("=" * 76)
    print("NON-ZERO CITATION PROPORTIONS (Primary, Method, or Other Publications):")
    print(f"  * All bio.tools (incl. ELIXIR):        {non_zero_pmo_all:,} / {total_tools:,} ({non_zero_pmo_all/total_tools*100:.2f}%)")
    print(f"  * ELIXIR tools:                        {non_zero_pmo_elixir:,} / {total_elixir:,} ({non_zero_pmo_elixir/total_elixir*100:.2f}%)")
    print(f"  * Non-ELIXIR tools:                    {non_zero_pmo_non_elixir:,} / {len(non_elixir_tools):,} ({non_zero_pmo_non_elixir/len(non_elixir_tools)*100:.2f}%)")
    print("-" * 76)
    print("ZERO CITATION PROPORTIONS (Primary, Method, or Other Publications):")
    print(f"  * All bio.tools (0 citations):         {zero_pmo_all:,} ({zero_pmo_all/total_tools*100:.2f}%)")
    print(f"  * ELIXIR tools (0 citations):          {zero_pmo_elixir:,} ({zero_pmo_elixir/total_elixir*100:.2f}%)")
    print("-" * 76)
    print("CITATION DISTRIBUTION METRICS (Primary, Method, or Other Publications):")
    print(f"  * Total citations across ALL tools:    {stats_pmo_all['sum']:,}")
    print(f"  * Total citations across ELIXIR tools: {stats_pmo_elixir['sum']:,} ({stats_pmo_elixir['sum']/stats_pmo_all['sum']*100:.2f}% of all citations)" if stats_pmo_all['sum'] else "")
    print(f"  * Mean citations per tool:             ALL: {stats_pmo_all['mean']:.1f} | ELIXIR: {stats_pmo_elixir['mean']:.1f}")
    print(f"  * Median citations per tool:           ALL: {stats_pmo_all['median']:.1f} | ELIXIR: {stats_pmo_elixir['median']:.1f}")
    print(f"  * Maximum citations for a tool:        ALL: {stats_pmo_all['max']:,} | ELIXIR: {stats_pmo_elixir['max']:,}")

    # 1. Categorize tools three times:
    # 1a. Based on Total Citations (All related publications)
    enriched_tools, metadata_all = categorize_tools(
        tools=tools,
        citation_key="total_citations",
        category_attr="category",
        rank_attr="global_rank",
        percentile_attr="percentile_rank",
    )
    # 1b. Based on Primary Citations (Primary publications only)
    enriched_tools, metadata_prim = categorize_tools(
        tools=enriched_tools,
        citation_key="primary_citations",
        category_attr="category_primary",
        rank_attr="primary_rank",
        percentile_attr="primary_percentile_rank",
    )
    # 1c. Based on PMO Citations (Primary, Method, or Other publications)
    enriched_tools, metadata_pmo = categorize_tools(
        tools=enriched_tools,
        citation_key="pmo_citations",
        category_attr="category_pmo",
        rank_attr="pmo_rank",
        percentile_attr="pmo_percentile_rank",
    )

    # 2. Tool-level categorization analysis
    # 2a. All Related Publications
    analyze_tool_percentiles(
        enriched_tools=enriched_tools,
        metadata=metadata_all,
        max_print_per_tier=args.max_tools_print,
        title_suffix="Ranked by Total Citations [All Publications]",
    )
    # 2b. Primary Publications Only
    analyze_tool_percentiles(
        enriched_tools=enriched_tools,
        metadata=metadata_prim,
        max_print_per_tier=args.max_tools_print,
        title_suffix="Ranked by Primary Citations [Primary Publications Only]",
    )
    # 2c. Primary, Method, or Other Publications
    analyze_tool_percentiles(
        enriched_tools=enriched_tools,
        metadata=metadata_pmo,
        max_print_per_tier=args.max_tools_print,
        title_suffix="Ranked by PMO Citations [Primary, Method, or Other Publications]",
    )

    # 3. Publication-level percentile analysis (Top 1% and Top 10%)
    pub_tiers = [
        ("Top 1%", 0.01),
        ("Top 10%", 0.10),
    ]
    analyze_publication_percentiles(
        tools=tools,
        tiers=pub_tiers,
        print_pubs=True,
        max_print_per_tier=10,
    )

    # 4. Citations & Tools by Year analysis (three times: All vs Primary vs PMO)
    yearly_data_all = analyze_citations_by_year(
        tools=tools,
        start_year=args.plot_start_year,
        export_csv=args.export_year_csv,
        citation_key="total_citations",
        date_key="firstPublication",
        title_label="All Related Publications",
    )
    yearly_data_prim = analyze_citations_by_year(
        tools=tools,
        start_year=args.plot_start_year,
        export_csv=args.export_year_primary_csv,
        citation_key="primary_citations",
        date_key="first_primary_publication",
        title_label="Primary Publications Only",
    )
    yearly_data_pmo = analyze_citations_by_year(
        tools=tools,
        start_year=args.plot_start_year,
        export_csv=args.export_year_pmo_csv,
        citation_key="pmo_citations",
        date_key="first_pmo_publication",
        title_label="Primary, Method, or Other Publications",
    )

    # 5. Export Ranked CSVs (All, Primary, and PMO)
    export_ranked_csvs(
        enriched_tools=enriched_tools,
        all_csv_path=args.export_all_csv,
        elixir_csv_path=args.export_elixir_csv,
        primary_all_csv_path=args.export_all_primary_csv,
        primary_elixir_csv_path=args.export_elixir_primary_csv,
        pmo_all_csv_path=args.export_all_pmo_csv,
        pmo_elixir_csv_path=args.export_elixir_pmo_csv,
    )

    # 6. Generate Figures
    enable_png = not args.no_png

    # 6a. Citations Histograms
    if args.plot_citations_file and args.plot_citations_file.lower() != "none":
        generate_citations_histogram(
            yearly_data=yearly_data_all,
            output_path=args.plot_citations_file,
            start_year=args.plot_start_year,
            enable_png=enable_png,
            title="Distribution of Total Citations by Tool's First Publication Year",
            subtitle=f"Sum of citations across bio.tools (top) and ELIXIR tools (bottom) [All Publications] | Years {args.plot_start_year}+",
            panel1_title="■ All bio.tools (Total Citations)",
            panel2_title="■ ELIXIR Europe Tools (Total Citations)",
            y_axis_label="Total Citations",
        )

    if args.plot_citations_primary_file and args.plot_citations_primary_file.lower() != "none":
        generate_citations_histogram(
            yearly_data=yearly_data_prim,
            output_path=args.plot_citations_primary_file,
            start_year=args.plot_start_year,
            enable_png=enable_png,
            title="Distribution of Primary Citations by Tool Publication Year",
            subtitle=f"Sum of citations across bio.tools (top) and ELIXIR tools (bottom) [Primary Publications Only] | Years {args.plot_start_year}+",
            panel1_title="■ All bio.tools (Primary Citations)",
            panel2_title="■ ELIXIR Europe Tools (Primary Citations)",
            y_axis_label="Primary Citations",
        )

    if args.plot_citations_pmo_file and args.plot_citations_pmo_file.lower() != "none":
        generate_citations_histogram(
            yearly_data=yearly_data_pmo,
            output_path=args.plot_citations_pmo_file,
            start_year=args.plot_start_year,
            enable_png=enable_png,
            title="Distribution of PMO Citations by Tool Publication Year",
            subtitle=f"Sum of citations across bio.tools (top) and ELIXIR tools (bottom) [Primary, Method, or Other] | Years {args.plot_start_year}+",
            panel1_title="■ All bio.tools (PMO Citations)",
            panel2_title="■ ELIXIR Europe Tools (PMO Citations)",
            y_axis_label="PMO Citations",
        )

    # 6b. Tools Histograms
    if args.plot_tools_file and args.plot_tools_file.lower() != "none":
        generate_tools_histogram(
            yearly_data=yearly_data_all,
            output_path=args.plot_tools_file,
            start_year=args.plot_start_year,
            enable_png=enable_png,
            title="Distribution of Tool Counts by First Publication Year",
            subtitle=f"Number of tools first published per year: bio.tools (top) and ELIXIR software tools (bottom) [All Tools] | Years {args.plot_start_year}+",
            panel1_title="■ All bio.tools (Tool Count)",
            panel2_title="■ ELIXIR Europe Tools (Tool Count)",
        )

    if args.plot_tools_primary_file and args.plot_tools_primary_file.lower() != "none":
        generate_tools_histogram(
            yearly_data=yearly_data_prim,
            output_path=args.plot_tools_primary_file,
            start_year=args.plot_start_year,
            enable_png=enable_png,
            title="Distribution of Tools with Primary Publications by Year",
            subtitle=f"Number of tools with primary publications: bio.tools (top) and ELIXIR tools (bottom) [Primary Publications Only] | Years {args.plot_start_year}+",
            panel1_title="■ All bio.tools (Tools with Primary Pub)",
            panel2_title="■ ELIXIR Europe Tools (Tools with Primary Pub)",
        )

    if args.plot_tools_pmo_file and args.plot_tools_pmo_file.lower() != "none":
        generate_tools_histogram(
            yearly_data=yearly_data_pmo,
            output_path=args.plot_tools_pmo_file,
            start_year=args.plot_start_year,
            enable_png=enable_png,
            title="Distribution of Tools with PMO Publications by Year",
            subtitle=f"Number of tools with Primary, Method, or Other publications: bio.tools (top) and ELIXIR tools (bottom) | Years {args.plot_start_year}+",
            panel1_title="■ All bio.tools (Tools with PMO Pub)",
            panel2_title="■ ELIXIR Europe Tools (Tools with PMO Pub)",
        )

    # 6c. Pie Charts
    color_top1 = "#d97706"
    color_top10 = "#2563eb"
    color_avg = "#64748b"

    # Pie charts for All Publications
    counts_all = metadata_all["category_counts_all"]
    slices_all = [
        {"label": "Top 1%", "count": counts_all["Top 1%"], "color": color_top1},
        {"label": "Top 10%", "count": counts_all["Top 10%"], "color": color_top10},
        {"label": "Average", "count": counts_all["Average"], "color": color_avg},
    ]
    if args.plot_biotools_pie and args.plot_biotools_pie.lower() != "none":
        generate_pie_chart_svg(
            slices=slices_all,
            title="Citation Category Breakdown: All bio.tools (All Publications)",
            subtitle=f"Distribution of {total_tools:,} tools across Top 1%, Top 10%, and Average tiers",
            output_path=args.plot_biotools_pie,
            enable_png=enable_png,
        )

    counts_elixir = metadata_all["category_counts_elixir"]
    slices_elixir = [
        {"label": "Top 1%", "count": counts_elixir["Top 1%"], "color": color_top1},
        {"label": "Top 10%", "count": counts_elixir["Top 10%"], "color": color_top10},
        {"label": "Average", "count": counts_elixir["Average"], "color": color_avg},
    ]
    if args.plot_elixir_pie and args.plot_elixir_pie.lower() != "none":
        generate_pie_chart_svg(
            slices=slices_elixir,
            title="Citation Category Breakdown: ELIXIR Tools (All Publications)",
            subtitle=f"Distribution of {total_elixir:,} ELIXIR tools across bio.tools citation tiers",
            output_path=args.plot_elixir_pie,
            enable_png=enable_png,
        )

    # Pie charts for Primary Publications Only
    counts_prim_all = metadata_prim["category_counts_all"]
    slices_prim_all = [
        {"label": "Top 1%", "count": counts_prim_all["Top 1%"], "color": color_top1},
        {"label": "Top 10%", "count": counts_prim_all["Top 10%"], "color": color_top10},
        {"label": "Average", "count": counts_prim_all["Average"], "color": color_avg},
    ]
    if args.plot_biotools_pie_primary and args.plot_biotools_pie_primary.lower() != "none":
        generate_pie_chart_svg(
            slices=slices_prim_all,
            title="Citation Category Breakdown: All bio.tools (Primary Publications)",
            subtitle=f"Distribution of {total_tools:,} tools based on Primary Publication citations",
            output_path=args.plot_biotools_pie_primary,
            enable_png=enable_png,
        )

    counts_prim_elixir = metadata_prim["category_counts_elixir"]
    slices_prim_elixir = [
        {"label": "Top 1%", "count": counts_prim_elixir["Top 1%"], "color": color_top1},
        {"label": "Top 10%", "count": counts_prim_elixir["Top 10%"], "color": color_top10},
        {"label": "Average", "count": counts_prim_elixir["Average"], "color": color_avg},
    ]
    if args.plot_elixir_pie_primary and args.plot_elixir_pie_primary.lower() != "none":
        generate_pie_chart_svg(
            slices=slices_prim_elixir,
            title="Citation Category Breakdown: ELIXIR Tools (Primary Publications)",
            subtitle=f"Distribution of {total_elixir:,} ELIXIR tools based on Primary Publication citations",
            output_path=args.plot_elixir_pie_primary,
            enable_png=enable_png,
        )

    # Pie charts for Primary, Method, or Other Publications
    counts_pmo_all = metadata_pmo["category_counts_all"]
    slices_pmo_all = [
        {"label": "Top 1%", "count": counts_pmo_all["Top 1%"], "color": color_top1},
        {"label": "Top 10%", "count": counts_pmo_all["Top 10%"], "color": color_top10},
        {"label": "Average", "count": counts_pmo_all["Average"], "color": color_avg},
    ]
    if args.plot_biotools_pie_pmo and args.plot_biotools_pie_pmo.lower() != "none":
        generate_pie_chart_svg(
            slices=slices_pmo_all,
            title="Citation Category Breakdown: All bio.tools (Primary, Method, or Other)",
            subtitle=f"Distribution of {total_tools:,} tools based on Primary, Method, or Other publication citations",
            output_path=args.plot_biotools_pie_pmo,
            enable_png=enable_png,
        )

    counts_pmo_elixir = metadata_pmo["category_counts_elixir"]
    slices_pmo_elixir = [
        {"label": "Top 1%", "count": counts_pmo_elixir["Top 1%"], "color": color_top1},
        {"label": "Top 10%", "count": counts_pmo_elixir["Top 10%"], "color": color_top10},
        {"label": "Average", "count": counts_pmo_elixir["Average"], "color": color_avg},
    ]
    if args.plot_elixir_pie_pmo and args.plot_elixir_pie_pmo.lower() != "none":
        generate_pie_chart_svg(
            slices=slices_pmo_elixir,
            title="Citation Category Breakdown: ELIXIR Tools (Primary, Method, or Other)",
            subtitle=f"Distribution of {total_elixir:,} ELIXIR tools based on Primary, Method, or Other publication citations",
            output_path=args.plot_elixir_pie_pmo,
            enable_png=enable_png,
        )

    # 6d. Top Tools Across Rankings Side-by-Side Comparison Figures
    top_n = max(1, args.top_tools_n)
    if args.plot_top30_all_file and args.plot_top30_all_file.lower() != "none":
        generate_top_tools_comparison_svg(
            enriched_tools=enriched_tools,
            output_path=args.plot_top30_all_file,
            only_elixir=False,
            top_n=top_n,
            enable_png=enable_png,
        )

    if args.plot_top30_elixir_file and args.plot_top30_elixir_file.lower() != "none":
        generate_top_tools_comparison_svg(
            enriched_tools=enriched_tools,
            output_path=args.plot_top30_elixir_file,
            only_elixir=True,
            top_n=top_n,
            enable_png=enable_png,
        )

    print("\n" + "=" * 76)
    print("                       ANALYSIS COMPLETED")
    print("=" * 76 + "\n")


if __name__ == "__main__":
    main()

