# CHESS Data Scripts

This directory contains scripts for downloading and processing CHESS (Colorado Headwaters Ecological Spectroscopy Study) data.

## Scripts

### 1. download_chess_data.sh

**Purpose**: Downloads all CHESS datasets from ESS-DIVE repository.

**Features**:
- Downloads data for all 13 CHESS datasets
- Skips files larger than 1GB (creates placeholder files instead)
- Creates detailed download logs for each dataset
- Generates README.md files with dataset citations

**Usage**:
```bash
./download_chess_data.sh
```

**Output**:
- Data files in each dataset directory (e.g., `leaf_area_index/`, `soil_metagenomes/`)
- `DOWNLOAD_LOG.md` in each directory listing all files
- Placeholder files (`.placeholder` extension) for files >1GB

**Requirements**:
- wget
- unzip
- Internet connection

---

### 2. parse_bervo_ontology.py

**Purpose**: Parses the BERVO ontology file and creates a JSON lookup dictionary.

**Features**:
- Extracts all BERVO terms from the OBO format ontology
- Creates bidirectional mapping (name ↔ ID)
- Outputs JSON file for fast lookups

**Usage**:
```bash
python3 parse_bervo_ontology.py
```

**Input**:
- `ontologies/bervo/bervo.obo` - BERVO ontology in OBO format

**Output**:
- `/tmp/bervo_terms.json` - JSON dictionary with 4,616 BERVO concepts

**Example output**:
```json
{
  "temperature": "bervo:BERVO_8000133",
  "bervo:BERVO_8000133": "temperature",
  "leaf area index": "bervo:BERVO_8000164",
  ...
}
```

---

### 3. map_to_bervo.py

**Purpose**: Maps data dictionary columns to BERVO (Biological and Environmental Research Variable Ontology) terms.

**Features**:
- Automatically maps measurements to BERVO concepts
- Extracts qualifiers (depth, replicate, method, statistics, context)
- Handles metadata fields (marks as "unnecessary?")
- Creates unique combinations for each column
- Identifies ambiguous cases for manual review

**Usage**:
```bash
# First, parse the BERVO ontology
python3 parse_bervo_ontology.py

# Then run the mapping
python3 map_to_bervo.py
```

**Input**:
- `/tmp/bervo_terms.json` - BERVO term dictionary (from parse_bervo_ontology.py)
- `*/dd.csv` - Data dictionary files in each dataset directory

**Output**:
- `*/dd_bervo.csv` - Enhanced data dictionaries with BERVO mappings
- `BERVO_DUPLICATES_FOR_REVIEW.csv` - Cases requiring manual review

**BERVO Combination Format**:
```
Main Concept, modifier1 = value, modifier2 = value
```

**Examples**:
- `Temperature, Depth = 20 (cm), replicate = 1`
- `Leaf area index, method = 2200, processing = clumping corrected`
- `Date, Context=Collection`

---

### 4. check_bervo_duplicates.py

**Purpose**: Validates BERVO mappings by checking for duplicate combinations.

**Features**:
- Identifies non-unique BERVO combinations
- Reports which columns share the same combination
- Provides statistics on mapping completeness

**Usage**:
```bash
python3 check_bervo_duplicates.py
```

**Input**:
- `*/dd_bervo.csv` - BERVO-mapped data dictionaries

**Output**:
- Console report showing:
  - Number of duplicate combinations per dataset
  - Which columns share combinations
  - Mapping statistics

**Example output**:
```
geophysical_survey:
  ✓ No duplicates found
  Total unique combinations: 13 / 13

leaf_area_index:
  ⚠ Found 6 duplicate combinations:
    'Leaf area index' appears 14 times
      Columns: L_2200, Le_2200, L_WN, Le_WN...
```

---

## Workflow

### Initial Setup (First Time)

1. **Download CHESS data**:
   ```bash
   ./download_chess_data.sh
   ```

2. **Download BERVO ontology** (if not already done):
   ```bash
   # Should already be in bervo/ directory
   ls ontologies/bervo/bervo.obo
   ```

3. **Parse BERVO ontology**:
   ```bash
   python3 parse_bervo_ontology.py
   ```

### Map Data Dictionaries to BERVO

4. **Run BERVO mapping**:
   ```bash
   python3 map_to_bervo.py
   ```

5. **Check for duplicates**:
   ```bash
   python3 check_bervo_duplicates.py
   ```

6. **Review and fix duplicates** (if any):
   - Edit `BERVO_DUPLICATES_FOR_REVIEW.csv`
   - Fill in "Proposed_Combination" column
   - Re-run mapping script after fixes

### Validation

7. **Final validation**:
   ```bash
   python3 check_bervo_duplicates.py
   # Should show ✓ No duplicates for all datasets
   ```

---

## Dependencies

**Python Scripts**:
- Python 3.6+
- Standard library only (csv, json, re, pathlib, collections)

**Shell Scripts**:
- bash
- wget
- unzip

---

## File Structure

After running all scripts, your directory structure will be:
```
chess/
├── scripts/
│   ├── README.md (this file)
│   ├── download_chess_data.sh
│   ├── parse_bervo_ontology.py
│   ├── map_to_bervo.py
│   └── check_bervo_duplicates.py
├── bervo/
│   ├── bervo.obo
│   ├── bervo.owl
│   ├── bervo.json
│   └── README.md
├── leaf_area_index/
│   ├── dd.csv
│   ├── dd_bervo.csv
│   ├── README.md
│   ├── DOWNLOAD_LOG.md
│   └── [data files]
├── soil_metagenomes/
│   ├── dd.csv
│   ├── dd_bervo.csv
│   └── [data files]
└── [other datasets...]
```

---

## Notes

- All scripts are idempotent (safe to run multiple times)
- Download script skips already-downloaded files
- Mapping script overwrites previous mappings
- Review file is regenerated each time if duplicates exist

---

## Troubleshooting

**"No such file or directory: bervo.obo"**
- Ensure BERVO ontology is downloaded to `ontologies/bervo/bervo.obo`
- Run from the correct directory (`/h/jmc/data/bioepic/chess`)

**"File not found: /tmp/bervo_terms.json"**
- Run `parse_bervo_ontology.py` first before `map_to_bervo.py`

**"Still have duplicate combinations"**
- This is expected! Review `BERVO_DUPLICATES_FOR_REVIEW.csv`
- Some cases require domain knowledge for disambiguation
- See `BERVO_MAPPING_STATUS.md` for guidance

---

## Version History

- **2026-03-20**: Initial version
  - Download script with 1GB size limit
  - BERVO mapping with automatic qualifier extraction
  - Duplicate detection and review workflow
  - Successfully mapped 63% of columns automatically
  - Reduced duplicates from 118 to 56 (53% reduction)

---

## Contact

For questions about BERVO mapping or script usage, see:
- BERVO ontology: https://github.com/bioepic-data/bervo
- ESS-DIVE: https://ess-dive.lbl.gov/
- CHESS data portal: https://data.ess-dive.lbl.gov/portals/chess
