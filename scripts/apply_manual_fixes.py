#!/usr/bin/env python3
"""
Apply manual BERVO combination fixes from BERVO_DUPLICATES_FOR_REVIEW.csv
Run this after filling in the "Proposed_Combination" column.
"""
import csv
from pathlib import Path

# Read the review file
review_file = Path('../BERVO_DUPLICATES_FOR_REVIEW.csv')

if not review_file.exists():
    print("Error: BERVO_DUPLICATES_FOR_REVIEW.csv not found")
    print("Run map_to_bervo.py first to generate the review file.")
    exit(1)

# Load manual fixes
manual_fixes = {}
with open(review_file, 'r') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if row['Proposed_Combination'].strip():
            dataset = row['Dataset']
            column = row['Column_Name']
            new_combo = row['Proposed_Combination']
            
            if dataset not in manual_fixes:
                manual_fixes[dataset] = {}
            manual_fixes[dataset][column] = new_combo

if not manual_fixes:
    print("No manual fixes found in BERVO_DUPLICATES_FOR_REVIEW.csv")
    print("Please fill in the 'Proposed_Combination' column first.")
    exit(0)

print(f"Found {sum(len(v) for v in manual_fixes.values())} manual fixes")
print("=" * 70)

# Apply fixes to each dataset
base_dir = Path('..')
for dataset, column_fixes in manual_fixes.items():
    dd_bervo_file = base_dir / dataset / 'dd_bervo.csv'
    
    if not dd_bervo_file.exists():
        print(f"Warning: {dd_bervo_file} not found, skipping")
        continue
    
    print(f"\nApplying fixes to {dataset}...")
    
    # Read the file
    with open(dd_bervo_file, 'r') as f:
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
    
    # Apply fixes
    changes = 0
    for row in rows:
        col_name = row[col_field]
        if col_name in column_fixes:
            old_combo = row['BERVO Combination']
            new_combo = column_fixes[col_name]
            row['BERVO Combination'] = new_combo
            print(f"  {col_name}: '{old_combo}' → '{new_combo}'")
            changes += 1
    
    # Write back
    with open(dd_bervo_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    
    print(f"  Applied {changes} changes")

print("\n" + "=" * 70)
print("✓ Manual fixes applied successfully!")
print("\nRun check_bervo_duplicates.py to verify all combinations are now unique.")

