#!/usr/bin/env python3
import re
import json

# Parse BERVO OBO file
def parse_bervo_obo(filepath):
    terms = {}
    current_id = None
    current_name = None
    
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line.startswith('id: bervo:BERVO_'):
                current_id = line.split('id: ')[1]
            elif line.startswith('name: '):
                current_name = line.split('name: ', 1)[1]
                if current_id and current_name:
                    # Store both full ID and just the numeric part
                    terms[current_name.lower()] = current_id
                    terms[current_id] = current_name
            elif line == '[Term]':
                current_id = None
                current_name = None
    
    return terms

# Parse and save
bervo_file = '/h/jmc/data/bioepic/chess/ontologies/bervo/bervo.obo'
terms = parse_bervo_obo(bervo_file)

# Save to JSON for easy lookup
with open('/tmp/bervo_terms.json', 'w') as f:
    json.dump(terms, f, indent=2)

print(f"Parsed {len(terms)} BERVO terms")
print("\nSample terms:")
for i, (key, value) in enumerate(list(terms.items())[:20]):
    if isinstance(key, str) and not key.startswith('bervo:'):
        print(f"  {key}: {value}")
    if i >= 10:
        break
