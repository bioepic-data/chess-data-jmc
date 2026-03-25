#!/usr/bin/env python3
"""
Convert CHESS geophysical survey datasets to ontologized format.

Creates for each dataset:
- .tsv file with data
- _schema.py file with PySpark schema
- _ddt_ndarray.tsv with dataset metadata
- _sys_ddt_typedef.tsv with column metadata
"""

import csv
import json
import struct
import re
from pathlib import Path


def load_uo_terms():
    """Load UO ontology terms for unit name mapping."""
    try:
        with open('/tmp/uo_terms.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def dbf_to_records(dbf_path):
    """Read DBF file and return records as list of dicts."""
    with open(dbf_path, 'rb') as f:
        # Read header
        header = f.read(32)
        num_records = struct.unpack('<I', header[4:8])[0]
        header_length = struct.unpack('<H', header[8:10])[0]
        record_length = struct.unpack('<H', header[10:12])[0]

        # Read field descriptors
        num_fields = (header_length - 33) // 32
        fields = []
        for i in range(num_fields):
            field_info = f.read(32)
            name = field_info[0:11].decode('ascii').strip('\x00')
            ftype = chr(field_info[11])
            length = field_info[16]
            decimal_count = field_info[17]
            fields.append((name, ftype, length, decimal_count))

        # Skip field descriptor terminator
        f.read(1)

        # Read records
        records = []
        for rec_num in range(num_records):
            deletion_flag = f.read(1)
            if deletion_flag == b'*':
                f.read(record_length - 1)
                continue

            record = {}
            for name, ftype, length, decimals in fields:
                value_bytes = f.read(length)
                value_str = value_bytes.decode('ascii', errors='ignore').strip()

                if ftype == 'N' and value_str:
                    try:
                        if '.' in value_str or decimals > 0:
                            record[name] = float(value_str)
                        else:
                            record[name] = int(value_str)
                    except ValueError:
                        record[name] = value_str
                else:
                    record[name] = value_str

            records.append(record)

        return fields, records


def get_uo_unit_name(uo_id, uo_terms):
    """Get UO unit name from UO ID."""
    if not uo_id or not uo_terms:
        return None

    if uo_id in uo_terms:
        return uo_terms[uo_id]
    return None


def map_unit_to_uo(unit_str):
    """Map unit string to UO ontology term."""
    if not unit_str or unit_str == 'N/A':
        return None

    # Normalize unit string
    unit_lower = unit_str.lower().strip()

    # Direct mappings to UO terms
    unit_mappings = {
        'm': 'UO:0000008',
        'meter': 'UO:0000008',
        'metre': 'UO:0000008',
        'celsius (°c)': 'UO:0000027',
        '°c': 'UO:0000027',
        'degree celsius': 'UO:0000027',
        '%': 'UO:0000187',
        'percent': 'UO:0000187',
        'ms/m': 'UO:0010002',
        'millisiemens': 'UO:0010002',
        'ppt': 'UO:0000168',
        'parts per thousand': 'UO:0000168',
        'second': 'UO:0000010',
        'minute': 'UO:0000031',
        'hour': 'UO:0000032',
        'hh:mm:ss.mmm': None,
        'yyyy-mm-dd': None,
    }

    return unit_mappings.get(unit_lower)


def get_column_unit_suffix(unit_str, uo_terms):
    """Return the normalized unit suffix used in BERDL column names."""
    if not unit_str or unit_str == 'N/A':
        return None

    uo_id = map_unit_to_uo(unit_str)
    if not uo_id:
        return None

    # There does not appear to be a direct UO term for mS/m in the local lookup.
    if unit_str.lower() == 'ms/m':
        return 'millisiemens_per_meter'

    unit_name = get_uo_unit_name(uo_id, uo_terms)
    if not unit_name:
        return None

    return unit_name.lower().replace(' ', '_').replace('-', '_')


def get_typedef_unit_name(unit_str, uo_terms):
    """Return the human-readable unit name stored in sys_ddt_typedef/schema metadata."""
    if not unit_str or unit_str == 'N/A':
        return ''

    uo_id = map_unit_to_uo(unit_str)
    if not uo_id:
        return ''

    if unit_str.lower() == 'ms/m':
        return 'millisiemens per meter'

    return get_uo_unit_name(uo_id, uo_terms) or ''


def primary_term_name(bervo_combination):
    """Return the primary BERVO term name from a BERVO combination string."""
    if not bervo_combination:
        return ''
    return bervo_combination.split(',', 1)[0].strip()


def normalize_bervo_curie(text):
    """Convert BERVO IDs from `bervo:BERVO_#########` to `BERVO:#########`."""
    if not isinstance(text, str):
        return text
    return re.sub(r'bervo:BERVO_([A-Za-z0-9_]+)', r'BERVO:\1', text)


def normalize_bervo_value(value):
    """Recursively normalize BERVO identifiers in nested objects."""
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


def json_cell(value):
    """Serialize a Python object for a single TSV cell."""
    return json.dumps(normalize_bervo_value(value))


def get_dimension_info(dimension_number):
    """Return the dimension ontology metadata for a dimension number."""
    if dimension_number == 1:
        return 'BERVO:8000394', 'Location'
    if dimension_number == 2:
        return 'BERVO:8000238', 'Time'
    return '', ''


def spark_type_to_scalar_type(spark_type):
    """Map Spark type names to sys_ddt_typedef scalar types."""
    mapping = {
        'StringType': 'string',
        'IntegerType': 'int',
        'DoubleType': 'float',
    }
    return mapping.get(spark_type, 'string')


def normalize_missing_value(value):
    """Convert common null/missing sentinels to empty strings for TSV export."""
    if value is None:
        return ''

    text = str(value).strip()
    if text.lower() in {'n/a', 'na', 'null', 'none', '-9999'}:
        return ''

    return value


def build_schema_comment(description, unit_name='', foreign_key=''):
    """Match the older brick schema metadata shape as closely as practical."""
    comment_dict = {
        "description": description
    }
    if foreign_key:
        comment_dict["type"] = "foreign_key"
        comment_dict["references"] = foreign_key
    if unit_name:
        comment_dict["unit"] = unit_name
    return json.dumps(comment_dict).replace('"', '\\"')


def build_ddt_name(dataset_id):
    """Use the older brick-style ndarray naming convention."""
    return f"{dataset_id}.ndarray"


def bervo_combination_to_column_name(bervo_combination, unit_str, dimension_prefix, uo_terms):
    """Convert BERVO combination to column name following CORAL convention."""
    if not bervo_combination or bervo_combination == 'unnecessary?':
        return None

    # Remove Context qualifiers from column names to keep them concise.
    combo = re.sub(r',?\s*Context\s*=\s*[^,]+', '', bervo_combination, flags=re.IGNORECASE)

    # Convert to lowercase with underscores
    name = combo.lower()

    # Replace special characters
    replacements = [
        (', ', '_'),
        (' = ', '_'),
        ('(', ''),
        (')', ''),
        (' ', '_'),
        (',', '_'),
        ('-', '_'),  # hyphen to underscore
        ('__', '_'),
    ]

    for old, new in replacements:
        name = name.replace(old, new)

    # Clean up multiple underscores and leading/trailing underscores
    while '__' in name:
        name = name.replace('__', '_')
    name = name.strip('_')

    # Add unit suffix if present
    if unit_str and unit_str != 'N/A':
        unit_suffix = get_column_unit_suffix(unit_str, uo_terms)
        if unit_suffix:
            name = f"{name}_{unit_suffix}"

    # Add dimension prefix
    if dimension_prefix:
        # Check if dimension name equals variable name (e.g., region_region -> region)
        if dimension_prefix.lower() == name.split('_')[0]:
            # Already starts with dimension name, don't duplicate
            pass
        else:
            name = f"{dimension_prefix}_{name}"

    return name


def python_type_to_spark(value):
    """Map Python value to Spark type."""
    if value is None or value == '':
        return 'StringType'
    elif isinstance(value, int):
        return 'IntegerType'
    elif isinstance(value, float):
        return 'DoubleType'
    else:
        return 'StringType'


def expand_comment_units(comment_text):
    """Expand shorthand units inside BERVO combination comments to full names."""
    replacements = {
        '(cm)': '(centimeter)',
        '(m)': '(meter)',
        '(kHz)': '(kilohertz)',
    }
    expanded = comment_text
    for old, new in replacements.items():
        expanded = expanded.replace(old, new)
    return expanded


def add_comment_note(comment_text, note):
    """Append a human-readable note without introducing a new x=y clause."""
    if not note:
        return comment_text
    return f"{comment_text}, comment = {note}"


def infer_csv_spark_type(records, field_name):
    """Infer a Spark type from CSV string values."""
    spark_type = 'StringType'
    for record in records:
        val = record.get(field_name, '')
        if val:
            try:
                float(val)
                if '.' in val:
                    spark_type = 'DoubleType'
                else:
                    spark_type = 'IntegerType'
            except ValueError:
                spark_type = 'StringType'
            break
    return spark_type


def build_schema_lines(schema_fields):
    """Create a schema.py body with only the required Spark type imports."""
    imports = {'StructType', 'StructField'}
    for field in schema_fields:
        imports.add(field['spark_type'])

    import_list = ', '.join(sorted(imports))
    lines = [
        f"from pyspark.sql.types import {import_list}\n",
        "\nschema = StructType([\n"
    ]

    for field in schema_fields:
        lines.append(
            f'    StructField("{field["name"]}", {field["spark_type"]}(), True, '
            f'metadata={{"comment": "{field["comment"]}"}}),\n'
        )

    lines.append("])\n")
    return lines


def convert_tdr_dataset(base_dir, output_dir):
    """Convert NEON_plot_TDR.csv to ontologized format."""

    dataset_id = "geophysical_survey_tdr_plot_data"

    # Load UO terms
    uo_terms = load_uo_terms()

    # Read data
    tdr_file = base_dir / "geophysical_survey" / "NEON_plot_TDR.csv"
    dd_bervo_file = base_dir / "geophysical_survey" / "dd_bervo.csv"

    with open(tdr_file, 'r') as f:
        reader = csv.DictReader(f)
        tdr_data = list(reader)
        tdr_fieldnames = reader.fieldnames

    # Read BERVO mappings
    bervo_map = {}
    with open(dd_bervo_file, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            col_name = row['Column_or_Row_Name']
            bervo_comb = row['BERVO Combination']
            bervo_term = row['BERVO Term']
            unit = row.get('Unit', '')
            definition = row.get('Definition', '')

            mapping_data = {
                'combination': bervo_comb,
                'term': bervo_term,
                'unit': unit,
                'definition': definition
            }

            # Try exact match first
            if col_name in tdr_fieldnames:
                bervo_map[col_name] = mapping_data
            else:
                # Try with normalized spacing
                normalized_name = col_name.replace(' _', '_').replace('_ ', '_')
                if normalized_name in tdr_fieldnames:
                    bervo_map[normalized_name] = mapping_data

    # Define dimensions and their variables
    dimension_1_fields = ['SampleSiteCode', 'Easting', 'Northing', 'VegetationType', 'Site']
    dimension_2_fields = ['Collection Date']
    data_variable_fields = ['VWC_1', 'VWC_2', 'avg_VWC', 'Temp_1', 'Temp_2', 'avg_Temp']
    ordered_fields = dimension_1_fields + dimension_2_fields + data_variable_fields

    # Build new column names mapping
    new_column_names = {}

    for field_name in tdr_fieldnames:
        if field_name in bervo_map:
            bm = bervo_map[field_name]

            # Determine dimension prefix
            if field_name in dimension_1_fields:
                dim_prefix = 'location'
            elif field_name in dimension_2_fields:
                dim_prefix = 'time'
            else:
                dim_prefix = None  # data variables

            new_name = bervo_combination_to_column_name(
                bm['combination'],
                bm['unit'],
                dim_prefix,
                uo_terms
            )

            if new_name:
                new_column_names[field_name] = new_name
            else:
                new_column_names[field_name] = field_name.lower().replace(' ', '_')
        else:
            new_column_names[field_name] = field_name.lower().replace(' ', '_')

    # Rename columns in data
    renamed_data = []
    for row in tdr_data:
        new_row = {new_column_names[k]: normalize_missing_value(v) for k, v in row.items()}
        renamed_data.append(new_row)

    new_fieldnames = [new_column_names[f] for f in ordered_fields]

    # Write TSV
    tsv_path = output_dir / f"{dataset_id}.tsv"
    with open(tsv_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=new_fieldnames, delimiter='\t')
        writer.writeheader()
        for row in renamed_data:
            ordered_row = {new_column_names[f]: row.get(new_column_names[f], '') for f in ordered_fields}
            writer.writerow(ordered_row)

    schema_fields = []
    sys_typedef_rows = []

    for orig_field_name in ordered_fields:
        new_field_name = new_column_names[orig_field_name]

        # Add to sys_typedef
        unit_str = bervo_map.get(orig_field_name, {}).get('unit', '')
        uo_term = map_unit_to_uo(unit_str) if unit_str else ''
        unit_name = get_typedef_unit_name(unit_str, uo_terms)
        spark_type = infer_csv_spark_type(tdr_data, orig_field_name)

        # Determine dimension info
        if orig_field_name in dimension_1_fields:
            dim_number = 1
            var_number = dimension_1_fields.index(orig_field_name) + 1
            data_type = 'dimension_variable'
        elif orig_field_name in dimension_2_fields:
            dim_number = 2
            var_number = dimension_2_fields.index(orig_field_name) + 1
            data_type = 'dimension_variable'
        else:
            dim_number = ''
            if orig_field_name in data_variable_fields:
                var_number = data_variable_fields.index(orig_field_name) + 1
            else:
                var_number = ''
            data_type = 'variable'

        dim_oterm_id, dim_oterm_name = get_dimension_info(dim_number)
        comment_text = bervo_map.get(orig_field_name, {}).get('combination') or bervo_map.get(orig_field_name, {}).get('definition') or orig_field_name
        comment_text = expand_comment_units(comment_text)
        variable_term_name = primary_term_name(bervo_map.get(orig_field_name, {}).get('combination', ''))

        schema_fields.append({
            'name': new_field_name,
            'spark_type': spark_type,
            'comment': build_schema_comment(comment_text, unit_name)
        })

        sys_typedef_rows.append({
            'ddt_ndarray_id': dataset_id,
            'berdl_column_name': new_field_name,
            'berdl_column_data_type': data_type,
            'scalar_type': spark_type_to_scalar_type(spark_type),
            'foreign_key': '',
            'comment': comment_text,
            'unit_sys_oterm_id': uo_term or '',
            'unit_sys_oterm_name': unit_name,
            'dimension_number': dim_number,
            'dimension_oterm_id': dim_oterm_id,
            'dimension_oterm_name': dim_oterm_name,
            'variable_number': var_number,
            'variable_oterm_id': bervo_map.get(orig_field_name, {}).get('term', ''),
            'variable_oterm_name': variable_term_name,
            'original_description': bervo_map.get(orig_field_name, {}).get('definition', '')
        })

    schema_lines = build_schema_lines(schema_fields)
    schema_path = output_dir / f"{dataset_id}_schema.py"
    with open(schema_path, 'w') as f:
        f.writelines(schema_lines)

    # Generate ddt_ndarray.tsv
    ddt_ndarray_path = output_dir / f"{dataset_id}_ddt_ndarray.tsv"
    with open(ddt_ndarray_path, 'w', newline='') as f:
        writer = csv.writer(f, delimiter='\t')
        writer.writerow([
            'ddt_ndarray_id', 'ddt_ndarray_name', 'ddt_ndarray_description',
            'ddt_ndarray_metadata', 'ddt_ndarray_type_sys_oterm_id',
            'ddt_ndarray_type_sys_oterm_name', 'ddt_ndarray_shape',
            'ddt_ndarray_dimension_types_sys_oterm_id',
            'ddt_ndarray_dimension_types_sys_oterm_name',
            'ddt_ndarray_dimension_variable_types_sys_oterm_id',
            'ddt_ndarray_dimension_variable_types_sys_oterm_name',
            'ddt_ndarray_variable_types_sys_oterm_id',
            'ddt_ndarray_variable_types_sys_oterm_name',
            'withdrawn_date', 'superceded_by_ddt_ndarray_id'
        ])
        writer.writerow([
            dataset_id,
            build_ddt_name(dataset_id),
            'Time Domain Reflectometry measurements of volumetric water content and temperature at NEON survey plots, East River, CO 2018',
            json_cell([
                ["Location <bervo:BERVO_8000394>", "East River, CO"],
                ["Time <bervo:BERVO_8000238>", "2018"]
            ]),
            'BERVO:0001703',
            'Geophysical Measurement',
            f'[{len(tdr_data)}]',
            '["BERVO:8000394", "BERVO:8000238"]',
            '["Location", "Time"]',
            '[["BERVO:8000528", "BERVO:8000440", "BERVO:8000441", "BERVO:8000404", "BERVO:8000519"], ["BERVO:8000239"]]',
            '[["Identifier", "Easting", "Northing", "Community type", "Region"], ["Date"]]',
            '["BERVO:0001743", "BERVO:8000133"]',
            '["Volumetric water content", "Temperature"]',
            '',
            ''
        ])

    # Generate sys_ddt_typedef.tsv
    sys_typedef_path = output_dir / f"{dataset_id}_sys_ddt_typedef.tsv"
    with open(sys_typedef_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'ddt_ndarray_id', 'berdl_column_name', 'berdl_column_data_type',
            'scalar_type', 'foreign_key', 'comment', 'unit_sys_oterm_id',
            'unit_sys_oterm_name', 'dimension_number', 'dimension_oterm_id',
            'dimension_oterm_name', 'variable_number', 'variable_oterm_id',
            'variable_oterm_name', 'original_description'
        ], delimiter='\t')
        writer.writeheader()
        writer.writerows([normalize_bervo_value(row) for row in sys_typedef_rows])

    print(f"✓ Created {dataset_id}:")
    print(f"  - {tsv_path.name} ({len(tdr_data)} records, {len(new_fieldnames)} columns)")
    print(f"  - {schema_path.name}")
    print(f"  - {ddt_ndarray_path.name}")
    print(f"  - {sys_typedef_path.name}")


def convert_emi_dataset(base_dir, output_dir):
    """Convert NEON_2018_EMI_survey.dbf to ontologized format."""

    dataset_id = "geophysical_survey_emi_survey"

    # Load UO terms
    uo_terms = load_uo_terms()

    # Read DBF
    dbf_file = base_dir / "geophysical_survey" / "NEON_2018_EMI_survey.dbf"
    fields, records = dbf_to_records(dbf_file)

    print(f"Read {len(records)} records from EMI survey DBF")

    # Field names from DBF
    field_names = [f[0] for f in fields]

    # BERVO mappings for EMI fields
    emi_bervo_map = {
        'Northing': {
            'combination': 'Northing, projected coordinate system = UTM Zone 13N',
            'term': 'BERVO:8000441',
            'unit': 'm',
            'definition': 'UTM northing coordinate in WGS84 UTM Zone 13N',
        },
        'Easting': {
            'combination': 'Easting, projected coordinate system = UTM Zone 13N',
            'term': 'BERVO:8000440',
            'unit': 'm',
            'definition': 'UTM easting coordinate in WGS84 UTM Zone 13N',
        },
        'Altitude': {
            'combination': 'Altitude',
            'term': 'BERVO:8000099',
            'unit': 'm',
            'definition': 'Elevation above sea level'
        },
        'Time': {
            'combination': 'Time',
            'term': 'BERVO:8000238',
            'unit': 'HH:MM:SS.mmm',
            'definition': 'GPS timestamp of measurement'
        },
        'Cond.1[mS/': {
            'combination': 'Soil electrical conductivity, Depth = 0.5 (m), frequency = 30 (kHz)',
            'term': 'BERVO:0000916',
            'unit': 'mS/m',
            'definition': 'Electrical conductivity at 0.5m depth, 30 kHz (excluded from analysis due to noise)'
        },
        'Inph.1[ppt': {
            'combination': 'Electromagnetic in-phase response, Depth = 0.5 (m), frequency = 30 (kHz)',
            'term': 'BERVO:8000553',
            'unit': 'ppt',
            'definition': 'In-phase component at 0.5m depth, 30 kHz (excluded from analysis due to noise)'
        },
        'Cond.2[mS/': {
            'combination': 'Soil electrical conductivity, Depth = 1.0 (m), frequency = 30 (kHz)',
            'term': 'BERVO:0000916',
            'unit': 'mS/m',
            'definition': 'Electrical conductivity at 1.0m depth, 30 kHz'
        },
        'Inph.2[ppt': {
            'combination': 'Electromagnetic in-phase response, Depth = 1.0 (m), frequency = 30 (kHz)',
            'term': 'BERVO:8000553',
            'unit': 'ppt',
            'definition': 'In-phase component at 1.0m depth, 30 kHz'
        },
        'Cond.3[mS/': {
            'combination': 'Soil electrical conductivity, Depth = 1.8 (m), frequency = 30 (kHz)',
            'term': 'BERVO:0000916',
            'unit': 'mS/m',
            'definition': 'Electrical conductivity at 1.8m depth, 30 kHz'
        },
        'Inph.3[ppt': {
            'combination': 'Electromagnetic in-phase response, Depth = 1.8 (m), frequency = 30 (kHz)',
            'term': 'BERVO:8000553',
            'unit': 'ppt',
            'definition': 'In-phase component at 1.8m depth, 30 kHz'
        },
        'Site': {
            'combination': 'Region',
            'term': 'BERVO:8000519',
            'unit': 'N/A',
            'definition': 'Site name'
        },
        'Site_code': {
            'combination': 'Identifier, Context = Region',
            'term': 'BERVO:8000528',
            'unit': 'N/A',
            'definition': 'Site abbreviation code'
        }
    }

    # Define dimensions
    dimension_1_fields = ['Northing', 'Easting', 'Altitude', 'Site', 'Site_code']
    dimension_2_fields = ['Time']
    data_variable_fields = ['Cond.1[mS/', 'Inph.1[ppt', 'Cond.2[mS/', 'Inph.2[ppt', 'Cond.3[mS/', 'Inph.3[ppt']
    ordered_fields = dimension_1_fields + dimension_2_fields + data_variable_fields

    # Build new column names mapping
    new_column_names = {}

    for field_name in field_names:
        if field_name in emi_bervo_map:
            bm = emi_bervo_map[field_name]

            # Determine dimension prefix
            if field_name in dimension_1_fields:
                dim_prefix = 'location'
            elif field_name in dimension_2_fields:
                dim_prefix = 'time'
            else:
                dim_prefix = None  # data variables

            new_name = bervo_combination_to_column_name(
                bm['combination'],
                bm['unit'],
                dim_prefix,
                uo_terms
            )

            if new_name:
                new_column_names[field_name] = new_name
            else:
                new_column_names[field_name] = field_name.lower().replace(' ', '_')
        else:
            new_column_names[field_name] = field_name.lower().replace(' ', '_')

    # Rename columns in data
    renamed_data = []
    for row in records:
        new_row = {new_column_names[k]: normalize_missing_value(v) for k, v in row.items()}
        renamed_data.append(new_row)

    new_fieldnames = [new_column_names[f] for f in ordered_fields]

    tsv_path = output_dir / f"{dataset_id}.tsv"
    with open(tsv_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=new_fieldnames, delimiter='\t')
        writer.writeheader()
        for row in renamed_data:
            ordered_row = {new_column_names[f]: row.get(new_column_names[f], '') for f in ordered_fields}
            writer.writerow(ordered_row)

    schema_fields = []
    sys_typedef_rows = []

    field_info_by_name = {field_name: (field_type, field_length, decimals) for field_name, field_type, field_length, decimals in fields}

    for field_name in ordered_fields:
        field_type, field_length, decimals = field_info_by_name[field_name]
        new_field_name = new_column_names[field_name]

        # Map DBF type to Spark type
        if field_type == 'N':
            if decimals > 0:
                spark_type = 'DoubleType'
            else:
                spark_type = 'IntegerType'
        elif field_type == 'C':
            spark_type = 'StringType'
        else:
            spark_type = 'StringType'

        # Add to sys_typedef
        unit_str = emi_bervo_map.get(field_name, {}).get('unit', '')
        uo_term = map_unit_to_uo(unit_str) if unit_str else ''
        unit_name = get_typedef_unit_name(unit_str, uo_terms)

        # Determine dimension info
        if field_name in dimension_1_fields:
            dim_number = 1
            var_number = dimension_1_fields.index(field_name) + 1
            data_type = 'dimension_variable'
        elif field_name in dimension_2_fields:
            dim_number = 2
            var_number = dimension_2_fields.index(field_name) + 1
            data_type = 'dimension_variable'
        else:
            dim_number = ''
            if field_name in data_variable_fields:
                var_number = data_variable_fields.index(field_name) + 1
            else:
                var_number = ''
            data_type = 'variable'

        dim_oterm_id, dim_oterm_name = get_dimension_info(dim_number)
        comment_text = emi_bervo_map.get(field_name, {}).get('combination', field_name)
        comment_text = expand_comment_units(comment_text)
        if field_name in {'Cond.1[mS/', 'Inph.1[ppt'}:
            comment_text = add_comment_note(comment_text, 'excluded from analysis due to noise')
        variable_term_name = primary_term_name(emi_bervo_map.get(field_name, {}).get('combination', ''))

        schema_fields.append({
            'name': new_field_name,
            'spark_type': spark_type,
            'comment': build_schema_comment(comment_text, unit_name)
        })

        sys_typedef_rows.append({
            'ddt_ndarray_id': dataset_id,
            'berdl_column_name': new_field_name,
            'berdl_column_data_type': data_type,
            'scalar_type': spark_type_to_scalar_type(spark_type),
            'foreign_key': '',
            'comment': comment_text,
            'unit_sys_oterm_id': uo_term or '',
            'unit_sys_oterm_name': unit_name,
            'dimension_number': dim_number,
            'dimension_oterm_id': dim_oterm_id,
            'dimension_oterm_name': dim_oterm_name,
            'variable_number': var_number,
            'variable_oterm_id': emi_bervo_map.get(field_name, {}).get('term', ''),
            'variable_oterm_name': variable_term_name,
            'original_description': emi_bervo_map.get(field_name, {}).get('definition', '')
        })

    schema_lines = build_schema_lines(schema_fields)
    schema_path = output_dir / f"{dataset_id}_schema.py"
    with open(schema_path, 'w') as f:
        f.writelines(schema_lines)

    # Generate ddt_ndarray.tsv
    ddt_ndarray_path = output_dir / f"{dataset_id}_ddt_ndarray.tsv"
    with open(ddt_ndarray_path, 'w', newline='') as f:
        writer = csv.writer(f, delimiter='\t')
        writer.writerow([
            'ddt_ndarray_id', 'ddt_ndarray_name', 'ddt_ndarray_description',
            'ddt_ndarray_metadata', 'ddt_ndarray_type_sys_oterm_id',
            'ddt_ndarray_type_sys_oterm_name', 'ddt_ndarray_shape',
            'ddt_ndarray_dimension_types_sys_oterm_id',
            'ddt_ndarray_dimension_types_sys_oterm_name',
            'ddt_ndarray_dimension_variable_types_sys_oterm_id',
            'ddt_ndarray_dimension_variable_types_sys_oterm_name',
            'ddt_ndarray_variable_types_sys_oterm_id',
            'ddt_ndarray_variable_types_sys_oterm_name',
            'withdrawn_date', 'superceded_by_ddt_ndarray_id'
        ])
        writer.writerow([
            dataset_id,
            build_ddt_name(dataset_id),
            'Electromagnetic Induction survey using CMD Mini-Explorer at 30 kHz, measuring soil electrical conductivity and in-phase response at three depths (0.5m, 1.0m, 1.8m), East River, CO 2018',
            json_cell([
                ["Location <bervo:BERVO_8000394>", "East River, CO"],
                ["Time <bervo:BERVO_8000238>", "2018"],
                ["Date, Context=Start <bervo:BERVO_8000239>", "2018-06-14"],
                ["Date, Context=End <bervo:BERVO_8000239>", "2018-06-28"],
                ["Instrument", "CMD Mini-Explorer (GF Instruments)"],
                ["Frequency", "30 kHz"],
                ["Depths", "0.5m, 1.0m, 1.8m"],
                ["Projected coordinate system", "UTM Zone 13N"]
            ]),
            'BERVO:0000916',
            'Soil electrical conductivity',
            f'[{len(records)}]',
            '["BERVO:8000394", "BERVO:8000238"]',
            '["Location", "Time"]',
            '[["BERVO:8000441", "BERVO:8000440", "BERVO:8000099", "BERVO:8000519", "BERVO:8000528"], ["BERVO:8000238"]]',
            '[["Northing", "Easting", "Altitude", "Region", "Identifier"], ["Time"]]',
            '["BERVO:0000916", "BERVO:8000553"]',
            '["Soil electrical conductivity", "Electromagnetic in-phase response"]',
            '',
            ''
        ])

    # Generate sys_ddt_typedef.tsv
    sys_typedef_path = output_dir / f"{dataset_id}_sys_ddt_typedef.tsv"
    with open(sys_typedef_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'ddt_ndarray_id', 'berdl_column_name', 'berdl_column_data_type',
            'scalar_type', 'foreign_key', 'comment', 'unit_sys_oterm_id',
            'unit_sys_oterm_name', 'dimension_number', 'dimension_oterm_id',
            'dimension_oterm_name', 'variable_number', 'variable_oterm_id',
            'variable_oterm_name', 'original_description'
        ], delimiter='\t')
        writer.writeheader()
        writer.writerows([normalize_bervo_value(row) for row in sys_typedef_rows])

    print(f"✓ Created {dataset_id}:")
    print(f"  - {tsv_path.name} ({len(records)} records, {len(new_fieldnames)} columns)")
    print(f"  - {schema_path.name}")
    print(f"  - {ddt_ndarray_path.name}")
    print(f"  - {sys_typedef_path.name}")


def main():
    base_dir = Path('/h/jmc/data/bioepic/chess')
    output_dir = base_dir / 'ontologized_datasets'
    output_dir.mkdir(exist_ok=True)

    print("=" * 80)
    print("CONVERTING CHESS DATASETS TO ONTOLOGIZED FORMAT")
    print("=" * 80)
    print()

    # Convert TDR dataset
    print("Converting TDR plot data...")
    convert_tdr_dataset(base_dir, output_dir)
    print()

    # Convert EMI dataset
    print("Converting EMI survey data...")
    convert_emi_dataset(base_dir, output_dir)
    print()

    print("=" * 80)
    print("✓ CONVERSION COMPLETE")
    print("=" * 80)
    print(f"\nOutput directory: {output_dir}")
    print("\nFiles created:")
    for f in sorted(output_dir.glob("*")):
        print(f"  {f.name}")


if __name__ == "__main__":
    main()
