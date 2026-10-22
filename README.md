# ELIXIR Tools Impact & bio.tools Citation Toolkit

A modular Python toolkit to extract, enrich, and analyze citation impact for bioinformatics tools registered in [bio.tools](https://bio.tools), querying citation metrics from the [BIP! Services API](https://bip-api.imsi.athenarc.gr/documentation), publication dates from the [OpenAIRE Graph API](https://graph.openaire.eu/), and identifying ELIXIR services via the [ELIXIR Europe Directory](https://elixir-europe.org/services/tag/software-tools).

---

## Table of Contents

- [Overview](#overview)
- [Directory Structure](#directory-structure)
- [Requirements & Setup](#requirements--setup)
- [Quickstart Workflow](#quickstart-workflow)
- [Script 1: `extract_biotools_publications.py`](#script-1-extract_biotools_publicationspy)
- [Script 2: `identify_elixir_tools.py`](#script-2-identify_elixir_toolspy)
- [Script 3: `analyse_elixir_citations.py`](#script-3-analyse_elixir_citationspy)
- [Output Schema](#output-schema)
- [Caching & Reproduction](#caching--reproduction)

---

## Overview

The toolkit consists of three coordinated CLI scripts:

1. **`extract_biotools_publications.py`**:
   Parses local bio.tools entry folders, extracts tool metadata (names, URLs, repositories, EDAM functional annotations), resolves earliest publication dates via OpenAIRE and bio.tools, queries the BIP! API in batches for official citation counts, and aggregates citations across three scopes: **All**, **Primary-only**, and **Primary/Method/Other (PMO)** publications.
2. **`identify_elixir_tools.py`**:
   Cross-references tools with the ELIXIR Europe directory (using local CSV parsing or live web scraping) and enriches the dataset with the `is_elixir` boolean flag.
3. **`analyse_elixir_citations.py`**:
   Computes citation percentiles (Top 1%, Top 10%, Average), exports comprehensive ranked CSV tables, and produces publication-grade vector (SVG) and raster (PNG) charts across all three citation metrics.

---

## Directory Structure

```text
elixir-tools-impact/
├── inputs/
│   ├── content-master/           # bio.tools raw data dump (git-ignored, see setup)
│   └── ELIXIR-tools_with bio.csv # Reference ELIXIR directory CSV (included)
├── outputs/
│   ├── json/                     # Enriched dataset JSON files
│   ├── csv/                      # Ranked CSV tables and yearly statistics
│   └── plots/                    # Generated SVG and PNG figures
├── cache/
│   ├── bip_cache.json            # Persistent cache for BIP! citation counts
│   └── openaire_cache.json       # Persistent cache for OpenAIRE publication dates
├── extract_biotools_publications.py
├── identify_elixir_tools.py
├── analyse_elixir_citations.py
├── requirements.txt
├── README.md
└── .gitignore
```

---

## Requirements & Setup

- **Python 3.8+**
- **Core dependencies**: None. The pipeline runs using the **Python Standard Library** only.
- **Optional dependencies** (for high-resolution PNG rendering of SVG charts):
  ```bash
  pip install -r requirements.txt
  ```

### Obtaining the bio.tools Data Dump

Because the bio.tools repository contains over 40,000 JSON files (~1 GB), it is kept unversioned. Download or clone it into `inputs/content-master`:

```bash
# Option A: Shallow clone (recommended, ~400 MB transfer)
git clone --depth 1 https://github.com/bio-tools/content.git inputs/content-master

# Option B: Download and extract zip archive
curl -L https://github.com/bio-tools/content/archive/refs/heads/master.zip -o content.zip
unzip -q content.zip -d inputs/ && mv inputs/content-master* inputs/content-master && rm content.zip
```

---

## Quickstart Workflow

Execute the three-step pipeline in order:

```bash
# Step 1: Extract bio.tools metadata, dates (OpenAIRE), and citations (BIP! API)
python3 extract_biotools_publications.py

# Step 2: Flag ELIXIR tools using the included reference CSV (instant & offline)
python3 identify_elixir_tools.py --method csv

# Step 3: Run citation categorization, export ranked CSVs, and generate plots
python3 analyse_elixir_citations.py
```

---

## Script 1: `extract_biotools_publications.py`

### Key Features
- **High Performance**: Multithreaded parsing (`ThreadPoolExecutor`, 16 workers by default) processes >34,000 bio.tools JSON entries in under 20 seconds.
- **Date Resolution Precedence**:
  1. OpenAIRE Graph API (queried concurrently by DOI/PMID).
  2. `bio.tools` publication metadata (fallback).
  3. `null` if unavailable (`additionDate` is strictly never used as a proxy for publication date).
- **Code Repository Resolution**: Cascading check across `link (Repository)` -> `download (Source code)` -> `homepage` matching git hosts (GitHub, GitLab, Bitbucket, SourceForge, etc.).
- **BIP! API Integration**: Batches up to 50 publication IDs per request with exponential backoff retry.
- **Persistent Caching**: Caches BIP! citations (`cache/bip_cache.json`) and OpenAIRE dates (`cache/openaire_cache.json`) to allow safe interruption and resumption.
- **Incremental Updates (`--update`)**: Non-destructively refresh metadata, citations (`--refresh-citations`), or dates without re-running the entire pipeline.

### Common Usage Examples

```bash
# Standard run from scratch
python3 extract_biotools_publications.py

# Use OpenAIRE personal access token for higher rate limits (up to 7,200 req/hr)
python3 extract_biotools_publications.py --openaire-token "YOUR_TOKEN"

# Fast metadata-only run (skip BIP! and OpenAIRE API calls)
python3 extract_biotools_publications.py --skip-citations --skip-openaire

# Incremental update: refresh citations from BIP! API only
python3 extract_biotools_publications.py --update --update-sources bip --refresh-citations
```

### CLI Options

| Option | Default | Description |
| :--- | :--- | :--- |
| `--data-dir`, `-d` | `inputs/content-master/data` | Path to bio.tools entry folders |
| `--output`, `-o` | `outputs/json/biotools_publications.json` | Path for generated JSON file |
| `--workers`, `-w` | `16` | Thread pool workers for file parsing |
| `--skip-citations` | `False` | Skip BIP! API citation queries |
| `--reset-cache` | `False` | Overwrite BIP! cache and query fresh |
| `--refresh-citations` | `False` | Force refresh of citation scores for existing items |
| `--skip-openaire` | `False` | Skip OpenAIRE date querying (use bio.tools dates only) |
| `--reset-openaire-cache`| `False` | Overwrite OpenAIRE cache and query fresh |
| `--openaire-token` | `None` / `$OPENAIRE_API_TOKEN` | OpenAIRE API Personal Access Token |
| `--openaire-upgrade-biotools` | `False` | Query OpenAIRE to upgrade tools currently using bio.tools dates |
| `--update` | `False` | Enable non-destructive update mode on existing dataset |
| `--update-sources` | `all` | Sources to update: `biotools`, `bip`, `openaire`, or `all` |
| `--compact` | `False` | Output compact single-line JSON |

---

## Script 2: `identify_elixir_tools.py`

### Supported Methods
1. **`--method csv` (Recommended)**: Parses `inputs/ELIXIR-tools_with bio.csv` (fast, offline, reproducible).
2. **`--method scrape`**: Live scrapes the ELIXIR Software Tools catalog (`https://elixir-europe.org/services/tag/software-tools`).
3. **`--method scrape-all`**: Live scrapes all ELIXIR services including databases and platforms (`https://elixir-europe.org/services/list`).

### Common Usage Examples

```bash
# Method 1: CSV identification (default recommended)
python3 identify_elixir_tools.py --method csv

# Method 2: Web scraping with polite rate limiting
python3 identify_elixir_tools.py --method scrape --delay 0.5

# Save extracted ELIXIR catalog as standalone JSON
python3 identify_elixir_tools.py --method scrape-all --save-elixir-list "outputs/json/elixir_all_services.json"
```

### CLI Options

| Option | Default | Description |
| :--- | :--- | :--- |
| `--method`, `-m` | `scrape` | Identification method: `csv`, `scrape`, or `scrape-all` |
| `--csv-file` | `inputs/ELIXIR-tools_with bio.csv` | Path to input CSV (when `--method csv`) |
| `--csv-column` | `field_bio_tools_link` | Header containing bio.tools links |
| `--delay` | `0.5` | Delay in seconds between scraping requests |
| `--input-json`, `-i` | `outputs/json/biotools_publications.json` | Path to extracted bio.tools JSON |
| `--output-json`, `-o`| `outputs/json/biotools_publications_elixir_incl.json` | Path for enriched output JSON |
| `--flag-name` | `is_elixir` | Boolean flag field name |
| `--save-elixir-list` | `None` | Optional path to export extracted ELIXIR catalog |

---

## Script 3: `analyse_elixir_citations.py`

### Analysis Scope
Evaluates tools across **three independent publication scopes**:
1. **Total Citations**: All publications linked to the tool.
2. **Primary Citations**: Publications flagged as `"Primary"`.
3. **PMO Citations**: Publications flagged as `"Primary"`, `"Method"`, or `"Other"`.

For each scope, tools are classified into **three impact categories**:
- **Top 1%** (99th percentile)
- **Top 10%** (90th percentile)
- **Average** (Remaining tools)

### Outputs Generated
- **6 Ranked CSVs** (`outputs/csv/`): Global bio.tools rankings and ELIXIR-only rankings across Total, Primary, and PMO citations.
- **14 Visualizations** (`outputs/plots/`, both SVG and PNG):
  - Citations per year histograms (Total, Primary, PMO).
  - Tools by first publication year histograms (Total, Primary, PMO).
  - Category distribution pie charts (All bio.tools vs. ELIXIR across all 3 scopes).
  - Top 30 side-by-side comparative ranking panels with ELIXIR badges.

### Common Usage Examples

```bash
# Standard analysis (generates 6 CSVs + 14 SVG plots + 14 PNG plots)
python3 analyse_elixir_citations.py

# SVG-only mode (skip PNG rasterization)
python3 analyse_elixir_citations.py --no-png

# Custom plot starting year and top tools count
python3 analyse_elixir_citations.py --plot-start-year 1995 --top-tools-n 20
```

### Key CLI Options

| Option | Default | Description |
| :--- | :--- | :--- |
| `--input-json`, `-i` | `outputs/json/biotools_publications_elixir_incl.json` | Path to enriched dataset |
| `--export-all-csv` | `outputs/csv/all_biotools_ranked.csv` | Ranked CSV of all tools (Total citations) |
| `--export-elixir-csv` | `outputs/csv/elixir_tools_ranked.csv` | Ranked CSV of ELIXIR tools (Total citations) |
| `--export-all-primary-csv` | `outputs/csv/all_biotools_primary_ranked.csv` | Ranked CSV of all tools (Primary citations) |
| `--export-elixir-primary-csv` | `outputs/csv/elixir_tools_primary_ranked.csv` | Ranked CSV of ELIXIR tools (Primary citations) |
| `--export-all-pmo-csv` | `outputs/csv/all_biotools_pmo_ranked.csv` | Ranked CSV of all tools (PMO citations) |
| `--export-elixir-pmo-csv` | `outputs/csv/elixir_tools_pmo_ranked.csv` | Ranked CSV of ELIXIR tools (PMO citations) |
| `--top-tools-n` | `30` | Number of tools in comparative ranking figures |
| `--plot-start-year` | `1990` | Minimum publication year on histogram X-axis |
| `--no-png` | `False` | Disable automatic PNG export alongside SVGs |

---

## Output Schema

Each entry in `outputs/json/biotools_publications_elixir_incl.json` contains:

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
        { "term": "Deposition", "uri": "http://edamontology.org/operation_3431" }
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
  "total_citations": 12,
  "primary_citations": 12,
  "pmo_citations": 12,
  "publications": [
    {
      "id": "10.1101/2024.03.08.584032",
      "type": "doi",
      "publication_type": ["Primary"],
      "is_primary": true,
      "is_pmo": true,
      "date": "2024-03-08",
      "date_source": "openaire",
      "citations": 12,
      "doi": "10.1101/2024.03.08.584032"
    }
  ]
}
```

---

## Caching & Reproduction

- **`cache/bip_cache.json`**: Caches publication identifier -> citation count mappings.
- **`cache/openaire_cache.json`**: Caches publication identifier -> resolved publication date mappings.
- To force an end-to-end fresh query bypassing local caches:
  ```bash
  python3 extract_biotools_publications.py --reset-cache --reset-openaire-cache
  ```
