#!/usr/bin/env python3
"""Parse UO (Units Ontology) and create JSON lookup."""

import re
import json

def parse_uo_obo(filepath):
    """Parse UO OBO file and return terms with their IDs and metadata."""
    terms = {}
    current_id = None
    current_name = None
    current_def = None
    current_synonyms = []

    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()

            if line.startswith('id: UO:'):
                current_id = line.split('id: ')[1]
            elif line.startswith('name: '):
                current_name = line.split('name: ', 1)[1]
            elif line.startswith('def: '):
                # Extract definition from quotes
                match = re.match(r'def: "(.*?)"', line)
                if match:
                    current_def = match.group(1)
            elif line.startswith('synonym: '):
                # Extract synonym from quotes
                match = re.match(r'synonym: "(.*?)"', line)
                if match:
                    current_synonyms.append(match.group(1))
            elif line == '[Term]' or line == '':
                # Save previous term
                if current_id and current_name:
                    # Store by name (lowercase)
                    terms[current_name.lower()] = {
                        'id': current_id,
                        'name': current_name,
                        'definition': current_def,
                        'synonyms': current_synonyms
                    }
                    # Store by ID
                    terms[current_id] = current_name

                    # Also store by common synonyms
                    for syn in current_synonyms:
                        syn_lower = syn.lower()
                        if syn_lower not in terms:
                            terms[syn_lower] = {
                                'id': current_id,
                                'name': current_name,
                                'definition': current_def,
                                'synonyms': current_synonyms
                            }

                # Reset
                current_id = None
                current_name = None
                current_def = None
                current_synonyms = []

    return terms

# Parse and save
uo_file = '/h/jmc/data/bioepic/chess/ontologies/uo/uo.obo'
terms = parse_uo_obo(uo_file)

# Save to JSON for easy lookup
with open('/tmp/uo_terms.json', 'w') as f:
    json.dump(terms, f, indent=2)

print(f"Parsed {len([k for k in terms.keys() if isinstance(k, str) and k.startswith('UO:')])} UO terms")

# Find common units used in CHESS
common_units = [
    'meter', 'metre', 'm',
    'degree celsius', 'celsius', '°c',
    'percent', '%',
    'millisiemens per meter',
    'parts per thousand', 'ppt',
    'second', 'hour', 'minute'
]

print("\nCommon units in CHESS datasets:")
for unit in common_units:
    if unit in terms:
        info = terms[unit]
        if isinstance(info, dict):
            print(f"  {unit}: {info['id']} ({info['name']})")
        else:
            print(f"  {unit}: -> {info}")
