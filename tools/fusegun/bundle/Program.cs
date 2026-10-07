using System.Text;
using System.Text.Json;
using SoulsFormats;
using SoulsFormats.Cryptography;

// T015's converter-side preservation, extended to preserve existing body materials.
internal static class Program
{
    static readonly JsonSerializerOptions Json = new() { WriteIndented=true, IncludeFields=true,
        PropertyNamingPolicy=JsonNamingPolicy.SnakeCaseLower,
        Encoder=System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping };
    static string Stem(string path) => Path.GetFileNameWithoutExtension(path.Replace('\\','/').Split('/').Last());
    static BND4 Read(string path) {
        byte[] bytes=File.ReadAllBytes(path);
        return BND4.Read(DCX.Is(bytes) ? DCX.Decompress(bytes) : bytes);
    }
    static string Output(string path) {
        string full=Path.GetFullPath(path);
        if (!full.Contains(@"\er-data\s3\octane_gun\",StringComparison.OrdinalIgnoreCase)) throw new ArgumentException("Output escapes exclusive T019 folder");
        Directory.CreateDirectory(Path.GetDirectoryName(full)!); return full;
    }
    static void Save(string path, object value) => File.WriteAllText(Output(path),JsonSerializer.Serialize(value,Json)+"\n");
    static HashSet<string> Targets(string path,string key) {
        using var doc=JsonDocument.Parse(File.ReadAllText(path));
        return new(doc.RootElement.GetProperty(key).EnumerateArray().Select(x=>x.GetString()!),StringComparer.OrdinalIgnoreCase);
    }
    static object Entry(BinderFile f) => new { f.ID, f.Name, flags=(int)f.Flags, size=f.Bytes.Length };
    static object Header(BND4 b) => new { b.Version,b.Format,b.Unk04,b.Unk05,b.BigEndian,b.BitBigEndian,b.Unicode,b.Extended };
    static void Require(bool condition, string message) { if (!condition) throw new InvalidDataException(message); }
    static bool SameMetadata(BinderFile a, BinderFile b) => a.ID==b.ID && a.Name==b.Name && a.Flags==b.Flags &&
        a.CompressionInfo.GetType()==b.CompressionInfo.GetType() &&
        JsonSerializer.Serialize(a.CompressionInfo,a.CompressionInfo.GetType(),Json)==JsonSerializer.Serialize(b.CompressionInfo,b.CompressionInfo.GetType(),Json);
    static object Compare(BND4 input, BND4 output, HashSet<string> generated,HashSet<string> replace) {
        Require(JsonSerializer.Serialize(Header(input),Json)==JsonSerializer.Serialize(Header(output),Json),"Binder header changed");
        Require(output.Files.Count>=input.Files.Count,"Input entries were lost");
        var preserved=new List<object>(); var replaced=new List<object>();
        for (int i=0;i<input.Files.Count;i++) {
            var a=input.Files[i]; var b=output.Files[i];
            Require(SameMetadata(a,b),"Input entry order/metadata changed: "+a.Name);
            if (replace.Contains(Stem(a.Name))) {
                MATBIN.Read(b.Bytes); replaced.Add(new { original=Entry(a), output=Entry(b), bytes_identical=a.Bytes.SequenceEqual(b.Bytes) });
            } else {
                Require(a.Bytes.SequenceEqual(b.Bytes),"Input entry bytes changed: "+a.Name); preserved.Add(Entry(a));
            }
        }
        var additions=output.Files.Skip(input.Files.Count).ToList();
        var present=input.Files.Select(f=>Stem(f.Name)).ToHashSet(StringComparer.OrdinalIgnoreCase);
        var expected=generated.Where(t=>!present.Contains(t)).ToHashSet(StringComparer.OrdinalIgnoreCase);
        Require(additions.Count==expected.Count && expected.SetEquals(additions.Select(f=>Stem(f.Name))),"Unexpected added entries");
        foreach(var f in additions) { MATBIN.Read(f.Bytes); Require(!present.Contains(Stem(f.Name)),"Duplicate target entry"); }
        Require(output.Files.Select(f=>f.ID).Distinct().Count()==output.Files.Count,"Duplicate binder IDs");
        return new { status="PASS",input_entries=input.Files.Count,output_entries=output.Files.Count,
            preserved_entries=preserved.Count,replaced_entries=replaced.Count,added_entries=additions.Count,
            direct_byte_comparison=true,original_order_and_metadata_exact=true,
            preserved,replaced,added=additions.Select(Entry) };
    }
    static void WriteKrak(BND4 bnd,string path) {
        byte[] raw=bnd.Write(new DCX.NoCompressionInfo());
        File.WriteAllBytes(Output(path),DCX.Compress(raw,new DCX.DcxKrakCompressionInfo(DCX.KrakCompressionPreset.EldenRing)));
    }
    static int Main(string[] args) {
        try {
            Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);
            Oodle.Oodle6Ptr=System.Runtime.InteropServices.NativeLibrary.Load(Path.Combine(Environment.GetEnvironmentVariable("ELDEN_RING_DIR") is { Length: > 0 } erDir ? erDir : @"E:\SteamLibrary\steamapps\common\ELDEN RING\Game", "oo2core_6_win64.dll"));
            if(args[0]=="prepare" && args.Length==5) {
                var bnd=Read(args[1]);var targets=Targets(args[2],"generated");
                var collisions=bnd.Files.Where(f=>targets.Contains(Stem(f.Name))).Select(Entry).ToArray();
                int count=bnd.Files.Count;bnd.Files.RemoveAll(f=>targets.Contains(Stem(f.Name)));
                File.WriteAllBytes(Output(args[3]),bnd.Write(new DCX.NoCompressionInfo()));
                Save(args[4],new { input_entries=count,builder_entries=bnd.Files.Count,collisions,
                    rule="remove generated target basenames only in private copy; preserve original body entries during finish" });
                Console.WriteLine($"Prepared material copy: {count} entries, {collisions.Length} private collisions");
            } else if(args[0]=="finish" && args.Length==5) {
                var original=Read(args[1]);var built=Read(args[2]);
                var targets=Targets(args[3],"generated");var replace=Targets(args[3],"replace");
                if(original.Files.Any(f=>targets.Contains(Stem(f.Name)))) {
                    var generated=built.Files.Where(f=>targets.Contains(Stem(f.Name))).ToDictionary(f=>Stem(f.Name),StringComparer.OrdinalIgnoreCase);
                    Require(targets.SetEquals(generated.Keys),"Missing generated material");
                    var present=original.Files.Select(f=>Stem(f.Name)).ToHashSet(StringComparer.OrdinalIgnoreCase);
                    foreach(var f in original.Files.Where(f=>replace.Contains(Stem(f.Name)))) f.Bytes=generated[Stem(f.Name)].Bytes;
                    int next=original.Files.Max(f=>f.ID)+1;
                    foreach(var f in built.Files.Where(f=>targets.Contains(Stem(f.Name)) && !present.Contains(Stem(f.Name)))) {
                        f.ID=next++;original.Files.Add(f);
                    }
                    WriteKrak(original,args[2]);
                }
                Save(args[4],Compare(Read(args[1]),Read(args[2]),targets,replace));
                Console.WriteLine("PASS material bundle: all non-replaced input bytes, order and metadata preserved");
            } else if(args[0]=="verify" && args.Length==5) {
                Save(args[4],Compare(Read(args[1]),Read(args[2]),Targets(args[3],"generated"),Targets(args[3],"replace")));
                Console.WriteLine("PASS independent bundle byte comparison");
            } else throw new ArgumentException("prepare input targets output report | finish/verify input output targets report");
            return 0;
        } catch(Exception ex) { Console.Error.WriteLine("MaterialBundle: "+ex.Message); return 1; }
    }
}
