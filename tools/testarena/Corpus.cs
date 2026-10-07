using System.Buffers.Binary;
using System.Text.Json;
using SoulsFormats;
using static TestArena.Program;

namespace TestArena;

internal static class Corpus
{
    internal sealed record Result(int Files, int MsbFiles, int EmevdFiles, long DecompressedBytes, int InstantiatedEvents, uint[] ReservedIds);
    sealed record VanillaEvent(string File, EMEVD.Event Event);

    internal static Result Scan(Config config)
    {
        string manifestPath = Path.Combine(DataDir, "corpus-manifest.json");
        Require(File.Exists(manifestPath), "Missing corpus-manifest.json; run python run.py extract");
        using JsonDocument manifest = JsonDocument.Parse(File.ReadAllText(manifestPath));
        var entries = manifest.RootElement.GetProperty("entries").EnumerateArray().ToArray();
        var paths = entries.Select(e => e.GetProperty("path").GetString()!).ToArray();
        Require(paths.Length > 0 && paths.Distinct(StringComparer.OrdinalIgnoreCase).Count() == paths.Length, "Invalid corpus inventory");
        var actual = Directory.GetFiles(Path.Combine(DataDir, "originals"), "*.dcx", SearchOption.AllDirectories)
            .Select(f => "/" + Path.GetRelativePath(Path.Combine(DataDir, "originals"), f).Replace('\\', '/')).ToHashSet(StringComparer.OrdinalIgnoreCase);
        Require(actual.SetEquals(paths), "Extracted input file inventory differs from archive manifest");
        Require(paths.Contains("/" + MapPath(config.TargetMap)) && paths.Contains("/" + EventPath(config.TargetMap)) &&
            paths.Contains("/" + MapPath(config.Template.Map)) && paths.Contains("/" + MapPath(config.Reference.Map)) &&
            paths.Contains("/event/common.emevd.dcx") && paths.Contains("/event/common_func.emevd.dcx"), "Required inputs missing from corpus");
        var reserved = config.ReservedIds.ToHashSet();
        List<object> literals = new(), ranges = new();
        List<VanillaEvent> events = new();
        int msbs = 0, emevds = 0;
        long decompressedBytes = 0;
        Console.WriteLine($"Scanning {entries.Length} vanilla files, checking SHA256 and every byte offset for {reserved.Count} reserved IDs...");
        for (int index = 0; index < entries.Length; index++)
        {
            JsonElement entry = entries[index];
            string file = entry.GetProperty("path").GetString()!;
            string path = Original(file);
            Require(new FileInfo(path).Length == entry.GetProperty("size").GetInt64(), "Input size mismatch: " + file);
            Require(Sha256(path).Equals(entry.GetProperty("sha256").GetString(), StringComparison.OrdinalIgnoreCase), "Input SHA256 mismatch: " + file);
            byte[] raw = DCX.Decompress(File.ReadAllBytes(path));
            decompressedBytes += raw.Length;
            for (int offset = 0; offset <= raw.Length - 4; offset++)
            {
                uint value = BinaryPrimitives.ReadUInt32LittleEndian(raw.AsSpan(offset, 4));
                if (reserved.Contains(value)) literals.Add(new { File = file, Offset = offset, Id = value });
            }
            if (file.EndsWith(".msb.dcx", StringComparison.OrdinalIgnoreCase)) msbs++;
            else if (file.EndsWith(".emevd.dcx", StringComparison.OrdinalIgnoreCase))
            {
                emevds++;
                foreach (EMEVD.Event ev in EMEVD.Read(raw).Events)
                {
                    events.Add(new(file, ev));
                    for (int i = 0; i < ev.Instructions.Count; i++)
                        CheckRanges(config, file, ev.ID, i, ev.Instructions[i], ranges, null);
                }
            }
            else throw new InvalidDataException("Unexpected corpus file: " + file);
        }
        // Check concrete initializer arguments substituted into parameterized batch/range flag operations.
        // The unmodified instructions and every initializer argument were already covered by the byte scan.
        var byId = events.GroupBy(e => e.Event.ID).ToDictionary(g => g.Key, g => g.ToArray());
        int instantiated = 0;
        foreach (VanillaEvent parent in events)
        {
            for (int i = 0; i < parent.Event.Instructions.Count; i++)
            {
                EMEVD.Instruction call = parent.Event.Instructions[i];
                if (call.Bank != 2000 || call.ID is not (0 or 6) || call.ArgData.Length < 12) continue;
                long calledId = BinaryPrimitives.ReadUInt32LittleEndian(call.ArgData.AsSpan(4, 4));
                if (!byId.TryGetValue(calledId, out VanillaEvent[]? children)) continue;
                foreach (VanillaEvent child in children)
                {
                    if (child.Event.Parameters.Count == 0) continue;
                    if (call.ID == 0 && child.File != parent.File && !child.File.StartsWith("/event/common", StringComparison.Ordinal)) continue;
                    if (call.ID == 6 && !child.File.StartsWith("/event/common", StringComparison.Ordinal)) continue;
                    instantiated++;
                    foreach (var group in child.Event.Parameters.GroupBy(p => p.InstructionIndex))
                    {
                        int instructionIndex = checked((int)group.Key);
                        EMEVD.Instruction original = child.Event.Instructions[instructionIndex];
                        if (!IsRangeInstruction(original)) continue;
                        byte[] arguments = (byte[])original.ArgData.Clone();
                        bool concrete = true;
                        foreach (EMEVD.Parameter parameter in group)
                        {
                            if (parameter.SourceStartByte < 0 || parameter.SourceStartByte + 8 + parameter.ByteCount > call.ArgData.Length)
                            {
                                concrete = false; break;
                            }
                            Array.Copy(call.ArgData, parameter.SourceStartByte + 8, arguments, parameter.TargetStartByte, parameter.ByteCount);
                        }
                        if (concrete)
                            CheckRanges(config, child.File, calledId, instructionIndex, new(original.Bank, original.ID, arguments), ranges,
                                $"{parent.File}: event {parent.Event.ID}, instruction {i}");
                    }
                }
            }
        }
        var result = new Result(entries.Length, msbs, emevds, decompressedBytes, instantiated, config.ReservedIds);
        WriteJson("evidence/collision-scan.json", new
        {
            Result = result, ManifestSha256 = Sha256(manifestPath),
            Scope = "Every archive-listed MSB and EMEVD, including DLC and common*.emevd; exact u32 values at every byte offset; known flag ranges; concrete initializer parameter substitution for range operations.",
            LiteralCollisions = literals, FlagRangeCollisions = ranges,
            Limit = "Dynamically computed flags or engine-internal allocations are not proven by a static vanilla scan."
        });
        Require(literals.Count == 0 && ranges.Count == 0, $"Reserved ID collision: {literals.Count} literal / {ranges.Count} range matches; see evidence/collision-scan.json");
        Console.WriteLine($"PASS reserved IDs: {msbs} MSB + {emevds} EMEVD; 0 literal/range collisions");
        return result;
    }

    static bool IsRangeInstruction(EMEVD.Instruction instruction) =>
        instruction.Bank == 3 && instruction.ID is 1 or 10 ||
        instruction.Bank == 1003 && instruction.ID is 3 or 4 or 103 ||
        instruction.Bank == 2003 && instruction.ID is 17 or 22 or 63;

    static void CheckRanges(Config config, string file, long eventId, int index, EMEVD.Instruction instruction, List<object> hits, string? initializer)
    {
        if (!IsRangeInstruction(instruction)) return;
        int offset = instruction.Bank == 2003 ? 0 : 4;
        if (instruction.Bank == 3 && instruction.ID == 10 && instruction.ArgData[1] != 0) return;
        if (instruction.Bank is 3 or 1003 && instruction.ID != 10 && instruction.ArgData[2] != 0) return;
        Require(instruction.ArgData.Length >= offset + 8, "Malformed flag range instruction");
        uint start = BinaryPrimitives.ReadUInt32LittleEndian(instruction.ArgData.AsSpan(offset, 4));
        uint end = BinaryPrimitives.ReadUInt32LittleEndian(instruction.ArgData.AsSpan(offset + 4, 4));
        foreach (uint id in new[] { config.TestFlag, config.EventId })
            if (start <= id && id <= end)
                hits.Add(new { File = file, EventId = eventId, InstructionIndex = index, instruction.Bank, InstructionId = instruction.ID, Start = start, End = end, Id = id, Initializer = initializer });
    }
}
