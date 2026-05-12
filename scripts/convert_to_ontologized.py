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
import tarfile
from pathlib import Path


def load_uo_terms():
    """Load UO ontology terms for unit name mapping."""
    try:
        with open('/tmp/uo_terms.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        terms = {}
        uo_path = Path(__file__).resolve().parents[1] / 'ontologies' / 'uo' / 'uo.obo'
        current_id = None
        current_name = None
        if not uo_path.exists():
            return terms
        with uo_path.open('r', encoding='utf-8') as f:
            for raw_line in f:
                line = raw_line.strip()
                if line == '[Term]':
                    if current_id and current_name:
                        terms[current_id] = current_name
                    current_id = None
                    current_name = None
                elif line.startswith('id: UO:'):
                    current_id = line.split('id: ', 1)[1]
                elif line.startswith('name: '):
                    current_name = line.split('name: ', 1)[1]
            if current_id and current_name:
                terms[current_id] = current_name
        return terms


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
        'meters': 'UO:0000008',
        'metre': 'UO:0000008',
        'metres': 'UO:0000008',
        'cm': 'UO:0000015',
        'centimeter': 'UO:0000015',
        'centimeters': 'UO:0000015',
        'centimetre': 'UO:0000015',
        'centimetres': 'UO:0000015',
        'celsius': 'UO:0000027',
        'celsius (°c)': 'UO:0000027',
        '°c': 'UO:0000027',
        'degree celsius': 'UO:0000027',
        'degree': 'UO:0000185',
        'degrees': 'UO:0000185',
        'decimal degree': 'UO:0000185',
        'decimal degrees': 'UO:0000185',
        '%': 'UO:0000187',
        'percent': 'UO:0000187',
        'ph': 'UO:0000196',
        'dimensionless': 'UO:0000186',
        'dimensionless unit': 'UO:0000186',
        'milligram per kilogram': 'UO:0000308',
        'milligrams per kilogram': 'UO:0000308',
        'mg/kg': 'UO:0000308',
        'microgram per gram': 'UO:0000308',
        'micrograms per gram': 'UO:0000308',
        'microgram per gram dry soil': 'UO:0000308',
        'micrograms per gram dry soil': 'UO:0000308',
        'ug/g': 'UO:0000308',
        'µg/g': 'UO:0000308',
        'byte': 'UO:0000233',
        'bytes': 'UO:0000233',
        'count': 'UO:0000189',
        'count unit': 'UO:0000189',
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
    try:
        if float(text) in {-999.0, -9999.0}:
            return ''
    except ValueError:
        pass
    if text.lower() in {
        '',
        'n/a',
        'na',
        'nan',
        'null',
        'none',
        '-999',
        '-999.0',
        '-9999',
        '-9999.0',
    }:
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
        ('.', '_'),
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


TYPEDEF_FIELDNAMES = [
    'ddt_ndarray_id', 'berdl_column_name', 'berdl_column_data_type',
    'scalar_type', 'foreign_key', 'comment', 'unit_sys_oterm_id',
    'unit_sys_oterm_name', 'dimension_number', 'dimension_oterm_id',
    'dimension_oterm_name', 'variable_number', 'variable_oterm_id',
    'variable_oterm_name', 'original_description'
]


DDT_NDARRAY_FIELDNAMES = [
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
]


SOIL_DIMENSIONS = {
    1: ('BERVO:8000342', 'Environmental sample', 'environmental_sample'),
    2: ('BERVO:8000394', 'Location', 'location'),
    3: ('BERVO:8000238', 'Time', 'time'),
    4: ('BERVO:8000409', 'Genome', 'genome'),
}


FIELD_SAMPLING_DIMENSIONS = {
    1: ('BERVO:8000342', 'Environmental sample', 'environmental_sample'),
    2: ('BERVO:8000394', 'Location', 'location'),
    3: ('BERVO:8000238', 'Time', 'time'),
    4: ('BERVO:8000324', 'Taxon', 'taxon'),
}


LAI_DIMENSIONS = {
    1: ('BERVO:8000394', 'Location', 'location'),
    2: ('BERVO:8000238', 'Time', 'time'),
    3: ('BERVO:8000324', 'Taxon', 'taxon'),
    4: ('BERVO:8000443', 'Position', 'position'),
}


SOIL_INFERRED_UNITS = {
    # The NMDC data dictionary leaves these as N/A, but the reported values
    # include units or have standard coordinate/depth units.
    'water content': 'percent',
    'sample storage temperature': 'degree Celsius',
    'depth, meters': 'meter',
    'elevation, meters': 'meter',
    'geographic location (latitude and longitude)': 'degree',
    'pH': 'pH',
    'Latitude': 'degree',
    'Longitude': 'degree',
    'Depth in core max': 'meter',
    # Source values are reported as ug/g dry soil; numerically this is mg/kg.
    'microbial biomass carbon': 'milligram per kilogram',
    'microbial biomass nitrogen': 'milligram per kilogram',
    'ammonium nitrogen': 'milligram per kilogram',
    'nitrate_nitrogen': 'milligram per kilogram',
}


SOIL_DD_SOURCE_ALIASES = {
    'Primary physiographic feature': 'Primary Physiographic feature',
    'Field program/cruise': 'Field program/Cruise',
}


SOIL_DD_EXTRA_SOURCE_DEFINITIONS = {
    'Material': ('Material of the collected sample.', 'text'),
    'Description': ('Free-text description of the collected sample.', 'text'),
    'Location description': ('Description of the sample collection location.', 'text'),
    'City/Township': ('City or township associated with the sample.', 'text'),
    'State/Province': ('State or province associated with the sample.', 'text'),
    'Current Archive': ('Current archive where the sample is held.', 'text'),
    'Current archive contact': ('Contact for the current sample archive.', 'text'),
}


SOIL_ARRAY_METADATA_SOURCES = {
    'analysis/data type',
    'environmental medium',
    'depth, meters',
    'growth facility',
    'storage conditions',
    'broad-scale environmental context',
    'local environmental context',
    'ecosystem',
    'ecosystem_category',
    'ecosystem_type',
    'ecosystem_subtype',
    'specific_ecosystem',
    'geographic location (country and/or sea,region)',
    'sample storage temperature',
    'water content method',
    'pH method',
    'microbial biomass carbon method',
    'microbial biomass nitrogen method',
    'Material',
    'Description',
    'Collection method',
    'Depth in core max',
    'Navigation type',
    'Primary Physiographic feature',
    'City/Township',
    'State/Province',
    'Country',
    'Release Date',
    'Field program/Cruise',
    'Collector/Chief Scientist',
    'Current Archive',
    'Current archive contact',
}


SOIL_REDUNDANT_SOURCES = {
    'Depth scale',
}


SOIL_MAPPING_REVIEW = {
    'analysis/data type': (
        'Current mapping uses Environmental measurement with an analysis-data-type context.',
        'Analysis data type',
    ),
    'growth facility': (
        'Current mapping uses Environmental sample location with a growth-facility context.',
        'Growth facility',
    ),
    'storage conditions': (
        'Current mapping uses generic Condition with a sample-storage context.',
        'Sample storage condition',
    ),
    'water content method': (
        'Current mapping uses generic Method with a volumetric-water-content context.',
        'Volumetric water content measurement method',
    ),
    'pH method': (
        'Current mapping uses generic Method with a pH context.',
        'pH measurement method',
    ),
    'microbial biomass carbon': (
        'Current mapping uses generic Biomass plus carbon and dry-soil qualifiers.',
        'Soil microbial biomass carbon content',
    ),
    'microbial biomass nitrogen': (
        'Current mapping uses generic Biomass plus nitrogen and dry-soil qualifiers.',
        'Soil microbial biomass nitrogen content',
    ),
    'microbial biomass carbon method': (
        'Current mapping uses generic Method with a microbial-biomass-carbon context.',
        'Microbial biomass carbon measurement method',
    ),
    'microbial biomass nitrogen method': (
        'Current mapping uses generic Method with a microbial-biomass-nitrogen context.',
        'Microbial biomass nitrogen measurement method',
    ),
    'ammonium nitrogen': (
        'Current mapping uses Ammonium plus nitrogen and dry-soil qualifiers.',
        'Soil ammonium nitrogen content',
    ),
    'nitrate_nitrogen': (
        'Current mapping uses Nitrate plus nitrogen and dry-soil qualifiers.',
        'Soil nitrate nitrogen content',
    ),
    'Collection method': (
        'Current mapping uses generic Method with a sample-collection context.',
        'Environmental sample collection method',
    ),
    'Depth scale': (
        'Source values are unit metadata; current mapping as Method is weak.',
        'Depth measurement unit',
    ),
    'Navigation type': (
        'Current mapping uses generic Method with a navigation context.',
        'Navigation method',
    ),
    'Description': (
        'Current mapping uses generic Comment with a sample-description context.',
        'Environmental sample description',
    ),
    'Field program/cruise': (
        'Current mapping uses generic Identifier with a field-program context.',
        'Field program identifier',
    ),
    'Collector/Chief Scientist': (
        'Current mapping uses generic Identifier with a collector context.',
        'Collector identifier',
    ),
    'Current Archive': (
        'Current mapping uses generic Identifier with an archive context.',
        'Archive identifier',
    ),
    'Current archive contact': (
        'Current mapping uses generic Identifier with an archive-contact context.',
        'Archive contact identifier',
    ),
}


def normalize_column_token(text):
    """Normalize arbitrary labels to BERDL-safe column name fragments."""
    text = normalize_bervo_curie(str(text or '')).replace('µ', 'u')
    text = re.sub(r'\[[^\]]*\]', '', text)
    text = text.lower()
    text = re.sub(r'[^a-z0-9]+', '_', text)
    text = re.sub(r'_+', '_', text).strip('_')
    return text


def ensure_unique_column_name(candidate, used_names, source_name):
    """Keep generated ontology-based column names unique within a table."""
    base = normalize_column_token(candidate) or normalize_column_token(source_name)
    name = base
    if name not in used_names:
        used_names.add(name)
        return name

    source_suffix = normalize_column_token(source_name)
    if source_suffix and source_suffix not in name:
        name = f"{base}_{source_suffix}"
        if name not in used_names:
            used_names.add(name)
            return name

    counter = 2
    while f"{base}_{counter}" in used_names:
        counter += 1
    name = f"{base}_{counter}"
    used_names.add(name)
    return name


def parse_first_float(value):
    """Extract the first numeric token from mixed numeric/unit fields."""
    normalized = normalize_missing_value(value)
    if normalized == '':
        return ''
    match = re.search(r'-?\d+(?:\.\d+)?', str(normalized).replace(',', ''))
    if not match:
        return ''
    number = match.group(0)
    if float(number) in {-999.0, -9999.0}:
        return ''
    return number


def parse_latitude(value):
    parts = str(normalize_missing_value(value)).split()
    return parts[0] if len(parts) >= 2 else ''


def parse_longitude(value):
    parts = str(normalize_missing_value(value)).split()
    return parts[1] if len(parts) >= 2 else ''


def parse_depth_start(value):
    parts = re.findall(r'-?\d+(?:\.\d+)?', str(normalize_missing_value(value)))
    return parts[0] if parts else ''


def parse_depth_end(value):
    parts = re.findall(r'-?\d+(?:\.\d+)?', str(normalize_missing_value(value)))
    return parts[-1] if parts else ''


def read_csv_records(path, skip_rows=0):
    with path.open('r', encoding='utf-8-sig', newline='') as f:
        for _ in range(skip_rows):
            next(f)
        reader = csv.DictReader(f)
        return list(reader), reader.fieldnames


def load_dd_definitions(dd_path):
    definitions = {}
    units = {}
    data_types = {}
    with dd_path.open('r', encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            col = row['column_or_row_name']
            definitions[col] = row.get('definition', '')
            units[col] = row.get('unit', '')
            data_types[col] = row.get('data_type', '')
    return definitions, units, data_types


def make_spec(source, combination, term, *, dimension_number='', unit='',
              spark_type='StringType', transform=None, output_name=None,
              original_description=''):
    return {
        'source': source,
        'combination': combination,
        'term': term,
        'dimension_number': dimension_number,
        'unit': unit,
        'spark_type': spark_type,
        'transform': transform,
        'output_name': output_name,
        'original_description': original_description,
    }


def metadata_label_for_spec(spec):
    """Build a metadata label from an ontologized column spec."""
    combination = expand_comment_units(spec.get('combination', ''))
    term = spec.get('term', '')
    if term:
        return f"{combination} <{term}>"
    return combination


def metadata_value_for_constant(value, spec, uo_terms):
    """Include unit names for constant numeric metadata when a spec has units."""
    unit_name = get_typedef_unit_name(spec.get('unit', ''), uo_terms)
    if unit_name:
        return f"{value} {unit_name}"
    return value


def transformed_spec_value(spec, record):
    transform = spec.get('transform')
    if transform:
        value = transform(record)
    else:
        value = record.get(spec['source'], '')
    return normalize_missing_value(value)


def constant_spec_value(records, spec):
    """Return the value when every record has the same non-empty spec value."""
    if not records:
        return None
    values = [transformed_spec_value(spec, record) for record in records]
    if any(value == '' for value in values):
        return None
    unique_values = {str(value) for value in values}
    if len(unique_values) != 1:
        return None
    return str(values[0])


def get_soil_mapping_definitions():
    """Mappings for soil metagenome metadata fields that are imported or documented."""
    return {
        'sample name': ('Identifier, Context = environmental sample', 'BERVO:8000528'),
        'Sample Name': ('Identifier, Context = environmental sample', 'BERVO:8000528'),
        'source material identifier': ('Identifier, Context = source material', 'BERVO:8000528'),
        'IGSN': ('Identifier, Context = source material', 'BERVO:8000528'),
        'analysis/data type': ('Environmental measurement, Context = analysis data type', 'BERVO:8000412'),
        'sample linkage': ('Identifier, Context = sample linkage', 'BERVO:8000528'),
        'broad-scale environmental context': ('Environmental feature, Context = broad scale', 'BERVO:8000400'),
        'local environmental context': ('Environmental feature, Context = local', 'BERVO:8000400'),
        'environmental medium': ('Environmental material', 'BERVO:8000402'),
        'Material': ('Environmental material', 'BERVO:8000402'),
        'ecosystem': ('Ecosystem', 'BERVO:8000043'),
        'ecosystem_category': ('Ecosystem, Context = category', 'BERVO:8000043'),
        'ecosystem_type': ('Ecosystem, Context = type', 'BERVO:8000043'),
        'ecosystem_subtype': ('Ecosystem, Context = subtype', 'BERVO:8000043'),
        'specific_ecosystem': ('Ecosystem, Context = specific', 'BERVO:8000043'),
        'slope aspect': ('Slope, Context = aspect', 'BERVO:8000031'),
        'slope gradient': ('Slope, Context = gradient', 'BERVO:8000031'),
        'mean annual precipitation': ('Precipitation, statistic = mean annual', 'BERVO:8000032'),
        'average seasonal precipitation': ('Precipitation, statistic = average seasonal', 'BERVO:8000032'),
        'mean annual temperature': ('Temperature, statistic = mean annual', 'BERVO:8000133'),
        'mean seasonal temperature': ('Temperature, statistic = mean seasonal', 'BERVO:8000133'),
        'temperature': ('Temperature, Context = sample collection', 'BERVO:8000133'),
        'sample storage temperature': ('Temperature, Context = sample storage', 'BERVO:8000133'),
        'air temperature regimen': ('Temperature, Context = air regimen', 'BERVO:8000133'),
        'collection date': ('Date, Context = collection', 'BERVO:8000239'),
        'Collection date': ('Date, Context = collection', 'BERVO:8000239'),
        'Sample_Collection_Date': ('Date, Context = collection', 'BERVO:8000239'),
        'Release Date': ('Date, Context = release', 'BERVO:8000239'),
        'collection time, GMT': ('Time, Context = collection', 'BERVO:8000238'),
        'incubation collection date': ('Date, Context = incubation collection', 'BERVO:8000239'),
        'incubation collection time, GMT': ('Time, Context = incubation collection', 'BERVO:8000238'),
        'incubation start date': ('Date, Context = incubation start', 'BERVO:8000239'),
        'incubation start time, GMT': ('Time, Context = incubation start', 'BERVO:8000238'),
        'geographic location (country and/or sea,region)': ('Region, Context = geographic location', 'BERVO:8000519'),
        'geographic location (latitude and longitude)': ('Location, Context = latitude and longitude', 'BERVO:8000394'),
        'Latitude': ('Latitude', 'BERVO:8000395'),
        'Longitude': ('Longitude', 'BERVO:8000396'),
        'elevation, meters': ('Altitude', 'BERVO:8000099'),
        'Depth in core max': ('Depth, Context = core maximum', 'BERVO:8000069'),
        'Depth scale': ('Method, Context = depth scale', 'BERVO:8000303'),
        'depth, meters': ('Depth, Context = sample interval', 'BERVO:8000069'),
        'Country': ('Country', 'BERVO:8000398'),
        'City/Township': ('Region, Context = city', 'BERVO:8000519'),
        'State/Province': ('Region, Context = state', 'BERVO:8000519'),
        'Location description': ('Location, Context = description', 'BERVO:8000394'),
        'Primary Physiographic feature': ('Environmental feature, Context = physiographic', 'BERVO:8000400'),
        'Primary physiographic feature': ('Environmental feature, Context = physiographic', 'BERVO:8000400'),
        'Navigation type': ('Method, Context = navigation', 'BERVO:8000303'),
        'soil_taxonomic/FAO classification': ('Soil type, Context = FAO classification', 'BERVO:8000497'),
        'soil_taxonomic/local classification': ('Soil type, Context = local classification', 'BERVO:8000497'),
        'soil_taxonomic/local classification method': ('Method, Context = local soil classification', 'BERVO:8000303'),
        'soil type': ('Soil type', 'BERVO:8000497'),
        'soil type method': ('Method, Context = soil type', 'BERVO:8000303'),
        'soil horizon': ('Layer, Context = soil horizon', 'BERVO:8000226'),
        'soil horizon method': ('Method, Context = soil horizon', 'BERVO:8000303'),
        'soil texture measurement': ('Soil type, Context = texture', 'BERVO:8000497'),
        'soil texture method': ('Method, Context = soil texture', 'BERVO:8000303'),
        'drainage classification': ('Condition, Context = drainage classification', 'BERVO:8000302'),
        'current land use': ('Environmental sample location, Context = current land use', 'BERVO:8000514'),
        'current vegetation': ('Taxon, Context = current vegetation', 'BERVO:8000324'),
        'current vegetation method': ('Method, Context = vegetation classification', 'BERVO:8000303'),
        'water content': ('Volumetric water content, Context = water filled pore space', 'BERVO:0001743'),
        'water content method': ('Method, Context = volumetric water content', 'BERVO:8000303'),
        'pH': ('pH', 'BERVO:8000261'),
        'pH method': ('Method, Context = pH', 'BERVO:8000303'),
        'microbial biomass': ('Biomass, Context = microbial', 'BERVO:8000296'),
        'microbial biomass method': ('Method, Context = microbial biomass', 'BERVO:8000303'),
        'microbial biomass carbon': ('Biomass, Context = microbial, Element = carbon, Environmental material = dry soil', 'BERVO:8000296'),
        'microbial biomass nitrogen': ('Biomass, Context = microbial, Element = nitrogen, Environmental material = dry soil', 'BERVO:8000296'),
        'microbial biomass carbon method': ('Method, Context = microbial biomass carbon', 'BERVO:8000303'),
        'microbial biomass nitrogen method': ('Method, Context = microbial biomass nitrogen', 'BERVO:8000303'),
        'non-microbial biomass': ('Biomass, Context = non-microbial', 'BERVO:8000296'),
        'non-microbial biomass method': ('Method, Context = non-microbial biomass', 'BERVO:8000303'),
        'carbon/nitrogen ratio': ('Carbon to nitrogen ratio', 'BERVO:8000109'),
        'organic matter': ('Organic matter', 'BERVO:8000286'),
        'organic nitrogen': ('Nitrogen, Context = organic', 'BERVO:8000167'),
        'organic nitrogen method': ('Method, Context = organic nitrogen', 'BERVO:8000303'),
        'total carbon': ('Carbon, statistic = total', 'BERVO:8000075'),
        'total nitrogen content': ('Nitrogen, statistic = total', 'BERVO:8000167'),
        'total nitrogen content method': ('Method, Context = total nitrogen', 'BERVO:8000303'),
        'total organic carbon': ('Soil organic carbon content', 'BERVO:0001523'),
        'total organic carbon method': ('Method, Context = soil organic carbon', 'BERVO:8000303'),
        'total phosphorus': ('Phosphorus, statistic = total', 'BERVO:8000001'),
        'phosphate': ('Phosphate', 'BERVO:8000138'),
        'salinity': ('Salinity', 'BERVO:8000427'),
        'salinity method': ('Method, Context = salinity', 'BERVO:8000303'),
        'ammonium nitrogen': ('Ammonium, Element = nitrogen, Environmental material = dry soil', 'BERVO:8000113'),
        'nitrate_nitrogen': ('Nitrate, Element = nitrogen, Environmental material = dry soil', 'BERVO:8000168'),
        'nitrite_nitrogen': ('Nitrogen, Context = nitrite', 'BERVO:8000167'),
        'bulk electrical conductivity': ('Conductivity, Context = bulk electrical', 'BERVO:8000348'),
        'manganese': ('Element, Context = manganese', 'BERVO:8000220'),
        'zinc': ('Element, Context = zinc', 'BERVO:8000220'),
        'growth facility': ('Environmental sample location, Context = growth facility', 'BERVO:8000514'),
        'storage conditions': ('Condition, Context = sample storage', 'BERVO:8000302'),
        'composite design/sieving': ('Method, Context = composite design and sieving', 'BERVO:8000303'),
        'sample material processing': ('Method, Context = sample material processing', 'BERVO:8000303'),
        'sample collection device': ('Instrument, Context = sample collection', 'BERVO:8000306'),
        'sample collection method': ('Method, Context = sample collection', 'BERVO:8000303'),
        'Collection method': ('Method, Context = sample collection', 'BERVO:8000303'),
        'Description': ('Comment, Context = sample description', 'BERVO:8000305'),
        'Field program/Cruise': ('Identifier, Context = field program', 'BERVO:8000528'),
        'Field program/cruise': ('Identifier, Context = field program', 'BERVO:8000528'),
        'Collector/Chief Scientist': ('Identifier, Context = collector', 'BERVO:8000528'),
        'Current Archive': ('Identifier, Context = archive', 'BERVO:8000528'),
        'Current archive contact': ('Identifier, Context = archive contact', 'BERVO:8000528'),
        'links to additional analysis': ('Identifier, Context = additional analysis link', 'BERVO:8000528'),
    }


def collect_soil_source_metadata(source_tables):
    """Return source file and non-empty example values for soil source columns."""
    values_by_column = {}
    files_by_column = {}
    for source_file, records in source_tables:
        for record in records:
            for column_name, raw_value in record.items():
                if column_name is None:
                    continue
                values_by_column.setdefault(column_name, []).append(raw_value)
                files_by_column.setdefault(column_name, set()).add(source_file)
    return values_by_column, files_by_column


def nonempty_source_values(values):
    cleaned = []
    for value in values:
        normalized = normalize_missing_value(value)
        if normalized == '':
            continue
        cleaned.append(clean_text(normalized))
    return cleaned


def clean_text(value):
    """Normalize source text for metadata cells."""
    if value is None:
        value = ''
    return re.sub(r'\s+', ' ', str(value)).strip()


def sample_source_values(values, limit=5):
    samples = []
    for value in nonempty_source_values(values):
        if value not in samples:
            samples.append(value)
        if len(samples) >= limit:
            break
    return ' | '.join(samples)


def soil_dd_status(column_name, source_column, source_values, row_sources,
                   metadata_sources, redundant_sources, structural_fields):
    if column_name in structural_fields:
        return 'data_dictionary_metadata'
    if source_column in row_sources:
        return 'used_in_berdl_data_table'
    if source_column in metadata_sources:
        return 'array_level_metadata'
    if source_column in redundant_sources:
        return 'redundant_to_typed_unit'
    if source_values is None:
        return 'unused_no_source_column'
    if not nonempty_source_values(source_values):
        return 'unused_empty_source_column'
    return 'unused_not_selected_for_berdl'


def write_soil_dd_bervo(base_dir, field_mappings, row_sources, metadata_sources,
                        redundant_sources, source_tables):
    """Regenerate soil_metagenomes/dd_bervo.csv from dd.csv plus local mappings."""
    dd_path = base_dir / 'soil_metagenomes' / 'dd.csv'
    out_path = base_dir / 'soil_metagenomes' / 'dd_bervo.csv'
    structural_fields = {
        'file_name', 'file_description', 'standard', 'column_or_row_name',
        'unit', 'definition', 'data_type', 'missing_value_code'
    }
    values_by_column, files_by_column = collect_soil_source_metadata(source_tables)
    written_source_columns = set()

    fieldnames = [
        'column_or_row_name', 'BERVO Combination', 'BERVO Term',
        'unit', 'definition', 'data_type', 'source_file', 'berdl_export_status',
        'nonempty_value_count', 'sample_values', 'mapping_notes',
        'proposed_bervo_term'
    ]

    def build_output_row(row, *, source_column=None):
        col = row['column_or_row_name']
        source_column = source_column or SOIL_DD_SOURCE_ALIASES.get(col, col)
        written_source_columns.add(source_column)
        mapping = field_mappings.get(col) or field_mappings.get(source_column)
        if col in structural_fields:
            combo = 'unnecessary?'
            term = ''
        elif mapping:
            combo, term = mapping
        else:
            combo = ''
            term = ''

        values = values_by_column.get(source_column)
        cleaned_values = nonempty_source_values(values or [])
        status = soil_dd_status(
            col, source_column, values, row_sources, metadata_sources,
            redundant_sources, structural_fields
        )
        notes, proposed_term = SOIL_MAPPING_REVIEW.get(col) or SOIL_MAPPING_REVIEW.get(source_column) or ('', '')
        if status != 'used_in_berdl':
            notes = ''
            proposed_term = ''

        return {
            'column_or_row_name': col,
            'BERVO Combination': normalize_bervo_curie(combo),
            'BERVO Term': normalize_bervo_curie(term),
            'unit': SOIL_INFERRED_UNITS.get(col, SOIL_INFERRED_UNITS.get(source_column, normalize_missing_value(row.get('unit', '')))),
            'definition': row.get('definition', ''),
            'data_type': row.get('data_type', ''),
            'source_file': ';'.join(sorted(files_by_column.get(source_column, []))),
            'berdl_export_status': status,
            'nonempty_value_count': len(cleaned_values) if values is not None else '',
            'sample_values': sample_source_values(values or []) if status in {
                'used_in_berdl_data_table',
                'array_level_metadata',
                'redundant_to_typed_unit',
            } else '',
            'mapping_notes': notes,
            'proposed_bervo_term': proposed_term,
        }

    with dd_path.open('r', encoding='utf-8-sig', newline='') as in_f, out_path.open('w', encoding='utf-8', newline='') as out_f:
        reader = csv.DictReader(in_f)
        writer = csv.DictWriter(out_f, fieldnames=fieldnames)
        writer.writeheader()
        for row in reader:
            writer.writerow(build_output_row(row))

        documented_sources = written_source_columns | set(SOIL_DD_SOURCE_ALIASES.values())
        documented_review_sources = row_sources | metadata_sources | redundant_sources
        for source_column in sorted(documented_review_sources - documented_sources):
            definition, data_type = SOIL_DD_EXTRA_SOURCE_DEFINITIONS.get(source_column, ('', 'text'))
            writer.writerow(build_output_row({
                'column_or_row_name': source_column,
                'unit': SOIL_INFERRED_UNITS.get(source_column, ''),
                'definition': definition,
                'data_type': data_type,
            }, source_column=source_column))


def write_generic_ontologized_table(dataset_id, records, specs, output_dir,
                                    description, metadata_items,
                                    table_type_id, table_type_name,
                                    dimensions=None):
    """Write TSV, schema.py, ddt_ndarray.tsv, and sys_ddt_typedef.tsv for one table."""
    uo_terms = load_uo_terms()
    dimensions = dimensions or SOIL_DIMENSIONS
    metadata_items = list(metadata_items)
    used_names = set()
    column_specs = []

    for spec in specs:
        dim_number = spec.get('dimension_number') or ''
        dim_prefix = ''
        if dim_number:
            dim_prefix = dimensions[int(dim_number)][2]
        candidate = spec.get('output_name') or bervo_combination_to_column_name(
            spec['combination'], spec.get('unit', ''), dim_prefix, uo_terms
        )
        new_name = ensure_unique_column_name(candidate, used_names, spec['source'])
        spec = dict(spec)
        spec['berdl_column_name'] = new_name
        column_specs.append(spec)

    retained_column_specs = []
    for spec in column_specs:
        constant_value = constant_spec_value(records, spec)
        if constant_value is not None:
            metadata_items.append([
                metadata_label_for_spec(spec),
                metadata_value_for_constant(constant_value, spec, uo_terms),
            ])
        else:
            retained_column_specs.append(spec)
    column_specs = retained_column_specs

    tsv_path = output_dir / f"{dataset_id}.tsv"
    with tsv_path.open('w', newline='', encoding='utf-8') as f:
        fieldnames = [spec['berdl_column_name'] for spec in column_specs]
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter='\t')
        writer.writeheader()
        for record in records:
            out_row = {}
            for spec in column_specs:
                out_row[spec['berdl_column_name']] = transformed_spec_value(spec, record)
            writer.writerow(out_row)

    schema_fields = []
    sys_typedef_rows = []
    variable_counter = 0
    dimension_counters = {}
    dimension_ids_by_number = {}
    dimension_names_by_number = {}
    dimension_variable_ids = {}
    dimension_variable_names = {}
    variable_ids = []
    variable_names = []

    for spec in column_specs:
        dim_number = spec.get('dimension_number') or ''
        if dim_number:
            dim_number = int(dim_number)
            dimension_counters[dim_number] = dimension_counters.get(dim_number, 0) + 1
            var_number = dimension_counters[dim_number]
            data_type = 'dimension_variable'
            dim_oterm_id, dim_oterm_name, _ = dimensions[dim_number]
            dimension_ids_by_number[dim_number] = dim_oterm_id
            dimension_names_by_number[dim_number] = dim_oterm_name
            dimension_variable_ids.setdefault(dim_number, []).append(spec['term'])
            dimension_variable_names.setdefault(dim_number, []).append(primary_term_name(spec['combination']))
        else:
            variable_counter += 1
            var_number = variable_counter
            data_type = 'variable'
            dim_oterm_id = ''
            dim_oterm_name = ''
            variable_ids.append(spec['term'])
            variable_names.append(primary_term_name(spec['combination']))

        unit_str = spec.get('unit', '')
        uo_term = map_unit_to_uo(unit_str) if unit_str else ''
        unit_name = get_typedef_unit_name(unit_str, uo_terms)
        comment_text = expand_comment_units(spec['combination'])
        schema_fields.append({
            'name': spec['berdl_column_name'],
            'spark_type': spec['spark_type'],
            'comment': build_schema_comment(comment_text, unit_name)
        })
        sys_typedef_rows.append({
            'ddt_ndarray_id': dataset_id,
            'berdl_column_name': spec['berdl_column_name'],
            'berdl_column_data_type': data_type,
            'scalar_type': spark_type_to_scalar_type(spec['spark_type']),
            'foreign_key': '',
            'comment': comment_text,
            'unit_sys_oterm_id': uo_term or '',
            'unit_sys_oterm_name': unit_name,
            'dimension_number': dim_number or '',
            'dimension_oterm_id': dim_oterm_id,
            'dimension_oterm_name': dim_oterm_name,
            'variable_number': var_number,
            'variable_oterm_id': spec['term'],
            'variable_oterm_name': primary_term_name(spec['combination']),
            'original_description': spec.get('original_description', '')
        })

    schema_path = output_dir / f"{dataset_id}_schema.py"
    with schema_path.open('w', encoding='utf-8') as f:
        f.writelines(build_schema_lines(schema_fields))

    dimension_numbers = sorted(dimension_ids_by_number)
    unique_variable_ids = []
    unique_variable_names = []
    for term_id, term_name in zip(variable_ids, variable_names):
        if term_id not in unique_variable_ids:
            unique_variable_ids.append(term_id)
            unique_variable_names.append(term_name)

    ddt_row = {
        'ddt_ndarray_id': dataset_id,
        'ddt_ndarray_name': build_ddt_name(dataset_id),
        'ddt_ndarray_description': description,
        'ddt_ndarray_metadata': json_cell(metadata_items),
        'ddt_ndarray_type_sys_oterm_id': table_type_id,
        'ddt_ndarray_type_sys_oterm_name': table_type_name,
        'ddt_ndarray_shape': f'[{len(records)}]',
        'ddt_ndarray_dimension_types_sys_oterm_id': json_cell([dimension_ids_by_number[n] for n in dimension_numbers]),
        'ddt_ndarray_dimension_types_sys_oterm_name': json_cell([dimension_names_by_number[n] for n in dimension_numbers]),
        'ddt_ndarray_dimension_variable_types_sys_oterm_id': json_cell([dimension_variable_ids[n] for n in dimension_numbers]),
        'ddt_ndarray_dimension_variable_types_sys_oterm_name': json_cell([dimension_variable_names[n] for n in dimension_numbers]),
        'ddt_ndarray_variable_types_sys_oterm_id': json_cell(unique_variable_ids),
        'ddt_ndarray_variable_types_sys_oterm_name': json_cell(unique_variable_names),
        'withdrawn_date': '',
        'superceded_by_ddt_ndarray_id': ''
    }

    ddt_ndarray_path = output_dir / f"{dataset_id}_ddt_ndarray.tsv"
    with ddt_ndarray_path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=DDT_NDARRAY_FIELDNAMES, delimiter='\t')
        writer.writeheader()
        writer.writerow(normalize_bervo_value(ddt_row))

    sys_typedef_path = output_dir / f"{dataset_id}_sys_ddt_typedef.tsv"
    with sys_typedef_path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=TYPEDEF_FIELDNAMES, delimiter='\t')
        writer.writeheader()
        writer.writerows([normalize_bervo_value(row) for row in sys_typedef_rows])

    print(f"✓ Created {dataset_id}:")
    print(f"  - {tsv_path.name} ({len(records)} records, {len(column_specs)} columns)")
    print(f"  - {schema_path.name}")
    print(f"  - {ddt_ndarray_path.name}")
    print(f"  - {sys_typedef_path.name}")


def load_field_metadata_key(field_dir):
    """Load the 2018 field-sampling metadata_column_key.csv as a source dictionary."""
    rows = []
    by_key = {}
    with (field_dir / 'metadata_column_key.csv').open('r', encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            csv_name = clean_text(row.get('csv', '')).removesuffix('.csv')
            column = clean_text(row.get('column', ''))
            description = clean_text(row.get('description', ''))
            normalized = {
                'csv': csv_name,
                'column': column,
                'description': description,
            }
            rows.append(normalized)
            by_key[(csv_name, column)] = description
    return rows, by_key


def field_description(metadata_key, csv_name, column, fallback=''):
    description = metadata_key.get((csv_name, column), '')
    return description or fallback or column


def load_sampling_area_lookup(field_dir):
    lookup = {}
    with (field_dir / 'sampling_area.csv').open('r', encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = clean_text(row.get('ShortName', ''))
            if not code:
                continue
            lookup[code] = {
                'full_name': clean_text(row.get('FullName', '')),
                'state': clean_text(row.get('State', '')),
                'country': clean_text(row.get('Country', '')),
            }
    return lookup


def sampling_area_full_name(row, sampling_areas):
    return sampling_area_field(row, sampling_areas, 'full_name')


def sampling_area_field(row, sampling_areas, field_name):
    code = clean_text(normalize_missing_value(row.get('SamplingArea', '')))
    if not code:
        return ''
    return sampling_areas.get(code, {}).get(field_name) or ''


def load_species_lookup(field_dir):
    """Return cover-code lookups resolved to species-list metadata."""
    lookup = {}
    lower_lookup = {}

    def clean_taxon_value(value):
        value = clean_text(value)
        return '' if value.upper() == 'NA' else value

    def add_lookup(code, detail):
        if not code:
            return
        lookup[code] = detail
        lower_lookup[code.lower()] = detail

    with (field_dir / 'species_list.csv').open('r', encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            cover_code = clean_text(row.get('CoverCode', ''))
            alt_code = clean_text(row.get('AltFieldCode', ''))
            detail = {
                'cover_code': cover_code,
                'family': clean_taxon_value(row.get('Family', '')),
                'genus': clean_taxon_value(row.get('Genus', '')),
                'species': clean_taxon_value(row.get('Species', '')),
                'alt_field_code': alt_code,
                'notes': clean_text(row.get('Notes', '')),
            }

            add_lookup(cover_code, detail)
            add_lookup(alt_code, detail)

    # Obvious one-off field-code variants seen in fractional_cover.csv.
    if 'Gooseberry' in lookup:
        ribes = dict(lookup['Gooseberry'])
        ribes['cover_code'] = 'RibMon'
        base_note = ribes.get('notes', '')
        ribes['notes'] = f"{base_note}; species-list mapping inferred from Gooseberry code" if base_note else 'species-list mapping inferred from Gooseberry code'
        add_lookup('RibMon', ribes)
    if 'Raspberry' in lookup:
        rubus = dict(lookup['Raspberry'])
        rubus['cover_code'] = 'RubIda'
        base_note = rubus.get('notes', '')
        rubus['notes'] = f"{base_note}; species-list mapping inferred from Raspberry code" if base_note else 'species-list mapping inferred from Raspberry code'
        add_lookup('RubIda', rubus)
    return lookup, lower_lookup


def cover_label(row, species_lookup, species_lower_lookup):
    detail = cover_detail(row, species_lookup, species_lower_lookup)
    if not detail:
        return clean_text(normalize_missing_value(row.get('CoverCode', '')))
    taxon_parts = [detail.get('genus', ''), detail.get('species', '')]
    taxon_label = ' '.join(part for part in taxon_parts if part)
    return taxon_label or detail.get('family') or detail.get('notes') or clean_text(normalize_missing_value(row.get('CoverCode', '')))


def cover_detail(row, species_lookup, species_lower_lookup):
    code = clean_text(normalize_missing_value(row.get('CoverCode', '')))
    if not code:
        return {}
    return (
        species_lookup.get(code)
        or species_lower_lookup.get(code.lower())
        or {}
    )


def cover_detail_value(row, species_lookup, species_lower_lookup, field_name):
    if field_name == 'source_cover_code':
        return clean_text(normalize_missing_value(row.get('CoverCode', '')))
    return cover_detail(row, species_lookup, species_lower_lookup).get(field_name, '')


def field_sampling_date(row):
    year = clean_text(normalize_missing_value(row.get('Year', '')))
    month = clean_text(normalize_missing_value(row.get('Month', '')))
    day = clean_text(normalize_missing_value(row.get('Day', '')))
    if not (year and month and day):
        return ''
    try:
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    except ValueError:
        return ''


def fractional_collection_date(row):
    value = clean_text(normalize_missing_value(row.get('CollectionDate', '')))
    if not value:
        return ''
    parts = value.split('/')
    if len(parts) != 3:
        return value
    try:
        month, day, year = (int(part) for part in parts)
    except ValueError:
        return value
    if year < 100:
        year += 2000
    return f"{year:04d}-{month:02d}-{day:02d}"


def date_range(records, date_func):
    dates = sorted({date_func(record) for record in records if date_func(record)})
    if not dates:
        return ''
    if len(dates) == 1:
        return dates[0]
    return f"{dates[0]} to {dates[-1]}"


def sample_site_area_lookup(sample_site_records, sampling_areas):
    lookup = {}
    for record in sample_site_records:
        sample_id = clean_text(normalize_missing_value(record.get('SampleSiteCode', '')))
        if sample_id and sample_id not in lookup:
            area_code = clean_text(normalize_missing_value(record.get('SamplingArea', '')))
            lookup[sample_id] = sampling_areas.get(area_code, {})
    return lookup


def sample_site_sampling_area_field(row, sample_site_areas, field_name):
    sample_id = clean_text(normalize_missing_value(row.get('SampleSiteCode', '')))
    return sample_site_areas.get(sample_id, {}).get(field_name, '')


def combined_fractional_note(row):
    notes = [
        clean_text(normalize_missing_value(row.get('Note', ''))),
        clean_text(normalize_missing_value(row.get('', ''))),
    ]
    return '; '.join(note for note in notes if note)


def first_constant(records, source):
    values = sorted({
        clean_text(normalize_missing_value(record.get(source, '')))
        for record in records
        if clean_text(normalize_missing_value(record.get(source, '')))
    })
    return values[0] if len(values) == 1 else ''


def sample_transformed_values(records, transform, limit=5):
    values = []
    for record in records:
        value = clean_text(normalize_missing_value(transform(record)))
        if not value or value in values:
            continue
        values.append(value)
        if len(values) >= limit:
            break
    return ' | '.join(values)


LAI_SPECIES_LOOKUP = {
    'ABLA': {
        'family': 'Pinaceae',
        'genus': 'Abies',
        'species_epithet': 'lasiocarpa',
        'binomial': 'Abies lasiocarpa',
        'ncbi_taxon_id': '34340',
        'gbif_taxon_id': '2685313',
    },
    'PICO': {
        'family': 'Pinaceae',
        'genus': 'Pinus',
        'species_epithet': 'contorta',
        'binomial': 'Pinus contorta',
        'ncbi_taxon_id': '3339',
        'gbif_taxon_id': '5285750',
    },
    'PIEN': {
        'family': 'Pinaceae',
        'genus': 'Picea',
        'species_epithet': 'engelmannii',
        'binomial': 'Picea engelmannii',
        'ncbi_taxon_id': '3334',
        'gbif_taxon_id': '5284917',
    },
    'POTR': {
        'family': 'Salicaceae',
        'genus': 'Populus',
        'species_epithet': 'tremuloides',
        'binomial': 'Populus tremuloides',
        'ncbi_taxon_id': '3693',
        'gbif_taxon_id': '3040215',
    },
    'PSME': {
        'family': 'Pinaceae',
        'genus': 'Pseudotsuga',
        'species_epithet': 'menziesii',
        'binomial': 'Pseudotsuga menziesii',
        'ncbi_taxon_id': '3357',
        'gbif_taxon_id': '',
    },
}


def load_lai_dd_bervo_rows(lai_dir):
    with (lai_dir / 'dd_bervo.csv').open('r', encoding='utf-8-sig', newline='') as f:
        return {row['column_or_row_name']: row for row in csv.DictReader(f)}


def lai_unit_for_spec(row):
    unit = clean_text(normalize_missing_value(row.get('unit', '')))
    return '' if unit == 'YYYY-MM-DD' else unit


def make_lai_spec(dd_rows, row_name, *, source=None, dimension_number='',
                  transform=None, output_name=None, spark_type=None,
                  original_description=None):
    row = dd_rows[row_name]
    if spark_type is None:
        spark_type = 'DoubleType' if row.get('data_type') == 'numeric' else 'StringType'
    return make_spec(
        source or row_name,
        row['BERVO Combination'],
        row['BERVO Term'],
        dimension_number=dimension_number,
        unit=lai_unit_for_spec(row),
        spark_type=spark_type,
        transform=transform,
        output_name=output_name,
        original_description=original_description or row.get('definition', ''),
    )


def parse_lai_sampling_area_label(label):
    label = clean_text(normalize_missing_value(label))
    if not label:
        return '', ''
    if label == 'Ad Hoc Site':
        return label, label
    match = re.match(r'^[^:]+:\s*(.*?)\s*\(([^)]+)\)\s*$', label)
    if not match:
        return '', label
    full_name = clean_text(match.group(1))
    code = clean_text(match.group(2))
    if code == 'RU':
        full_name = 'Taylor River Road'
    return code, full_name


def load_lai_sampling_area_lookup(base_dir):
    lookup = {
        'AU': 'Ancillary aspen understory',
        'Ad Hoc Site': 'Ad Hoc Site',
    }
    veg_dir = base_dir / 'vegetation_attributes_photos'
    for file_name in (
        'chess_tree_site_cleaned.csv',
        'chess_shrub_site_cleaned.csv',
        'chess_meadow_site_cleaned.csv',
    ):
        path = veg_dir / file_name
        if not path.exists():
            continue
        records, _ = read_csv_records(path)
        for record in records:
            code, full_name = parse_lai_sampling_area_label(record.get('Sampling_Area', ''))
            if not code or not full_name:
                continue
            if code == 'RU':
                lookup[code] = 'Taylor River Road'
            else:
                lookup.setdefault(code, full_name)
    return lookup


def lai_sampling_area_full_name(row, sampling_area_lookup):
    code = clean_text(normalize_missing_value(row.get('Sampling_Area', '')))
    if not code:
        return ''
    return sampling_area_lookup.get(code, code)


def lai_species_code(row):
    return clean_text(normalize_missing_value(row.get('Focal_Tree_Species', '')))


def lai_species_lookup_value(row, field_name):
    code = lai_species_code(row)
    if not code:
        return ''
    return LAI_SPECIES_LOOKUP.get(code, {}).get(field_name, '')


def lai_site_key(row):
    return (
        clean_text(normalize_missing_value(row.get('Site_Number', ''))),
        clean_text(normalize_missing_value(row.get('Location_Type', ''))),
        clean_text(normalize_missing_value(row.get('Sampling_Area', ''))),
    )


def load_lai_metadata_records(lai_dir):
    records = []
    for prefix in ('au', 'meadow', 'shrub', 'tree'):
        file_name = f'lai_{prefix}_metadata_cleaned.csv'
        file_records, _ = read_csv_records(lai_dir / file_name)
        for record in file_records:
            row = dict(record)
            row['__source_file'] = file_name
            records.append(row)
    return records


def load_lai_summary_records(lai_dir, metadata_records):
    metadata_by_key = {lai_site_key(record): record for record in metadata_records}
    records = []
    for prefix in ('au', 'meadow', 'shrub', 'tree'):
        file_name = f'lai_{prefix}_summary_data_cleaned.csv'
        file_records, _ = read_csv_records(lai_dir / file_name)
        for record in file_records:
            merged = dict(metadata_by_key.get(lai_site_key(record), {}))
            merged.update(record)
            merged['__source_file'] = file_name
            records.append(merged)
    return records


def lai_date_value(row):
    return clean_text(normalize_missing_value(row.get('Collection_Date', '')))


def convert_leaf_area_index(base_dir, output_dir):
    """Convert CHESS 2025 LAI metadata and summary observations."""
    lai_dir = base_dir / 'leaf_area_index'
    dd_rows = load_lai_dd_bervo_rows(lai_dir)
    sampling_area_lookup = load_lai_sampling_area_lookup(base_dir)
    site_records = load_lai_metadata_records(lai_dir)
    summary_records = load_lai_summary_records(lai_dir, site_records)

    def area_name(row):
        return lai_sampling_area_full_name(row, sampling_area_lookup)

    def species_field(field_name):
        return lambda row: lai_species_lookup_value(row, field_name)

    common_metadata_items = [
        ["Link, Context = dataset DOI <BERVO:8000391>", "10.15485/3022242"],
        ["US state <BERVO:8000439>", "CO"],
        ["Country <BERVO:8000398>", "USA"],
        ["Campaign <BERVO:8000393>", "CHESS 2025"],
        ["Comment, Context = excluded source files <BERVO:8000305>", "spot_checks.csv, raw_lai_2200C.zip, intermediate_results.zip, and scattering_correction_logs.zip are not included in this import"],
    ]
    site_metadata_items = common_metadata_items + [
        ["Date, Context = collection <BERVO:8000239>", date_range(site_records, lai_date_value)],
        ["Comment, Context = lookup source <BERVO:8000305>", "Sampling_Area codes resolved from vegetation_attributes_photos site metadata where available; RU is mapped to Taylor River Road; focal-tree USDA-style codes are expanded through local taxonomy lookup metadata"],
    ]
    summary_metadata_items = common_metadata_items + [
        ["Date, Context = collection <BERVO:8000239>", date_range(summary_records, lai_date_value)],
        ["Comment, Context = source table join <BERVO:8000305>", "LAI summary rows are joined to LAI site metadata by Site_Number, Location_Type, and Sampling_Area to add collection date and focal-tree metadata"],
    ]

    location_specs = [
        make_lai_spec(dd_rows, 'Site_Number', dimension_number=1, output_name='location_measurement_site_identifier'),
        make_lai_spec(dd_rows, 'Location_Type', dimension_number=1, output_name='location_land_cover_community_type'),
        make_lai_spec(dd_rows, 'Sampling_Area', dimension_number=1, output_name='location_sampling_area_region_code'),
        make_lai_spec(dd_rows, 'Sampling_Area_Full_Name', source='Sampling_Area', dimension_number=1, transform=area_name, output_name='location_resolved_sampling_area_region'),
    ]
    spatial_specs = [
        make_lai_spec(dd_rows, 'Latitude', dimension_number=1, output_name='location_latitude_degree'),
        make_lai_spec(dd_rows, 'Longitude', dimension_number=1, output_name='location_longitude_degree'),
    ]
    time_specs = [
        make_lai_spec(dd_rows, 'Collection_Date', dimension_number=2, output_name='time_collection_date'),
    ]
    taxon_specs = [
        make_lai_spec(dd_rows, 'Focal_Tree_Species', dimension_number=3, transform=lai_species_code, output_name='taxon_focal_tree_usda_plants_code'),
        make_lai_spec(dd_rows, 'Focal_Tree_Taxon_Family', source='Focal_Tree_Species', dimension_number=3, transform=species_field('family'), output_name='taxon_focal_tree_family'),
        make_lai_spec(dd_rows, 'Focal_Tree_Taxon_Genus', source='Focal_Tree_Species', dimension_number=3, transform=species_field('genus'), output_name='taxon_focal_tree_genus'),
        make_lai_spec(dd_rows, 'Focal_Tree_Taxon_Species_Epithet', source='Focal_Tree_Species', dimension_number=3, transform=species_field('species_epithet'), output_name='taxon_focal_tree_species_epithet'),
        make_lai_spec(dd_rows, 'Focal_Tree_Taxon_Binomial', source='Focal_Tree_Species', dimension_number=3, transform=species_field('binomial'), output_name='taxon_focal_tree_binomial'),
        make_lai_spec(dd_rows, 'Focal_Tree_NCBI_Taxon_ID', source='Focal_Tree_Species', dimension_number=3, transform=species_field('ncbi_taxon_id'), output_name='taxon_focal_tree_ncbi_taxon_identifier'),
        make_lai_spec(dd_rows, 'Focal_Tree_GBIF_Taxon_ID', source='Focal_Tree_Species', dimension_number=3, transform=species_field('gbif_taxon_id'), output_name='taxon_focal_tree_gbif_taxon_identifier'),
    ]
    site_metadata_specs = (
        location_specs
        + spatial_specs
        + time_specs
        + taxon_specs
        + [
            make_lai_spec(dd_rows, 'Light_Conditions', output_name='sky_and_illumination_conditions_description'),
            make_lai_spec(dd_rows, 'Requires_K', output_name='scattering_correction_required_binary'),
            make_lai_spec(dd_rows, 'Associated_K', output_name='associated_scattering_correction_record_identifier'),
            make_lai_spec(dd_rows, 'Contains_K', output_name='scattering_correction_record_collected_at_site_binary'),
            make_lai_spec(dd_rows, 'K_Record_Azimuth', output_name='scattering_correction_sensor_cap_azimuth_degree', spark_type='StringType'),
            make_lai_spec(dd_rows, 'Asky_FOV', output_name='a_b_record_sensor_cap_field_of_view_angle_degree'),
            make_lai_spec(dd_rows, 'Widesky_FOV', output_name='wide_sky_reference_field_of_view_angle_degree'),
            make_lai_spec(dd_rows, 'Notes', output_name='measurement_notes_comment'),
            make_lai_spec(dd_rows, 'QC_Flag', output_name='leaf_area_index_quality_control_flag'),
            make_lai_spec(dd_rows, 'Plot_Contains_Focal_Tree', output_name='plot_contains_focal_tree_binary'),
            make_lai_spec(dd_rows, 'A_Record', output_name='licor_above_canopy_reference_record_identifier'),
            make_lai_spec(dd_rows, 'B_Record', output_name='licor_below_canopy_record_identifier'),
            make_lai_spec(dd_rows, 'K_Record', output_name='licor_scattering_correction_record_identifier'),
            make_lai_spec(dd_rows, 'A_Record_Azimuth', output_name='a_b_record_sensor_orientation_azimuth_degree'),
        ]
    )
    summary_specs = (
        location_specs
        + time_specs
        + taxon_specs
        + [
            make_lai_spec(dd_rows, 'Corner', dimension_number=4, output_name='position_plot_corner_index'),
            make_lai_spec(dd_rows, 'L_2200', output_name='leaf_area_index_licor_2200_dimensionless_unit'),
            make_lai_spec(dd_rows, 'Le_2200', output_name='effective_leaf_area_index_licor_2200_dimensionless_unit'),
            make_lai_spec(dd_rows, 'SEL_2200', output_name='leaf_area_index_standard_error_licor_2200_dimensionless_unit'),
            make_lai_spec(dd_rows, 'ACF_2200', output_name='apparent_clumping_factor_licor_2200_dimensionless_unit'),
            make_lai_spec(dd_rows, 'L_WN', output_name='leaf_area_index_welles_norman_dimensionless_unit'),
            make_lai_spec(dd_rows, 'Le_WN', output_name='effective_leaf_area_index_welles_norman_dimensionless_unit'),
            make_lai_spec(dd_rows, 'SEL_WN', output_name='leaf_area_index_standard_error_welles_norman_dimensionless_unit'),
            make_lai_spec(dd_rows, 'ACF_WN', output_name='apparent_clumping_factor_welles_norman_dimensionless_unit'),
            make_lai_spec(dd_rows, 'L_LANG', output_name='leaf_area_index_lang_dimensionless_unit'),
            make_lai_spec(dd_rows, 'SEL_LANG', output_name='leaf_area_index_standard_error_lang_dimensionless_unit'),
            make_lai_spec(dd_rows, 'L_ELLIP', output_name='leaf_area_index_ellipsoidal_intermediate_dimensionless_unit'),
            make_lai_spec(dd_rows, 'L_SCATCOR', output_name='leaf_area_index_scatter_corrected_dimensionless_unit'),
            make_lai_spec(dd_rows, 'S_SCATCOR', output_name='scattering_correction_factor_dimensionless_unit'),
            make_lai_spec(dd_rows, 'ACF_SCATCOR', output_name='apparent_clumping_factor_scatter_corrected_dimensionless_unit'),
            make_lai_spec(dd_rows, 'CHI_SCATCOR', output_name='leaf_angle_distribution_chi_algorithm_parameter_dimensionless_unit'),
        ]
    )

    write_generic_ontologized_table(
        'leaf_area_index_site_metadata',
        site_records,
        site_metadata_specs,
        output_dir,
        'CHESS 2025 LAI site-level metadata for meadow, shrub, tree, and ancillary aspen understory measurements with sampling-area and focal-tree code expansions',
        site_metadata_items,
        'BERVO:8000394',
        'Location',
        dimensions=LAI_DIMENSIONS,
    )
    write_generic_ontologized_table(
        'leaf_area_index_summary',
        summary_records,
        summary_specs,
        output_dir,
        'CHESS 2025 leaf area index summary observations from meadow, shrub, tree, and ancillary aspen understory measurements',
        summary_metadata_items,
        'BERVO:8000164',
        'Leaf area index',
        dimensions=LAI_DIMENSIONS,
    )


def write_field_sampling_dd_bervo(field_dir, metadata_rows, source_tables,
                                  field_mappings, status_overrides,
                                  sample_transforms):
    """Write a reviewable BERVO mapping file from metadata_column_key.csv."""
    out_path = field_dir / 'dd_bervo.csv'
    fieldnames = [
        'csv', 'column', 'BERVO Combination', 'BERVO Term', 'unit',
        'definition', 'data_type', 'source_file', 'berdl_export_status',
        'nonempty_value_count', 'sample_values', 'mapping_notes',
        'proposed_bervo_term'
    ]

    values_by_key = {}
    for csv_name, records in source_tables.items():
        for record in records:
            for column, value in record.items():
                if column is None:
                    continue
                values_by_key.setdefault((csv_name, column), []).append(value)
    if ('sampling_area', 'ShortName') in values_by_key:
        values_by_key[('sampling_area', 'SamplingArea')] = values_by_key[('sampling_area', 'ShortName')]
    if ('fractional_cover', 'Note') in values_by_key:
        values_by_key[('fractional_cover', 'Notes')] = values_by_key[('fractional_cover', 'Note')]

    lookup_only_csvs = {'sampling_area', 'species_list'}

    def row_status(csv_name, column, values):
        if (csv_name, column) in status_overrides:
            return status_overrides[(csv_name, column)]
        if csv_name in lookup_only_csvs:
            return 'lookup_only_not_imported'
        if csv_name == 'CRBU2018_AOP_Crowns.geojson':
            return 'unused_spatial_polygon_not_imported'
        if values is not None and not nonempty_source_values(values):
            return 'unused_empty_source_column'
        return 'unused_not_selected_for_berdl'

    with out_path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for metadata_row in metadata_rows:
            csv_name = metadata_row['csv']
            column = metadata_row['column']
            key = (csv_name, column)
            mapping = field_mappings.get(key, {})
            values = values_by_key.get(key)
            status = row_status(csv_name, column, values)
            transform = sample_transforms.get(key)
            sample_values = ''
            if values is not None and status != 'unused_empty_source_column':
                if transform:
                    records = source_tables.get(csv_name, [])
                    sample_values = sample_transformed_values(records, transform)
                else:
                    sample_values = sample_source_values(values)

            writer.writerow({
                'csv': csv_name,
                'column': column,
                'BERVO Combination': normalize_bervo_curie(mapping.get('combination', '')),
                'BERVO Term': normalize_bervo_curie(mapping.get('term', '')),
                'unit': mapping.get('unit', ''),
                'definition': metadata_row['description'],
                'data_type': mapping.get('data_type', ''),
                'source_file': f"{csv_name}.csv" if csv_name and not csv_name.endswith('.geojson') else csv_name,
                'berdl_export_status': status,
                'nonempty_value_count': len(nonempty_source_values(values or [])) if values is not None else '',
                'sample_values': sample_values,
                'mapping_notes': mapping.get('notes', ''),
                'proposed_bervo_term': mapping.get('proposed_bervo_term', ''),
            })


def convert_field_sampling_2018(base_dir, output_dir):
    """Convert 2018 field sampling tables using lookup files as context."""
    field_dir = base_dir / '2018_field_sampling'
    metadata_rows, metadata_key = load_field_metadata_key(field_dir)
    sampling_areas = load_sampling_area_lookup(field_dir)
    species_lookup, species_lower_lookup = load_species_lookup(field_dir)

    sample_site_records, _ = read_csv_records(field_dir / 'sample_site.csv')
    fractional_records, _ = read_csv_records(field_dir / 'fractional_cover.csv')
    rtk_records, _ = read_csv_records(field_dir / 'raw_rtk_gps_points.csv')
    sample_site_areas = sample_site_area_lookup(sample_site_records, sampling_areas)

    def desc(csv_name, column, fallback=''):
        return field_description(metadata_key, csv_name, column, fallback)

    def area_name(row):
        return sampling_area_full_name(row, sampling_areas)

    def rtk_area_name(row):
        return sample_site_sampling_area_field(row, sample_site_areas, 'full_name')

    def fractional_label(row):
        return cover_label(row, species_lookup, species_lower_lookup)

    def fractional_species_field(field_name):
        return lambda row: cover_detail_value(row, species_lookup, species_lower_lookup, field_name)

    common_metadata_items = [
        ["Link, Context = dataset DOI <BERVO:8000391>", "10.15485/1618130"],
        ["Location <BERVO:8000394>", "East River, CO"],
        ["US state <BERVO:8000439>", "CO"],
        ["Country <BERVO:8000398>", "USA"],
        ["Campaign <BERVO:8000393>", "ER18"],
    ]

    sample_site_metadata_items = common_metadata_items + [
        ["Date, Context = collection <BERVO:8000239>", date_range(sample_site_records, field_sampling_date)],
        ["Position, Context = coordinate reference system <BERVO:8000443>", f"EPSG:{first_constant(sample_site_records, 'EPSG')}"],
        ["Comment, Context = latitude longitude header correction <BERVO:8000305>", "Source columns named Longitude and Latitude contain latitude-like and longitude-like values respectively; exported columns are assigned by numeric range"],
    ]

    fractional_metadata_items = common_metadata_items + [
        ["Date, Context = collection <BERVO:8000239>", date_range(fractional_records, fractional_collection_date)],
        ["Comment, Context = lookup source <BERVO:8000305>", "SamplingArea codes resolved through sampling_area.csv; CoverCode values resolved through species_list.csv where possible"],
    ]

    rtk_metadata_items = common_metadata_items + [
        ["Date, Context = collection <BERVO:8000239>", date_range(sample_site_records, field_sampling_date)],
        ["Projected Coordinate System <BERVO:8000442>", f"EPSG:{first_constant(rtk_records, 'EPSG')} / UTM Zone 13N"],
        ["Method, Context = GPS source <BERVO:8000303>", "RTK GPS"],
    ]

    sample_site_specs = [
        make_spec('SampleSiteCode', 'Identifier, Context = sample site', 'BERVO:8000528', dimension_number=1, output_name='environmental_sample_site_identifier', original_description=desc('sample_site', 'SampleSiteCode')),
        make_spec('Foliar_IGSN', 'Identifier, Context = foliar sample', 'BERVO:8000528', dimension_number=1, output_name='environmental_sample_foliar_igsn_identifier', original_description=desc('sample_site', 'Foliar_IGSN')),
        make_spec('SamplingArea', 'Region, Context = city or sampling area', 'BERVO:8000519', dimension_number=2, transform=area_name, output_name='location_city_or_sampling_area_region', original_description=desc('sample_site', 'SamplingArea', 'Resolved from SamplingArea code using sampling_area.csv FullName.')),
        make_spec('Longitude', 'Latitude', 'BERVO:8000395', dimension_number=2, unit='degree', spark_type='DoubleType', output_name='location_latitude_degree', original_description=desc('sample_site', 'Longitude', 'Source column is named Longitude, but values are latitude-like decimal degrees.')),
        make_spec('Latitude', 'Longitude', 'BERVO:8000396', dimension_number=2, unit='degree', spark_type='DoubleType', output_name='location_longitude_degree', original_description=desc('sample_site', 'Latitude', 'Source column is named Latitude, but values are longitude-like decimal degrees.')),
        make_spec('Elevation_m', 'Altitude', 'BERVO:8000099', dimension_number=2, unit='meter', spark_type='DoubleType', output_name='location_altitude_meter', original_description=desc('sample_site', 'Elevation_m')),
        make_spec('GPS_source', 'Method, Context = GPS source', 'BERVO:8000303', dimension_number=2, output_name='location_gps_source_method', original_description=desc('sample_site', 'GPS_source')),
        make_spec('VegetationType', 'Community type, Context = field vegetation', 'BERVO:8000404', dimension_number=2, output_name='location_field_vegetation_community_type', original_description=desc('sample_site', 'VegetationType')),
        make_spec('Year', 'Date, Context = collection', 'BERVO:8000239', dimension_number=3, transform=field_sampling_date, output_name='time_collection_date', original_description='Derived from Month, Day, and Year source columns.'),
        make_spec('FieldVegHeightMax_cm', 'Height, Context = maximum field vegetation', 'BERVO:8000076', unit='centimeter', spark_type='DoubleType', output_name='field_vegetation_height_max_centimeter', original_description=desc('sample_site', 'FieldVegHeightMax_cm')),
        make_spec('FieldVegHeightMedian_cm', 'Height, Context = median field vegetation', 'BERVO:8000076', unit='centimeter', spark_type='DoubleType', output_name='field_vegetation_height_median_centimeter', original_description=desc('sample_site', 'FieldVegHeightMedian_cm')),
        make_spec('SoilMoisture_%_1', 'Volumetric water content, Context = replicate 1', 'BERVO:0001743', unit='percent', spark_type='DoubleType', output_name='volumetric_water_content_replicate_1_percent', original_description=desc('sample_site', 'SoilMoisture_%_1')),
        make_spec('SoilMoisture_%_2', 'Volumetric water content, Context = replicate 2', 'BERVO:0001743', unit='percent', spark_type='DoubleType', output_name='volumetric_water_content_replicate_2_percent', original_description=desc('sample_site', 'SoilMoisture_%_2')),
        make_spec('SoilMoisture_%_3', 'Volumetric water content, Context = replicate 3', 'BERVO:0001743', unit='percent', spark_type='DoubleType', output_name='volumetric_water_content_replicate_3_percent', original_description=desc('sample_site', 'SoilMoisture_%_3')),
    ]

    fractional_cover_specs = [
        make_spec('SampleSiteCode', 'Identifier, Context = sample site', 'BERVO:8000528', dimension_number=1, output_name='environmental_sample_site_identifier', original_description=desc('fractional_cover', 'SampleSiteCode')),
        make_spec('SamplingArea', 'Region, Context = city or sampling area', 'BERVO:8000519', dimension_number=2, transform=area_name, output_name='location_city_or_sampling_area_region', original_description=desc('fractional_cover', 'SamplingArea', 'Resolved from SamplingArea code using sampling_area.csv FullName.')),
        make_spec('CollectionDate', 'Date, Context = collection', 'BERVO:8000239', dimension_number=3, transform=fractional_collection_date, output_name='time_collection_date', original_description=desc('fractional_cover', 'CollectionDate')),
        make_spec('CoverCode', 'Identifier, Context = cover code', 'BERVO:8000528', dimension_number=4, transform=fractional_species_field('source_cover_code'), output_name='taxon_cover_code_identifier', original_description=desc('fractional_cover', 'CoverCode')),
        make_spec('CoverCode', 'Taxon, Context = family', 'BERVO:8000324', dimension_number=4, transform=fractional_species_field('family'), output_name='taxon_family', original_description='Derived from CoverCode or AltFieldCode using species_list.csv Family.'),
        make_spec('CoverCode', 'Taxon, Context = genus', 'BERVO:8000324', dimension_number=4, transform=fractional_species_field('genus'), output_name='taxon_genus', original_description='Derived from CoverCode or AltFieldCode using species_list.csv Genus.'),
        make_spec('CoverCode', 'Taxon, Context = species', 'BERVO:8000324', dimension_number=4, transform=fractional_species_field('species'), output_name='taxon_species', original_description='Derived from CoverCode or AltFieldCode using species_list.csv Species.'),
        make_spec('CoverCode', 'Identifier, Context = alternate cover code', 'BERVO:8000528', dimension_number=4, transform=fractional_species_field('alt_field_code'), output_name='taxon_alternate_cover_code_identifier', original_description='Derived from CoverCode or AltFieldCode using species_list.csv AltFieldCode.'),
        make_spec('CoverCode', 'Comment, Context = species list', 'BERVO:8000305', dimension_number=4, transform=fractional_species_field('notes'), output_name='taxon_species_list_comment', original_description='Derived from CoverCode or AltFieldCode using species_list.csv Notes.'),
        make_spec('FractionalCover', 'Percent area covered by specified plant', 'BERVO:0001834', unit='percent', spark_type='DoubleType', output_name='percent_area_covered_by_specified_plant_percent', original_description=desc('fractional_cover', 'FractionalCover')),
        make_spec('Note', 'Comment, Context = fractional cover', 'BERVO:8000305', transform=combined_fractional_note, output_name='fractional_cover_comment', original_description=desc('fractional_cover', 'Notes', 'Free-text note; includes one unlabeled source note column.')),
    ]

    rtk_specs = [
        make_spec('SampleSiteCode', 'Identifier, Context = sample site', 'BERVO:8000528', dimension_number=1, output_name='environmental_sample_site_identifier', original_description=desc('raw_rtk_gps_points', 'SampleSiteCode')),
        make_spec('SampleSiteCode', 'Region, Context = city or sampling area', 'BERVO:8000519', dimension_number=2, transform=rtk_area_name, output_name='location_city_or_sampling_area_region', original_description='Derived from SampleSiteCode using sample_site.csv and sampling_area.csv FullName.'),
        make_spec('FieldPointName', 'Identifier, Context = field point', 'BERVO:8000528', dimension_number=2, output_name='location_field_point_identifier', original_description=desc('raw_rtk_gps_points', 'FieldPointName')),
        make_spec('Northing', 'Northing, Projected Coordinate System = UTM Zone 13N', 'BERVO:8000441', dimension_number=2, unit='meter', spark_type='DoubleType', output_name='location_northing_projected_coordinate_system_utm_zone_13n_meter', original_description=desc('raw_rtk_gps_points', 'Northing', 'UTM northing coordinate in EPSG:26913.')),
        make_spec('Easting', 'Easting, Projected Coordinate System = UTM Zone 13N', 'BERVO:8000440', dimension_number=2, unit='meter', spark_type='DoubleType', output_name='location_easting_projected_coordinate_system_utm_zone_13n_meter', original_description=desc('raw_rtk_gps_points', 'Easting', 'UTM easting coordinate in EPSG:26913.')),
        make_spec('Elevation', 'Altitude', 'BERVO:8000099', dimension_number=2, unit='meter', spark_type='DoubleType', output_name='location_altitude_meter', original_description=desc('raw_rtk_gps_points', 'Elevation')),
        make_spec('Code', 'Identifier, Context = field point class', 'BERVO:8000528', dimension_number=2, output_name='location_field_point_class_identifier', original_description=desc('raw_rtk_gps_points', 'Code')),
    ]

    field_mappings = {
        ('sample_site', 'SamplingArea'): {'combination': 'Region, Context = city or sampling area; US state; Country', 'term': 'BERVO:8000519', 'data_type': 'string', 'notes': 'Resolved through sampling_area.csv FullName, State, and Country; raw area codes are not exported. Constant State and Country values are promoted to array-level metadata.'},
        ('sample_site', 'Campaign'): {'combination': 'Campaign', 'term': 'BERVO:8000393', 'data_type': 'string'},
        ('sample_site', 'SampleSiteCode'): {'combination': 'Identifier, Context = sample site', 'term': 'BERVO:8000528', 'data_type': 'string'},
        ('sample_site', 'Month'): {'combination': 'Date, Context = collection', 'term': 'BERVO:8000239', 'data_type': 'integer', 'notes': 'Used only to derive ISO collection date.'},
        ('sample_site', 'Day'): {'combination': 'Date, Context = collection', 'term': 'BERVO:8000239', 'data_type': 'integer', 'notes': 'Used only to derive ISO collection date.'},
        ('sample_site', 'Year'): {'combination': 'Date, Context = collection', 'term': 'BERVO:8000239', 'data_type': 'integer', 'notes': 'Constant 2018; used in array metadata and derived ISO collection date.'},
        ('sample_site', 'Longitude'): {'combination': 'Latitude', 'term': 'BERVO:8000395', 'unit': 'degree', 'data_type': 'float', 'notes': 'Source header appears swapped; values are latitude-like.'},
        ('sample_site', 'Latitude'): {'combination': 'Longitude', 'term': 'BERVO:8000396', 'unit': 'degree', 'data_type': 'float', 'notes': 'Source header appears swapped; values are longitude-like.'},
        ('sample_site', 'EPSG'): {'combination': 'Position, Context = coordinate reference system', 'term': 'BERVO:8000443', 'data_type': 'string', 'notes': 'Constant EPSG:4326 geographic coordinate reference system; stored as array-level metadata.'},
        ('sample_site', 'GPS_source'): {'combination': 'Method, Context = GPS source', 'term': 'BERVO:8000303', 'data_type': 'string'},
        ('sample_site', 'Elevation_m'): {'combination': 'Altitude', 'term': 'BERVO:8000099', 'unit': 'meter', 'data_type': 'float'},
        ('sample_site', 'VegetationType'): {'combination': 'Community type, Context = field vegetation', 'term': 'BERVO:8000404', 'data_type': 'string'},
        ('sample_site', 'FieldVegHeightMax_cm'): {'combination': 'Height, Context = maximum field vegetation', 'term': 'BERVO:8000076', 'unit': 'centimeter', 'data_type': 'float'},
        ('sample_site', 'FieldVegHeightMedian_cm'): {'combination': 'Height, Context = median field vegetation', 'term': 'BERVO:8000076', 'unit': 'centimeter', 'data_type': 'float'},
        ('sample_site', 'SoilMoisture_%_1'): {'combination': 'Volumetric water content, Context = replicate 1', 'term': 'BERVO:0001743', 'unit': 'percent', 'data_type': 'float'},
        ('sample_site', 'SoilMoisture_%_2'): {'combination': 'Volumetric water content, Context = replicate 2', 'term': 'BERVO:0001743', 'unit': 'percent', 'data_type': 'float'},
        ('sample_site', 'SoilMoisture_%_3'): {'combination': 'Volumetric water content, Context = replicate 3', 'term': 'BERVO:0001743', 'unit': 'percent', 'data_type': 'float'},
        ('sample_site', 'Foliar_IGSN'): {'combination': 'Identifier, Context = foliar sample', 'term': 'BERVO:8000528', 'data_type': 'string'},
        ('fractional_cover', 'SampleSiteCode'): {'combination': 'Identifier, Context = sample site', 'term': 'BERVO:8000528', 'data_type': 'string'},
        ('fractional_cover', 'SamplingArea'): {'combination': 'Region, Context = city or sampling area; US state; Country', 'term': 'BERVO:8000519', 'data_type': 'string', 'notes': 'Resolved through sampling_area.csv FullName, State, and Country; raw area codes are not exported. Constant State and Country values are promoted to array-level metadata.'},
        ('fractional_cover', 'CollectionDate'): {'combination': 'Date, Context = collection', 'term': 'BERVO:8000239', 'data_type': 'date', 'notes': 'Converted from M/D/YY to ISO date.'},
        ('fractional_cover', 'CoverCode'): {'combination': 'Identifier, Context = cover code; Taxon, Context = family; Taxon, Context = genus; Taxon, Context = species; Identifier, Context = alternate cover code; Comment, Context = species list', 'term': 'BERVO:8000528', 'data_type': 'string', 'notes': 'Expanded through species_list.csv into cover code, family, genus, species, alternate field code, and species-list notes. RibMon and RubIda are inferred from obvious species-list entries.'},
        ('fractional_cover', 'FractionalCover'): {'combination': 'Percent area covered by specified plant', 'term': 'BERVO:0001834', 'unit': 'percent', 'data_type': 'float'},
        ('fractional_cover', 'Notes'): {'combination': 'Comment, Context = fractional cover', 'term': 'BERVO:8000305', 'data_type': 'string'},
        ('raw_rtk_gps_points', 'SampleSiteCode'): {'combination': 'Identifier, Context = sample site', 'term': 'BERVO:8000528', 'data_type': 'string'},
        ('raw_rtk_gps_points', 'FieldPointName'): {'combination': 'Identifier, Context = field point', 'term': 'BERVO:8000528', 'data_type': 'string'},
        ('raw_rtk_gps_points', 'Northing'): {'combination': 'Northing, Projected Coordinate System = UTM Zone 13N', 'term': 'BERVO:8000441', 'unit': 'meter', 'data_type': 'float'},
        ('raw_rtk_gps_points', 'Easting'): {'combination': 'Easting, Projected Coordinate System = UTM Zone 13N', 'term': 'BERVO:8000440', 'unit': 'meter', 'data_type': 'float'},
        ('raw_rtk_gps_points', 'Elevation'): {'combination': 'Altitude', 'term': 'BERVO:8000099', 'unit': 'meter', 'data_type': 'float'},
        ('raw_rtk_gps_points', 'Code'): {'combination': 'Identifier, Context = field point class', 'term': 'BERVO:8000528', 'data_type': 'string'},
        ('raw_rtk_gps_points', 'EPSG'): {'combination': 'Projected Coordinate System', 'term': 'BERVO:8000442', 'data_type': 'string', 'notes': 'Constant; stored as array-level metadata.'},
        ('sampling_area', 'SamplingArea'): {'combination': 'Identifier, Context = sampling area', 'term': 'BERVO:8000528', 'data_type': 'string'},
        ('sampling_area', 'FullName'): {'combination': 'Region, Context = city or sampling area', 'term': 'BERVO:8000519', 'data_type': 'string'},
        ('sampling_area', 'State'): {'combination': 'US state', 'term': 'BERVO:8000439', 'data_type': 'string', 'notes': 'Promoted to array-level metadata because all exported field-sampling rows resolve to CO.'},
        ('sampling_area', 'Country'): {'combination': 'Country', 'term': 'BERVO:8000398', 'data_type': 'string', 'notes': 'Promoted to array-level metadata because all exported field-sampling rows resolve to USA.'},
        ('species_list', 'CoverCode'): {'combination': 'Identifier, Context = cover code', 'term': 'BERVO:8000528', 'data_type': 'string'},
        ('species_list', 'Family'): {'combination': 'Taxon, Context = family', 'term': 'BERVO:8000324', 'data_type': 'string'},
        ('species_list', 'Genus'): {'combination': 'Taxon, Context = genus', 'term': 'BERVO:8000324', 'data_type': 'string'},
        ('species_list', 'Species'): {'combination': 'Taxon, Context = species', 'term': 'BERVO:8000324', 'data_type': 'string'},
        ('species_list', 'AltFieldCode'): {'combination': 'Identifier, Context = alternate cover code', 'term': 'BERVO:8000528', 'data_type': 'string'},
        ('species_list', 'Notes'): {'combination': 'Comment, Context = species list', 'term': 'BERVO:8000305', 'data_type': 'string'},
    }

    status_overrides = {
        ('sample_site', 'Campaign'): 'array_level_metadata',
        ('sample_site', 'Month'): 'derived_into_collection_date',
        ('sample_site', 'Day'): 'derived_into_collection_date',
        ('sample_site', 'Year'): 'array_level_metadata_and_derived_into_collection_date',
        ('sample_site', 'EPSG'): 'array_level_metadata',
        ('raw_rtk_gps_points', 'EPSG'): 'array_level_metadata',
        ('sampling_area', 'FullName'): 'lookup_only_projected_into_location_dimension',
        ('sampling_area', 'State'): 'lookup_only_array_level_metadata',
        ('sampling_area', 'Country'): 'lookup_only_array_level_metadata',
        ('species_list', 'CoverCode'): 'lookup_only_projected_into_taxon_dimension',
        ('species_list', 'Family'): 'lookup_only_projected_into_taxon_dimension',
        ('species_list', 'Genus'): 'lookup_only_projected_into_taxon_dimension',
        ('species_list', 'Species'): 'lookup_only_projected_into_taxon_dimension',
        ('species_list', 'AltFieldCode'): 'lookup_only_projected_into_taxon_dimension',
        ('species_list', 'Notes'): 'lookup_only_projected_into_taxon_dimension',
    }
    for key in field_mappings:
        if key not in status_overrides and key[0] not in {'sampling_area', 'species_list'}:
            status_overrides.setdefault(key, 'used_in_berdl_data_table')
    status_overrides[('CRBU2018_AOP_Crowns.geojson', '')] = 'unused_spatial_polygon_not_imported'

    sample_transforms = {
        ('sample_site', 'SamplingArea'): area_name,
        ('sample_site', 'Month'): field_sampling_date,
        ('sample_site', 'Day'): field_sampling_date,
        ('sample_site', 'Year'): field_sampling_date,
        ('sample_site', 'Longitude'): lambda row: row.get('Longitude', ''),
        ('sample_site', 'Latitude'): lambda row: row.get('Latitude', ''),
        ('fractional_cover', 'SamplingArea'): area_name,
        ('fractional_cover', 'CollectionDate'): fractional_collection_date,
        ('fractional_cover', 'CoverCode'): fractional_label,
        ('fractional_cover', 'Notes'): combined_fractional_note,
    }

    write_field_sampling_dd_bervo(
        field_dir,
        metadata_rows,
        {
            'sample_site': sample_site_records,
            'fractional_cover': fractional_records,
            'raw_rtk_gps_points': rtk_records,
            'sampling_area': read_csv_records(field_dir / 'sampling_area.csv')[0],
            'species_list': read_csv_records(field_dir / 'species_list.csv')[0],
        },
        field_mappings,
        status_overrides,
        sample_transforms,
    )

    write_generic_ontologized_table(
        'field_sampling_sample_site',
        sample_site_records,
        sample_site_specs,
        output_dir,
        '2018 East River field-sampling site metadata, including resolved sampling area names, coordinates, vegetation type, vegetation height, and soil-moisture measurements',
        sample_site_metadata_items,
        'BERVO:8000342',
        'Environmental sample',
        dimensions=FIELD_SAMPLING_DIMENSIONS,
    )
    write_generic_ontologized_table(
        'field_sampling_fractional_cover',
        fractional_records,
        fractional_cover_specs,
        output_dir,
        'Fractional cover observations from 2018 East River field sampling with sampling-area codes and cover codes resolved through lookup files',
        fractional_metadata_items,
        'BERVO:0001834',
        'Percent area covered by specified plant',
        dimensions=FIELD_SAMPLING_DIMENSIONS,
    )
    write_generic_ontologized_table(
        'field_sampling_rtk_gps_points',
        rtk_records,
        rtk_specs,
        output_dir,
        'Raw RTK GPS plot-corner and field-point coordinates from 2018 East River field sampling, with sample-site area resolved through sample_site.csv',
        rtk_metadata_items,
        'BERVO:8000394',
        'Location',
        dimensions=FIELD_SAMPLING_DIMENSIONS,
    )


def derive_mag_manifest_records(soil_dir):
    """Build a manifest of MAG FASTA files without extracting sequence contents."""
    records = []
    repo_dir = soil_dir.parent
    for archive_path in sorted(soil_dir.glob('neon_genomes*_tar.gz')):
        with tarfile.open(archive_path, 'r:gz') as tar:
            for member in tar.getmembers():
                if not member.isfile() or not member.name.lower().endswith(('.fa', '.fasta', '.fna')):
                    continue
                file_name = Path(member.name).name
                stem = re.sub(r'\.(fa|fasta|fna)$', '', file_name, flags=re.IGNORECASE)
                method = ''
                genome_id = stem
                if '.' in stem and not stem.split('.', 1)[0].isdigit():
                    method, genome_id = stem.split('.', 1)
                records.append({
                    'archive_file_name': archive_path.name,
                    'archive_file_path': str(archive_path.relative_to(repo_dir)),
                    'genome_collection': Path(member.name).parts[0] if Path(member.name).parts else '',
                    'genome_binning_method': method,
                    'genome_identifier': genome_id,
                    'sequence_file_name': file_name,
                    'sequence_file_path': member.name,
                    'sequence_file_size_bytes': member.size,
                })
    return records


def convert_soil_metagenomes(base_dir, output_dir):
    """Convert soil metagenome metadata and MAG archive manifests to ontologized tables."""
    soil_dir = base_dir / 'soil_metagenomes'
    definitions, _, _ = load_dd_definitions(soil_dir / 'dd.csv')
    field_mappings = get_soil_mapping_definitions()

    nmdc_records, _ = read_csv_records(soil_dir / 'neon_Gs0149986_samples_soilproperties_metagenomes.csv')
    samples_records, _ = read_csv_records(soil_dir / 'samples.csv', skip_rows=1)
    mag_records = derive_mag_manifest_records(soil_dir)

    def desc(source, extra=''):
        base = definitions.get(source, '')
        return f"{extra} {base}".strip() if extra else base

    nmdc_specs = [
        make_spec('sample name', *field_mappings['sample name'], dimension_number=1, output_name='environmental_sample_identifier', original_description=desc('sample name')),
        make_spec('source material identifier', *field_mappings['source material identifier'], dimension_number=1, output_name='environmental_sample_source_material_identifier', original_description=desc('source material identifier')),
        make_spec('analysis/data type', *field_mappings['analysis/data type'], dimension_number=1, output_name='environmental_sample_analysis_data_type', original_description=desc('analysis/data type')),
        make_spec('environmental medium', *field_mappings['environmental medium'], dimension_number=1, output_name='environmental_sample_material', original_description=desc('environmental medium')),
        make_spec('depth, meters', 'Depth, Context = sample interval start', 'BERVO:8000069', dimension_number=1, unit='meter', spark_type='DoubleType', transform=lambda row: parse_depth_start(row.get('depth, meters')), output_name='environmental_sample_depth_start_meter', original_description=desc('depth, meters', 'Derived interval start.')),
        make_spec('depth, meters', 'Depth, Context = sample interval end', 'BERVO:8000069', dimension_number=1, unit='meter', spark_type='DoubleType', transform=lambda row: parse_depth_end(row.get('depth, meters')), output_name='environmental_sample_depth_end_meter', original_description=desc('depth, meters', 'Derived interval end.')),
        make_spec('growth facility', *field_mappings['growth facility'], dimension_number=1, output_name='environmental_sample_growth_facility', original_description=desc('growth facility')),
        make_spec('storage conditions', *field_mappings['storage conditions'], dimension_number=1, output_name='environmental_sample_storage_condition', original_description=desc('storage conditions')),
        make_spec('broad-scale environmental context', *field_mappings['broad-scale environmental context'], dimension_number=2, output_name='location_environmental_feature_broad_scale', original_description=desc('broad-scale environmental context')),
        make_spec('local environmental context', *field_mappings['local environmental context'], dimension_number=2, output_name='location_environmental_feature_local', original_description=desc('local environmental context')),
        make_spec('ecosystem', *field_mappings['ecosystem'], dimension_number=2, output_name='location_ecosystem', original_description=desc('ecosystem')),
        make_spec('ecosystem_category', *field_mappings['ecosystem_category'], dimension_number=2, output_name='location_ecosystem_category', original_description=desc('ecosystem_category')),
        make_spec('ecosystem_type', *field_mappings['ecosystem_type'], dimension_number=2, output_name='location_ecosystem_type', original_description=desc('ecosystem_type')),
        make_spec('ecosystem_subtype', *field_mappings['ecosystem_subtype'], dimension_number=2, output_name='location_ecosystem_subtype', original_description=desc('ecosystem_subtype')),
        make_spec('specific_ecosystem', *field_mappings['specific_ecosystem'], dimension_number=2, output_name='location_specific_ecosystem', original_description=desc('specific_ecosystem')),
        make_spec('geographic location (country and/or sea,region)', *field_mappings['geographic location (country and/or sea,region)'], dimension_number=2, output_name='location_geographic_region', original_description=desc('geographic location (country and/or sea,region)')),
        make_spec('geographic location (latitude and longitude)', 'Latitude', 'BERVO:8000395', dimension_number=2, unit='degree', spark_type='DoubleType', transform=lambda row: parse_latitude(row.get('geographic location (latitude and longitude)')), output_name='location_latitude_degree', original_description=desc('geographic location (latitude and longitude)', 'Derived latitude in decimal degrees.')),
        make_spec('geographic location (latitude and longitude)', 'Longitude', 'BERVO:8000396', dimension_number=2, unit='degree', spark_type='DoubleType', transform=lambda row: parse_longitude(row.get('geographic location (latitude and longitude)')), output_name='location_longitude_degree', original_description=desc('geographic location (latitude and longitude)', 'Derived longitude in decimal degrees.')),
        make_spec('elevation, meters', *field_mappings['elevation, meters'], dimension_number=2, unit='meter', spark_type='DoubleType', output_name='location_altitude_meter', original_description=desc('elevation, meters')),
        make_spec('collection date', *field_mappings['collection date'], dimension_number=3, output_name='time_collection_date', original_description=desc('collection date')),
        make_spec('sample storage temperature', *field_mappings['sample storage temperature'], unit='degree Celsius', spark_type='DoubleType', transform=lambda row: parse_first_float(row.get('sample storage temperature')), output_name='sample_storage_temperature_degree_celsius', original_description=desc('sample storage temperature')),
        make_spec('water content', *field_mappings['water content'], unit='percent', spark_type='DoubleType', transform=lambda row: parse_first_float(row.get('water content')), output_name='volumetric_water_content_percent', original_description=desc('water content', 'Reported as percent water-filled pore space.')),
        make_spec('water content method', *field_mappings['water content method'], output_name='volumetric_water_content_method', original_description=desc('water content method')),
        make_spec('pH', *field_mappings['pH'], unit='pH', spark_type='DoubleType', output_name='ph', original_description=desc('pH')),
        make_spec('pH method', *field_mappings['pH method'], output_name='ph_method', original_description=desc('pH method')),
        make_spec('microbial biomass carbon', *field_mappings['microbial biomass carbon'], unit='milligram per kilogram', spark_type='DoubleType', transform=lambda row: parse_first_float(row.get('microbial biomass carbon')), output_name='microbial_biomass_carbon_milligram_per_kilogram', original_description=desc('microbial biomass carbon', 'Reported as microgram carbon per gram dry soil; stored as equivalent milligram per kilogram.')),
        make_spec('microbial biomass carbon method', *field_mappings['microbial biomass carbon method'], output_name='microbial_biomass_carbon_method', original_description=desc('microbial biomass carbon method')),
        make_spec('microbial biomass nitrogen', *field_mappings['microbial biomass nitrogen'], unit='milligram per kilogram', spark_type='DoubleType', transform=lambda row: parse_first_float(row.get('microbial biomass nitrogen')), output_name='microbial_biomass_nitrogen_milligram_per_kilogram', original_description=desc('microbial biomass nitrogen', 'Reported as microgram nitrogen per gram dry soil; stored as equivalent milligram per kilogram.')),
        make_spec('microbial biomass nitrogen method', *field_mappings['microbial biomass nitrogen method'], output_name='microbial_biomass_nitrogen_method', original_description=desc('microbial biomass nitrogen method')),
        make_spec('ammonium nitrogen', *field_mappings['ammonium nitrogen'], unit='milligram per kilogram', spark_type='DoubleType', transform=lambda row: parse_first_float(row.get('ammonium nitrogen')), output_name='ammonium_nitrogen_milligram_per_kilogram', original_description=desc('ammonium nitrogen', 'Reported as microgram per gram; inferred as microgram nitrogen per gram dry soil and stored as equivalent milligram per kilogram.')),
        make_spec('nitrate_nitrogen', *field_mappings['nitrate_nitrogen'], unit='milligram per kilogram', spark_type='DoubleType', transform=lambda row: parse_first_float(row.get('nitrate_nitrogen')), output_name='nitrate_nitrogen_milligram_per_kilogram', original_description=desc('nitrate_nitrogen', 'Reported as microgram per gram; inferred as microgram nitrogen per gram dry soil and stored as equivalent milligram per kilogram.')),
    ]

    sample_specs = [
        make_spec('Sample Name', *field_mappings['Sample Name'], dimension_number=1, output_name='environmental_sample_identifier', original_description=desc('Sample Name')),
        make_spec('IGSN', *field_mappings['IGSN'], dimension_number=1, output_name='environmental_sample_igsn_identifier', original_description=desc('IGSN')),
        make_spec('Material', *field_mappings['Material'], dimension_number=1, output_name='environmental_sample_material', original_description='Material of the collected sample.'),
        make_spec('Description', *field_mappings['Description'], dimension_number=1, output_name='environmental_sample_description', original_description='Free-text description of the collected sample.'),
        make_spec('Collection method', *field_mappings['Collection method'], dimension_number=1, output_name='environmental_sample_collection_method', original_description=desc('Collection method')),
        make_spec('Depth in core max', *field_mappings['Depth in core max'], dimension_number=1, unit='meter', spark_type='DoubleType', output_name='environmental_sample_core_depth_max_meter', original_description=desc('Depth in core max')),
        make_spec('Depth scale', *field_mappings['Depth scale'], dimension_number=1, output_name='environmental_sample_depth_scale', original_description=desc('Depth scale')),
        make_spec('Latitude', *field_mappings['Latitude'], dimension_number=2, unit='degree', spark_type='DoubleType', output_name='location_latitude_degree', original_description=desc('Latitude', 'Decimal degrees.')),
        make_spec('Longitude', *field_mappings['Longitude'], dimension_number=2, unit='degree', spark_type='DoubleType', output_name='location_longitude_degree', original_description=desc('Longitude', 'Decimal degrees.')),
        make_spec('Navigation type', *field_mappings['Navigation type'], dimension_number=2, output_name='location_navigation_method', original_description=desc('Navigation type')),
        make_spec('Primary Physiographic feature', *field_mappings['Primary Physiographic feature'], dimension_number=2, output_name='location_physiographic_feature', original_description=desc('Primary physiographic feature')),
        make_spec('Location description', *field_mappings['Location description'], dimension_number=2, output_name='location_description', original_description='Description of the sample collection location.'),
        make_spec('City/Township', *field_mappings['City/Township'], dimension_number=2, output_name='location_city', original_description='City or township associated with the sample.'),
        make_spec('State/Province', *field_mappings['State/Province'], dimension_number=2, output_name='location_state_province', original_description='State or province associated with the sample.'),
        make_spec('Country', *field_mappings['Country'], dimension_number=2, output_name='location_country', original_description=desc('Country')),
        make_spec('Release Date', *field_mappings['Release Date'], dimension_number=3, output_name='time_release_date', original_description=desc('Release Date')),
        make_spec('Collection date', *field_mappings['Collection date'], dimension_number=3, output_name='time_collection_datetime', original_description=desc('Collection date')),
        make_spec('Field program/Cruise', *field_mappings['Field program/Cruise'], output_name='field_program_identifier', original_description=desc('Field program/cruise')),
        make_spec('Collector/Chief Scientist', *field_mappings['Collector/Chief Scientist'], output_name='collector_identifier', original_description=desc('Collector/Chief Scientist')),
        make_spec('Current Archive', *field_mappings['Current Archive'], output_name='current_archive_identifier', original_description='Current archive where the sample is held.'),
        make_spec('Current archive contact', *field_mappings['Current archive contact'], output_name='current_archive_contact_identifier', original_description='Contact for the current sample archive.'),
    ]

    mag_specs = [
        make_spec('archive_file_name', 'Identifier, Context = genome archive file name', 'BERVO:8000528', dimension_number=4, output_name='genome_archive_file_name', original_description='Name of the downloaded tar.gz archive containing MAG FASTA files.'),
        make_spec('archive_file_path', 'Identifier, Context = genome archive file path', 'BERVO:8000528', dimension_number=4, output_name='genome_archive_file_path', original_description='Repo-relative path to the downloaded tar.gz archive containing MAG FASTA files.'),
        make_spec('genome_collection', 'Identifier, Context = genome collection', 'BERVO:8000528', dimension_number=4, output_name='genome_collection_identifier', original_description='Top-level collection directory inside the MAG archive.'),
        make_spec('genome_binning_method', 'Method, Context = genome binning', 'BERVO:8000303', dimension_number=4, output_name='genome_binning_method', original_description='Genome binning method inferred from the FASTA filename prefix when present.'),
        make_spec('genome_identifier', 'Identifier, Context = genome', 'BERVO:8000528', dimension_number=4, output_name='genome_identifier', original_description='Genome identifier inferred from the FASTA filename.'),
        make_spec('sequence_file_name', 'Identifier, Context = sequence file name', 'BERVO:8000528', dimension_number=4, output_name='genome_sequence_file_name', original_description='FASTA file name inside the MAG archive.'),
        make_spec('sequence_file_path', 'Identifier, Context = sequence file path', 'BERVO:8000528', dimension_number=4, output_name='genome_sequence_file_path', original_description='FASTA member path inside the MAG archive. Sequence contents are not imported.'),
        make_spec('sequence_file_size_bytes', 'Size, Context = sequence file', 'BERVO:8000350', unit='byte', spark_type='IntegerType', output_name='genome_sequence_file_size_byte', original_description='Uncompressed FASTA member size in bytes.'),
    ]

    nmdc_array_metadata_sources = SOIL_ARRAY_METADATA_SOURCES & {spec['source'] for spec in nmdc_specs}
    sample_array_metadata_sources = SOIL_ARRAY_METADATA_SOURCES & {spec['source'] for spec in sample_specs}
    redundant_sources = SOIL_REDUNDANT_SOURCES & {spec['source'] for spec in nmdc_specs + sample_specs}

    nmdc_specs = [
        spec for spec in nmdc_specs
        if spec['source'] not in nmdc_array_metadata_sources
    ]
    sample_specs = [
        spec for spec in sample_specs
        if spec['source'] not in sample_array_metadata_sources
        and spec['source'] not in redundant_sources
    ]

    def first_nonempty(records, source, transform=None):
        for record in records:
            value = transform(record) if transform else record.get(source, '')
            value = normalize_missing_value(value)
            if value != '':
                return str(value)
        return ''

    common_metadata_items = [
        ["Link, Context = dataset DOI <BERVO:8000391>", "10.15485/2587101"],
        ["Location <BERVO:8000394>", "East River, CO"],
        ["Date, Context = collection <BERVO:8000239>", "2018-06-14 to 2018-06-28"],
    ]

    nmdc_metadata_items = common_metadata_items + [
        ["Environmental measurement, Context = analysis data type <BERVO:8000412>", first_nonempty(nmdc_records, 'analysis/data type')],
        ["Environmental material <BERVO:8000402>", first_nonempty(nmdc_records, 'environmental medium')],
        ["Depth, Context = sample interval start <BERVO:8000069>", f"{first_nonempty(nmdc_records, 'depth, meters', lambda row: parse_depth_start(row.get('depth, meters')))} meter"],
        ["Depth, Context = sample interval end <BERVO:8000069>", f"{first_nonempty(nmdc_records, 'depth, meters', lambda row: parse_depth_end(row.get('depth, meters')))} meter"],
        ["Environmental sample location, Context = growth facility <BERVO:8000514>", first_nonempty(nmdc_records, 'growth facility')],
        ["Condition, Context = sample storage <BERVO:8000302>", first_nonempty(nmdc_records, 'storage conditions')],
        ["Environmental feature, Context = broad scale <BERVO:8000400>", first_nonempty(nmdc_records, 'broad-scale environmental context')],
        ["Environmental feature, Context = local <BERVO:8000400>", first_nonempty(nmdc_records, 'local environmental context')],
        ["Ecosystem <BERVO:8000043>", first_nonempty(nmdc_records, 'ecosystem')],
        ["Ecosystem, Context = category <BERVO:8000043>", first_nonempty(nmdc_records, 'ecosystem_category')],
        ["Ecosystem, Context = type <BERVO:8000043>", first_nonempty(nmdc_records, 'ecosystem_type')],
        ["Ecosystem, Context = subtype <BERVO:8000043>", first_nonempty(nmdc_records, 'ecosystem_subtype')],
        ["Ecosystem, Context = specific <BERVO:8000043>", first_nonempty(nmdc_records, 'specific_ecosystem')],
        ["Region, Context = geographic location <BERVO:8000519>", first_nonempty(nmdc_records, 'geographic location (country and/or sea,region)')],
        ["Temperature, Context = sample storage <BERVO:8000133>", f"{first_nonempty(nmdc_records, 'sample storage temperature', lambda row: parse_first_float(row.get('sample storage temperature')))} degree Celsius"],
        ["Method, Context = volumetric water content <BERVO:8000303>", first_nonempty(nmdc_records, 'water content method')],
        ["Method, Context = pH <BERVO:8000303>", first_nonempty(nmdc_records, 'pH method')],
        ["Method, Context = microbial biomass carbon <BERVO:8000303>", first_nonempty(nmdc_records, 'microbial biomass carbon method')],
        ["Method, Context = microbial biomass nitrogen <BERVO:8000303>", first_nonempty(nmdc_records, 'microbial biomass nitrogen method')],
    ]

    sample_metadata_items = common_metadata_items + [
        ["Environmental material <BERVO:8000402>", first_nonempty(samples_records, 'Material')],
        ["Comment, Context = sample description <BERVO:8000305>", first_nonempty(samples_records, 'Description')],
        ["Method, Context = sample collection <BERVO:8000303>", first_nonempty(samples_records, 'Collection method')],
        ["Depth, Context = core maximum <BERVO:8000069>", f"{first_nonempty(samples_records, 'Depth in core max')} meter"],
        ["Method, Context = navigation <BERVO:8000303>", first_nonempty(samples_records, 'Navigation type')],
        ["Environmental feature, Context = physiographic <BERVO:8000400>", first_nonempty(samples_records, 'Primary Physiographic feature')],
        ["Region, Context = city <BERVO:8000519>", first_nonempty(samples_records, 'City/Township')],
        ["Region, Context = state <BERVO:8000519>", first_nonempty(samples_records, 'State/Province')],
        ["Country <BERVO:8000398>", first_nonempty(samples_records, 'Country')],
        ["Date, Context = release <BERVO:8000239>", first_nonempty(samples_records, 'Release Date')],
        ["Identifier, Context = field program <BERVO:8000528>", first_nonempty(samples_records, 'Field program/Cruise')],
        ["Identifier, Context = collector <BERVO:8000528>", first_nonempty(samples_records, 'Collector/Chief Scientist')],
        ["Identifier, Context = archive <BERVO:8000528>", first_nonempty(samples_records, 'Current Archive')],
        ["Identifier, Context = archive contact <BERVO:8000528>", first_nonempty(samples_records, 'Current archive contact')],
    ]

    mag_metadata_items = common_metadata_items + [
        ["Environmental measurement, Context = analysis data type <BERVO:8000412>", "metagenomics"],
        ["Comment, Context = sequence import policy <BERVO:8000305>", "MAG FASTA contents are not imported; archive member metadata are represented in the manifest table"],
    ]

    dd_review_sources = {spec['source'] for spec in nmdc_specs + sample_specs}
    write_soil_dd_bervo(
        base_dir,
        field_mappings,
        dd_review_sources,
        nmdc_array_metadata_sources | sample_array_metadata_sources,
        redundant_sources,
        [
            ('neon_Gs0149986_samples_soilproperties_metagenomes.csv', nmdc_records),
            ('samples.csv', samples_records),
        ],
    )

    write_generic_ontologized_table(
        'soil_metagenomes_nmdc_soil_properties',
        nmdc_records,
        nmdc_specs,
        output_dir,
        'NMDC-compliant soil metagenome sample metadata and associated soil physical and chemical measurements from topsoils collected during the NEON 2018 East River campaign',
        nmdc_metadata_items,
        'BERVO:8000412',
        'Environmental measurement'
    )
    write_generic_ontologized_table(
        'soil_metagenomes_sample_metadata',
        samples_records,
        sample_specs,
        output_dir,
        'IGSN sample registration metadata for topsoil samples associated with the NEON 2018 East River metagenome-assembled genomes dataset',
        sample_metadata_items,
        'BERVO:8000342',
        'Environmental sample'
    )
    write_generic_ontologized_table(
        'soil_metagenomes_mag_manifest',
        mag_records,
        mag_specs,
        output_dir,
        'Manifest of MAG FASTA files packaged with the soil metagenomes dataset; sequence contents are intentionally excluded from BERDL import',
        mag_metadata_items,
        'BERVO:8000409',
        'Genome'
    )


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
            'combination': 'Northing, Projected Coordinate System = UTM Zone 13N',
            'term': 'BERVO:8000441',
            'unit': 'm',
            'definition': 'UTM northing coordinate in WGS84 UTM Zone 13N',
        },
        'Easting': {
            'combination': 'Easting, Projected Coordinate System = UTM Zone 13N',
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
                ["Projected Coordinate System <BERVO:8000442>", "UTM Zone 13N"]
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
    base_dir = Path(__file__).resolve().parents[1]
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

    # Convert soil metagenome metadata and MAG archive manifest.
    print("Converting soil metagenome metadata...")
    convert_soil_metagenomes(base_dir, output_dir)
    print()

    # Convert 2018 field-sampling tabular data using lookup files as context.
    print("Converting 2018 field sampling data...")
    convert_field_sampling_2018(base_dir, output_dir)
    print()

    # Convert CHESS 2025 LAI metadata and summary observations.
    print("Converting leaf area index data...")
    convert_leaf_area_index(base_dir, output_dir)
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
