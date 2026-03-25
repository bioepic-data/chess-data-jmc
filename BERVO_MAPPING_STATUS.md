# BERVO Mapping Status Report

## Summary

Successfully reduced duplicate BERVO combinations from **118 to 56** (53% reduction).

### Status by Dataset

| Dataset | Status | Duplicates Remaining |
|---------|--------|---------------------|
| geophysical_survey | ✅ COMPLETE | 0 |
| vegetation_soil_spectra | ✅ COMPLETE | 0 |
| leaf_area_index | ⚠️ NEEDS REVIEW | 20 |
| vegetation_attributes_photos | ⚠️ NEEDS REVIEW | 13 |
| soil_metagenomes | ⚠️ NEEDS REVIEW | 23 |

**Total requiring manual review: 56 column definitions**

## Fixed Issues

### Clear Cases Resolved
1. ✅ Date_Start / Date_End now have Context=Start and Context=End
2. ✅ Species/taxonomy fields properly identified as "Taxon"
3. ✅ Boolean/flag fields identified with "Quality control" + specifying what they're for
4. ✅ Standard error fields distinguished by method (2200, Welles and Norman, Lang)
5. ✅ LAI measurements distinguished by processing type and method
6. ✅ Site/location metadata properly categorized

## Remaining Issues Requiring Manual Review

See **BERVO_DUPLICATES_FOR_REVIEW.csv** for detailed list.

### Main Problem Categories

**1. Leaf Area Index (20 duplicates)**
- Issue: Misclassified measurements
  - L_2200, Le_2200, L_FV2200, Le_FV2200 incorrectly mapped to "Clumping factor"
  - Should be "Leaf area index" with software/processing qualifiers
- Data records (A_Record, B_Record, K_Record) all mapped to same combination
  - Need: type = A record vs B record vs K record
- Clumping factors (ACF_2200, ACF_WN) need distinguishing

**2. Vegetation Attributes (13 duplicates)**
- 11 "Taxon" fields need distinguishing:
  - Location_Type, Cover_Type, Vegetation_Species, Taxon_family, etc.
  - Need qualifiers like: rank = family, rank = species, rank = genus
  - Or: context = location classification, context = vegetation type

**3. Soil Metagenomes (23 duplicates)**
- Temperature fields (3): need context qualifiers
- Date fields (6): need context (collection vs storage vs release)
- Taxon fields (4): need rank or context
- Site fields: need attribute qualifiers

## Next Steps

1. **Manual Review**: Fill in "Proposed_Combination" column in `BERVO_DUPLICATES_FOR_REVIEW.csv`
2. **Apply Changes**: Script will apply your proposed combinations
3. **Final Validation**: Verify all combinations are unique

## How to Fill Review File

For each row, provide a unique BERVO Combination in the format:
```
Main Concept, modifier1 = value, modifier2 = value
```

### Examples:

**For LAI measurements:**
- L_2200 → `Leaf area index, method = 2200, processing = clumping corrected`
- Le_2200 → `Leaf area index, method = 2200, processing = effective`
- L_FV2200 → `Leaf area index, method = 2200, software = FV2200, processing = clumping corrected`

**For data records:**
- A_Record → `Data record, type = A record`
- B_Record → `Data record, type = B record`
- K_Record → `Data record, type = K record`

**For taxonomy:**
- Taxon_family → `Taxon, rank = family`
- Taxon_genus → `Taxon, rank = genus`
- Vegetation_Species → `Taxon, rank = species, context = vegetation`

**For dates:**
- collection_date → `Date, Context=Collection`
- release_date → `Date, Context=Release`
- sample_storage_date → `Date, Context=Storage`

All modifiers (method, processing, software, type, rank, Context, etc.) should ideally be BERVO concepts where possible.

