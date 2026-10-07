"""Read MBNK v49 event names directly; no action decoding or audio export.

Offsets independently validated against RSX 2.3.0 game/audio/miles.h.
The release disables HAS_MILES_EVENTS, so its CSV contains asrc only.
Available sound source names and languages come from the RSX CSV.
"""
import collections
import csv
import json
import gzip
import mmap
from pathlib import Path
import struct
from rtech_hash import string_to_guid

TERMS = ['fuse', 'diag_mp_fuse', 'r301', 'rspn101']


def build_audio_inventory(bank: Path, out: Path):
    counts = {term: {'aevt': 0, 'asrc': 0} for term in TERMS}
    event_rows = []
    with bank.open('rb') as file, mmap.mmap(file.fileno(), 0, access=mmap.ACCESS_READ) as data:
        magic, version, file_size = struct.unpack_from('<III', data)
        if magic != int.from_bytes(b'KNBC', 'little') or version != 49:
            raise ValueError(f'Expected MBNK v49, got {magic:x}, {version}')
        if file_size > len(data) or file_size < 0xa0:
            raise ValueError('MBNK declared size outside file')
        trailing_bytes = len(data) - file_size
        event_count = struct.unpack_from('<I', data, 0x1c)[0]
        source_count = struct.unpack_from('<I', data, 0x38)[0]
        localised_count = struct.unpack_from('<I', data, 0x3c)[0]
        events, strings = struct.unpack_from('<QQ', data, 0x68)
        event_data = struct.unpack_from('<I', data, 0x2c)[0]
        if events + event_count * 8 > len(data) or strings >= len(data):
            raise ValueError('MBNK event/string table out of bounds')
        for index in range(event_count):
            name_offset, action_offset = struct.unpack_from('<II', data, events + index * 8)
            position = strings + name_offset
            end = data.find(b'\0', position)
            if end < position or end - position > 4096:
                raise ValueError('Invalid event name')
            name = data[position:end].decode('utf8')
            event_rows.append({'type': 'aevt', 'guid': f'{string_to_guid(name):016x}', 'index': index, 'asset_name': name,
                               'file_name': bank.name, 'name_offset': name_offset,
                               'action_offset': event_data + action_offset})
            for term in TERMS:
                counts[term]['aevt'] += term in name.lower()
        # v49 source records occupy the final 80-byte table. This installation
        # has 10 localized groups; upstream Construct() mistakenly multiplies
        # localizedSourceCount by languageNames.size()-1 and omits group 9.
        source_offset = struct.unpack_from('<I', data, 0x34)[0]
        table_bytes = file_size - source_offset
        if table_bytes % 80:
            raise ValueError('MBNK v49 final source table is not aligned to 80-byte records')
        full_source_count = table_bytes // 80
        groups = (full_source_count - source_count) // localised_count
        if source_count + groups * localised_count != full_source_count:
            raise ValueError('Source count does not match v49 table layout')
        build_tag = struct.unpack_from('<I', data, 0x10)[0]
        stream_files = {}
        for stream in sorted(bank.parent.glob('*.mstr')):
            header = stream.open('rb').read(20)
            if len(header) == 20:
                # Layout: language @6, patch @12, buildTag @16.
                language = struct.unpack_from('<H', header, 6)[0]
                patch, tag = struct.unpack_from('<II', header, 12)
                if tag == build_tag:
                    stream_files[(language, patch)] = stream.name
        names = {}
        bank_source_matches = collections.Counter()
        language_counts = collections.Counter()
        available_by_table = 0
        fields = ['type', 'guid', 'index', 'asset_name', 'file_name', 'language_idx', 'patch_idx',
                  'sample_rate', 'sample_count', 'stream_header_offset', 'stream_data_offset']
        with gzip.open(out / 'lists/audio_sources.csv.gz', 'wt', newline='', encoding='utf8', compresslevel=1) as output:
            writer = csv.writer(output)
            writer.writerow(fields)
            for index in range(full_source_count):
                pos = source_offset + index * 80
                name_offset, language, patch = struct.unpack_from('<QHH', data, pos)
                if name_offset not in names:
                    begin = strings + name_offset
                    end = data.find(b'\0', begin)
                    if end < begin or end - begin > 4096:
                        raise ValueError('Invalid sound source name')
                    name = data[begin:end].decode('utf8')
                    names[name_offset] = (name, f'{string_to_guid(name):016x}')
                name, guid = names[name_offset]
                sample_rate = struct.unpack_from('<H', data, pos + 16)[0]
                sample_count, header_offset, data_offset = struct.unpack_from('<QQQ', data, pos + 40)
                stream_name = stream_files.get((language, patch), '')
                available_by_table += bool(stream_name)
                language_counts[str(language)] += 1
                for term in TERMS:
                    bank_source_matches[term] += term in name.lower()
                writer.writerow(['asrc', guid, index, name, stream_name, language, patch,
                                 sample_rate, sample_count, header_offset, data_offset])
    with (out / 'lists/audio_events.csv').open('w', newline='', encoding='utf8') as file:
        writer = csv.DictWriter(file, fieldnames=event_rows[0].keys())
        writer.writeheader()
        writer.writerows(event_rows)
    sources = 0
    languages = collections.Counter()
    matched = [row for row in event_rows if any(term in row['asset_name'].lower() for term in TERMS)]
    with (out / 'lists/audio_named.csv').open(encoding='utf8') as file:
        for row in csv.DictReader(file):
            sources += 1
            languages[row['file_name']] += 1
            matching = [term for term in TERMS if term in row['asset_name'].lower()]
            for term in matching:
                counts[term]['asrc'] += 1
            if matching:
                matched.append(row)
    report = {'bank': str(bank), 'version': version, 'event_count': event_count,
              'declared_file_size': file_size, 'trailing_bytes': trailing_bytes,
              'declared_sources': source_count, 'declared_localised_sources': localised_count,
              'available_source_count': sources, 'available_sources_by_stream': dict(languages),
              'full_bank_source_count': full_source_count, 'localized_group_count': groups,
              'raw_sources_by_language_idx': dict(language_counts),
              'raw_bank_source_substring_counts': dict(bank_source_matches),
              'available_by_raw_table': available_by_table,
              'full_source_list': 'lists/audio_sources.csv.gz',
              'substring_counts': counts,
              'scope': 'aevt: all bank event names; asrc: sources with locally installed matching MSTR files',
              'events_parser': 'MBNK v49 nameOffset/dataOffset tables; action contents not decoded',
              'matches': matched}
    (out / 'audio_inventory.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    return report
