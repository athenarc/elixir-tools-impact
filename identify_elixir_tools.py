#!/usr/bin/env python3
"""
identify_elixir_tools.py

Identifies ELIXIR Europe software tools and enriches the bio.tools dataset
(e.g. `biotools_publications.json`) with an `is_elixir` boolean flag,
producing `biotools_publications_elixir_incl.json`.

Supported Identification Methods:
  1. 'scrape' (or 'web'):
     Scrapes the ELIXIR Europe software tools catalogue:
     https://elixir-europe.org/services/tag/software-tools (across all paginated pages).
  2. 'scrape-all' (or 'web-all'):
     Scrapes the complete ELIXIR Europe service catalogue including databases,
     platforms, and interoperability services:
     https://elixir-europe.org/services/list (across all paginated pages).
  3. 'csv' (or 'file'):
     Reads an exported CSV file (e.g. "ELIXIR-tools_with bio.csv") and extracts
     bio.tools links from the specified column (default: "field_bio_tools_link").

All methods extract bio.tools identifiers, match them against the bio.tools dataset,
and add the `is_elixir` flag to each entry.
"""

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Set, Tuple

ELIXIR_SOFTWARE_TOOLS_URL = "https://elixir-europe.org/services/tag/software-tools"
ELIXIR_ALL_SERVICES_URL = "https://elixir-europe.org/services/list"
ELIXIR_TOOLS_BASE_URL = ELIXIR_SOFTWARE_TOOLS_URL
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
DEFAULT_CSV_FILE = "inputs/ELIXIR-tools_with bio.csv"
DEFAULT_CSV_COLUMN = "field_bio_tools_link"


def extract_biotools_ids_from_text(text: Optional[str]) -> List[str]:
    """
    Extracts and normalizes all bio.tools IDs from a given URL or text string.
    Matches forms like:
      - https://bio.tools/tool_name
      - http://dev.bio.tools/tool-name/
      - bio.tools/tool_name
    """
    if not text:
        return []
    matches = re.findall(r"bio\.tools/([a-zA-Z0-9_\-]+)", text.strip())
    # Return unique lowercased identifiers preserving order
    seen = set()
    result = []
    for m in matches:
        clean_id = m.lower().rstrip("/")
        if clean_id and clean_id not in seen:
            seen.add(clean_id)
            result.append(clean_id)
    return result


def extract_biotools_id_from_url(url: Optional[str]) -> Optional[str]:
    """Extracts and normalizes the primary bio.tools ID from a bio.tools URL."""
    ids = extract_biotools_ids_from_text(url)
    return ids[0] if ids else None


# =====================================================================
# METHOD 1: Web Scraping from ELIXIR Europe Website
# =====================================================================

def scrape_elixir_page(
    page_num: int, base_url: str, user_agent: str
) -> Tuple[List[Dict[str, Any]], bool]:
    """
    Scrapes a single page of the ELIXIR software tools or all-services directory.

    Returns:
        (services_on_page, has_next_page)
    """
    url = f"{base_url}?page={page_num}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        print(f"Error fetching page {page_num} (HTTP {e.code}): {e}", file=sys.stderr)
        return [], False
    except Exception as e:
        print(f"Error fetching page {page_num}: {e}", file=sys.stderr)
        return [], False

    # Extract all table rows (filtering for rows that contain table cells <td>)
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL)
    data_rows = [r for r in rows if "<td" in r]

    if not data_rows:
        return [], False

    services = []
    for r in data_rows:
        # Service name & official link
        title_m = re.search(r"views-field-title[^>]*>(.*?)</td>", r, re.DOTALL)
        if title_m:
            title_html = title_m.group(1)
            title = re.sub(r"<[^>]+>", "", title_html).strip()
            href_m = re.search(r"href=[\"']([^\"']+)[\"']", title_html)
            service_url = href_m.group(1).strip() if href_m else None
        else:
            title = "Unknown"
            service_url = None

        # ELIXIR Node (present in software-tools, optional in services/list)
        node_m = re.search(r"views-field-field-elixir-node[^>]*>(.*?)</td>", r, re.DOTALL)
        node = re.sub(r"<[^>]+>", "", node_m.group(1)).strip() if node_m else None

        # Description (views-field-body)
        desc_m = re.search(r"views-field-body[^>]*>(.*?)</td>", r, re.DOTALL)
        description = re.sub(r"<[^>]+>", "", desc_m.group(1)).strip() if desc_m else None

        # Extract all bio.tools identifiers and links from the row
        extracted_ids = extract_biotools_ids_from_text(r)
        primary_id = extracted_ids[0] if extracted_ids else None

        # Extract primary bio.tools URL if present
        bt_url_m = re.search(
            r"href=[\"'](https?://(?:dev\.)?bio\.tools/[a-zA-Z0-9_\-]+(?:/[a-zA-Z0-9_\-]+)*)[\"']", r
        )
        if bt_url_m:
            biotools_url = bt_url_m.group(1).strip()
        elif primary_id:
            biotools_url = f"https://bio.tools/{primary_id}"
        else:
            biotools_url = None

        services.append({
            "title": title,
            "service_url": service_url,
            "elixir_node": node,
            "description": description,
            "bio_tools_url": biotools_url,
            "biotools_id": primary_id,
            "all_biotools_ids": extracted_ids,
            "has_bio_tools": bool(extracted_ids),
        })

    # Check if there is a next page in pagination
    has_next = (
        'rel="next"' in html
        or 'pager__item--next' in html
        or f"?page={page_num + 1}" in html
        or f"page={page_num + 1}" in html
    )
    return services, has_next


def scrape_all_elixir_services(
    base_url: str = ELIXIR_SOFTWARE_TOOLS_URL,
    user_agent: str = DEFAULT_USER_AGENT,
    delay: float = 0.5,
) -> List[Dict[str, Any]]:
    """Scrapes all pages of the ELIXIR service or software tools catalogue."""
    print(f"Starting web scrape of ELIXIR services from: {base_url}")
    all_services = []
    page = 0

    while True:
        services, has_next = scrape_elixir_page(page, base_url, user_agent)
        if not services:
            break

        all_services.extend(services)
        with_bt = sum(1 for s in services if s["has_bio_tools"])
        print(
            f"  Page {page:2d}: {len(services):2d} services parsed "
            f"({with_bt:2d} with bio.tools link) | Total collected: {len(all_services):3d}"
        )

        if not has_next:
            break

        page += 1
        if delay > 0:
            time.sleep(delay)

    return all_services


# =====================================================================
# METHOD 2: CSV File Extraction
# =====================================================================

def parse_elixir_csv(
    csv_path: str, link_column: str = DEFAULT_CSV_COLUMN
) -> List[Dict[str, Any]]:
    """
    Reads an ELIXIR tools CSV file and extracts tool information and bio.tools links.

    Returns:
        A list of service dictionaries with keys:
          - 'title': Name of the service
          - 'bio_tools_url': Raw bio.tools link(s)
          - 'biotools_id': Normalized primary bio.tools ID
          - 'all_biotools_ids': List of all extracted bio.tools IDs
          - 'has_bio_tools': Boolean indicating presence of a bio.tools link
          - 'extra_metadata': Additional columns present in the CSV row
    """
    if not os.path.isfile(csv_path):
        raise FileNotFoundError(f"CSV file not found: '{csv_path}'")

    print(f"Reading ELIXIR tools from CSV file: '{csv_path}'")
    services = []

    with open(csv_path, "r", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"CSV file '{csv_path}' is empty or has no header.")

        # Identify column name case-insensitively if not found exactly
        actual_col = None
        for col in reader.fieldnames:
            if col.strip().lower() == link_column.strip().lower():
                actual_col = col
                break

        if not actual_col:
            avail = ", ".join(f"'{c}'" for c in reader.fieldnames)
            raise KeyError(
                f"Column '{link_column}' not found in CSV. Available columns: {avail}"
            )

        # Also find name column if present
        name_col = None
        for col in reader.fieldnames:
            clean = col.strip().lower()
            if "name" in clean or "service" in clean or "title" in clean:
                name_col = col
                break

        for row_idx, row in enumerate(reader, start=1):
            raw_link = row.get(actual_col, "").strip()
            extracted_ids = extract_biotools_ids_from_text(raw_link)

            title = row.get(name_col, f"Row {row_idx}").strip() if name_col else f"Row {row_idx}"
            primary_id = extracted_ids[0] if extracted_ids else None

            # Collect other columns as extra metadata
            extra_meta = {
                k.strip(): v.strip()
                for k, v in row.items()
                if k not in (actual_col, name_col) and v
            }

            services.append({
                "title": title,
                "bio_tools_url": raw_link if raw_link else None,
                "biotools_id": primary_id,
                "all_biotools_ids": extracted_ids,
                "has_bio_tools": bool(extracted_ids),
                "extra_metadata": extra_meta,
            })

    return services


# =====================================================================
# Main Pipeline: Identification & Dataset Enrichment
# =====================================================================

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Identify ELIXIR software tools (via web scraping or CSV parsing) "
            "and add the 'is_elixir' boolean flag to the bio.tools dataset."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # Method selection
    parser.add_argument(
        "--method",
        "-m",
        choices=["scrape", "scrape-all", "web", "web-all", "csv", "file"],
        default="scrape",
        help=(
            "Source/method to identify ELIXIR tools: "
            "'scrape' (or 'web') to scrape the ELIXIR Software Tools catalogue (https://elixir-europe.org/services/tag/software-tools); "
            "'scrape-all' (or 'web-all') to scrape all ELIXIR services including databases and platforms (https://elixir-europe.org/services/list); "
            "'csv' (or 'file') to read from a local CSV file."
        ),
    )

    # CSV-specific options
    parser.add_argument(
        "--csv-file",
        default=DEFAULT_CSV_FILE,
        help="Path to ELIXIR tools CSV file (used when --method is csv).",
    )
    parser.add_argument(
        "--csv-column",
        default=DEFAULT_CSV_COLUMN,
        help="Column header containing the bio.tools URL in the CSV file.",
    )

    # Web scraping options
    parser.add_argument(
        "--scrape-url",
        default=None,
        help=(
            "Optional base URL to override scraping target "
            "(defaults to ELIXIR software tools URL for 'scrape', and all services URL for 'scrape-all')."
        ),
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Delay in seconds between page requests during web scraping.",
    )

    # Dataset input & output options
    parser.add_argument(
        "--input-json",
        "-i",
        default="outputs/json/biotools_publications.json",
        help="Path to input bio.tools JSON file (default: outputs/json/biotools_publications.json).",
    )
    parser.add_argument(
        "--output-json",
        "-o",
        default="outputs/json/biotools_publications_elixir_incl.json",
        help="Path for output enriched JSON file (default: outputs/json/biotools_publications_elixir_incl.json).",
    )
    parser.add_argument(
        "--flag-name",
        default="is_elixir",
        help="Name of the boolean flag field to add in each record.",
    )
    parser.add_argument(
        "--save-elixir-list",
        help="Optional path to save the identified ELIXIR tools/services as a JSON file.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Write compact output JSON without line indentations.",
    )

    args = parser.parse_args()

    # Normalize method aliases
    raw_method = args.method.lower()
    if raw_method in ("web", "scrape"):
        method = "scrape"
        scrape_url = args.scrape_url if args.scrape_url else ELIXIR_SOFTWARE_TOOLS_URL
    elif raw_method in ("web-all", "scrape-all"):
        method = "scrape-all"
        scrape_url = args.scrape_url if args.scrape_url else ELIXIR_ALL_SERVICES_URL
    elif raw_method in ("csv", "file"):
        method = "csv"
        scrape_url = None
    else:
        method = "scrape"
        scrape_url = args.scrape_url if args.scrape_url else ELIXIR_SOFTWARE_TOOLS_URL

    # Auto-fallback to legacy root directory paths if new directory structure is not used
    if not os.path.isfile(args.input_json) and os.path.isfile("biotools_publications.json"):
        args.input_json = "biotools_publications.json"
    if not os.path.isfile(args.csv_file) and os.path.isfile("ELIXIR-tools_with bio.csv"):
        args.csv_file = "ELIXIR-tools_with bio.csv"

    if not os.path.isfile(args.input_json):
        print(f"Error: Input JSON file '{args.input_json}' does not exist.", file=sys.stderr)
        sys.exit(1)

    t_start = time.time()

    # 1. Identify ELIXIR services based on chosen method
    elixir_services: List[Dict[str, Any]] = []
    source_description = ""

    if method in ("scrape", "scrape-all"):
        scope_name = "all services" if method == "scrape-all" else "software tools"
        source_description = f"Live web scraping ({scope_name}) from {scrape_url}"
        elixir_services = scrape_all_elixir_services(
            base_url=scrape_url, delay=args.delay
        )
    elif method == "csv":
        source_description = f"CSV file '{args.csv_file}' (column: '{args.csv_column}')"
        try:
            elixir_services = parse_elixir_csv(
                csv_path=args.csv_file, link_column=args.csv_column
            )
        except Exception as e:
            print(f"Error reading CSV file: {e}", file=sys.stderr)
            sys.exit(1)

    t_retrieval = time.time()

    # 2. Extract unique bio.tools IDs and URLs
    elixir_bt_ids: Set[str] = set()
    elixir_bt_urls: Set[str] = set()
    services_with_bt = 0

    for s in elixir_services:
        has_link = False
        # Extract from 'all_biotools_ids' if present (CSV), or 'biotools_id' (scrape)
        all_ids = s.get("all_biotools_ids") or ([s["biotools_id"]] if s.get("biotools_id") else [])
        for bid in all_ids:
            if bid:
                elixir_bt_ids.add(bid.lower())
                has_link = True

        raw_url = s.get("bio_tools_url")
        if raw_url:
            clean_url = raw_url.strip().rstrip("/").lower()
            elixir_bt_urls.add(clean_url)
            has_link = True

        if has_link:
            services_with_bt += 1

    # Optional export of extracted ELIXIR tools
    if args.save_elixir_list:
        el_dir = os.path.dirname(os.path.abspath(args.save_elixir_list))
        if el_dir:
            os.makedirs(el_dir, exist_ok=True)
        with open(args.save_elixir_list, "w", encoding="utf-8") as f:
            json.dump(elixir_services, f, indent=2, ensure_ascii=False)
        print(f"Saved extracted ELIXIR service catalogue to '{args.save_elixir_list}'.")

    # 3. Read input bio.tools dataset
    print(f"\nLoading input dataset from '{args.input_json}'...")
    with open(args.input_json, "r", encoding="utf-8") as f:
        biotools_records = json.load(f)

    print(f"Loaded {len(biotools_records):,} records from '{args.input_json}'.")

    # 4. Update records with the ELIXIR flag
    matched_count = 0
    matched_tool_ids: Set[str] = set()
    updated_records = []

    for record in biotools_records:
        tool_id = str(record.get("biotools_id", "")).strip().lower()
        tool_url = str(record.get("bio_tools_url", "")).strip().rstrip("/").lower()

        is_elixir = (tool_id in elixir_bt_ids) or (tool_url in elixir_bt_urls)
        if is_elixir:
            matched_count += 1
            if tool_id:
                matched_tool_ids.add(tool_id)

        # Place the flag immediately after bio_tools_url
        new_record = {}
        for k, v in record.items():
            new_record[k] = v
            if k == "bio_tools_url":
                new_record[args.flag_name] = is_elixir

        if args.flag_name not in new_record:
            new_record[args.flag_name] = is_elixir

        updated_records.append(new_record)

    # Check for ELIXIR bio.tools IDs that did not match any dataset entry
    unmatched_elixir_ids = elixir_bt_ids - matched_tool_ids

    # 5. Write enriched JSON
    print(f"Writing enriched dataset to '{args.output_json}'...")
    out_dir = os.path.dirname(os.path.abspath(args.output_json))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    indent = None if args.compact else 2
    with open(args.output_json, "w", encoding="utf-8") as f:
        json.dump(updated_records, f, indent=indent, ensure_ascii=False)

    t_end = time.time()
    file_size_mb = os.path.getsize(args.output_json) / (1024 * 1024)

    # 6. Summary Report
    print("\n" + "=" * 65)
    print("             ELIXIR TOOLS IDENTIFICATION REPORT")
    print("=" * 65)
    print(f"Identification Method:                  {method.upper()} ({source_description})")
    print(f"Total ELIXIR service entries parsed:    {len(elixir_services):,}")
    print(f"  - Entries WITH bio.tools link:        {services_with_bt:,} ({services_with_bt/len(elixir_services)*100:.1f}%)" if elixir_services else "0")
    print(f"  - Entries WITHOUT bio.tools link:     {len(elixir_services) - services_with_bt:,} ({(len(elixir_services) - services_with_bt)/len(elixir_services)*100:.1f}%)" if elixir_services else "0")
    print(f"Distinct bio.tools IDs identified:     {len(elixir_bt_ids):,}")
    print("-" * 65)
    print(f"Total records in bio.tools dataset:     {len(biotools_records):,}")
    print(f"Records matched with ELIXIR ({args.flag_name}=True):  {matched_count:,}")
    print(f"Records not in ELIXIR list ({args.flag_name}=False): {len(biotools_records) - matched_count:,}")
    if unmatched_elixir_ids:
        print(f"ELIXIR bio.tools IDs not in dataset:    {len(unmatched_elixir_ids):,}")
        sample_unmatched = sorted(list(unmatched_elixir_ids))[:6]
        print(f"  (e.g., {', '.join(sample_unmatched)})")
    print("-" * 65)
    print(f"Output saved to:                        {args.output_json}")
    print(f"Output file size:                       {file_size_mb:.2f} MB")
    print(f"Identification step time:               {t_retrieval - t_start:.2f}s")
    print(f"Total pipeline time:                    {t_end - t_start:.2f}s")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
