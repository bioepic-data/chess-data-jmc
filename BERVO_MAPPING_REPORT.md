# BERVO Data Dictionary Mapping Report

Generated: $(date)

## Summary

All data dictionaries (dd.csv files) in the CHESS datasets have been mapped to BERVO (Biological and Environmental Research Variable Ontology) terms.

### Overall Statistics

- **Total datasets processed**: 5
- **Total columns mapped**: 237 / 376
- **Overall mapping rate**: 63.0%

### Mapping Results by Dataset

| Dataset | Columns Mapped | Total Columns | Mapping Rate |
|---------|----------------|---------------|--------------|
| Geophysical Survey | 23 | 24 | 95.8% |
| Leaf Area Index | 58 | 91 | 63.7% |
| Soil Metagenomes | 83 | 141 | 58.9% |
| Vegetation Attributes Photos | 45 | 62 | 72.6% |
| Vegetation Soil Spectra | 28 | 58 | 48.3% |

## Mapping Methodology

The mapping process:

1. **Identified main concepts**: Primary measurement or observation being recorded
2. **Extracted qualifiers**: Context such as depth, replicate number, statistical treatment
3. **Built BERVO combinations**: Main concept + qualifiers using actual BERVO term names
4. **Assigned BERVO IDs**: Primary concept's BERVO identifier

### BERVO Combination Format

Combinations follow the pattern: `Main Concept, Qualifier1 = Value, Qualifier2 = Value`

Examples:
- `Temperature, Depth = 20 (cm), replicate = 1` → bervo:BERVO_8000133
- `Volumetric Water Content, Depth = 20 (cm), statistic = average` → bervo:BERVO_0001743
- `Latitude` → bervo:BERVO_8000395
- `Date, Context=Collection` → bervo:BERVO_8000239

### Common Qualifiers

- **Depth**: Physical depth of measurement (e.g., "Depth = 20 (cm)")
- **Replicate**: Replicate measurement number (e.g., "replicate = 1")
- **Statistic**: Statistical treatment (e.g., "statistic = average", "statistic = standard error")
- **Context**: Temporal or experimental context (e.g., "Context=Start", "Context=Collection")

## Files Created

Each dataset directory now contains:
- `dd.csv` - Original data dictionary
- `dd_bervo.csv` - BERVO-mapped version with two new columns:
  - **BERVO Combination**: Human-readable combination of BERVO concepts
  - **BERVO Term**: BERVO ID for the primary concept

### File Locations

```
geophysical_survey/dd_bervo.csv
leaf_area_index/dd_bervo.csv
soil_metagenomes/dd_bervo.csv
vegetation_attributes_photos/dd_bervo.csv
vegetation_soil_spectra/dd_bervo.csv
```

## Metadata Fields

Administrative/metadata fields marked as "unnecessary?" include:
- file_name, file_description
- standard, file_version
- data_orientation, header_rows
- column_or_row_name, unit, definition, data_type
- missing_value_code, contact

These are structural metadata rather than actual measurements.

## BERVO Ontology

**Source**: https://github.com/bioepic-data/bervo
**Local copy**: bervo/ directory
**Total terms**: 4,616 concepts

The BERVO ontology provides standardized terminology for:
- Biogeochemical research variables
- Ecosystem measurements
- Environmental monitoring
- DOE Environmental System Science (ESS) research

## Notes

- Fields with "suggested" as BERVO Term indicate a reasonable mapping was created but the exact concept may need refinement or addition to BERVO
- Empty BERVO Combination/Term fields indicate no suitable mapping was found
- Manual review recommended for domain-specific or highly technical measurements

---

*Automated mapping performed using BERVO ontology version 2025-12-22*

## Example Mappings

### Geographic Coordinates
- `Latitude` → bervo:BERVO_8000395
- `Longitude` → bervo:BERVO_8000396
- `Easting` → bervo:BERVO_8000440
- `Northing` → bervo:BERVO_8000441

### Leaf Area Index Measurements
- `L_2200` (Leaf area index) → bervo:BERVO_8000164
- `Le_2200` (Effective leaf area index) → bervo:BERVO_8000164
- `ACF_2200` (Apparent clumping factor) → bervo:BERVO_8000164

### Environmental Measurements
- `Temperature, Depth = 20 (cm), replicate = 1` → bervo:BERVO_8000133
- `Temperature, Depth = 20 (cm), statistic = average` → bervo:BERVO_8000133
- `Volumetric Water Content, Depth = 20 (cm), replicate = 2` → bervo:BERVO_0001743

### Dates and Temporal Data
- `Date, Context=Collection` → bervo:BERVO_8000239
- `Date, Context=Start` → bervo:BERVO_8000239
- `Date, Context=End` → bervo:BERVO_8000239

### Site Information
- `Site` → bervo:BERVO_8000514 (Environmental sample location)

