#!/usr/bin/env python3
"""
extract_biotools_publications.py

Scans tool folders in `content-master/data` (or a user-specified directory),
detects entries containing a `*.biotools.json` metadata file, extracts tool
information and publications, queries the BIP! Services API in batches to fetch
citation counts for each publication, and produces a consolidated JSON file.

Features:
  - Parallel scanning of tool directories.
  - Multi-identifier support: queries DOIs (case-normalized), PMIDs, and PMCIDs.
  - BIP! API batch querying (up to 50 IDs per request).
  - Rate-limiting (configurable delay between batches) and retry with backoff.
  - Persistent disk cache (`bip_cache.json`) to avoid re-fetching existing data.
  - Computes tool-level `total_citations` (sum across all publications).
  - Detailed dataset and citation statistics.
"""

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Set, Tuple

BIP_API_BATCH_URL = "https://bip-api.imsi.athenarc.gr/paper/scores/batch/{dois}"
OPENAIRE_GRAPH_API_URL = "https://api.openaire.eu/graph/v4/research-products?filter={filter_param}&pageSize=1"
DEFAULT_USER_AGENT = "SoftwareCitationsBot/1.0 (bio.tools metadata analysis with BIP! and OpenAIRE Graph API)"
DEFAULT_BIP_CACHE = "cache/bip_cache.json"
DEFAULT_OPENAIRE_CACHE = "cache/openaire_cache.json"


def clean_doi(doi_str: str) -> str:
    """Normalize and clean a DOI string: strips common URL prefixes and lowercases."""
    doi = str(doi_str).strip()
    prefixes = [
        "https://doi.org/",
        "http://doi.org/",
        "https://dx.doi.org/",
        "http://dx.doi.org/",
        "doi:",
    ]
    for prefix in prefixes:
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix):].strip()
    # BIP! API matches DOIs case-insensitively in lower-case
    return doi.lower()


def clean_pmid(pmid_str: Any) -> Optional[str]:
    """Clean a PMID to its raw numeric representation for BIP! API."""
    if not pmid_str:
        return None
    val = str(pmid_str).strip()
    if val.upper().startswith("PMID:"):
        val = val[5:].strip()
    return val if val else None


def clean_pmcid(pmcid_str: Any) -> Optional[str]:
    """Clean a PMCID (e.g. PMC1234567) for BIP! API, consistently capitalized."""
    if not pmcid_str:
        return None
    val = str(pmcid_str).strip()
    if val.upper().startswith("PMC"):
        val = val[3:].strip()
    return f"PMC{val}" if val else None


REPO_DOMAINS = (
    "github.com",
    "gitlab.",
    "bitbucket.org",
    "sourceforge.net",
    "codeberg.org",
    "savannah.gnu.org",
    "git.bioconductor.org",
    "launchpad.net",
    "cgit.",
    "gitea.",
)


def is_repo_host(url: Optional[str]) -> bool:
    """Checks if a URL points to a known code repository hosting service."""
    if not url:
        return False
    u = str(url).lower()
    return any(dom in u for dom in REPO_DOMAINS)


def normalize_repo_url(url: Optional[str]) -> Optional[str]:
    """Cleans and normalizes repository URLs."""
    if not url:
        return None
    url = str(url).strip()
    url = url.strip("<>()[]\"'")
    url = url.split("#")[0]  # strip URL fragment/anchor
    url = url.rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    return url if url else None


def extract_repository_url(data: Dict) -> Tuple[Optional[str], Optional[str]]:
    """
    Extracts code repository URL and the metadata field source using a priority hierarchy:
      1. link with type 'Repository' -> 'link (Repository)'
      2. download with type 'Source code' matching a known repo host -> 'download (Source code)'
      3. homepage matching a known repo host -> 'homepage'
      4. link with type 'Mirror' matching a known repo host -> 'link (Mirror)'
      5. documentation matching a known repo host -> 'documentation'
      6. Any other download with type 'Source code' -> 'download (Source code)'

    Returns:
        (repository_url, repository_source) or (None, None)
    """
    # 1. link with type 'Repository'
    for link in data.get("link") or []:
        if isinstance(link, dict):
            types = link.get("type") or []
            if isinstance(types, str):
                types = [types]
            if "Repository" in types and link.get("url"):
                return normalize_repo_url(link["url"]), "link (Repository)"

    # 2. download with type 'Source code' (matching repo host)
    for dl in data.get("download") or []:
        if isinstance(dl, dict):
            if dl.get("type") == "Source code" and dl.get("url") and is_repo_host(dl["url"]):
                return normalize_repo_url(dl["url"]), "download (Source code)"

    # 3. homepage matching repo host
    homepage = data.get("homepage")
    if homepage and is_repo_host(homepage):
        return normalize_repo_url(homepage), "homepage"

    # 4. link with type 'Mirror' pointing to repo host
    for link in data.get("link") or []:
        if isinstance(link, dict):
            types = link.get("type") or []
            if isinstance(types, str):
                types = [types]
            if "Mirror" in types and link.get("url") and is_repo_host(link["url"]):
                return normalize_repo_url(link["url"]), "link (Mirror)"

    # 5. documentation pointing to repo host
    for doc in data.get("documentation") or []:
        if isinstance(doc, dict) and doc.get("url") and is_repo_host(doc["url"]):
            return normalize_repo_url(doc["url"]), "documentation"

    # 6. Fallback: any download with type 'Source code'
    for dl in data.get("download") or []:
        if isinstance(dl, dict) and dl.get("type") == "Source code" and dl.get("url"):
            return normalize_repo_url(dl["url"]), "download (Source code)"

    return None, None


def parse_biotools_file(item: Tuple[str, str]) -> Optional[Dict]:
    """
    Parses a single .biotools.json file and extracts relevant metadata.

    Args:
        item: Tuple of (folder_name, file_path)

    Returns:
        Dictionary containing extracted metadata, or None if reading failed.
    """
    folder_name, fpath = item
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"Warning: Could not read '{fpath}': {e}", file=sys.stderr)
        return None

    biotools_id = data.get("biotoolsID") or folder_name
    name = data.get("name") or biotools_id
    bio_tools_url = f"https://bio.tools/{biotools_id}"
    addition_date = data.get("additionDate")
    if addition_date:
        addition_date = str(addition_date).strip() or None

    raw_publications = data.get("publication") or []
    tool_publications = []
    seen_ids: Set[str] = set()

    for pub in raw_publications:
        if not isinstance(pub, dict):
            continue

        raw_doi = pub.get("doi")
        raw_pmid = pub.get("pmid")
        raw_pmcid = pub.get("pmcid")

        # Extract publication types and determine if marked as Primary, Method, or Other
        raw_type = pub.get("type") or []
        if isinstance(raw_type, str):
            raw_type = [raw_type]
        pub_types = [str(t).strip() for t in raw_type if t and str(t).strip()]
        lower_types = {t.lower() for t in pub_types}
        is_primary = "primary" in lower_types
        is_pmo = bool(lower_types.intersection({"primary", "method", "other"}))

        # Extract publication date (direct or under metadata)
        raw_date = pub.get("date")
        if not raw_date and isinstance(pub.get("metadata"), dict):
            raw_date = pub["metadata"].get("date")
        pub_date = str(raw_date).strip() if raw_date else None

        doi = clean_doi(raw_doi) if raw_doi else None
        pmid = clean_pmid(raw_pmid)
        pmcid = clean_pmcid(raw_pmcid)

        # Determine primary identifier to query BIP! API
        query_id = None
        id_type = None

        if doi:
            query_id = doi
            id_type = "doi"
        elif pmid:
            query_id = pmid
            id_type = "pmid"
        elif pmcid:
            query_id = pmcid
            id_type = "pmcid"

        if query_id and query_id not in seen_ids:
            seen_ids.add(query_id)
            tool_publications.append({
                "id": query_id,
                "type": id_type,
                "publication_type": pub_types,
                "is_primary": is_primary,
                "is_pmo": is_pmo,
                "date": pub_date,
                "doi": doi,
                "pmid": pmid,
                "pmcid": pmcid,
                "citations": None,  # Will be populated by BIP! API
            })

    repository_url, repository_source = extract_repository_url(data)

    raw_functions = data.get("function") or []
    tool_functions = []
    if isinstance(raw_functions, list):
        for fn in raw_functions:
            if isinstance(fn, dict):
                tool_functions.append(fn)

    return {
        "name": name,
        "biotools_id": biotools_id,
        "bio_tools_url": bio_tools_url,
        "additionDate": addition_date,
        "repository_url": repository_url,
        "repository_source": repository_source,
        "function": tool_functions,
        "publications": tool_publications,
        "has_raw_publication": bool(raw_publications),
    }


def scan_tool_directories(data_dir: str) -> Tuple[int, List[Tuple[str, str]]]:
    """
    Quickly scans the data directory using os.scandir to find all folders
    and locate any *.biotools.json files within each folder.
    """
    total_folders = 0
    tool_files = []

    with os.scandir(data_dir) as it:
        for entry in it:
            if not entry.is_dir():
                continue
            total_folders += 1
            try:
                for child in os.scandir(entry.path):
                    if child.name.endswith(".biotools.json"):
                        tool_files.append((entry.name, child.path))
                        break
            except OSError:
                continue

    return total_folders, tool_files


def load_bip_cache(cache_path: str) -> Dict[str, Optional[int]]:
    """Loads existing citation cache from disk if present."""
    if os.path.isfile(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                print(f"Loaded {len(data):,} cached publication citation records from '{cache_path}'.")
                return data
        except Exception as e:
            print(f"Warning: Failed to load cache file '{cache_path}': {e}", file=sys.stderr)
    return {}


def save_bip_cache(cache: Dict[str, Optional[int]], cache_path: str):
    """Saves citation cache to disk."""
    try:
        dir_name = os.path.dirname(os.path.abspath(cache_path))
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        temp_path = f"{cache_path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
        os.replace(temp_path, cache_path)
    except Exception as e:
        print(f"Warning: Failed to save cache file '{cache_path}': {e}", file=sys.stderr)


def query_bip_batch(
    batch_ids: List[str],
    user_agent: str = DEFAULT_USER_AGENT,
    max_retries: int = 3,
) -> Dict[str, Optional[int]]:
    """
    Queries BIP! API batch endpoint for up to 50 publication IDs.
    Returns a mapping of identifier -> citation count (or None if not indexed).
    """
    # BIP! expects comma-separated IDs in the URL path.
    # Slashes in DOIs must be percent-encoded as %2F, while commas remain literal separators.
    encoded_ids = urllib.parse.quote(",".join(batch_ids), safe=",")
    url = BIP_API_BATCH_URL.format(dois=encoded_ids)

    req = urllib.request.Request(url, headers={"User-Agent": user_agent})

    for attempt in range(1, max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status == 200:
                    payload = json.loads(resp.read().decode("utf-8"))
                    results = {}
                    if isinstance(payload, list):
                        for item in payload:
                            # BIP! returns the queried identifier in the 'doi' field
                            ret_id = str(item.get("doi", "")).strip().lower()
                            cc = item.get("cc")
                            results[ret_id] = cc
                    return results
        except urllib.error.HTTPError as e:
            if e.code == 429:  # Rate limited
                wait_time = attempt * 5
                print(f"\n[BIP! API 429] Rate limit hit. Waiting {wait_time}s before retry...", file=sys.stderr)
                time.sleep(wait_time)
            elif e.code in (500, 502, 503, 504):
                wait_time = attempt * 2
                print(f"\n[BIP! API {e.code}] Server error. Retrying in {wait_time}s...", file=sys.stderr)
                time.sleep(wait_time)
            else:
                print(f"\n[BIP! API Error] HTTP {e.code} for batch: {e}", file=sys.stderr)
                break
        except Exception as e:
            print(f"\n[BIP! API Exception] Attempt {attempt} failed: {e}", file=sys.stderr)
            time.sleep(attempt * 2)

    # Return None for all IDs if the request completely failed
    return {i: None for i in batch_ids}


def fetch_all_citations(
    unique_ids: List[str],
    cache: Dict[str, Optional[int]],
    cache_path: str,
    batch_size: int = 50,
    delay: float = 0.5,
    limit_batches: Optional[int] = None,
) -> Dict[str, Optional[int]]:
    """
    Fetches citation counts for all unique publication identifiers using BIP! API in batches.
    Respects cache and polite delay between requests.
    """
    to_query = [i for i in unique_ids if i not in cache]
    total_to_query = len(to_query)
    total_batches = (total_to_query + batch_size - 1) // batch_size

    if limit_batches is not None:
        total_batches = min(total_batches, limit_batches)
        to_query = to_query[: total_batches * batch_size]
        total_to_query = len(to_query)

    print(f"\nTotal unique publication IDs: {len(unique_ids):,}")
    print(f"Already cached:                {len(unique_ids) - total_to_query:,}")
    print(f"IDs to query from BIP! API:    {total_to_query:,} across {total_batches:,} batch requests")

    if total_to_query == 0:
        return cache

    print(f"Starting batch requests with {delay}s delay between calls...")
    t0 = time.time()
    batch_num = 0

    for i in range(0, total_to_query, batch_size):
        batch = to_query[i : i + batch_size]
        batch_num += 1

        batch_results = query_bip_batch(batch)
        for q_id, cc in batch_results.items():
            cache[q_id] = cc

        # Mark any requested ID not explicitly returned in the payload
        for q_id in batch:
            if q_id not in cache:
                cache[q_id] = None

        elapsed = time.time() - t0
        pct = (batch_num / total_batches) * 100
        progress_str = f"\r[BIP! API] Batch {batch_num}/{total_batches} ({pct:.1f}%) | Cached {len(cache):,} IDs | Elapsed: {elapsed:.1f}s"
        sys.stdout.write(progress_str)
        sys.stdout.flush()

        # Periodically save cache every 20 batches
        if batch_num % 20 == 0:
            save_bip_cache(cache, cache_path)

        if batch_num < total_batches:
            time.sleep(delay)

    print()
    save_bip_cache(cache, cache_path)
    if unique_ids:
        found_in_bip = sum(1 for q in unique_ids if cache.get(q) is not None)
        not_found_in_bip = sum(1 for q in unique_ids if cache.get(q) is None)
        print(f"BIP! citation retrieval complete: {found_in_bip:,} papers found ({found_in_bip/len(unique_ids)*100:.1f}%), {not_found_in_bip:,} papers not found/unindexed ({not_found_in_bip/len(unique_ids)*100:.1f}%).")
    return cache


def load_openaire_cache(cache_path: str) -> Dict[str, Optional[str]]:
    """Loads existing OpenAIRE publication date cache from disk if present."""
    if os.path.isfile(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                print(f"Loaded {len(data):,} cached OpenAIRE publication date records from '{cache_path}'.")
                return data
        except Exception as e:
            print(f"Warning: Failed to load OpenAIRE cache file '{cache_path}': {e}", file=sys.stderr)
    return {}


def save_openaire_cache(cache: Dict[str, Optional[str]], cache_path: str):
    """Saves OpenAIRE publication date cache to disk."""
    try:
        dir_name = os.path.dirname(os.path.abspath(cache_path))
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        temp_path = f"{cache_path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
        os.replace(temp_path, cache_path)
    except Exception as e:
        print(f"Warning: Failed to save OpenAIRE cache file '{cache_path}': {e}", file=sys.stderr)


def query_openaire_single(
    identifier: str,
    id_type: str = "doi",
    token: Optional[str] = None,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout: int = 15,
    max_retries: int = 3,
) -> Tuple[str, Optional[str]]:
    """
    Queries the OpenAIRE Graph API for a single publication identifier (DOI or PMID).
    Returns (identifier, publicationDate or None).
    """
    filter_param = f"ids.{id_type}:{identifier}"
    url = OPENAIRE_GRAPH_API_URL.format(filter_param=urllib.parse.quote(filter_param, safe=":"))
    headers = {"User-Agent": user_agent}
    if token:
        headers["Authorization"] = f"Bearer {token.strip()}"

    req = urllib.request.Request(url, headers=headers)

    for attempt in range(1, max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    payload = json.loads(resp.read().decode("utf-8"))
                    results = payload.get("results") or []
                    if results and isinstance(results[0], dict):
                        pub_date = results[0].get("publicationDate")
                        if pub_date:
                            return identifier, str(pub_date).strip()
                    return identifier, None
        except urllib.error.HTTPError as e:
            if e.code == 429:
                # Check for Retry-After header
                retry_after = e.headers.get("Retry-After") if hasattr(e, "headers") else None
                try:
                    wait_time = float(retry_after) if retry_after else attempt * 5.0
                except (ValueError, TypeError):
                    wait_time = attempt * 5.0
                time.sleep(wait_time)
            elif e.code in (500, 502, 503, 504):
                time.sleep(attempt * 2.0)
            else:
                break
        except Exception:
            time.sleep(attempt * 1.5)

    return identifier, None


def fetch_all_openaire_dates(
    query_items: List[Tuple[str, str]],
    cache: Dict[str, Optional[str]],
    cache_path: str,
    workers: int = 8,
    delay: float = 0.05,
    limit: Optional[int] = None,
    token: Optional[str] = None,
    user_agent: str = DEFAULT_USER_AGENT,
) -> Dict[str, Optional[str]]:
    """
    Queries OpenAIRE Graph API in parallel using ThreadPoolExecutor for all uncached IDs.
    `query_items` is a list of (identifier, id_type) tuples.
    Saves results to `cache` and periodically flushes to disk.
    """
    to_query = [item for item in query_items if item[0] not in cache]
    total_to_query = len(to_query)

    if limit is not None and limit > 0:
        to_query = to_query[:limit]
        total_to_query = len(to_query)

    print(f"\nTotal publication identifiers for OpenAIRE: {len(query_items):,}")
    print(f"Already cached in OpenAIRE cache:         {len(query_items) - len([i for i in query_items if i[0] not in cache]):,}")
    print(f"Identifiers to query from OpenAIRE API:   {total_to_query:,}")

    if total_to_query == 0:
        return cache

    print(f"Fetching OpenAIRE publication dates using {workers} concurrent workers...")
    t0 = time.time()
    completed = 0
    resolved_dates = 0

    def worker_task(item: Tuple[str, str]) -> Tuple[str, Optional[str]]:
        ident, id_type = item
        if delay > 0:
            time.sleep(delay)
        return query_openaire_single(ident, id_type=id_type, token=token, user_agent=user_agent)

    # Process in chunks of 50 to periodically persist cache and report progress
    chunk_size = 50
    for chunk_start in range(0, total_to_query, chunk_size):
        chunk = to_query[chunk_start : chunk_start + chunk_size]
        with ThreadPoolExecutor(max_workers=workers) as executor:
            batch_results = list(executor.map(worker_task, chunk))

        for ident, pub_date in batch_results:
            cache[ident] = pub_date
            completed += 1
            if pub_date:
                resolved_dates += 1

        elapsed = time.time() - t0
        pct = (completed / total_to_query) * 100.0
        rate = completed / elapsed if elapsed > 0 else 0
        progress_str = (
            f"\r[OpenAIRE API] {completed}/{total_to_query} ({pct:.1f}%) | "
            f"Resolved: {resolved_dates:,} | Rate: {rate:.1f} req/s | Elapsed: {elapsed:.1f}s"
        )
        sys.stdout.write(progress_str)
        sys.stdout.flush()

        save_openaire_cache(cache, cache_path)

    print()
    save_openaire_cache(cache, cache_path)
    return cache


def find_matching_publication(
    inc_pub: Dict[str, Any], existing_pubs: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """
    Matches an incoming publication against an existing tool's publications list
    using normalized DOI, PMID, PMCID, or ID.
    """
    inc_id = (inc_pub.get("id") or "").strip().lower()
    inc_doi = (inc_pub.get("doi") or "").strip().lower()
    inc_pmid = str(inc_pub.get("pmid") or "").strip().lower()
    inc_pmcid = str(inc_pub.get("pmcid") or "").strip().lower()

    for p in existing_pubs:
        p_id = (p.get("id") or "").strip().lower()
        p_doi = (p.get("doi") or "").strip().lower()
        p_pmid = str(p.get("pmid") or "").strip().lower()
        p_pmcid = str(p.get("pmcid") or "").strip().lower()

        if inc_id and p_id and inc_id == p_id:
            return p
        if inc_doi and p_doi and inc_doi == p_doi:
            return p
        if inc_pmid and p_pmid and inc_pmid == p_pmid:
            return p
        if inc_pmcid and p_pmcid and inc_pmcid == p_pmcid:
            return p
    return None


def merge_biotools_metadata(
    existing_records: List[Dict[str, Any]],
    parsed_tools: List[Dict[str, Any]],
) -> Dict[str, int]:
    """
    Non-destructively merges freshly parsed bio.tools metadata into existing records.
    Preserves existing citations, dates, date sources, and custom flags (e.g. is_elixir).
    Updates/adds function metadata, repository URLs, addition dates, and newly found publications or tools.

    Returns:
        Dictionary of update statistics.
    """
    stats = {
        "tools_updated": 0,
        "functions_added_or_updated": 0,
        "repos_added_or_updated": 0,
        "pubs_added": 0,
        "new_tools_added": 0,
    }

    records_by_id: Dict[str, Dict[str, Any]] = {
        r["biotools_id"].lower(): r
        for r in existing_records
        if r.get("biotools_id")
    }

    for t in parsed_tools:
        tid = t["biotools_id"].lower()
        if tid in records_by_id:
            rec = records_by_id[tid]

            # 1. Update basic fields if provided
            if t.get("name"):
                rec["name"] = t["name"]
            if t.get("bio_tools_url"):
                rec["bio_tools_url"] = t["bio_tools_url"]
            if t.get("additionDate") and not rec.get("additionDate"):
                rec["additionDate"] = t["additionDate"]

            # 2. Update repository info (never overwrite existing repo with None)
            if t.get("repository_url"):
                if not rec.get("repository_url"):
                    stats["repos_added_or_updated"] += 1
                rec["repository_url"] = t["repository_url"]
                rec["repository_source"] = t["repository_source"]

            # 3. Update / add function classes
            new_funcs = t.get("function") or []
            if new_funcs:
                if not rec.get("function"):
                    stats["functions_added_or_updated"] += 1
                rec["function"] = new_funcs
            elif "function" not in rec:
                rec["function"] = []

            # 4. Merge publications without losing existing dates or citations
            existing_pubs = rec.get("publications") or []
            for inc_p in (t.get("publications") or []):
                matched = find_matching_publication(inc_p, existing_pubs)
                if matched:
                    # Enrich missing identifier fields
                    if not matched.get("doi") and inc_p.get("doi"):
                        matched["doi"] = inc_p["doi"]
                    if not matched.get("pmid") and inc_p.get("pmid"):
                        matched["pmid"] = inc_p["pmid"]
                    if not matched.get("pmcid") and inc_p.get("pmcid"):
                        matched["pmcid"] = inc_p["pmcid"]
                    # Update publication types and primary/PMO flags
                    if inc_p.get("publication_type"):
                        matched["publication_type"] = inc_p["publication_type"]
                    if "is_primary" in inc_p:
                        matched["is_primary"] = bool(inc_p["is_primary"])
                    if "is_pmo" in inc_p:
                        matched["is_pmo"] = bool(inc_p["is_pmo"])
                    # If date was missing, fill from bio.tools
                    if not matched.get("date") and inc_p.get("date"):
                        matched["date"] = inc_p["date"]
                        matched["date_source"] = "biotools"
                else:
                    # New publication discovered in bio.tools
                    new_p_entry = {
                        "id": inc_p["id"],
                        "type": inc_p["type"],
                        "publication_type": inc_p.get("publication_type") or [],
                        "is_primary": bool(inc_p.get("is_primary")),
                        "is_pmo": bool(inc_p.get("is_pmo")),
                        "date": inc_p.get("date"),
                        "date_source": "biotools" if inc_p.get("date") else None,
                        "citations": None,
                    }
                    if inc_p.get("doi"):
                        new_p_entry["doi"] = inc_p["doi"]
                    if inc_p.get("pmid"):
                        new_p_entry["pmid"] = inc_p["pmid"]
                    if inc_p.get("pmcid"):
                        new_p_entry["pmcid"] = inc_p["pmcid"]
                    existing_pubs.append(new_p_entry)
                    stats["pubs_added"] += 1

            rec["publications"] = existing_pubs
            rec["publication_count"] = len(existing_pubs)
            stats["tools_updated"] += 1

        else:
            # Entirely new tool entry found in bio.tools
            new_pubs = []
            for p in (t.get("publications") or []):
                p_entry = {
                    "id": p["id"],
                    "type": p["type"],
                    "publication_type": p.get("publication_type") or [],
                    "is_primary": bool(p.get("is_primary")),
                    "is_pmo": bool(p.get("is_pmo")),
                    "date": p.get("date"),
                    "date_source": "biotools" if p.get("date") else None,
                    "citations": None,
                }
                if p.get("doi"):
                    p_entry["doi"] = p["doi"]
                if p.get("pmid"):
                    p_entry["pmid"] = p["pmid"]
                if p.get("pmcid"):
                    p_entry["pmcid"] = p["pmcid"]
                new_pubs.append(p_entry)

            new_rec = {
                "name": t["name"],
                "biotools_id": t["biotools_id"],
                "bio_tools_url": t["bio_tools_url"],
                "additionDate": t.get("additionDate"),
                "firstPublication": None,
                "first_primary_publication": None,
                "first_pmo_publication": None,
                "repository_url": t.get("repository_url"),
                "repository_source": t.get("repository_source"),
                "function": t.get("function") or [],
                "publication_count": len(new_pubs),
                "primary_publication_count": sum(1 for p in new_pubs if p.get("is_primary")),
                "pmo_publication_count": sum(1 for p in new_pubs if p.get("is_pmo")),
                "total_citations": None,
                "primary_citations": None,
                "total_primary_citations": None,
                "pmo_citations": None,
                "total_pmo_citations": None,
                "primary_method_other_citations": None,
                "publications": new_pubs,
            }
            existing_records.append(new_rec)
            records_by_id[tid] = new_rec
            stats["new_tools_added"] += 1

    return stats


def recalculate_tool_metrics(records: List[Dict[str, Any]]):
    """
    Recalculates publication_count, primary_publication_count, pmo_publication_count,
    total_citations, primary_citations, pmo_citations, firstPublication,
    first_primary_publication, and first_pmo_publication
    across all tool records to maintain dataset consistency.
    """
    for tool in records:
        pubs = tool.get("publications") or []
        tool["publication_count"] = len(pubs)

        for p in pubs:
            if p.get("is_pmo") is None:
                pub_types = p.get("publication_type") or []
                lower_types = {str(t).strip().lower() for t in pub_types if t}
                p["is_pmo"] = bool(lower_types.intersection({"primary", "method", "other"})) or bool(p.get("is_primary"))

        primary_pubs = [
            p for p in pubs
            if p.get("is_primary") or ("Primary" in (p.get("publication_type") or []))
        ]
        tool["primary_publication_count"] = len(primary_pubs)

        pmo_pubs = [
            p for p in pubs
            if p.get("is_pmo")
        ]
        tool["pmo_publication_count"] = len(pmo_pubs)

        # 1. Total citations (all related publications)
        known_cits = [p["citations"] for p in pubs if p.get("citations") is not None]
        if known_cits:
            tool["total_citations"] = sum(known_cits)
        elif pubs:
            tool["total_citations"] = 0
        else:
            tool["total_citations"] = None

        # 2. Primary citations (only primary related publications)
        known_primary_cits = [p["citations"] for p in primary_pubs if p.get("citations") is not None]
        if known_primary_cits:
            tool["primary_citations"] = sum(known_primary_cits)
        elif primary_pubs:
            tool["primary_citations"] = 0
        elif pubs:
            tool["primary_citations"] = 0
        else:
            tool["primary_citations"] = None
        tool["total_primary_citations"] = tool["primary_citations"]

        # 3. PMO citations (Primary, Method, or Other related publications)
        known_pmo_cits = [p["citations"] for p in pmo_pubs if p.get("citations") is not None]
        if known_pmo_cits:
            tool["pmo_citations"] = sum(known_pmo_cits)
        elif pmo_pubs:
            tool["pmo_citations"] = 0
        elif pubs:
            tool["pmo_citations"] = 0
        else:
            tool["pmo_citations"] = None
        tool["total_pmo_citations"] = tool["pmo_citations"]
        tool["primary_method_other_citations"] = tool["pmo_citations"]

        # 4. First publication date (all publications)
        valid_dates = [
            p["date"]
            for p in pubs
            if p.get("date") and isinstance(p["date"], str) and p["date"].strip()
        ]
        tool["firstPublication"] = min(valid_dates) if valid_dates else None

        # 5. First primary publication date (primary publications only)
        valid_primary_dates = [
            p["date"]
            for p in primary_pubs
            if p.get("date") and isinstance(p["date"], str) and p["date"].strip()
        ]
        tool["first_primary_publication"] = min(valid_primary_dates) if valid_primary_dates else None

        # 6. First PMO publication date (Primary, Method, or Other publications)
        valid_pmo_dates = [
            p["date"]
            for p in pmo_pubs
            if p.get("date") and isinstance(p["date"], str) and p["date"].strip()
        ]
        tool["first_pmo_publication"] = min(valid_pmo_dates) if valid_pmo_dates else None

        if "function" not in tool:
            tool["function"] = []


def main():
    parser = argparse.ArgumentParser(
        description="Extract bio.tools metadata and publication citations using BIP! Services API."
    )
    parser.add_argument(
        "--data-dir",
        "-d",
        default="inputs/content-master/data",
        help="Path to data directory containing tool folders (default: inputs/content-master/data).",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="outputs/json/biotools_publications.json",
        help="Path for generated output JSON file (default: outputs/json/biotools_publications.json).",
    )
    parser.add_argument(
        "--cache-file",
        "-c",
        default=DEFAULT_BIP_CACHE,
        help=f"Path to local JSON cache file for BIP! citation counts (default: {DEFAULT_BIP_CACHE}).",
    )
    parser.add_argument(
        "--skip-citations",
        action="store_true",
        help="Skip querying the BIP! API for citations (only extract metadata and publication IDs).",
    )
    parser.add_argument(
        "--reset-cache",
        action="store_true",
        help="Ignore and overwrite any existing citation cache, querying the BIP! API from scratch.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Batch size for BIP! API queries (max 50, default: 50).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Polite wait time (in seconds) between BIP! API batch calls (default: 0.5s).",
    )
    parser.add_argument(
        "--limit-batches",
        type=int,
        default=None,
        help="Optional limit on number of BIP! API batches to fetch (useful for testing).",
    )
    parser.add_argument(
        "--workers",
        "-w",
        type=int,
        default=16,
        help="Number of worker threads for parallel file parsing (default: 16).",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Write compact output JSON without line indentations.",
    )
    # OpenAIRE Graph API arguments
    parser.add_argument(
        "--openaire-cache",
        default=DEFAULT_OPENAIRE_CACHE,
        help=f"Path to local JSON cache file for OpenAIRE publication dates (default: {DEFAULT_OPENAIRE_CACHE}).",
    )
    parser.add_argument(
        "--skip-openaire",
        action="store_true",
        help="Skip querying the OpenAIRE Graph API for publication dates (uses bio.tools dates only).",
    )
    parser.add_argument(
        "--reset-openaire-cache",
        action="store_true",
        help="Ignore and overwrite any existing OpenAIRE date cache, querying fresh.",
    )
    parser.add_argument(
        "--openaire-workers",
        type=int,
        default=8,
        help="Number of worker threads for OpenAIRE Graph API queries (default: 8).",
    )
    parser.add_argument(
        "--openaire-delay",
        type=float,
        default=0.05,
        help="Polite wait time (in seconds) between OpenAIRE API requests per worker (default: 0.05s).",
    )
    parser.add_argument(
        "--limit-openaire-dois",
        type=int,
        default=None,
        help="Optional limit on the number of publication IDs to query from OpenAIRE (useful for testing).",
    )
    parser.add_argument(
        "--openaire-token",
        default=os.environ.get("OPENAIRE_API_TOKEN"),
        help="Optional OpenAIRE API Personal Access Token (or set OPENAIRE_API_TOKEN env var) for higher rate limits (up to 7,200 req/hour).",
    )
    parser.add_argument(
        "--elixir-csv",
        default="inputs/ELIXIR-tools_with bio.csv",
        help="Optional path to ELIXIR tools CSV to prioritize ELIXIR tools in OpenAIRE querying (default: inputs/ELIXIR-tools_with bio.csv).",
    )
    # Incremental update arguments
    parser.add_argument(
        "--update",
        action="store_true",
        help="Update mode: loads existing JSON dataset and updates records without losing previously collected metadata.",
    )
    parser.add_argument(
        "--update-file",
        default=None,
        help="Specific existing JSON file to update (defaults to --output if not specified).",
    )
    parser.add_argument(
        "--update-sources",
        default="all",
        help="Comma-separated list of sources to update: 'biotools', 'bip', 'openaire', or 'all' (default: 'all').",
    )
    parser.add_argument(
        "--refresh-citations",
        "--refresh-bip",
        action="store_true",
        help="Force re-querying BIP! API for citations even if already present in the dataset (to update citation scores).",
    )
    parser.add_argument(
        "--openaire-upgrade-biotools",
        action="store_true",
        help="Query OpenAIRE Graph API for publications whose date currently comes from bio.tools (to attempt upgrading them to OpenAIRE dates).",
    )
    parser.add_argument(
        "--refresh-openaire",
        action="store_true",
        help="Force re-querying OpenAIRE Graph API for all publications regardless of current date or source.",
    )

    args = parser.parse_args()

    # Enforce API constraint of max 50 DOIs per request
    if args.batch_size > 50:
        print("Warning: BIP! API allows at most 50 DOIs per request. Clamping batch size to 50.", file=sys.stderr)
        args.batch_size = 50

    # Auto-fallback to legacy root directory paths if inputs/ folder isn't used
    if not os.path.isdir(args.data_dir) and os.path.isdir("content-master/data"):
        args.data_dir = "content-master/data"
    if not os.path.isfile(args.elixir_csv) and os.path.isfile("ELIXIR-tools_with bio.csv"):
        args.elixir_csv = "ELIXIR-tools_with bio.csv"

    t_start = time.time()

    # =========================================================================
    # MODE 1: Incremental Update Mode (--update)
    # =========================================================================
    if args.update:
        target_file = args.update_file or args.output
        if not os.path.isfile(target_file):
            basename = os.path.basename(target_file)
            if os.path.isfile(basename):
                target_file = basename
            elif os.path.isfile("outputs/json/biotools_publications.json"):
                target_file = "outputs/json/biotools_publications.json"
            elif os.path.isfile("biotools_publications.json"):
                target_file = "biotools_publications.json"
            else:
                print(f"Error: Existing file '{target_file}' not found for update.", file=sys.stderr)
                sys.exit(1)

        print(f"\n[Update Mode] Loading existing dataset from '{target_file}'...")
        with open(target_file, "r", encoding="utf-8") as f:
            output_records = json.load(f)
        print(f"Loaded {len(output_records):,} existing tool records.")

        update_sources = [s.strip().lower() for s in args.update_sources.split(",") if s.strip()]
        do_all = "all" in update_sources
        do_biotools = do_all or "biotools" in update_sources
        do_bip = do_all or "bip" in update_sources
        do_openaire = do_all or "openaire" in update_sources

        print(f"Update sources enabled: bio.tools={do_biotools}, BIP! API={do_bip}, OpenAIRE={do_openaire}\n")

        # 1. Update from bio.tools JSON files
        if do_biotools:
            if not os.path.isdir(args.data_dir):
                print(f"Error: Directory '{args.data_dir}' not found.", file=sys.stderr)
                sys.exit(1)
            print(f"Scanning directory: {args.data_dir}")
            t_scan = time.time()
            total_folders, tool_files = scan_tool_directories(args.data_dir)
            print(f"Found {len(tool_files):,} .biotools.json files across {total_folders:,} folders.")
            print(f"Parsing bio.tools metadata using {args.workers} worker threads...")
            with ThreadPoolExecutor(max_workers=args.workers) as executor:
                results = list(executor.map(parse_biotools_file, tool_files))
            valid_tools = [r for r in results if r is not None]
            print(f"Parsed {len(valid_tools):,} bio.tools entries in {time.time() - t_scan:.2f}s.")

            print("Merging bio.tools metadata into existing records (preserving existing citations & dates)...")
            merge_stats = merge_biotools_metadata(output_records, valid_tools)
            print(f"  - Tools updated:                 {merge_stats['tools_updated']:,}")
            print(f"  - Functions added/updated:       {merge_stats['functions_added_or_updated']:,}")
            print(f"  - Repositories added/updated:    {merge_stats['repos_added_or_updated']:,}")
            print(f"  - New publications added:        {merge_stats['pubs_added']:,}")
            print(f"  - Newly discovered tools added:  {merge_stats['new_tools_added']:,}")

        # 2. Update citations from BIP! API
        citation_cache: Dict[str, Optional[int]] = {}
        if do_bip and not args.skip_citations:
            if args.reset_cache:
                print(f"Reset cache flag set: starting with empty citation cache.")
                citation_cache = {}
            else:
                citation_cache = load_bip_cache(args.cache_file)

            if args.refresh_citations:
                print("Refresh citations enabled: re-querying all publication IDs to update citation scores...")
                ids_to_query = sorted(list({
                    p["id"]
                    for t in output_records
                    for p in t.get("publications", [])
                    if p.get("id")
                }))
                for q_id in ids_to_query:
                    citation_cache.pop(q_id, None)
            else:
                ids_to_query = sorted(list({
                    p["id"]
                    for t in output_records
                    for p in t.get("publications", [])
                    if p.get("id") and (p.get("citations") is None or p["id"] not in citation_cache)
                }))

            citation_cache = fetch_all_citations(
                unique_ids=ids_to_query,
                cache=citation_cache,
                cache_path=args.cache_file,
                batch_size=args.batch_size,
                delay=args.delay,
                limit_batches=args.limit_batches,
            )

            # Apply citations to publications
            cits_updated_count = 0
            pubs_found_count = 0
            pubs_not_found_count = 0
            for t in output_records:
                for p in t.get("publications", []):
                    pub_id = p.get("id")
                    if pub_id in citation_cache:
                        new_c = citation_cache[pub_id]
                        if p.get("citations") != new_c:
                            cits_updated_count += 1
                        p["citations"] = new_c
                    if p.get("citations") is not None:
                        pubs_found_count += 1
                    else:
                        pubs_not_found_count += 1
            print(f"Updated citations for {cits_updated_count:,} publication entries.")
            print(f"  - Publication entries found in BIP!:     {pubs_found_count:,}")
            print(f"  - Publication entries NOT found in BIP!: {pubs_not_found_count:,}")

        # 3. Update publication dates from OpenAIRE Graph API
        openaire_cache: Dict[str, Optional[str]] = {}
        if do_openaire and not args.skip_openaire:
            if args.reset_openaire_cache:
                print(f"Reset OpenAIRE cache flag set: starting with empty OpenAIRE cache.")
                openaire_cache = {}
            else:
                openaire_cache = load_openaire_cache(args.openaire_cache)

            elixir_biotools_ids = set()
            if args.elixir_csv and os.path.isfile(args.elixir_csv):
                try:
                    import csv
                    with open(args.elixir_csv, "r", encoding="utf-8-sig") as f:
                        for row in csv.DictReader(f):
                            link = row.get("field_bio_tools_link") or ""
                            if "bio.tools/" in link:
                                clean_id = link.split("bio.tools/")[1].strip().split("/")[0].lower()
                                if clean_id:
                                    elixir_biotools_ids.add(clean_id)
                    if elixir_biotools_ids:
                        print(f"Loaded {len(elixir_biotools_ids):,} ELIXIR tools for OpenAIRE query prioritization.")
                except Exception as e:
                    print(f"Note: Could not parse '{args.elixir_csv}' for prioritization: {e}", file=sys.stderr)

            # Build prioritized queue for OpenAIRE
            t1_elixir_missing = []
            t2_other_missing = []
            t3_elixir_has_date = []
            t4_other_has_date = []
            seen_openaire_ids = set()

            for tool in output_records:
                is_elixir = tool["biotools_id"].lower() in elixir_biotools_ids or tool.get("is_elixir", False)
                for pub in tool.get("publications", []):
                    pub_doi = pub.get("doi")
                    pub_pmid = pub.get("pmid")
                    target_id = pub_doi if pub_doi else pub_pmid
                    target_type = "doi" if pub_doi else ("pmid" if pub_pmid else None)

                    if not target_id or not target_type or target_id in seen_openaire_ids:
                        continue

                    curr_source = pub.get("date_source")
                    has_date = bool(pub.get("date"))

                    should_query = False
                    if args.refresh_openaire:
                        should_query = True
                        openaire_cache.pop(target_id, None)
                    elif args.openaire_upgrade_biotools:
                        should_query = (not has_date) or (curr_source == "biotools") or (curr_source != "openaire")
                    else:
                        should_query = not has_date

                    if not should_query:
                        continue

                    seen_openaire_ids.add(target_id)
                    cits = pub.get("citations") or 0

                    if is_elixir and not has_date:
                        t1_elixir_missing.append((cits, (target_id, target_type)))
                    elif not is_elixir and not has_date:
                        t2_other_missing.append((cits, (target_id, target_type)))
                    elif is_elixir and has_date:
                        t3_elixir_has_date.append((cits, (target_id, target_type)))
                    else:
                        t4_other_has_date.append((cits, (target_id, target_type)))

            t1_elixir_missing.sort(key=lambda x: x[0], reverse=True)
            t2_other_missing.sort(key=lambda x: x[0], reverse=True)
            t3_elixir_has_date.sort(key=lambda x: x[0], reverse=True)
            t4_other_has_date.sort(key=lambda x: x[0], reverse=True)

            ordered_openaire_items = (
                [item for _, item in t1_elixir_missing]
                + [item for _, item in t2_other_missing]
                + [item for _, item in t3_elixir_has_date]
                + [item for _, item in t4_other_has_date]
            )

            openaire_cache = fetch_all_openaire_dates(
                query_items=ordered_openaire_items,
                cache=openaire_cache,
                cache_path=args.openaire_cache,
                workers=args.openaire_workers,
                delay=args.openaire_delay,
                limit=args.limit_openaire_dois,
                token=args.openaire_token,
                user_agent=DEFAULT_USER_AGENT,
            )

            # Apply resolved dates
            new_dates_count = 0
            upgraded_dates_count = 0
            for tool in output_records:
                for pub in tool.get("publications", []):
                    oa_date = None
                    if pub.get("doi") and openaire_cache.get(pub["doi"]):
                        oa_date = openaire_cache[pub["doi"]]
                    elif pub.get("pmid") and openaire_cache.get(pub["pmid"]):
                        oa_date = openaire_cache[pub["pmid"]]

                    if oa_date:
                        if pub.get("date_source") == "biotools":
                            if pub.get("date") != oa_date:
                                upgraded_dates_count += 1
                        elif not pub.get("date"):
                            new_dates_count += 1
                        pub["date"] = oa_date
                        pub["date_source"] = "openaire"

            print(f"OpenAIRE updates applied: {new_dates_count:,} new dates resolved, {upgraded_dates_count:,} dates upgraded from bio.tools to OpenAIRE.")

        # Recalculate metrics for dataset consistency
        print("Recalculating dataset metrics (total citations, publication counts, earliest dates)...")
        recalculate_tool_metrics(output_records)

    # =========================================================================
    # MODE 2: Standard Scratch Extraction
    # =========================================================================
    else:
        if not os.path.isdir(args.data_dir):
            print(f"Error: Directory '{args.data_dir}' not found.", file=sys.stderr)
            sys.exit(1)

        print(f"Scanning directory: {args.data_dir}")
        total_folders, tool_files = scan_tool_directories(args.data_dir)
        t_scan = time.time()
        print(
            f"Scan completed in {t_scan - t_start:.2f}s: "
            f"Found {len(tool_files):,} .biotools.json files across {total_folders:,} folders."
        )

        print(f"Parsing bio.tools metadata using {args.workers} worker threads...")
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            results = list(executor.map(parse_biotools_file, tool_files))

        valid_tools = [r for r in results if r is not None]
        t_parse = time.time()
        print(f"Parsed {len(valid_tools):,} bio.tools entries in {t_parse - t_scan:.2f}s.")

        # Collect all unique publication identifiers
        all_unique_ids = sorted(list({
            pub["id"]
            for tool in valid_tools
            for pub in tool["publications"]
        }))

        # Citation retrieval via BIP! API
        citation_cache: Dict[str, Optional[int]] = {}
        if not args.skip_citations:
            if args.reset_cache or args.refresh_citations:
                print(f"Reset cache flag set: starting with an empty cache (will overwrite '{args.cache_file}').")
                citation_cache = {}
            else:
                citation_cache = load_bip_cache(args.cache_file)
            citation_cache = fetch_all_citations(
                unique_ids=all_unique_ids,
                cache=citation_cache,
                cache_path=args.cache_file,
                batch_size=args.batch_size,
                delay=args.delay,
                limit_batches=args.limit_batches,
            )

        # Publication Date retrieval via OpenAIRE Graph API
        openaire_cache: Dict[str, Optional[str]] = {}
        if not args.skip_openaire:
            if args.reset_openaire_cache or args.refresh_openaire:
                print(f"Reset OpenAIRE cache flag set: starting with empty cache (will overwrite '{args.openaire_cache}').")
                openaire_cache = {}
            else:
                openaire_cache = load_openaire_cache(args.openaire_cache)

            # Check if ELIXIR tools CSV exists to prioritize ELIXIR tools in OpenAIRE query queue
            elixir_biotools_ids: Set[str] = set()
            if args.elixir_csv and os.path.isfile(args.elixir_csv):
                try:
                    import csv
                    with open(args.elixir_csv, "r", encoding="utf-8-sig") as f:
                        for row in csv.DictReader(f):
                            link = row.get("field_bio_tools_link") or ""
                            if "bio.tools/" in link:
                                clean_id = link.split("bio.tools/")[1].strip().split("/")[0].lower()
                                if clean_id:
                                    elixir_biotools_ids.add(clean_id)
                    if elixir_biotools_ids:
                        print(f"Loaded {len(elixir_biotools_ids):,} ELIXIR tools from '{args.elixir_csv}' for OpenAIRE query prioritization.")
                except Exception as e:
                    print(f"Note: Could not parse '{args.elixir_csv}' for prioritization: {e}", file=sys.stderr)

            # Build 4-tier priority list of publication identifiers for OpenAIRE
            t1_elixir_missing: List[Tuple[int, Tuple[str, str]]] = []
            t2_other_missing: List[Tuple[int, Tuple[str, str]]] = []
            t3_elixir_has_date: List[Tuple[int, Tuple[str, str]]] = []
            t4_other_has_date: List[Tuple[int, Tuple[str, str]]] = []
            seen_openaire_ids: Set[str] = set()

            for tool in valid_tools:
                is_elixir = tool["biotools_id"].lower() in elixir_biotools_ids
                for pub in tool["publications"]:
                    pub_doi = pub.get("doi")
                    pub_pmid = pub.get("pmid")
                    target_id = pub_doi if pub_doi else pub_pmid
                    target_type = "doi" if pub_doi else ("pmid" if pub_pmid else None)

                    if not target_id or not target_type or target_id in seen_openaire_ids:
                        continue
                    seen_openaire_ids.add(target_id)

                    cits = citation_cache.get(pub["id"]) or 0
                    has_biotools_date = bool(pub.get("date"))

                    if is_elixir and not has_biotools_date:
                        t1_elixir_missing.append((cits, (target_id, target_type)))
                    elif not is_elixir and not has_biotools_date:
                        t2_other_missing.append((cits, (target_id, target_type)))
                    elif is_elixir and has_biotools_date:
                        t3_elixir_has_date.append((cits, (target_id, target_type)))
                    else:
                        t4_other_has_date.append((cits, (target_id, target_type)))

            # Sort descending by citation count within each tier
            t1_elixir_missing.sort(key=lambda x: x[0], reverse=True)
            t2_other_missing.sort(key=lambda x: x[0], reverse=True)
            t3_elixir_has_date.sort(key=lambda x: x[0], reverse=True)
            t4_other_has_date.sort(key=lambda x: x[0], reverse=True)

            ordered_openaire_items = (
                [item for _, item in t1_elixir_missing]
                + [item for _, item in t2_other_missing]
                + [item for _, item in t3_elixir_has_date]
                + [item for _, item in t4_other_has_date]
            )

            openaire_cache = fetch_all_openaire_dates(
                query_items=ordered_openaire_items,
                cache=openaire_cache,
                cache_path=args.openaire_cache,
                workers=args.openaire_workers,
                delay=args.openaire_delay,
                limit=args.limit_openaire_dois,
                token=args.openaire_token,
                user_agent=DEFAULT_USER_AGENT,
            )

        # Attach citations, resolve dates, and calculate tool-level metrics
        output_records = []
        for tool in valid_tools:
            tool_total_citations = 0
            has_any_known_citations = False
            tool_primary_citations = 0
            has_any_known_primary_citations = False
            tool_pmo_citations = 0
            has_any_known_pmo_citations = False
            final_publications = []

            for pub in tool["publications"]:
                pub_id = pub["id"]
                citations = citation_cache.get(pub_id) if not args.skip_citations else None

                openaire_date = None
                if not args.skip_openaire:
                    if pub.get("doi"):
                        openaire_date = openaire_cache.get(pub["doi"])
                    if not openaire_date and pub.get("pmid"):
                        openaire_date = openaire_cache.get(pub["pmid"])

                biotools_date = pub.get("date")

                if openaire_date:
                    resolved_date = openaire_date
                    date_source = "openaire"
                elif biotools_date:
                    resolved_date = biotools_date
                    date_source = "biotools"
                else:
                    resolved_date = None
                    date_source = None

                is_prim = bool(pub.get("is_primary"))
                is_pmo = bool(pub.get("is_pmo"))
                pub_entry = {
                    "id": pub_id,
                    "type": pub["type"],
                    "publication_type": pub.get("publication_type") or [],
                    "is_primary": is_prim,
                    "is_pmo": is_pmo,
                    "date": resolved_date,
                    "date_source": date_source,
                    "citations": citations,
                }
                if pub.get("doi"):
                    pub_entry["doi"] = pub["doi"]
                if pub.get("pmid"):
                    pub_entry["pmid"] = pub["pmid"]
                if pub.get("pmcid"):
                    pub_entry["pmcid"] = pub["pmcid"]

                if citations is not None:
                    tool_total_citations += citations
                    has_any_known_citations = True
                    if is_prim:
                        tool_primary_citations += citations
                        has_any_known_primary_citations = True
                    if is_pmo:
                        tool_pmo_citations += citations
                        has_any_known_pmo_citations = True

                final_publications.append(pub_entry)

            primary_pubs = [p for p in final_publications if p.get("is_primary")]
            primary_pub_count = len(primary_pubs)

            pmo_pubs = [p for p in final_publications if p.get("is_pmo")]
            pmo_pub_count = len(pmo_pubs)

            pub_dates = [
                p["date"]
                for p in final_publications
                if p.get("date") and isinstance(p["date"], str)
            ]
            first_publication = min(pub_dates) if pub_dates else None

            primary_pub_dates = [
                p["date"]
                for p in primary_pubs
                if p.get("date") and isinstance(p["date"], str)
            ]
            first_primary_publication = min(primary_pub_dates) if primary_pub_dates else None

            pmo_pub_dates = [
                p["date"]
                for p in pmo_pubs
                if p.get("date") and isinstance(p["date"], str)
            ]
            first_pmo_publication = min(pmo_pub_dates) if pmo_pub_dates else None

            # Total citations (all related publications)
            if has_any_known_citations:
                total_cits = tool_total_citations
            elif tool["publications"]:
                total_cits = 0
            else:
                total_cits = None

            # Primary citations (primary publications only)
            if has_any_known_primary_citations:
                primary_cits = tool_primary_citations
            elif primary_pubs:
                primary_cits = 0
            elif tool["publications"]:
                primary_cits = 0
            else:
                primary_cits = None

            # PMO citations (Primary, Method, or Other publications)
            if has_any_known_pmo_citations:
                pmo_cits = tool_pmo_citations
            elif pmo_pubs:
                pmo_cits = 0
            elif tool["publications"]:
                pmo_cits = 0
            else:
                pmo_cits = None

            output_records.append({
                "name": tool["name"],
                "biotools_id": tool["biotools_id"],
                "bio_tools_url": tool["bio_tools_url"],
                "additionDate": tool.get("additionDate"),
                "firstPublication": first_publication,
                "first_primary_publication": first_primary_publication,
                "first_pmo_publication": first_pmo_publication,
                "repository_url": tool["repository_url"],
                "repository_source": tool["repository_source"],
                "function": tool.get("function") or [],
                "publication_count": len(final_publications),
                "primary_publication_count": primary_pub_count,
                "pmo_publication_count": pmo_pub_count,
                "total_citations": total_cits,
                "primary_citations": primary_cits,
                "total_primary_citations": primary_cits,
                "pmo_citations": pmo_cits,
                "total_pmo_citations": pmo_cits,
                "primary_method_other_citations": pmo_cits,
                "publications": final_publications,
            })

    # Sort tools alphabetically by biotools_id
    output_records.sort(key=lambda r: r["biotools_id"].lower())

    # Write output JSON
    print(f"\nWriting output to '{args.output}'...")
    out_dir = os.path.dirname(os.path.abspath(args.output))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    indent = None if args.compact else 2
    with open(args.output, "w", encoding="utf-8") as out_f:
        json.dump(output_records, out_f, indent=indent, ensure_ascii=False)

    t_end = time.time()
    file_size_mb = os.path.getsize(args.output) / (1024 * 1024)

    # Summary Statistics computed directly on output_records
    total_tools = len(output_records)
    tools_with_addition_date = sum(1 for r in output_records if r.get("additionDate"))
    tools_with_first_pub = sum(1 for r in output_records if r.get("firstPublication"))
    tools_with_repo = sum(1 for r in output_records if r.get("repository_url"))
    tools_with_function = sum(1 for r in output_records if r.get("function") and len(r["function"]) > 0)
    total_functions = sum(len(r["function"]) for r in output_records if r.get("function"))
    tools_with_pubs = sum(1 for r in output_records if r.get("publication_count", 0) > 0)
    tools_with_primary_pubs = sum(1 for r in output_records if r.get("primary_publication_count", 0) > 0)
    tools_with_pmo_pubs = sum(1 for r in output_records if r.get("pmo_publication_count", 0) > 0)
    all_pubs = [p for r in output_records for p in r.get("publications", [])]
    total_pubs = len(all_pubs)
    total_primary_pubs = sum(1 for p in all_pubs if p.get("is_primary"))
    total_pmo_pubs = sum(1 for p in all_pubs if p.get("is_pmo"))
    dates_from_openaire = sum(1 for p in all_pubs if p.get("date_source") == "openaire")
    dates_from_biotools = sum(1 for p in all_pubs if p.get("date_source") == "biotools")
    dates_missing_count = sum(1 for p in all_pubs if not p.get("date"))

    tools_with_citations = sum(1 for r in output_records if r.get("total_citations") and r["total_citations"] > 0)
    total_citations_across_tools = sum(r["total_citations"] for r in output_records if r.get("total_citations"))
    tools_with_primary_citations = sum(1 for r in output_records if r.get("primary_citations") and r["primary_citations"] > 0)
    total_primary_citations_across_tools = sum(r["primary_citations"] for r in output_records if r.get("primary_citations"))
    tools_with_pmo_citations = sum(1 for r in output_records if r.get("pmo_citations") and r["pmo_citations"] > 0)
    total_pmo_citations_across_tools = sum(r["pmo_citations"] for r in output_records if r.get("pmo_citations"))

    from collections import Counter
    repo_sources = Counter(r["repository_source"] for r in output_records if r.get("repository_source"))

    print("\n" + "=" * 60)
    print("                DATASET SUMMARY STATISTICS")
    print("=" * 60)
    print(f"Total tools in dataset:                  {total_tools:,}")
    print("-" * 60)
    print(f"Tools with function annotations:         {tools_with_function:,} ({tools_with_function/total_tools*100:.1f}%) [Total operations/functions: {total_functions:,}]")
    print(f"Tools with additionDate:                 {tools_with_addition_date:,} ({tools_with_addition_date/total_tools*100:.1f}%)")
    print(f"Tools with firstPublication date:        {tools_with_first_pub:,} ({tools_with_first_pub/total_tools*100:.1f}%)")
    print(f"Publication Date Resolution (Hierarchy: OpenAIRE -> bio.tools -> None):")
    if total_pubs > 0:
        print(f"  - Dates resolved via OpenAIRE API:     {dates_from_openaire:,} ({dates_from_openaire/total_pubs*100:.1f}%)")
        print(f"  - Dates resolved via bio.tools:        {dates_from_biotools:,} ({dates_from_biotools/total_pubs*100:.1f}%)")
        print(f"  - Publications without date:           {dates_missing_count:,} ({dates_missing_count/total_pubs*100:.1f}%)")
    else:
        print("  - No publications found.")
    print("-" * 60)
    print(f"Tools with code repository URL:          {tools_with_repo:,} ({tools_with_repo/total_tools*100:.1f}%)")
    for src, cnt in repo_sources.most_common():
        print(f"  - from {src:30s} {cnt:,} ({cnt/tools_with_repo*100:.1f}%)" if tools_with_repo else "")
    print(f"Tools without code repository URL:       {total_tools - tools_with_repo:,} ({(total_tools - tools_with_repo)/total_tools*100:.1f}%)")
    print("-" * 60)
    print(f"Tools with >= 1 publication:             {tools_with_pubs:,} ({tools_with_pubs/total_tools*100:.1f}%)")
    print(f"Tools with >= 1 Primary publication:     {tools_with_primary_pubs:,} ({tools_with_primary_pubs/total_tools*100:.1f}%)")
    print(f"Tools with >= 1 Primary/Method/Other pub:{tools_with_pmo_pubs:,} ({tools_with_pmo_pubs/total_tools*100:.1f}%)")
    print(f"Total publication entries:               {total_pubs:,}")
    print(f"Total Primary publication entries:       {total_primary_pubs:,} ({total_primary_pubs/total_pubs*100:.1f}%)" if total_pubs else "")
    print(f"Total Primary/Method/Other pub entries:  {total_pmo_pubs:,} ({total_pmo_pubs/total_pubs*100:.1f}%)" if total_pubs else "")
    print("-" * 60)
    if not args.skip_citations:
        if ("citation_cache" not in locals() or not citation_cache) and os.path.isfile(args.cache_file):
            citation_cache = load_bip_cache(args.cache_file)
        cached_count = len(citation_cache) if "citation_cache" in locals() and citation_cache else 0
        print("BIP! API Citation Metrics:")
        if cached_count:
            known_citations_count = sum(1 for v in citation_cache.values() if v is not None)
            not_found_bip_count = sum(1 for v in citation_cache.values() if v is None)
            print(f"  - Unique IDs in BIP! cache:            {cached_count:,}")
            print(f"  - Unique papers found in BIP! API:     {known_citations_count:,} ({known_citations_count/cached_count*100:.1f}%)")
            print(f"  - Unique papers NOT found in BIP! API: {not_found_bip_count:,} ({not_found_bip_count/cached_count*100:.1f}%)")
        pubs_found_count = sum(1 for p in all_pubs if p.get("citations") is not None)
        pubs_not_found_count = sum(1 for p in all_pubs if p.get("citations") is None)
        if total_pubs > 0:
            print(f"  - Publication entries found in BIP!:   {pubs_found_count:,} ({pubs_found_count/total_pubs*100:.1f}%)")
            print(f"  - Publication entries NOT found:       {pubs_not_found_count:,} ({pubs_not_found_count/total_pubs*100:.1f}%)")
        print(f"  - Tools with >= 1 citation found:      {tools_with_citations:,} ({tools_with_citations/total_tools*100:.1f}%)")
        print(f"  - Total citations (all publications):  {total_citations_across_tools:,}")
        print(f"  - Tools with >= 1 primary citation:    {tools_with_primary_citations:,} ({tools_with_primary_citations/total_tools*100:.1f}%)")
        print(f"  - Total citations (Primary only):      {total_primary_citations_across_tools:,}")
        print(f"  - Tools with >= 1 PMO citation:        {tools_with_pmo_citations:,} ({tools_with_pmo_citations/total_tools*100:.1f}%)")
        print(f"  - Total citations (Primary/Method/Other): {total_pmo_citations_across_tools:,}")

        # Show top 5 tools by citations
        top_tools = sorted(
            [t for t in output_records if t.get("total_citations")],
            key=lambda x: x["total_citations"],
            reverse=True,
        )[:5]
        if top_tools:
            print("\n  Top 5 Most Cited Tools:")
            for rank, t in enumerate(top_tools, 1):
                print(f"    {rank}. {t['name']} ({t['biotools_id']}): {t['total_citations']:,} citations")
    else:
        print("BIP! API Citation Metrics:               SKIPPED (--skip-citations enabled)")

    print("-" * 60)
    print(f"Output saved to:                         {args.output}")
    print(f"Output file size:                        {file_size_mb:.2f} MB")
    print(f"Total execution time:                    {t_end - t_start:.2f}s")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
