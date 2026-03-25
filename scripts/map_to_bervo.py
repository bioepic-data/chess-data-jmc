#!/usr/bin/env python3
import json
import csv
import re
from pathlib import Path
from collections import defaultdict

# Load BERVO terms
with open('/tmp/bervo_terms.json', 'r') as f:
    bervo_terms = json.load(f)

name_to_id = {k.lower(): v for k, v in bervo_terms.items() if not k.startswith('bervo:')}
id_to_name = {id_val: name for name, id_val in bervo_terms.items() if not name.startswith('bervo:')}

METADATA_FIELDS = {
    'file_name', 'file_description', 'standard', 'file_version', 'data_orientation',
    'header_rows', 'column_or_row_name_position', 'column_or_row_name', 'unit',
    'definition', 'column_or_row_long_name', 'data_type', 'missing_value_code',
    'missing_value_codes', 'contact'
}

def find_bervo_concept(search_terms):
    """Find BERVO concept"""
    if isinstance(search_terms, str):
        search_terms = [search_terms]
    
    for term in search_terms:
        term_lower = term.lower()
        if term_lower in name_to_id:
            return name_to_id[term_lower], term_lower
    
    for term in search_terms:
        term_lower = term.lower()
        matches = [(name, len(name)) for name in name_to_id.keys() 
                  if term_lower in name or name in term_lower]
        if matches:
            matches.sort(key=lambda x: x[1])
            best_match = matches[0][0]
            return name_to_id[best_match], best_match
    
    return None, None

def is_boolean_or_flag_field(column_name, definition):
    """Check if this is a boolean flag or QC field rather than actual measurement"""
    definition_lower = definition.lower()
    
    # Boolean indicators
    if 'whether' in definition_lower or 'true' in definition_lower or 'false' in definition_lower:
        return True
    
    # QC/Flag indicators
    if any(word in column_name.lower() for word in ['flag', 'qc', 'requires', 'contains']):
        return True
    
    # Controlled vocabulary / codes
    if 'code' in definition_lower and 'identifier' in definition_lower:
        return False  # Identifiers are not flags
    if 'code' in column_name.lower():
        return True
    
    return False

def is_species_or_taxonomy(column_name, definition):
    """Check if this is about species/taxonomy"""
    definition_lower = definition.lower()
    col_lower = column_name.lower()
    
    if 'species' in col_lower or 'taxon' in col_lower:
        return True
    
    if any(word in definition_lower for word in ['species code', 'taxonomic', 'usda', 'flora']):
        return True
    
    return False

def is_location_or_site_info(column_name, definition):
    """Check if this is site/location metadata"""
    definition_lower = definition.lower()
    col_lower = column_name.lower()
    
    # Location type, land cover, vegetation type
    if 'type' in col_lower and any(word in definition_lower for word in ['classification', 'land cover', 'vegetation']):
        return True
    
    # Site identifier or area code
    if ('site' in col_lower or 'area' in col_lower) and 'identifier' in definition_lower:
        return True
    
    return False

def map_column_improved(column_name, unit, definition, data_type):
    """Improved mapping with better edge case handling"""
    
    # Metadata check
    if column_name.lower() in METADATA_FIELDS:
        return "unnecessary?", ""
    
    if not definition or len(definition.strip()) < 5:
        return "", ""
    
    definition_lower = definition.lower()
    col_lower = column_name.lower()
    
    # Determine main concept
    main_concept = None
    main_id = None
    qualifiers = []
    
    # === SPECIAL CASES FIRST ===
    
    # Boolean/Flag fields
    if is_boolean_or_flag_field(column_name, definition):
        # Determine what it's a flag FOR
        if 'lai' in definition_lower or 'leaf area' in definition_lower:
            main_concept = "Quality control"
            main_id, _ = find_bervo_concept(['quality control', 'quality'])
            qualifiers.append("for = Leaf area index")
        elif 'scattering' in definition_lower or 'correction' in definition_lower:
            main_concept = "Quality control"
            main_id, _ = find_bervo_concept(['quality control'])
            qualifiers.append("for = scattering correction")
        elif 'gap fraction' in definition_lower:
            main_concept = "Quality control"
            main_id, _ = find_bervo_concept(['quality control'])
            qualifiers.append("for = Gap fraction")
        else:
            main_concept = "Boolean indicator"
            main_id = "suggested"
        
        # Add specific field purpose from column name
        if 'requires' in col_lower:
            qualifiers.append("type = requirement indicator")
        elif 'contains' in col_lower:
            qualifiers.append("type = containment indicator")
    
    # Species/Taxonomy fields
    elif is_species_or_taxonomy(column_name, definition):
        main_concept = "Taxon"
        main_id, _ = find_bervo_concept(['taxon', 'species'])
        
        if 'tree' in definition_lower or 'tree' in col_lower:
            qualifiers.append("organism = tree")
        if 'code' in col_lower:
            qualifiers.append("format = code")
    
    # Site/Location metadata
    elif is_location_or_site_info(column_name, definition):
        main_concept = "Site"
        main_id, _ = find_bervo_concept(['site', 'environmental sample location'])
        
        if 'type' in col_lower:
            qualifiers.append("attribute = type")
        elif 'identifier' in definition_lower or 'code' in col_lower:
            qualifiers.append("attribute = identifier")
        elif 'area' in col_lower:
            qualifiers.append("attribute = area code")
    
    # Date fields - FIXED to properly detect Start/End/Collection
    elif 'date' in definition_lower:
        main_concept = "Date"
        main_id, _ = find_bervo_concept(['date'])
        
        # Check column name AND definition for context
        if 'start' in col_lower or 'start' in definition_lower or 'begin' in definition_lower:
            qualifiers.append("Context=Start")
        elif 'end' in col_lower or 'end' in definition_lower:
            qualifiers.append("Context=End")
        elif 'collection' in col_lower or 'collection' in definition_lower:
            qualifiers.append("Context=Collection")
    
    # === MEASUREMENT TYPES ===
    
    # Standard error - is a statistic about another measurement
    elif 'standard error' in definition_lower or col_lower.startswith('sel_'):
        main_concept = "Standard error"
        main_id, _ = find_bervo_concept(['standard error', 'error'])
        
        # What is it of?
        if 'leaf area index' in definition_lower:
            qualifiers.append("of = Leaf area index")
        
        # What method?
        if '2200' in col_lower or '2200' in definition_lower:
            qualifiers.append("method = 2200")
        elif '_wn' in col_lower or 'welles' in definition_lower:
            qualifiers.append("method = Welles and Norman")
        elif 'lang' in col_lower or 'lang' in definition_lower:
            qualifiers.append("method = Lang")
    
    # Clumping factor
    elif 'clumping factor' in definition_lower or col_lower.startswith('acf'):
        main_concept = "Clumping factor"
        main_id = "suggested"
        
        # What method?
        if '2200' in col_lower:
            qualifiers.append("method = 2200")
        elif '_wn' in col_lower or 'welles' in definition_lower:
            qualifiers.append("method = Welles and Norman")
        elif 'scatcor' in col_lower or 'scatter' in definition_lower:
            qualifiers.append("method = scatter correction")
        
        # Per-ring vs overall
        if 'for each ring' in definition_lower or 'each ring' in definition_lower:
            qualifiers.append("resolution = per ring")
    
    # Gap fraction
    elif 'gap fraction' in definition_lower:
        main_concept = "Gap fraction"
        main_id, _ = find_bervo_concept(['gap fraction'])
        
        if 'each ring' in definition_lower or 'for each' in definition_lower:
            qualifiers.append("resolution = per ring")
        if 'mean' in definition_lower or 'average' in definition_lower:
            qualifiers.append("statistic = average")
    
    # Leaf Area Index
    elif 'leaf area index' in definition_lower or col_lower.startswith('l_') or col_lower.startswith('le_'):
        main_concept = "Leaf area index"
        main_id, _ = find_bervo_concept(['leaf area index'])
        
        # Processing type
        if 'effective' in definition_lower and 'random' in definition_lower:
            qualifiers.append("processing = effective")
        elif 'scatter-corrected' in definition_lower or 'scatter corrected' in definition_lower:
            qualifiers.append("processing = scatter corrected")
        elif 'clumping-corrected' in definition_lower or 'corrected for foliage clumping' in definition_lower:
            qualifiers.append("processing = clumping corrected")
        
        # Method/algorithm
        if '2200' in col_lower and 'fv' not in col_lower and 'rlai' not in col_lower:
            qualifiers.append("method = 2200")
        elif 'fv2200' in col_lower or 'fv2200' in definition_lower:
            qualifiers.append("method = FV2200")
        elif 'rlai' in col_lower or 'rlai' in definition_lower:
            qualifiers.append("method = rlai")
        elif '_wn' in col_lower or 'welles and norman' in definition_lower:
            qualifiers.append("method = Welles and Norman")
        elif 'lang' in col_lower or 'lang method' in definition_lower:
            qualifiers.append("method = Lang")
        elif 'ellip' in col_lower or 'ellipsoidal' in definition_lower:
            qualifiers.append("method = ellipsoidal")
        elif 'scatcor' in col_lower:
            qualifiers.append("method = scatter correction")
        
        # Per-measurement vs summary
        if 'for each measurement' in definition_lower or col_lower.endswith('j'):
            qualifiers.append("resolution = per measurement")
    
    # Temperature
    elif 'temperature' in definition_lower or 'temp' in col_lower:
        main_concept = "Temperature"
        main_id, _ = find_bervo_concept(['temperature'])
    
    # Water content
    elif 'water content' in definition_lower or 'vwc' in col_lower:
        main_concept = "Volumetric water content"
        main_id, _ = find_bervo_concept(['volumetric water content', 'water content'])
    
    # Coordinates
    elif 'latitude' in definition_lower:
        main_concept = "Latitude"
        main_id, _ = find_bervo_concept(['latitude'])
        
        if 'method' in definition_lower:
            qualifiers.append("attribute = measurement method")
    elif 'longitude' in definition_lower:
        main_concept = "Longitude"
        main_id, _ = find_bervo_concept(['longitude'])
    
    # Record identifiers
    elif 'record' in col_lower and 'identifier' in definition_lower:
        main_concept = "Data record"
        main_id = "suggested"
        
        if 'a record' in definition_lower or col_lower == 'a_record':
            qualifiers.append("type = above-canopy reference")
        elif 'b record' in definition_lower or col_lower == 'b_record':
            qualifiers.append("type = below-canopy")
        elif 'k record' in definition_lower or col_lower == 'k_record':
            qualifiers.append("type = scattering correction")
    
    # Corner/position
    elif 'corner' in col_lower and 'position' in definition_lower:
        main_concept = "Measurement position"
        main_id = "suggested"
        qualifiers.append("type = plot corner")
    
    if not main_concept:
        return "", ""
    
    # === COMMON QUALIFIERS ===
    
    # Depth (if not already added)
    depth_match = re.search(r'(\d+)\s*cm\s+depth', definition, re.IGNORECASE)
    if depth_match and not any('Depth' in q for q in qualifiers):
        qualifiers.append(f"Depth = {depth_match.group(1)} (cm)")
    
    # Replicate (if not already added)
    if not any('replicate' in q for q in qualifiers):
        rep_patterns = [
            (r'first\s+(reading|measurement)', '1'),
            (r'second\s+(reading|measurement)', '2'),
            (r'_1(?:\s|$|,)', '1'),
            (r'_2(?:\s|$|,)', '2')
        ]
        for pattern, rep_num in rep_patterns:
            if re.search(pattern, definition_lower) or re.search(pattern, col_lower):
                qualifiers.append(f"replicate = {rep_num}")
                break
    
    # Statistics (if not already added)
    if not any('statistic' in q for q in qualifiers):
        if 'average' in definition_lower or 'mean' in definition_lower or 'avg' in col_lower:
            qualifiers.append("statistic = average")
    
    # Build combination
    if qualifiers:
        combination = f"{main_concept}, " + ", ".join(qualifiers)
    else:
        combination = main_concept
    
    return combination, main_id if main_id else "suggested"

# Process files
base_dir = Path('/h/jmc/data/bioepic/chess')
dd_files = sorted(base_dir.glob('*/dd.csv'))

print("Fixing clear cases and improving mappings...")
print("=" * 70)

all_duplicates = []

for dd_file in dd_files:
    print(f"\nProcessing: {dd_file.parent.name}")
    
    with open(dd_file, 'r') as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames)
        rows = list(reader)
    
    # Find column name field
    col_field = None
    for field in fieldnames:
        if 'column' in field.lower() and 'name' in field.lower():
            col_field = field
            break
    if not col_field:
        col_field = fieldnames[0]
    
    # Process rows
    output_rows = []
    combinations_seen = defaultdict(list)
    
    for row in rows:
        col_name = row.get(col_field, '')
        unit = row.get('unit') or row.get('Unit') or 'N/A'
        definition = row.get('definition') or row.get('Definition') or ''
        data_type = row.get('data_type') or row.get('Data_Type') or ''
        
        combination, term_id = map_column_improved(col_name, unit, definition, data_type)
        
        if combination and combination != 'unnecessary?':
            combinations_seen[combination].append({
                'dataset': dd_file.parent.name,
                'column': col_name,
                'definition': definition
            })
        
        new_row = {
            col_field: col_name,
            'BERVO Combination': combination,
            'BERVO Term': term_id
        }
        for field in fieldnames:
            if field != col_field:
                new_row[field] = row[field]
        
        output_rows.append(new_row)
    
    # Check for duplicates
    duplicates = {combo: cols for combo, cols in combinations_seen.items() if len(cols) > 1}
    
    if duplicates:
        print(f"  ⚠ Still {len(duplicates)} duplicate combinations")
        for combo, cols in duplicates.items():
            for col_info in cols:
                all_duplicates.append({
                    'Dataset': col_info['dataset'],
                    'Column_Name': col_info['column'],
                    'Current_Combination': combo,
                    'Definition': col_info['definition'],
                    'Proposed_Combination': '',
                    'Notes': ''
                })
    else:
        print(f"  ✓ All combinations unique!")
    
    # Write output
    new_fieldnames = [col_field, 'BERVO Combination', 'BERVO Term'] + \
                     [f for f in fieldnames if f != col_field]
    
    output_path = dd_file.parent / 'dd_bervo.csv'
    with open(output_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=new_fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)
    
    mapped = len([r for r in output_rows if r['BERVO Combination']])
    print(f"  Mapped: {mapped} / {len(output_rows)}")

# Write duplicates review file
if all_duplicates:
    review_file = Path('/h/jmc/data/bioepic/chess/BERVO_DUPLICATES_FOR_REVIEW.csv')
    with open(review_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'Dataset', 'Column_Name', 'Current_Combination', 'Definition',
            'Proposed_Combination', 'Notes'
        ])
        writer.writeheader()
        writer.writerows(all_duplicates)
    
    print(f"\n{'=' * 70}")
    print(f"Remaining duplicates: {len(all_duplicates)} entries")
    print(f"Review file: BERVO_DUPLICATES_FOR_REVIEW.csv")
    print(f"{'=' * 70}")
else:
    print(f"\n{'=' * 70}")
    print("✓ All combinations are now unique!")
    print(f"{'=' * 70}")

print("\nDone!")

