// T009 additive, read-only metadata inspection. RSX 2.3.0 / T001 adapter.
#pragma once
#include <game/rtech/assets/ui.h>
#include <game/rtech/assets/ui_image.h>
#include <game/rtech/assets/ui_font_atlas.h>

using T009Writer = rapidjson::PrettyWriter<rapidjson::StringBuffer>;
inline void T009Num(T009Writer& w, double v) { if (std::isfinite(v)) w.Double(v); else w.Null(); }
inline void T009Save(rapidjson::StringBuffer& b, std::filesystem::path p) {
    p.replace_extension(".meta.json");
    std::ofstream f(p, std::ios::binary); f.write(b.GetString(), b.GetSize());
}
inline void T009Identity(T009Writer& w, CPakAsset* a) {
    w.Key("guid"); w.String(std::format("{:016x}", a->GetAssetGUID()).c_str());
    w.Key("version"); w.Uint(a->version());
    w.Key("asset_name"); w.String(a->GetAssetName().c_str());
}
inline bool T009ReadablePointer(uintptr_t p) {
    if (p < 65536) return false;
    MEMORY_BASIC_INFORMATION info{};
    if (!VirtualQuery(reinterpret_cast<void*>(p), &info, sizeof(info))) return false;
    return info.State == MEM_COMMIT && !(info.Protect & (PAGE_GUARD | PAGE_NOACCESS)) &&
        (info.Protect & (PAGE_READONLY | PAGE_READWRITE | PAGE_WRITECOPY));
}
// Only examine a committed readable region in this exporting process. No target
// game process is opened. Reject code pages, unbounded and non-ASCII strings.
inline std::string T009String(uintptr_t p) {
    if (p < 65536) return {};
    MEMORY_BASIC_INFORMATION info{};
    if (!VirtualQuery(reinterpret_cast<void*>(p), &info, sizeof(info))) return {};
    if (info.State != MEM_COMMIT || (info.Protect & (PAGE_GUARD | PAGE_NOACCESS))) return {};
    if (!(info.Protect & (PAGE_READONLY | PAGE_READWRITE | PAGE_WRITECOPY))) return {};
    size_t remain = reinterpret_cast<uintptr_t>(info.BaseAddress) + info.RegionSize - p;
    size_t count = std::min<size_t>(remain, 512);
    const char* s = reinterpret_cast<const char*>(p);
    for (size_t i = 0; i < count; ++i) {
        if (!s[i]) {
            std::string out(s, i);
            if (out.starts_with("rui/") || out.starts_with("ui/") || out == "white") return out;
            return {};
        }
        if (s[i] < 32 || s[i] > 126) return {};
    }
    return {};
}
inline void T009ExportUI(CPakAsset* a, UIAsset* u, std::filesystem::path p) {
    rapidjson::StringBuffer b; T009Writer w(b); w.StartObject(); T009Identity(w, a);
    w.Key("element_size"); w.StartArray(); T009Num(w, u->elementWidth); T009Num(w, u->elementHeight); w.EndArray();
    w.Key("element_ratio"); w.StartArray(); T009Num(w, u->elementWidthRatio); T009Num(w, u->elementHeightRatio); w.EndArray();
    w.Key("argument_names_present"); w.Bool(u->argNames != nullptr);
    w.Key("default_values_size"); w.Uint(u->argDefaultValueSize);
    w.Key("rui_struct_size"); w.Uint(u->ruiDataStructSize);
    const auto* hdr = reinterpret_cast<const UIAssetHeader_t*>(a->header());
    w.Key("render_job_count"); w.Uint(hdr->renderJobCount);
    w.Key("styles"); w.StartArray();
    for (uint16_t i = 0; i < u->styleDescCount; ++i) {
        const auto& s = u->styleDescriptors[i]; w.StartObject();
        w.Key("index"); w.Uint(i); w.Key("type"); w.Uint(s.type);
        w.Key("font_field_raw_u16"); w.Uint(s.fontIndex_1E);
        w.Key("text_size_field_raw_u16"); w.Uint(s.textSize);
        w.Key("text_stretch_field_raw_u16"); w.Uint(s.textStretch);
        // Observed 4-byte strides and words exceeding the defaults buffer:
        // these appear to be runtime offsets, NOT literal RGBA or point sizes.
        w.Key("color_fields_raw_u16"); w.StartArray();
        for (const auto& c : s.colors) { w.StartArray(); w.Uint(c.r); w.Uint(c.g); w.Uint(c.b); w.Uint(c.a); w.EndArray(); }
        w.EndArray(); w.EndObject();
    }
    w.EndArray();
    w.Key("string_references"); w.StartArray();
    for (uint32_t i = 0; i + 8 <= u->argDefaultValueSize; i += 4) {
        uintptr_t pointer; memcpy(&pointer, reinterpret_cast<char*>(u->argDefaultValues) + i, 8);
        const auto s = T009String(pointer); if (s.empty()) continue;
        w.StartObject(); w.Key("default_data_offset"); w.Uint(i); w.Key("path"); w.String(s.c_str()); w.EndObject();
    }
    w.EndArray();
    w.Key("shader_constants_f32"); w.StartArray();
    uint32_t end = u->argDefaultValueSize;
    for (int i = 0; i < u->argCount; ++i) if (u->args[i].type && u->args[i].dataOffset < end) end = u->args[i].dataOffset;
    for (uint32_t i = 0; i + 4 <= end; i += 4) {
        // Do not serialize ASLR pointers as floating-point constants.
        bool pointerPart = false;
        for (uint32_t j = (i >= 4 ? i - 4 : 0); j <= i && j + 8 <= end; j += 4) {
            uintptr_t v; memcpy(&v, reinterpret_cast<char*>(u->argDefaultValues) + j, 8);
            if (T009ReadablePointer(v)) pointerPart = true;
        }
        float v; memcpy(&v, reinterpret_cast<char*>(u->argDefaultValues) + i, 4);
        if (pointerPart) w.Null(); else T009Num(w, v);
    }
    w.EndArray(); w.Key("render_program_decoded"); w.Bool(false); w.EndObject(); T009Save(b, p);
}
inline void T009ExportImage(CPakAsset* a, UIImageAsset* u, std::filesystem::path p) {
    rapidjson::StringBuffer b; T009Writer w(b); w.StartObject(); T009Identity(w, a);
    w.Key("original_size"); w.StartArray(); w.Uint(u->width); w.Uint(u->height); w.EndArray();
    const auto* hdr = reinterpret_cast<const UIImageAssetHeader_v2_t*>(a->header());
    const auto* cpu = reinterpret_cast<const UIImageAssetData_v2_t*>(a->cpu());
    w.Key("header_floats_raw"); w.StartArray(); for (float v : hdr->unknownFloats) T009Num(w, v); w.EndArray();
    w.Key("cpu_floats_raw"); w.StartArray();
    const float* values = &cpu->unk_00; for (int i = 0; i < 8; ++i) T009Num(w, values[i]); w.EndArray();
    w.Key("size_shift_raw"); w.Uint(u->imgFlags.sizeShift);
    w.Key("streaming_available"); w.Bool(u->shouldStream);
    w.Key("qualities"); w.StartArray();
    for (int i = 0; i < 2; ++i) {
        const auto& r = u->resData[i]; w.StartObject(); w.Key("index"); w.Int(i);
        w.Key("size"); w.StartArray(); w.Uint(r.width); w.Uint(r.height); w.EndArray();
        w.Key("bc1_tiles"); w.Uint(r.numBc1Tiles); w.Key("bc7_tiles"); w.Uint(r.numBc7Tiles); w.EndObject();
    }
    w.EndArray(); w.EndObject(); T009Save(b, p);
}
inline void T009ExportFont(CPakAsset* a, UIFontAtlasAsset* u, std::filesystem::path p) {
    rapidjson::StringBuffer b; T009Writer w(b); w.StartObject(); T009Identity(w, a);
    w.Key("atlas_guid"); w.String(std::format("{:016x}", u->atlasGUID).c_str());
    w.Key("atlas_size"); w.StartArray(); w.Uint(u->width); w.Uint(u->height); w.EndArray();
    w.Key("dxgi_format"); w.Uint(u->txtrFormat);
    w.Key("fonts"); w.StartArray();
    for (uint16_t i = 0; i < u->fontCount; ++i) {
        const auto& f = u->fontData[i]; w.StartObject();
        w.Key("name"); if (f.name) w.String(f.name); else w.Null();
        w.Key("font_index"); w.Uint(f.fontIndex);
        w.Key("texture_index"); w.Uint(f.textureIndex);
        w.Key("unicode_texture_count"); w.Uint(f.numUnicodeTextures);
        w.Key("glyph_texture_count"); w.Uint(f.numGlyphTextures);
        w.Key("unicode_to_texture_rect"); w.StartArray();
        Vector2D bounds[8], sizes[8]; f.ParseProportions(bounds, sizes);
        // Use the actual unicode tables, without TextureFromUnicode's fallback.
        for (uint32_t cp = 0; cp < 65536 && f.unicodeChunks; ++cp) {
            int fixed = static_cast<int>(cp) - f.unicodeIndex; if (fixed < 0) continue;
            uint32_t chunk = static_cast<uint32_t>(fixed) >> 6; if (chunk >= f.numUnicodeChunks) continue;
            uint32_t table = f.unicodeChunks[chunk]; uint32_t bit = fixed & 63;
            uint64_t mask = f.unicodeChunksMask[table]; if (!(mask & (1ull << bit))) continue;
            uint32_t tex = f.unicodeChunksIndex[table] + static_cast<uint32_t>(__popcnt64(((1ull << bit) - 1) & mask));
            if (tex >= f.numUnicodeTextures) continue;
            UIFontCharacter_t c{}; c.SetBounds(u, &f.unicodeTextures[tex], bounds, sizes);
            w.StartArray(); w.Uint(cp); w.Uint(tex); w.Uint(c.posX); w.Uint(c.posY); w.Uint(c.width); w.Uint(c.height); w.EndArray();
        }
        w.EndArray(); w.EndObject();
    }
    w.EndArray(); w.Key("images"); w.StartArray();
    for (int i = 0; i < u->imageCount; ++i) {
        const auto& c = u->images[i]; w.StartObject(); w.Key("index"); w.Int(i);
        w.Key("font_local_index"); w.Uint(c.font); w.Key("unicode"); w.Int(c.utf16); w.Key("glyph"); w.Int(c.glyph);
        w.Key("rect"); w.StartArray(); w.Uint(c.posX); w.Uint(c.posY); w.Uint(c.width); w.Uint(c.height); w.EndArray(); w.EndObject();
    }
    w.EndArray(); w.EndObject(); T009Save(b, p);
}
