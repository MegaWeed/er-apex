"""Bounded MBNK v49 event/source reader.

Layout reference: local RSX 2.3.0 game/audio/{miles,event,source}.{h,cpp}.
Tool license: AGPL-3.0-only; LZB decoder adapted from RAD's MIT implementation.
See LICENSE and THIRD_PARTY.md. No name-based event/source matching is used.
"""
import mmap
import struct


def lzb_decode(data, size):
    if len(data) == size:
        return bytes(data)
    if not 0 < len(data) < size <= 65535:
        raise ValueError('Invalid LZB sizes')
    cursor = 0
    out = bytearray()

    def byte():
        nonlocal cursor
        if cursor >= len(data):
            raise ValueError('Truncated LZB')
        value = data[cursor]
        cursor += 1
        return value

    def excess():
        value = byte()
        if value >= 192:
            for shift in (6, 13, 20, 27):
                part = byte()
                value += part << shift
                if part < 128:
                    break
        return value

    while len(out) < size:
        control = byte()
        literals = control & 15
        match = control >> 4
        if literals == 15:
            literals += excess()
        elif literals == 9 and len(out) + literals >= size:
            literals = size - len(out)
        if cursor + literals > len(data) or len(out) + literals > size:
            raise ValueError('Invalid LZB literals')
        out.extend(data[cursor:cursor + literals])
        cursor += literals
        if len(out) == size:
            break
        length = match + 4
        if match < 15:
            offset = byte() | byte() << 8
        else:
            code = byte()
            if code & 128:
                offset = code & 7
                length = ((code & 127) >> 3) + 4
                if length == 19:
                    length += excess()
            else:
                offset = byte() | byte() << 8
                length += code
                if code == 127:
                    length += excess()
        if not 0 < offset <= len(out) or len(out) + length > size:
            raise ValueError('Invalid LZB back reference')
        for _ in range(length):
            out.append(out[-offset])
    if cursor != len(data):
        raise ValueError('LZB compressed bytes not fully consumed')
    return bytes(out)


class Bank:
    def __init__(self, path, *, preserve_action_bytes=False):
        self.preserve_action_bytes = preserve_action_bytes
        self.file = path.open('rb')
        self.data = mmap.mmap(self.file.fileno(), 0, access=mmap.ACCESS_READ)
        if self.data[:4] != b'KNBC' or self.u32(4) != 49:
            raise ValueError('Expected MBNK v49')
        self.strings = self.u64(0x70)
        self.sources = self.u32(0x34)
        self.source_count = (self.u32(8) - self.sources) // 80
        self.events = {}
        table = self.u64(0x68)
        for index in range(self.u32(0x1c)):
            name, offset = struct.unpack_from('<II', self.data, table + index * 8)
            self.events[self.string(name).lower()] = {
                'name': self.string(name), 'index': index,
                'action_offset': self.u32(0x2c) + offset}
        self.streams = {}
        for stream in sorted(path.parent.glob('*.mstr')):
            with stream.open('rb') as file:
                header = file.read(20)
            if len(header) == 20 and struct.unpack_from('<I', header, 16)[0] == self.u32(0x10):
                language = struct.unpack_from('<H', header, 6)[0]
                patch = struct.unpack_from('<I', header, 12)[0]
                self.streams[(language, patch)] = stream.name

    def close(self):
        self.data.close()
        self.file.close()

    def u32(self, offset):
        return struct.unpack_from('<I', self.data, offset)[0]

    def u64(self, offset):
        return struct.unpack_from('<Q', self.data, offset)[0]

    def string(self, offset):
        start = self.strings + offset
        end = self.data.find(b'\0', start, start + 4096)
        if end < start:
            raise ValueError('Invalid bank string')
        return self.data[start:end].decode('utf8')

    def source(self, index):
        if not 0 <= index < self.source_count:
            raise ValueError(f'Invalid source index {index}')
        pos = self.sources + index * 80
        name, language, patch = struct.unpack_from('<QHH', self.data, pos)
        rate = struct.unpack_from('<H', self.data, pos + 16)[0]
        samples, header, audio = struct.unpack_from('<QQQ', self.data, pos + 40)
        source = {'index': index, 'name': self.string(name), 'record_offset': pos,
                'language_idx': language, 'patch_idx': patch,
                'file_name': self.streams.get((language, patch)),
                'sample_rate': rate, 'sample_count': samples,
                'stream_header_offset': header, 'stream_data_offset': audio}
        if self.preserve_action_bytes:
            # v49 marker layout: local RSX miles.h/source.h and miles.cpp.
            count, relative = self.data[pos + 21], self.u32(pos + 64)
            table = self.u64(0x58)
            markers = []
            if count and (not table or relative % 16 or table + relative + count * 16 > len(self.data)):
                raise ValueError(f'Invalid source marker table: {index}')
            for ordinal in range(count):
                offset = table + relative + ordinal * 16
                marker_name, frame = struct.unpack_from('<II', self.data, offset)
                if frame > samples:
                    raise ValueError(f'Source marker outside sample frames: {index}')
                markers.append({'name': self.string(marker_name), 'frame_position': frame,
                                'record_offset': offset})
            source.update({'marker_count': count, 'marker_table_offset': relative, 'markers': markers})
        return source

    def parse_event(self, name):
        event = self.events[name.lower()]
        pos = event['action_offset']
        raw, compressed = struct.unpack_from('<HH', self.data, pos)
        decoded = lzb_decode(self.data[pos + 4:pos + 4 + compressed], raw)
        actions = []
        cursor = 0
        while cursor < len(decoded):
            kind, count, dwords = struct.unpack_from('<BBH', decoded, cursor)
            size = dwords * 4
            if size < 4 or cursor + size > len(decoded):
                raise ValueError('Invalid action size')
            data = decoded[cursor:cursor + size]
            action = {'type': kind & 15, 'decoded_offset': cursor,
                      'bytes': size, 'sources': [], 'events': [], 'states': []}
            if self.preserve_action_bytes:
                # Preserve unknown control/loop fields as evidence, without assigning semantics.
                action['raw_hex'] = data.hex()
            if action['type'] == 8:
                n = struct.unpack_from('<I', data, 4)[0]
                for i in range(n):
                    action['events'].append(self.string(struct.unpack_from('<I', data, 12 + i * 4)[0]))
            elif action['type'] == 0:
                def u16(p):
                    return struct.unpack_from('<H', data, p)[0]

                def i32(p):
                    return struct.unpack_from('<i', data, p)[0]

                def selector(root, p, path):
                    if p in path or len(path) > 64:
                        raise ValueError('Selector cycle/depth')
                    kind, weight, children = struct.unpack_from('<BBH', data, p)
                    node = {'type': kind & 7, 'weight': weight, 'offset': p}
                    if node['type'] == 0:
                        idx = i32(p + 4)
                        node['source_index'] = idx
                        if idx != -1:
                            source = self.source(idx)
                            source['selector_offset'] = p
                            source['weight'] = weight
                            action['sources'].append(source)
                    else:
                        node['children'] = [selector(root, root + u16(p + 12 + j * 2) * 4, path + [p])
                                            for j in range(children)]
                    return node

                state = u16(0x76) * 4
                for _ in range(count):
                    flags = u16(state + 14)
                    flags2 = u16(state + 18)
                    if flags & 1 or flags2 & 0x20 or not i32(state + 68):
                        break
                    n = data[state + 4]
                    entry = {'name': self.string(i32(state)), 'selectors': []}
                    if n:
                        if flags2 & 0x10 or not i32(state + 64):
                            break
                        ref = (u16(0x78) + data[state + 6]) * 4
                        for j in range(n):
                            relative = i32(ref + j * 36)
                            if relative != -1:
                                root = (u16(0x7a) + relative) * 4
                                entry['selectors'].append(selector(root, root, []))
                    action['states'].append(entry)
                    state += (104 if flags & 0x100 else 80) + 36 * (data[state + 8] + data[state + 9])
                action['graph_flags'] = struct.unpack_from('<I', data, 0x80)[0]
                action['pitch_raw'], action['volume_raw'] = struct.unpack_from('<ff', data, 0x3c)
            actions.append(action)
            cursor += size
            if kind & 16:
                if cursor != len(decoded):
                    raise ValueError('Trailing event action bytes')
                break
        if not actions or not kind & 16:
            raise ValueError('Missing final action')
        return {**event, 'raw_size': raw, 'compressed_size': compressed, 'actions': actions}

    def resolve(self, name, path=()):
        key = name.lower().removeprefix('/general/')
        if key in path or len(path) > 64:
            raise ValueError('Event cycle/depth')
        event = self.parse_event(key)
        sources = []
        graph = [event]
        for action in event['actions']:
            for source in action['sources']:
                sources.append({**source, 'event_chain': list(path) + [key],
                                'event_action_offset': event['action_offset'],
                                'decoded_action_offset': action['decoded_offset']})
            for child in action['events']:
                sub, nodes = self.resolve(child, path + (key,))
                sources.extend(sub)
                graph.extend(nodes)
        return sources, graph
