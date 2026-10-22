# Software Citations & bio.tools Metadata Toolkit

A set of modular Python scripts for extracting, enriching, and analyzing bioinformatics software tool metadata from [bio.tools](https://bio.tools), the [BIP! Services API](https://bip-api.imsi.athenarc.gr/documentation), and the [ELIXIR Europe Software Tools Directory](https://elixir-europe.org/services/tag/software-tools) (either via live web scraping or an exported CSV file).

---

## Table of Contents

- [Overview](#overview)
- [Directory Structure](#directory-structure)
- [Requirements](#requirements)
- [End-to-End Workflow](#end-to-end-workflow)
- [Script 1: `extract_biotools_publications.py`](#script-1-extract_biotools_publicationspy)
  - [Features](#features)
  - [Publication Date Resolution Hierarchy](#publication-date-resolution-hierarchy)
  - [Repository URL Extraction Hierarchy](#repository-url-extraction-hierarchy)
  - [BIP! API Citation Retrieval](#bip-api-citation-retrieval)
  - [Command-Line Usage](#command-line-usage)
  - [CLI Options](#cli-options)
- [Script 2: `identify_elixir_tools.py`](#script-2-identify_elixir_toolspy)
  - [Features](#features-1)
  - [Supported Identification Methods](#supported-identification-methods)
  - [Command-Line Usage](#command-line-usage-1)
  - [CLI Options](#cli-options-1)
- [Script 3: `analyse_elixir_citations.py`](#script-3-analyse_elixir_citationspy)
  - [Features](#features-2)
  - [Command-Line Usage](#command-line-usage-2)
  - [CLI Options](#cli-options-2)
- [Output JSON Data Schema](#output-json-data-schema)
- [Caching, Resetting & Reproduction](#caching-resetting--reproduction)

---

## Overview

This repository provides three coordinated tools:

1. **`extract_biotools_publications.py`**:
   Scans local bio.tools entry folders (e.g. `inputs/content-master/data`), extracts tool metadata (name, URL, repository link, source field, registration timestamp, functional annotations, earliest publication dates), collects publication identifiers (DOIs, PMIDs, PMCIDs) and publication classifications (detecting `"Primary"`, `"Method"`, and `"Other"` publications), queries the BIP! API in batches for official citation counts, and computes three indirect citation metrics per tool:
   - All related publications (`total_citations`)
   - Primary publications only (`primary_citations`)
   - Primary, Method, or Other publications (`pmo_citations`)

2. **`identify_elixir_tools.py`**:
   Identifies tools belonging to the ELIXIR Europe software catalogue using either **live web scraping** (from the ELIXIR website) or **CSV file parsing** (from an exported file such as `inputs/ELIXIR-tools_with bio.csv`), and enriches the bio.tools dataset with an `is_elixir` boolean flag.

3. **`analyse_elixir_citations.py`**:
   Analyzes the enriched dataset to measure ELIXIR tool representation across citation categories (**Top 1%**, **Top 10%**, and **Average**), exports ranked CSV files for all bio.tools and ELIXIR tools into `outputs/csv/`, and generates publication-grade vector visualizations alongside high-resolution raster images (SVG and PNG formats) into `outputs/plots/`, evaluating all three citation count cases side by side.

---

## Directory Structure

```text
software_citations/
├── inputs/
│   ├── content-master/           # Local raw bio.tools JSON entries (e.g. data/*)
│   └── ELIXIR-tools_with bio.csv # Exported ELIXIR directory CSV
├── outputs/
│   ├── json/
│   │   ├── biotools_publications.json
│   │   └── biotools_publications_elixir_incl.json
│   ├── csv/
│   │   ├── all_biotools_ranked.csv
│   │   ├── elixir_tools_ranked.csv
│   │   ├── all_biotools_primary_ranked.csv
│   │   ├── elixir_tools_primary_ranked.csv
│   │   ├── all_biotools_pmo_ranked.csv
│   │   ├── elixir_tools_pmo_ranked.csv
│   │   └── citations_by_year.csv
│   └── plots/
│       ├── citations_by_year.svg / .png
│       ├── citations_primary_by_year.svg / .png
│       ├── citations_pmo_by_year.svg / .png
│       ├── tools_by_year.svg / .png
│       ├── tools_primary_by_year.svg / .png
│       ├── tools_pmo_by_year.svg / .png
│       ├── biotools_categories_pie.svg / .png
│       ├── biotools_categories_pie_primary.svg / .png
│       ├── biotools_categories_pie_pmo.svg / .png
│       ├── elixir_categories_pie.svg / .png
│       ├── elixir_categories_pie_primary.svg / .png
│       ├── elixir_categories_pie_pmo.svg / .png
│       ├── top30_biotools_rankings.svg / .png
│       └── top30_elixir_rankings.svg / .png
├── cache/
│   ├── bip_cache.json            # Persistent cache for BIP! citation counts
│   └── openaire_cache.json       # Persistent cache for OpenAIRE publication dates
├── to-delete/                    # Archived legacy scripts and obsolete CSVs (git-ignored)
├── extract_biotools_publications.py # Main extraction script
├── identify_elixir_tools.py         # Main ELIXIR tagging script
├── analyse_elixir_citations.py      # Main analysis & visualization script
├── README.md
└── .gitignore
```

---

## Requirements

All scripts are implemented entirely with the **Python 3 standard library** (`urllib`, `json`, `csv`, `concurrent.futures`, `argparse`, `re`, `time`, `math`). No third-party packages or `pip install` commands are needed.

- Python 3.8+
- Internet connection (required when querying the BIP! Services API or when using web scraping mode for ELIXIR tools)

---

## End-to-End Workflow

With the organized directory structure, all three scripts run with sensible defaults out of the box:

```bash
# Step 1: Extract bio.tools metadata and fetch citation counts from BIP! API & OpenAIRE
# Reads:  inputs/content-master/data
# Writes: outputs/json/biotools_publications.json, cache/*
python3 extract_biotools_publications.py

# Step 2: Identify ELIXIR tools and add the `is_elixir` flag
# Reads:  outputs/json/biotools_publications.json & inputs/ELIXIR-tools_with bio.csv
# Writes: outputs/json/biotools_publications_elixir_incl.json
# Option A: Using the local CSV file (recommended, fast & offline)
python3 identify_elixir_tools.py --method csv

# Option B: Scraping the live ELIXIR Software Tools catalogue
python3 identify_elixir_tools.py --method scrape

# Option C: Scraping the broader ELIXIR all-services directory
python3 identify_elixir_tools.py --method scrape-all

# Step 3: Run citation categorization, export ranked CSVs, and generate vector plots
# Reads:  outputs/json/biotools_publications_elixir_incl.json
# Writes: outputs/csv/*.csv and outputs/plots/*.svg
python3 analyse_elixir_citations.py
```

---

## Script 1: `extract_biotools_publications.py`

### Features
- **High performance**: Fast directory traversal using `os.scandir` combined with multithreaded file parsing (`ThreadPoolExecutor`, 16 workers by default). Over 40,000 folders and 34,000 bio.tools JSON entries are parsed in ~15-18 seconds.
- **Function & EDAM ontology extraction**: Extracts the complete `function` array for each tool, including EDAM operation terms and URIs (`term`, `uri`), `input`, `output`, `cmd`, and `note`.
- **Publication extraction**: Collects publication objects with DOIs, PMIDs, and PMCIDs. DOIs are case-normalized to lower-case (required for exact BIP! API matching).
- **Date resolution hierarchy**: Integrates with the **OpenAIRE Graph API** (`https://api.openaire.eu/graph/v4/research-products`) as the primary source for accurate publication dates. If OpenAIRE does not have the date, falls back to `bio.tools` metadata dates.
- **Strict negative constraint**: `additionDate` is strictly **never** used as a fallback for publication date or `firstPublication` (preserving the integrity of timeline statistics).
- **Date tracking**: Records each publication's resolved date (`date`), the provenance of the date (`date_source`: `"openaire"` or `"biotools"`), the tool's bio.tools registration timestamp (`additionDate`), and computes the earliest publication date across valid papers (`firstPublication`).
- **Code repository extraction**: Implements a prioritized fallback strategy to locate the code repository and records the exact source field.
- **BIP! API batch integration**: Queries up to 50 publication IDs per request to `/paper/scores/batch/{dois}` with polite request intervals and exponential backoff retry.
- **Non-Destructive Incremental Updates (`--update`)**:
  Allows updating existing output datasets without losing previously collected metadata. You can selectively update:
  - `biotools`: Scans local bio.tools files to add `function` classes, new repository links, new publications, or newly discovered tools. Existing citations, dates, and custom flags (like `is_elixir`) are strictly preserved.
  - `bip`: Fetches citation counts for newly added publications, or forces a refresh of citation scores across the entire dataset via `--refresh-citations`.
  - `openaire`: Queries OpenAIRE Graph API for new or missing dates, or attempts to upgrade existing `bio.tools` dates to higher-accuracy OpenAIRE dates via `--openaire-upgrade-biotools`.
- **Persistent dual disk caching**:
  - `cache/bip_cache.json`: Caches publication citation counts retrieved from BIP! API.
  - `cache/openaire_cache.json`: Caches publication dates retrieved from OpenAIRE Graph API.
  Both caches update incrementally and can be safely interrupted and resumed without repeating network calls.

### Publication Date Resolution Hierarchy
When resolving the publication date for each paper (`date`) and computing a tool's earliest publication date (`firstPublication`), the script applies the following strict precedence:
1. **OpenAIRE Graph API**: Queried in parallel by DOI (or PMID). Resolved dates (e.g. `"2014-02-19"`) take precedence.
2. **`bio.tools` Metadata**: Fallback if OpenAIRE date is missing.
3. **`null`**: If neither OpenAIRE nor bio.tools has a date, the publication date remains `null`. `additionDate` is **never** used as a fallback.

### Repository URL Extraction Hierarchy
When determining the primary code repository URL (`repository_url`), the script applies the following order of precedence:
1. `link` entry with `type: "Repository"`
2. `download` entry with `type: "Source code"` matching a known code repository host (`github.com`, `gitlab.*`, `bitbucket.org`, `sourceforge.net`, `codeberg.org`, `git.*`, etc.)
3. `homepage` matching a known code repository host
4. `link` entry with `type: "Mirror"` pointing to a code repository host
5. `documentation` entry pointing to a code repository host
6. Any other `download` entry with `type: "Source code"`
7. Falls back to `null` if no repository is detected.

The originating source is stored in the `repository_source` field (e.g. `"link (Repository)"`, `"homepage"`, `"download (Source code)"`).

### BIP! API Citation Retrieval
- **Batch mode**: Globally deduplicates unique publication IDs across all tools, splitting them into chunks of 50.
- **Identifier support**: Tested and confirmed support for DOIs, raw PMIDs (e.g. `34267986`), and PMCIDs (e.g. `PMC8274303`).
- **Tool-level totals**: Aggregates the citation counts across each tool's publications into `total_citations`, `primary_citations`, and `pmo_citations`.
- **Coverage & Not-Found Reporting**: Tracks and explicitly reports the number and percentage of publications found vs. not found / unindexed in the BIP! API (both at the unique publication ID level and across all tool publication entries).

### Command-Line Usage

#### Standard Run (from scratch)
```bash
# Standard full extraction (reads inputs/content-master/data, queries BIP! and OpenAIRE)
python3 extract_biotools_publications.py

# Skip OpenAIRE date querying (uses bio.tools dates only)
python3 extract_biotools_publications.py --skip-openaire

# Query OpenAIRE with personal token (higher rate limit up to 7,200 req/hour)
python3 extract_biotools_publications.py --openaire-token "YOUR_OPENAIRE_TOKEN"

# Skip BIP! API queries (metadata and dates only)
python3 extract_biotools_publications.py --skip-citations

# Run from scratch ignoring and resetting cached citations and OpenAIRE dates
python3 extract_biotools_publications.py --reset-cache --reset-openaire-cache
```

#### Incremental Update Mode (`--update`)
```bash
# 1. Update ONLY bio.tools metadata (adds function, new repos, new pubs without calling APIs)
python3 extract_biotools_publications.py --update --update-sources biotools

# 2. Update publication dates from OpenAIRE, attempting to upgrade bio.tools dates to OpenAIRE
python3 extract_biotools_publications.py \
  --update \
  --update-sources openaire \
  --openaire-upgrade-biotools \
  --openaire-token "YOUR_OPENAIRE_TOKEN"

# 3. Refresh citation scores from BIP! API (fetches latest citation counts)
python3 extract_biotools_publications.py --update --update-sources bip --refresh-citations

# 4. Full non-destructive update from all sources
python3 extract_biotools_publications.py --update --update-sources all --openaire-token "YOUR_OPENAIRE_TOKEN"
```

### CLI Options

| Option | Default | Description |
| :--- | :--- | :--- |
| `--data-dir`, `-d` | `inputs/content-master/data` | Path to directory containing tool folders |
| `--output`, `-o` | `outputs/json/biotools_publications.json` | Path for the generated JSON file |
| `--update` | `False` | Enable incremental update mode on existing output file |
| `--update-file` | `None` | Specific JSON file to update (defaults to `--output`) |
| `--update-sources` | `all` | Comma-separated sources to update: `'biotools'`, `'bip'`, `'openaire'`, or `'all'` |
| `--cache-file`, `-c` | `cache/bip_cache.json` | Path to local JSON cache for BIP! citation scores |
| `--reset-cache` | `False` | Ignore and overwrite citation cache, querying fresh |
| `--refresh-citations`, `--refresh-bip` | `False` | Force re-querying BIP! API to refresh existing citation scores |
| `--skip-citations` | `False` | Skip BIP! API requests (extract metadata only) |
| `--batch-size` | `50` | Number of publications per BIP! API request (max 50) |
| `--delay` | `0.5` | Polite delay (seconds) between BIP! batch requests |
| `--limit-batches` | `None` | Optional limit on the number of BIP! batches to query |
| `--openaire-cache` | `cache/openaire_cache.json` | Path to local JSON cache for OpenAIRE publication dates |
| `--skip-openaire` | `False` | Skip querying OpenAIRE Graph API (uses bio.tools dates only) |
| `--reset-openaire-cache` | `False` | Ignore and overwrite existing OpenAIRE date cache |
| `--openaire-upgrade-biotools` | `False` | Query OpenAIRE specifically for publications whose date comes from bio.tools to upgrade them |
| `--refresh-openaire` | `False` | Force re-querying OpenAIRE Graph API for all publications |
| `--openaire-workers` | `8` | Worker threads for concurrent OpenAIRE API calls |
| `--openaire-delay` | `0.05` | Polite wait time (seconds) between OpenAIRE requests per worker |
| `--limit-openaire-dois` | `None` | Optional limit on the number of publication IDs to query from OpenAIRE |
| `--openaire-token` | `None` | Optional OpenAIRE API Personal Access Token (or set `OPENAIRE_API_TOKEN` env var) |
| `--elixir-csv` | `inputs/ELIXIR-tools_with bio.csv` | Optional path to ELIXIR tools CSV to prioritize ELIXIR tools in OpenAIRE query queue |
| `--workers`, `-w` | `16` | Worker threads for parallel file parsing |
| `--compact` | `False` | Output compact JSON without indentation |

---

## Script 2: `identify_elixir_tools.py`

### Features
- **Multi-source identification methods**: Supports identifying ELIXIR tools either via live web scraping (of software tools or all services) or from an exported CSV file.
- **Link parsing**: Robust regex extraction of bio.tools IDs from URLs (e.g. `https://bio.tools/<id>`), handling multiple links and case variations.
- **Dataset enrichment**: Reads `outputs/json/biotools_publications.json` and inserts the `is_elixir` boolean flag into each record, outputting `outputs/json/biotools_publications_elixir_incl.json`.
- **Optional catalogue export**: Can save the extracted ELIXIR service list as a standalone JSON file (`--save-elixir-list`).

### Supported Identification Methods

1. **Method 1 (`--method csv` or `--method file`) [Recommended]**:
   Parses a local CSV file (default: `inputs/ELIXIR-tools_with bio.csv`), reading bio.tools links from the specified column (`field_bio_tools_link` by default) with automatic UTF-8 BOM handling. Instantaneous and fully offline.
2. **Method 2 (`--method scrape` or `--method web`)**:
   Scrapes the ELIXIR Software Tools catalogue from `https://elixir-europe.org/services/tag/software-tools` (12 pages, ~346 tools) using a browser User-Agent to retrieve the latest tools catalogue.
3. **Method 3 (`--method scrape-all` or `--method web-all`)**:
   Scrapes the complete ELIXIR services directory from `https://elixir-europe.org/services/list` (20 pages, ~595 services), capturing bio.tools entries that may be categorized under databases, platforms, or interoperability services rather than tagged solely as software tools.

### Command-Line Usage

```bash
# Method 1: Identify from local CSV file (recommended default, instantaneous)
python3 identify_elixir_tools.py --method csv

# Method 2: Identify via web scraping software tools catalogue
python3 identify_elixir_tools.py --method scrape --delay 0.5

# Method 3: Identify via web scraping all ELIXIR services (broader scope)
python3 identify_elixir_tools.py --method scrape-all --delay 0.3

# Save the identified ELIXIR services to a separate JSON catalogue
python3 identify_elixir_tools.py \
  --method scrape-all \
  --save-elixir-list "outputs/json/elixir_all_services.json"

# Custom input and output paths
python3 identify_elixir_tools.py \
  --method csv \
  --csv-file "inputs/ELIXIR-tools_with bio.csv" \
  --input-json "outputs/json/biotools_publications.json" \
  --output-json "outputs/json/biotools_publications_elixir_incl.json"
```

### CLI Options

| Option | Default | Description |
| :--- | :--- | :--- |
| `--method`, `-m` | `scrape` | Identification method: `'scrape'` (software tools), `'scrape-all'` (all services), or `'csv'` (local file) |
| `--csv-file` | `inputs/ELIXIR-tools_with bio.csv` | Path to ELIXIR CSV file (used when method is `csv`) |
| `--csv-column` | `field_bio_tools_link` | Column header in CSV containing bio.tools links |
| `--scrape-url` | `None` | Optional base URL to override scraping target (defaults to software-tools for `scrape`, or services/list for `scrape-all`) |
| `--delay` | `0.5` | Polite delay in seconds between scraping page requests |
| `--input-json`, `-i` | `outputs/json/biotools_publications.json` | Path to input bio.tools JSON file |
| `--output-json`, `-o` | `outputs/json/biotools_publications_elixir_incl.json` | Path for output enriched JSON file |
| `--flag-name` | `is_elixir` | Name of boolean flag field to add in each record |
| `--save-elixir-list` | `None` | Optional path to save parsed ELIXIR services as JSON |
| `--compact` | `False` | Write compact JSON without indentation |

---

## Script 3: `analyse_elixir_citations.py`

### Features
- **3 Citation Count Metrics Evaluated Side by Side**:
  1. **All Related Publications** (`total_citations`): includes all publications associated with the tool in bio.tools.
  2. **Primary Publications Only** (`primary_citations` / `total_primary_citations`): isolates publications marked as `"Primary"` in bio.tools.
  3. **Primary, Method, or Other Publications** (`pmo_citations` / `total_pmo_citations`): considers publications marked as `"Primary"`, `"Method"`, or `"Other"` in bio.tools.
- **3-Tier Citation Categorization (Top 1%, Top 10%, Average)**:
  Independently categorizes tools across the three tiers for each of the three citation metrics.
- **Ranked CSV Exports (6 Files Total)**:
  - `all_biotools_ranked.csv`: Complete ranking of all 34,397 tools by total citations, with total, primary, and PMO citation ranks, categories, counts, and metadata.
  - `elixir_tools_ranked.csv`: Dedicated ranking of ELIXIR tools ordered by total citations.
  - `all_biotools_primary_ranked.csv`: All 34,397 tools ordered by primary publication citations.
  - `elixir_tools_primary_ranked.csv`: ELIXIR tools ordered by primary publication citations.
  - `all_biotools_pmo_ranked.csv`: All 34,397 tools ordered by Primary/Method/Other publication citations.
  - `elixir_tools_pmo_ranked.csv`: ELIXIR tools ordered by Primary/Method/Other publication citations.
- **Dual SVG + PNG Visualization Outputs (14 Figures Total, 28 Files)**:
  All charts are generated in both vector SVG and crisp high-resolution PNG format (via `resvg-py`) with zero configuration:
  - **Yearly Citations Histograms (3 plots)**:
    - `citations_by_year.svg` / `.png`: All Related Publications.
    - `citations_primary_by_year.svg` / `.png`: Primary Publications Only.
    - `citations_pmo_by_year.svg` / `.png`: Primary, Method, or Other Publications.
  - **Yearly Tools Histograms (3 plots)**:
    - `tools_by_year.svg` / `.png`: All tools by first publication year.
    - `tools_primary_by_year.svg` / `.png`: Tools with primary publications by primary publication year.
    - `tools_pmo_by_year.svg` / `.png`: Tools with PMO publications by PMO publication year.
  - **Category Breakdown Pie Charts (6 plots)**:
    - `biotools_categories_pie.svg` / `.png`: All bio.tools (All Publications).
    - `biotools_categories_pie_primary.svg` / `.png`: All bio.tools (Primary Publications Only).
    - `biotools_categories_pie_pmo.svg` / `.png`: All bio.tools (Primary, Method, or Other).
    - `elixir_categories_pie.svg` / `.png`: ELIXIR Tools (All Publications).
    - `elixir_categories_pie_primary.svg` / `.png`: ELIXIR Tools (Primary Publications Only).
    - `elixir_categories_pie_pmo.svg` / `.png`: ELIXIR Tools (Primary, Method, or Other).
  - **Top 30 Tools Side-by-Side Comparison Panels (2 plots)**:
    - `top30_biotools_rankings.svg` / `.png`: Top 30 tools across all bio.tools for the three rankings (Total, Primary, PMO) side by side, highlighting ELIXIR tools with an orange badge and proportional visual citation bars.
    - `top30_elixir_rankings.svg` / `.png`: Top 30 ELIXIR software tools for the three rankings side by side, displaying their global bio.tools ranks and citation counts.

### Command-Line Usage

```bash
# Standard run (prints console analysis and generates all 14 SVG + 14 PNG charts + 6 CSV files)
python3 analyse_elixir_citations.py

# Custom output paths for CSVs and charts
python3 analyse_elixir_citations.py \
  --export-all-csv "outputs/csv/custom_all_biotools_ranked.csv" \
  --export-elixir-csv "outputs/csv/custom_elixir_tools_ranked.csv" \
  --export-all-primary-csv "outputs/csv/custom_all_biotools_primary_ranked.csv" \
  --export-elixir-primary-csv "outputs/csv/custom_elixir_tools_primary_ranked.csv" \
  --export-all-pmo-csv "outputs/csv/custom_all_biotools_pmo_ranked.csv" \
  --export-elixir-pmo-csv "outputs/csv/custom_elixir_tools_pmo_ranked.csv" \
  --plot-citations-file "outputs/plots/custom_citations_by_year.svg" \
  --plot-citations-primary-file "outputs/plots/custom_citations_primary_by_year.svg" \
  --plot-citations-pmo-file "outputs/plots/custom_citations_pmo_by_year.svg" \
  --plot-tools-file "outputs/plots/custom_tools_by_year.svg" \
  --plot-tools-primary-file "outputs/plots/custom_tools_primary_by_year.svg" \
  --plot-tools-pmo-file "outputs/plots/custom_tools_pmo_by_year.svg" \
  --plot-biotools-pie "outputs/plots/custom_biotools_categories_pie.svg" \
  --plot-biotools-pie-primary "outputs/plots/custom_biotools_categories_pie_primary.svg" \
  --plot-biotools-pie-pmo "outputs/plots/custom_biotools_categories_pie_pmo.svg" \
  --plot-elixir-pie "outputs/plots/custom_elixir_categories_pie.svg" \
  --plot-elixir-pie-primary "outputs/plots/custom_elixir_categories_pie_primary.svg" \
  --plot-elixir-pie-pmo "outputs/plots/custom_elixir_categories_pie_pmo.svg" \
  --plot-top30-all-file "outputs/plots/custom_top30_biotools_rankings.svg" \
  --plot-top30-elixir-file "outputs/plots/custom_top30_elixir_rankings.svg" \
  --top-tools-n 30

# Disable PNG generation (SVG-only mode)
python3 analyse_elixir_citations.py --no-png

# Export yearly breakdown to CSV
python3 analyse_elixir_citations.py \
  --export-year-csv "outputs/csv/yearly_summary.csv" \
  --export-year-primary-csv "outputs/csv/yearly_summary_primary.csv" \
  --export-year-pmo-csv "outputs/csv/yearly_summary_pmo.csv"

# Set custom earliest publication year for histograms (e.g. 1995)
python3 analyse_elixir_citations.py --plot-start-year 1995

# Show up to 50 sample ELIXIR tools per tier in console output
python3 analyse_elixir_citations.py --max-tools-print 50
```

### CLI Options

| Option | Default | Description |
| :--- | :--- | :--- |
| `--input-json`, `-i` | `outputs/json/biotools_publications_elixir_incl.json` | Path to enriched bio.tools JSON file |
| `--export-all-csv`, `--export-csv` | `outputs/csv/all_biotools_ranked.csv` | Ranked CSV of all bio.tools by total citations |
| `--export-elixir-csv` | `outputs/csv/elixir_tools_ranked.csv` | Ranked CSV of ELIXIR tools by total citations |
| `--export-all-primary-csv` | `outputs/csv/all_biotools_primary_ranked.csv` | Ranked CSV of all bio.tools by primary citations |
| `--export-elixir-primary-csv` | `outputs/csv/elixir_tools_primary_ranked.csv` | Ranked CSV of ELIXIR tools by primary citations |
| `--export-all-pmo-csv` | `outputs/csv/all_biotools_pmo_ranked.csv` | Ranked CSV of all bio.tools by PMO citations |
| `--export-elixir-pmo-csv` | `outputs/csv/elixir_tools_pmo_ranked.csv` | Ranked CSV of ELIXIR tools by PMO citations |
| `--export-year-csv` | `None` | Optional path to export yearly breakdown to CSV (all publications) |
| `--export-year-primary-csv` | `None` | Optional path to export yearly breakdown to CSV (primary publications) |
| `--export-year-pmo-csv` | `None` | Optional path to export yearly breakdown to CSV (PMO publications) |
| `--plot-citations-file` | `outputs/plots/citations_by_year.svg` | Citations/year histogram (all publications) |
| `--plot-citations-primary-file` | `outputs/plots/citations_primary_by_year.svg` | Citations/year histogram (primary publications) |
| `--plot-citations-pmo-file` | `outputs/plots/citations_pmo_by_year.svg` | Citations/year histogram (PMO publications) |
| `--plot-tools-file` | `outputs/plots/tools_by_year.svg` | Tools/year histogram (all tools) |
| `--plot-tools-primary-file` | `outputs/plots/tools_primary_by_year.svg` | Tools/year histogram (tools with primary publications) |
| `--plot-tools-pmo-file` | `outputs/plots/tools_pmo_by_year.svg` | Tools/year histogram (tools with PMO publications) |
| `--plot-biotools-pie` | `outputs/plots/biotools_categories_pie.svg` | All bio.tools category pie chart (all publications) |
| `--plot-biotools-pie-primary` | `outputs/plots/biotools_categories_pie_primary.svg` | All bio.tools category pie chart (primary publications) |
| `--plot-biotools-pie-pmo` | `outputs/plots/biotools_categories_pie_pmo.svg` | All bio.tools category pie chart (PMO publications) |
| `--plot-elixir-pie` | `outputs/plots/elixir_categories_pie.svg` | ELIXIR tools category pie chart (all publications) |
| `--plot-elixir-pie-primary` | `outputs/plots/elixir_categories_pie_primary.svg` | ELIXIR tools category pie chart (primary publications) |
| `--plot-elixir-pie-pmo` | `outputs/plots/elixir_categories_pie_pmo.svg` | ELIXIR tools category pie chart (PMO publications) |
| `--plot-top30-all-file` | `outputs/plots/top30_biotools_rankings.svg` | Top N all bio.tools across 3 rankings side-by-side figure (alias `--plot-top20-all-file`) |
| `--plot-top30-elixir-file` | `outputs/plots/top30_elixir_rankings.svg` | Top N ELIXIR tools across 3 rankings side-by-side figure (alias `--plot-top20-elixir-file`) |
| `--top-tools-n` | `30` | Number of top tools displayed in side-by-side comparison figures |
| `--no-png` | `False` | Disable automatic generation of raster PNG copies alongside SVG figures |
| `--plot-start-year` | `1990` | Earliest publication year to include on histogram charts |
| `--max-tools-print` | `25` | Number of ELIXIR tools to list per tier in console output |

---

## Output JSON Data Schema

Each record in `outputs/json/biotools_publications_elixir_incl.json` follows this structure:

```json
{
  "name": "123FASTQ",
  "biotools_id": "123fastq",
  "bio_tools_url": "https://bio.tools/123fastq",
  "is_elixir": false,
  "additionDate": "2024-03-12T14:20:00Z",
  "firstPublication": "2024-03-08T00:00:00Z",
  "first_primary_publication": "2024-03-08T00:00:00Z",
  "first_pmo_publication": "2024-03-08T00:00:00Z",
  "repository_url": "https://sourceforge.net/projects/project-123ngs",
  "repository_source": "homepage",
  "function": [
    {
      "operation": [
        {
          "term": "Deposition",
          "uri": "http://edamontology.org/operation_3431"
        },
        {
          "term": "Genotyping",
          "uri": "http://edamontology.org/operation_3196"
        }
      ],
      "input": [],
      "output": [],
      "cmd": null,
      "note": null
    }
  ],
  "publication_count": 1,
  "primary_publication_count": 1,
  "pmo_publication_count": 1,
  "total_citations": 0,
  "primary_citations": 0,
  "total_primary_citations": 0,
  "pmo_citations": 0,
  "total_pmo_citations": 0,
  "primary_method_other_citations": 0,
  "publications": [
    {
      "id": "10.1101/2024.03.08.584032",
      "type": "doi",
      "publication_type": [
        "Primary"
      ],
      "is_primary": true,
      "is_pmo": true,
      "date": "2024-03-08",
      "date_source": "openaire",
      "citations": 0,
      "doi": "10.1101/2024.03.08.584032",
      "pmid": null,
      "pmcid": null
    }
  ]
}
```

### Field Definitions

- **`name`** (`str`): Display name of the tool from bio.tools.
- **`biotools_id`** (`str`): Unique bio.tools identifier.
- **`bio_tools_url`** (`str`): Canonical bio.tools URL (`https://bio.tools/<biotools_id>`).
- **`is_elixir`** (`bool`): `true` if the tool is in the ELIXIR Software Tools directory; `false` otherwise.
- **`additionDate`** (`str` or `null`): ISO 8601 timestamp of when the tool entry was registered in bio.tools.
- **`firstPublication`** (`str` or `null`): Earliest publication date string among all publications related to this tool.
- **`first_primary_publication`** (`str` or `null`): Earliest publication date string among primary publications related to this tool (`null` if no primary publication with date exists).
- **`first_pmo_publication`** (`str` or `null`): Earliest publication date string among Primary, Method, or Other publications related to this tool.
- **`repository_url`** (`str` or `null`): Resolved code repository URL (or `null` if none found).
- **`repository_source`** (`str` or `null`): Metadata field from which the repository was extracted.
- **`function`** (`list` of `object`): Functional annotations from bio.tools, including EDAM ontology operations.
- **`publication_count`** (`int`): Total number of associated publications extracted for this tool.
- **`primary_publication_count`** (`int`): Number of associated publications marked as `"Primary"`.
- **`pmo_publication_count`** (`int`): Number of associated publications marked as `"Primary"`, `"Method"`, or `"Other"`.
- **`total_citations`** (`int` or `null`): Sum of citation counts across all publications related to the tool.
- **`primary_citations`** (`int` or `null`): Sum of citation counts across primary publications only.
- **`total_primary_citations`** (`int` or `null`): Alias for `primary_citations`.
- **`pmo_citations`** (`int` or `null`): Sum of citation counts across Primary, Method, or Other publications.
- **`total_pmo_citations`** (`int` or `null`): Alias for `pmo_citations`.
- **`primary_method_other_citations`** (`int` or `null`): Alias for `pmo_citations`.
- **`publications`** (`list` of `object`): List of publication entries:
  - **`id`** (`str`): Query identifier used for BIP! API.
  - **`type`** (`str`): Identifier type (`"doi"`, `"pmid"`, or `"pmcid"`).
  - **`publication_type`** (`list` of `str`): Publication type classifications from bio.tools (e.g., `["Primary"]`, `["Method"]`, `["Other"]`, `["Review"]`).
  - **`is_primary`** (`bool`): `true` if `"Primary"` is included in the publication type; `false` otherwise.
  - **`is_pmo`** (`bool`): `true` if `"Primary"`, `"Method"`, or `"Other"` is included in the publication type; `false` otherwise.
  - **`date`** (`str` or `null`): Resolved publication date.
  - **`date_source`** (`str` or `null`): Source of the resolved date (`"openaire"`, `"biotools"`, or `null`).
  - **`citations`** (`int` or `null`): Citation count from BIP! API.
  - **`doi`**, **`pmid`**, **`pmcid`** (`str` or omitted): Identifier strings.

---

## Caching, Resetting & Reproduction

### Local Caches
- **`cache/bip_cache.json`**: Stores `{ "<identifier>": <citation_count> }` mappings across runs.
- **`cache/openaire_cache.json`**: Stores `{ "<identifier>": "<publicationDate>" }` mappings from the OpenAIRE Graph API.
- Both caches update incrementally and save to disk periodically, ensuring full idempotency and reproducibility without redundant network calls.

### Resetting Caches to Re-run from Scratch
To completely ignore previous caches and run a 100% fresh citation query against the BIP! API and OpenAIRE Graph API:
```bash
python3 extract_biotools_publications.py --reset-cache --reset-openaire-cache
```

### Performance Benchmarks
- **Local file parsing**: ~2,500 bio.tools JSON entries/second with 16 worker threads (~18 seconds total for 34,397 tools).
- **CSV ELIXIR identification**: Less than 1 second for 440 entries.
- **Web scraping ELIXIR identification**: ~20-25 seconds for 12 pages with polite 0.5s intervals.
- **BIP! API querying**: ~640 batch requests total for ~32,000 unique publication IDs across the entire bio.tools ecosystem.
