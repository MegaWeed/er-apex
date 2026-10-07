using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using SoulsFormats;
using SoulsFormats.Cryptography;

// A local adapter for the read-only builder, which rejects existing target MATBINs.
// Only staged/output copies are written. Original BND entries keep their order and metadata.
internal static class Program
{
    static string Stem(string name) => Path.GetFileNameWithoutExtension(name.Replace('\\', '/').Split('/').Last());
    static BND4 Read(string path) {
        byte[] bytes = File.ReadAllBytes(path);
        return BND4.Read(DCX.Is(bytes) ? DCX.Decompress(bytes) : bytes);
    }
    static string Header(BND4 b) => JsonSerializer.Serialize(new { b.Version, b.Format, b.Unk04, b.Unk05, b.BigEndian, b.BitBigEndian, b.Unicode, b.Extended });
    static void Save(string path, object value) => File.WriteAllText(path, JsonSerializer.Serialize(value, new JsonSerializerOptions { WriteIndented = true }) + "\n");
    static void Write(BND4 b, string path) => File.WriteAllBytes(path, DCX.Compress(b.Write(new DCX.NoCompressionInfo()), new DCX.DcxKrakCompressionInfo(DCX.KrakCompressionPreset.EldenRing)));
    static void Require(bool ok, string message) { if (!ok) throw new InvalidDataException(message); }

    static object Verify(BND4 original, BND4 result, HashSet<string> targets)
    {
        Require(Header(original) == Header(result), "BND header changed");
        Require(result.Files.Select(f => f.Name).Distinct().Count() == result.Files.Count, "Duplicate BND entry names");
        var same = new List<object>(); var replacements = new List<object>();
        for (int i = 0; i < original.Files.Count; i++) {
            var old = original.Files[i]; var current = result.Files[i];
            Require(old.Name == current.Name && old.ID == current.ID && old.Flags == current.Flags, "Entry order/ID/name/flags changed: " + old.Name);
            bool equal = old.Bytes.AsSpan().SequenceEqual(current.Bytes);
            if (targets.Contains(Stem(old.Name))) {
                MATBIN.Read(current.Bytes);
                replacements.Add(new { name = old.Name, id = old.ID, flags = old.Flags.ToString(), old_size = old.Bytes.Length, new_size = current.Bytes.Length, payload_changed = !equal });
            } else {
                Require(equal, "Original entry payload changed: " + old.Name);
                same.Add(new { name = old.Name, id = old.ID, flags = old.Flags.ToString(), size = old.Bytes.Length });
            }
        }
        var added = result.Files.Skip(original.Files.Count).Select(f => {
            Require(targets.Contains(Stem(f.Name)), "Unrequested added MATBIN: " + f.Name);
            MATBIN.Read(f.Bytes);
            return new { name = f.Name, id = f.ID, flags = f.Flags.ToString(), size = f.Bytes.Length };
        }).ToArray();
        foreach (string target in targets) Require(result.Files.Count(f => Stem(f.Name).Equals(target, StringComparison.OrdinalIgnoreCase)) == 1, "Target absent/ambiguous: " + target);
        return new { status = "PASS", original_entries = original.Files.Count, output_entries = result.Files.Count,
                     preserved_entries = same, replaced_entries = replacements, added_entries = added,
                     header_unchanged = true, original_entry_order_ids_names_flags_unchanged = true };
    }

    static int Main(string[] args)
    {
        try {
            Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);
            Oodle.Oodle6Ptr = System.Runtime.InteropServices.NativeLibrary.Load(Path.Combine(Environment.GetEnvironmentVariable("ELDEN_RING_DIR") is { Length: > 0 } erDir ? erDir : @"E:\SteamLibrary\steamapps\common\ELDEN RING\Game", "oo2core_6_win64.dll"));
            var targets = JsonSerializer.Deserialize<string[]>(File.ReadAllText(args[3]))!.ToHashSet(StringComparer.OrdinalIgnoreCase);
            var original = Read(args[1]);
            if (args[0] == "prepare") {
                int removed = original.Files.RemoveAll(f => targets.Contains(Stem(f.Name)));
                if (removed == 0) File.Copy(args[1], args[2], true); else Write(original, args[2]);
                Console.WriteLine($"Prepared material copy: {removed} existing target entries staged for replacement");
            } else if (args[0] == "merge") {
                // args: merge original generated targets.json output audit.json
                var built = Read(args[2]);
                var generated = built.Files.Where(f => targets.Contains(Stem(f.Name))).ToArray();
                Require(generated.Length == targets.Count, "Generated target inventory differs");
                int nextId = original.Files.Max(f => f.ID) + 1;
                bool changed = false;
                foreach (var fresh in generated) {
                    var previous = original.Files.SingleOrDefault(f => f.Name == fresh.Name);
                    if (previous is null) {
                        original.Files.Add(new BinderFile(fresh.Flags, nextId++, fresh.Name, fresh.Bytes) { CompressionInfo = fresh.CompressionInfo });
                        changed = true;
                    } else {
                        changed |= !previous.Bytes.AsSpan().SequenceEqual(fresh.Bytes);
                        previous.Bytes = fresh.Bytes;
                    }
                }
                if (changed) Write(original, args[4]); else File.Copy(args[1], args[4], true);
                Save(args[5], Verify(Read(args[1]), Read(args[4]), targets));
                Console.WriteLine($"Merged material bundle: {generated.Length} generated targets; all other input entries preserved");
            } else if (args[0] == "verify") {
                Save(args[4], Verify(original, Read(args[2]), targets));
                Console.WriteLine("PASS all input material payloads, entry metadata/order, and requested replacements");
            } else throw new ArgumentException("Expected prepare, merge, or verify");
            return 0;
        } catch (Exception error) { Console.Error.WriteLine(error); return 1; }
    }
}
