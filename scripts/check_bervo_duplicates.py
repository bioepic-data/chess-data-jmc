#!/usr/bin/env python3
import csv
from pathlib import Path
from collections import Counter

base_dir = Path('/h/jmc/data/bioepic/chess')
dd_files = sorted(base_dir.glob('*/dd_bervo.csv'))

print("=" * 70)
print("CHECKING FOR DUPLICATE BERVO COMBINATIONS")
print("=" * 70)

total_dups = 0

for dd_file in dd_files:
    print(f"\n{dd_file.parent.name}:")
    
    with open(dd_file, 'r') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)
    
    # Find column name field
    col_field = None
    for field in fieldnames:
        if 'column' in field.lower() and 'name' in field.lower():
            col_field = field
            break
    if not col_field:
        col_field = fieldnames[0]
    
    # Count BERVO combinations
    combinations = []
    col_to_combo = {}
    
    for r in rows:
        combo = r.get('BERVO Combination', '')
        col_name = r.get(col_field, '')
        if combo and combo != 'unnecessary?':
            combinations.append(combo)
            if combo not in col_to_combo:
                col_to_combo[combo] = []
            col_to_combo[combo].append(col_name)
    
    combo_counts = Counter(combinations)
    duplicates = {combo: count for combo, count in combo_counts.items() if count > 1}
    
    if duplicates:
        print(f"  ⚠ Found {len(duplicates)} duplicate combinations:")
        total_dups += sum(count - 1 for count in duplicates.values())
        for combo, count in sorted(duplicates.items(), key=lambda x: -x[1])[:10]:
            print(f"    '{combo}' appears {count} times")
            cols = col_to_combo[combo]
            print(f"      Columns: {', '.join(cols[:5])}" + (' ...' if len(cols) > 5 else ''))
    else:
        print(f"  ✓ No duplicates found")
    
    total_non_empty = len(combinations)
    print(f"  Total unique needed: {len(set(combinations))} / {total_non_empty} mapped")

print(f"\n{'=' * 70}")
print(f"TOTAL DUPLICATE INSTANCES: {total_dups}")
print(f"{'=' * 70}")

