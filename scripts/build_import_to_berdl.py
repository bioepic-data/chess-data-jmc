#!/usr/bin/env python3

import csv
import json
import re
from pathlib import Path


def normalize_bervo_curie(text):
    if not isinstance(text, str):
        return text
    return re.sub(r'bervo:BERVO_([A-Za-z0-9_]+)', r'BERVO:\1', text)


def normalize_bervo_value(value):
    if isinstance(value, str):
        return normalize_bervo_curie(value)
    if isinstance(value, list):
        return [normalize_bervo_value(item) for item in value]
    if isinstance(value, dict):
        return {
            normalize_bervo_curie(key): normalize_bervo_value(val)
            for key, val in value.items()
        }
    return value


def pyspark_to_sql_type(pyspark_type):
    mapping = {
        'StringType': 'STRING',
        'IntegerType': 'INT',
        'DoubleType': 'DOUBLE',
        'FloatType': 'FLOAT',
        'BooleanType': 'BOOLEAN',
        'LongType': 'BIGINT',
        'DateType': 'DATE',
        'TimestampType': 'TIMESTAMP',
    }
    return mapping.get(pyspark_type, 'STRING')


def parse_schema_with_comments(schema_path):
    pattern = r'StructField\("([^"]+)",\s*(\w+)\(\).*?metadata=\{"comment":\s*"((?:[^"\\]|\\.)*)"\}'
    content = schema_path.read_text(encoding='utf-8')
    matches = re.findall(pattern, content, re.DOTALL)

    columns = []
    for col_name, pyspark_type, comment in matches:
        columns.append({
            'name': col_name,
            'type': pyspark_to_sql_type(pyspark_type),
            'comment': comment.replace('\\"', '"'),
        })
    return columns


def tsv_to_csv(tsv_path, csv_path):
    with tsv_path.open('r', encoding='utf-8', newline='') as in_f:
        reader = csv.reader(in_f, delimiter='\t')
        with csv_path.open('w', encoding='utf-8', newline='') as out_f:
            writer = csv.writer(out_f)
            for row in reader:
                writer.writerow([normalize_bervo_curie(cell) for cell in row])


def append_tsv_to_csv(tsv_path, csv_path, skip_header):
    mode = 'a' if csv_path.exists() else 'w'
    with tsv_path.open('r', encoding='utf-8', newline='') as in_f:
        reader = csv.reader(in_f, delimiter='\t')
        with csv_path.open(mode, encoding='utf-8', newline='') as out_f:
            writer = csv.writer(out_f)
            for idx, row in enumerate(reader):
                if idx == 0 and skip_header:
                    continue
                writer.writerow([normalize_bervo_curie(cell) for cell in row])


def load_table_comments(ddt_ndarray_csv_path):
    comments = {}
    with ddt_ndarray_csv_path.open('r', encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            table_name = (row.get('ddt_ndarray_id') or '').strip()
            if not table_name:
                continue
            parts = [
                (row.get('ddt_ndarray_name') or '').strip(),
                (row.get('ddt_ndarray_description') or '').strip(),
            ]
            comments[table_name] = ' - '.join(part for part in parts if part)
    return comments


def generate_update_comments(output_dir, table_comments, schema_comments, database_name='chess'):
    script_path = output_dir / 'update_comments.py'
    lines = [
        '# Auto-generated script to update table and column comments.\n',
        '# Expects an existing `spark` session in scope.\n',
        '\n',
        'print("DEBUG: starting comment updates")\n',
        '\n',
    ]

    for table_name in sorted(schema_comments):
        lines.append(f'# Update comments for table: {table_name}\n')
        lines.append(f'print("DEBUG: updating comments for table: {table_name}")\n')

        table_comment = table_comments.get(table_name, '')
        if table_comment:
            escaped = table_comment.replace("'", "\\'")
            lines.extend([
                'spark.sql("""\n',
                f"    ALTER TABLE {database_name}.{table_name} SET TBLPROPERTIES ('comment' = '{escaped}')\n",
                '""")\n',
                f'print("DEBUG: updated table comment for {table_name}")\n',
                '\n',
            ])

        for col in schema_comments[table_name]:
            escaped = col['comment'].replace("'", "\\'")
            lines.extend([
                'spark.sql("""\n',
                f"    ALTER TABLE {database_name}.{table_name} CHANGE COLUMN {col['name']} {col['name']} {col['type']} COMMENT '{escaped}'\n",
                '""")\n',
                '\n',
            ])

        lines.append(f'print("DEBUG: updated {len(schema_comments[table_name])} columns for {table_name}")\n')
        lines.append('\n')

    if 'sys_oterm' in table_comments:
        lines.append('# Update comments for table: sys_oterm\n')
        lines.append('print("DEBUG: updating comments for table: sys_oterm")\n')
        escaped = table_comments['sys_oterm'].replace("'", "\\'")
        lines.extend([
            'spark.sql("""\n',
            f"    ALTER TABLE {database_name}.sys_oterm SET TBLPROPERTIES ('comment' = '{escaped}')\n",
            '""")\n',
            'print("DEBUG: updated table comment for sys_oterm")\n',
            '\n',
        ])
        for col in SYS_OTERM_COMMENTS:
            escaped_comment = col['comment'].replace("'", "\\'")
            lines.extend([
                'spark.sql("""\n',
                f"    ALTER TABLE {database_name}.sys_oterm CHANGE COLUMN {col['name']} {col['name']} {col['type']} COMMENT '{escaped_comment}'\n",
                '""")\n',
                '\n',
            ])
        lines.append(f'print("DEBUG: updated {len(SYS_OTERM_COMMENTS)} columns for sys_oterm")\n')
        lines.append('\n')

    lines.append('print("DEBUG: finished comment updates")\n')
    script_path.write_text(''.join(lines), encoding='utf-8')


def parse_obo_file(path):
    terms = {}
    current = {}
    in_term = False

    with path.open('r', encoding='utf-8') as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith('!'):
                continue

            if line == '[Term]':
                if in_term and 'id' in current:
                    terms[current['id']] = current
                current = {
                    'synonyms': [],
                    'xrefs': [],
                    'property_values': {},
                }
                in_term = True
                continue
            elif line.startswith('['):
                if in_term and 'id' in current:
                    terms[current['id']] = current
                in_term = False
                continue

            if not in_term or ':' not in line:
                continue

            key, value = line.split(':', 1)
            key = key.strip()
            value = value.strip()

            if key == 'id':
                current['id'] = normalize_bervo_curie(value)
            elif key == 'name':
                current['name'] = value
            elif key == 'def':
                match = re.match(r'^"(.*)"(?:\s+\[.*\])?$', value)
                current['definition'] = match.group(1) if match else value
            elif key == 'synonym':
                match = re.match(r'^"(.*)"\s+.*$', value)
                current['synonyms'].append(match.group(1) if match else value)
            elif key == 'xref':
                current['xrefs'].append(normalize_bervo_curie(value.split(' ', 1)[0]))
            elif key == 'is_a':
                current['parent'] = normalize_bervo_curie(value.split(' ', 1)[0])
            elif key == 'property_value':
                match = re.match(r'^(\S+)\s+"([^"]*)"', value)
                if match:
                    prop_curie = normalize_bervo_curie(match.group(1))
                    prop_val = normalize_bervo_curie(match.group(2))
                    current['property_values'].setdefault(prop_curie, []).append(prop_val)

    if in_term and 'id' in current:
        terms[current['id']] = current

    return terms


def write_sys_oterm_csv(output_path, ontology_paths):
    fieldnames = [
        'sys_oterm_id',
        'parent_sys_oterm_id',
        'sys_oterm_ontology',
        'sys_oterm_name',
        'sys_oterm_synonyms',
        'sys_oterm_definition',
        'sys_oterm_links',
        'sys_oterm_properties',
    ]

    rows = []
    for ontology_name, ontology_path in ontology_paths:
        for term_id, term in sorted(parse_obo_file(ontology_path).items()):
            prop_map = None
            if term.get('property_values'):
                prop_map = {k: ';'.join(v) for k, v in term['property_values'].items()}
            rows.append({
                'sys_oterm_id': term_id,
                'parent_sys_oterm_id': term.get('parent', ''),
                'sys_oterm_ontology': ontology_name,
                'sys_oterm_name': term.get('name', ''),
                'sys_oterm_synonyms': json.dumps(normalize_bervo_value(term['synonyms'])) if term.get('synonyms') else '',
                'sys_oterm_definition': term.get('definition', ''),
                'sys_oterm_links': json.dumps(normalize_bervo_value(term['xrefs'])) if term.get('xrefs') else '',
                'sys_oterm_properties': json.dumps(normalize_bervo_value(prop_map), sort_keys=True) if prop_map else '',
            })

    with output_path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


SYS_OTERM_COMMENTS = [
    {
        'name': 'sys_oterm_id',
        'type': 'STRING',
        'comment': 'Term identifier, aka CURIE (Primary key)',
    },
    {
        'name': 'parent_sys_oterm_id',
        'type': 'STRING',
        'comment': 'Parent term identifier (Foreign key to sys_oterm.sys_oterm_id)',
    },
    {
        'name': 'sys_oterm_ontology',
        'type': 'STRING',
        'comment': 'Ontology that each term is from',
    },
    {
        'name': 'sys_oterm_name',
        'type': 'STRING',
        'comment': 'Term name',
    },
    {
        'name': 'sys_oterm_synonyms',
        'type': 'ARRAY<STRING>',
        'comment': 'List of synonyms for a term',
    },
    {
        'name': 'sys_oterm_definition',
        'type': 'STRING',
        'comment': 'Term definition',
    },
    {
        'name': 'sys_oterm_links',
        'type': 'ARRAY<STRING>',
        'comment': 'Indicates that values are links to other tables (Ref) or ontological terms (ORef)',
    },
    {
        'name': 'sys_oterm_properties',
        'type': 'MAP<STRING, STRING>',
        'comment': 'Semicolon-separated map of ontology property values for each term',
    },
]


def main():
    base_dir = Path(__file__).resolve().parents[1]
    input_dir = base_dir / 'ontologized_datasets'
    output_dir = base_dir / 'import_to_berdl'
    output_dir.mkdir(exist_ok=True)

    data_tsvs = sorted(
        path for path in input_dir.glob('*.tsv')
        if not path.name.endswith('_ddt_ndarray.tsv') and not path.name.endswith('_sys_ddt_typedef.tsv')
    )

    ddt_ndarray_csv = output_dir / 'ddt_ndarray.csv'
    sys_ddt_typedef_csv = output_dir / 'sys_ddt_typedef.csv'
    sys_oterm_csv = output_dir / 'sys_oterm.csv'
    if ddt_ndarray_csv.exists():
        ddt_ndarray_csv.unlink()
    if sys_ddt_typedef_csv.exists():
        sys_ddt_typedef_csv.unlink()
    if sys_oterm_csv.exists():
        sys_oterm_csv.unlink()

    first_ddt = True
    first_sys = True
    schema_comments = {}

    for data_tsv in data_tsvs:
        stem = data_tsv.stem
        out_csv = output_dir / f'{stem}.csv'
        tsv_to_csv(data_tsv, out_csv)

        ddt_tsv = input_dir / f'{stem}_ddt_ndarray.tsv'
        sys_tsv = input_dir / f'{stem}_sys_ddt_typedef.tsv'
        schema_py = input_dir / f'{stem}_schema.py'

        append_tsv_to_csv(ddt_tsv, ddt_ndarray_csv, skip_header=not first_ddt)
        append_tsv_to_csv(sys_tsv, sys_ddt_typedef_csv, skip_header=not first_sys)
        first_ddt = False
        first_sys = False

        schema_comments[stem] = parse_schema_with_comments(schema_py)

    ontology_paths = [
        ('bervo', base_dir / 'ontologies' / 'bervo' / 'bervo.obo'),
        ('uo', base_dir / 'ontologies' / 'uo' / 'uo.obo'),
    ]
    sys_oterm_count = write_sys_oterm_csv(sys_oterm_csv, ontology_paths)

    table_comments = load_table_comments(ddt_ndarray_csv)
    table_comments['sys_oterm'] = 'Ontology terms used in CHESS (BERVO and UO)'
    generate_update_comments(output_dir, table_comments, schema_comments)

    print(f'Created {len(data_tsvs)} data CSV files in {output_dir}')
    print(f'Created {ddt_ndarray_csv.name}')
    print(f'Created {sys_ddt_typedef_csv.name}')
    print(f'Created {sys_oterm_csv.name} ({sys_oterm_count} terms)')
    print('Created update_comments.py')


if __name__ == '__main__':
    main()
