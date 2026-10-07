using System.Diagnostics;
using System.Numerics;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;
using SoulsFormats;
using SoulsFormats.Cryptography;

// All game-format serialization is delegated to the pinned SoulsFormatsNEXT dependency.
internal static class ArmorBuilder
{
    static readonly JsonSerializerOptions Json = new() {
        WriteIndented = true, IncludeFields = true, PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        Converters = { new JsonStringEnumConverter() },
        Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping
    };
    static readonly string DefaultGame = Environment.GetEnvironmentVariable("ELDEN_RING_DIR") is { Length: > 0 } erDir ? erDir : @"E:\SteamLibrary\steamapps\common\ELDEN RING\Game";
    // tools\bin\texconv next to this tool (ertool.exe is in tools\erdata\ertool\bin\Release\net8.0)
    static readonly string DefaultTexconv = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", "..", "bin", "texconv", "texconv.exe"));
    public static int Run(string[] args)
    {
        var options = new Dictionary<string, string>(); var inputs = new List<string>();
        for (int i = 1; i < args.Length; i++) {
            if (args[i].StartsWith("--")) {
                if (i + 1 == args.Length || args[i + 1].StartsWith("--")) throw new ArgumentException("Missing value for " + args[i]);
                if (!options.TryAdd(args[i], args[++i])) throw new ArgumentException("Duplicate option " + args[i - 1]);
            } else inputs.Add(args[i]);
        }
        string Need(string key) => options.GetValueOrDefault(key) ?? throw new ArgumentException("Required option: " + key);
        var allowed = new HashSet<string>(new[] { "--out", "--game-dir", "--matbin-bnd" });
        allowed.UnionWith(args[0] switch {
            "export-mesh" => new[] { "--tpf" },
            "build-armor" => new[] { "--template-dir", "--template-model", "--mesh", "--model", "--texconv",
                "--hd-template", "--bd-template", "--am-template", "--lg-template",
                "--hd-mesh", "--bd-mesh", "--am-mesh", "--lg-mesh" },
            "unpack-bnd" => new[] { "--filter" },
            _ => new[] { "--template-dir", "--models" }
        });
        foreach (string key in options.Keys) if (!allowed.Contains(key)) throw new ArgumentException("Unknown option: " + key);
        string game = options.GetValueOrDefault("--game-dir", DefaultGame);
        string dll = Path.Combine(game, "oo2core_6_win64.dll");
        if (File.Exists(dll)) Oodle.Oodle6Ptr = System.Runtime.InteropServices.NativeLibrary.Load(dll);
        switch (args[0]) {
            case "export-mesh":
                if (inputs.Count != 1) throw new ArgumentException("export-mesh needs one input file");
                Export(inputs[0], Need("--out"), options.GetValueOrDefault("--matbin-bnd"), options.GetValueOrDefault("--tpf")); break;
            case "build-armor":
                if (inputs.Count != 0) throw new ArgumentException("build-armor takes named options only");
                if (!File.Exists(dll)) throw new FileNotFoundException("KRAK requires the game's Oodle DLL", dll);
                Build(options, Model(Need("--model")), Need("--matbin-bnd"), Need("--out"), options.GetValueOrDefault("--texconv", DefaultTexconv)); break;
            case "armor-evidence":
                if (inputs.Count != 0) throw new ArgumentException("armor-evidence takes named options only");
                Evidence(Need("--template-dir"), Need("--models").Split(',').Select(Model).ToArray(), Need("--matbin-bnd"), Need("--out")); break;
            case "unpack-bnd":
                if (inputs.Count != 1) throw new ArgumentException("unpack-bnd needs one input file");
                string root = Need("--out"); Directory.CreateDirectory(root); var paths = new HashSet<string>(StringComparer.OrdinalIgnoreCase); int count = 0;
                foreach (var entry in Binder(inputs[0]).Files) {
                    if (options.TryGetValue("--filter", out string? filter) && !entry.Name.Contains(filter, StringComparison.OrdinalIgnoreCase)) continue;
                    string relative = Regex.Replace(entry.Name.Replace('\\', '/'), @"^([A-Za-z]):/", "$1/"); string target = Relative(root, relative);
                    if (!paths.Add(target)) throw new InvalidDataException("Duplicate BND output path: " + entry.Name);
                    Directory.CreateDirectory(Path.GetDirectoryName(target)!); File.WriteAllBytes(target, entry.Bytes); count++;
                }
                Console.WriteLine($"Unpacked {count} files to {root}"); break;
        }
        return 0;
    }
    static int Model(string text) => int.TryParse(text, out int n) && n is >= 0 and <= 9999 ? n : throw new ArgumentException("Model must be 0..9999");
    static byte[] Read(string path) { var bytes = File.ReadAllBytes(path); return DCX.Is(bytes) ? DCX.Decompress(bytes) : bytes; }
    static string Base(string path) => path.Replace('\\', '/').Split('/').Last();
    static string Stem(string path) => Path.GetFileNameWithoutExtension(Base(path));
    static void SaveJson(string path, object value) => File.WriteAllText(path, JsonSerializer.Serialize(value, Json) + "\n");
    static string Relative(string root, string path)
    {
        if (string.IsNullOrWhiteSpace(path) || Path.IsPathRooted(path) || path.Contains(':')) throw new InvalidDataException("Expected relative path: " + path);
        string full = Path.GetFullPath(Path.Combine(root, path));
        string prefix = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        if (!full.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("Path escapes fusemesh: " + path);
        return full;
    }
    static BND4 Binder(string path) => BND4.Read(Read(path));
    static BinderFile Entry(BND4 bnd, string ext) => bnd.Files.Single(f => f.Name.EndsWith(ext, StringComparison.OrdinalIgnoreCase));
    static string Part(string dir, string piece, int model, string lod) => Path.Combine(dir, $"{piece}_m_{model:D4}{lod}.partsbnd.dcx");
    static Dictionary<string, BinderFile> MaterialFiles(BND4 bnd) => bnd.Files.Where(f => f.Name.EndsWith(".matbin", StringComparison.OrdinalIgnoreCase)).GroupBy(f => Stem(f.Name), StringComparer.OrdinalIgnoreCase).ToDictionary(g => g.Key, g => g.OrderByDescending(f => f.Name.Contains(@"\Parts\", StringComparison.OrdinalIgnoreCase)).First(), StringComparer.OrdinalIgnoreCase);
    static Dictionary<string, TPF.Texture> TextureFiles(IEnumerable<TPF> tpfs) => tpfs.SelectMany(t => t.Textures).GroupBy(t => t.Name, StringComparer.OrdinalIgnoreCase).ToDictionary(g => g.Key, g => g.First(), StringComparer.OrdinalIgnoreCase);

    public sealed class MeshDocument
    {
        public string Format { get; set; } = "fusemesh";
        public int Version { get; set; } = 1;
        public string Space { get; set; } = "flver_model";
        public List<string> Bones { get; set; } = new();
        public List<MeshMaterial> Materials { get; set; } = new();
        public List<Submesh> Submeshes { get; set; } = new();
    }
    public sealed class MeshMaterial
    {
        public string Name { get; set; } = "";
        public string TemplateMatbin { get; set; } = "";
        public Dictionary<string, string> Textures { get; set; } = new();
        // Optional explicit replacements for shared detail samplers, keyed by exact Type.
        public Dictionary<string, string> SamplerTextures { get; set; } = new();
        public Dictionary<string, float> FloatParams { get; set; } = new();
        public string? FlverName { get; set; }
    }
    public sealed class Submesh
    {
        public string Name { get; set; } = "";
        public int Material { get; set; }
        public int VertexCount { get; set; }
        public int IndexCount { get; set; }
        public string Positions { get; set; } = "";
        public string Normals { get; set; } = "";
        public string Tangents { get; set; } = "";
        public string Uv0 { get; set; } = "";
        public string Uv1 { get; set; } = "";
        public string? Colors { get; set; }
        public string BoneIndices { get; set; } = "";
        public string BoneWeights { get; set; } = "";
        public string Indices { get; set; } = "";
        // Optional roundtrip metadata; the required v1 arrays remain usable by other exporters.
        public string? NodeName { get; set; }
        public string? NormalW { get; set; }
        public string? FlverBoneWeights { get; set; }
        public bool CullBackfaces { get; set; } = true;
        public List<Face>? FaceSets { get; set; }
        public Cloth? FlverCloth { get; set; }
    }
    public sealed class Cloth
    {
        public string Positions { get; set; } = "";
        public string Normals { get; set; } = "";
        public string Tangents { get; set; } = "";
        public string NormalW { get; set; } = "";
        public string Bitangents { get; set; } = "";
    }
    public sealed class Face
    {
        public uint Flags { get; set; }
        public bool CullBackfaces { get; set; } = true;
        public short Unk06 { get; set; }
        public string Indices { get; set; } = "";
        public int IndexCount { get; set; }
    }
    static void WriteArray(string dir, string name, Action<BinaryWriter> write) { using var bw = new BinaryWriter(File.Create(Relative(dir, name))); write(bw); }
    static void Vec(BinaryWriter b, Vector3 v) { b.Write(v.X); b.Write(v.Y); b.Write(v.Z); }
    static void Vec(BinaryWriter b, Vector4 v) { Vec(b, new Vector3(v.X, v.Y, v.Z)); b.Write(v.W); }
    static byte Color(float v) => checked((byte)Math.Round(Math.Clamp(v, 0, 1) * 255));

    static void Export(string file, string output, string? matbinPath, string? tpfPath)
    {
        var bytes = Read(file); BND4? bnd = BND4.Is(bytes) ? BND4.Read(bytes) : null;
        var flver = FLVER2.Read(bnd is null ? bytes : Entry(bnd, ".flver").Bytes);
        var tpfs = new List<TPF>();
        if (bnd is not null) tpfs.AddRange(bnd.Files.Where(f => f.Name.EndsWith(".tpf", StringComparison.OrdinalIgnoreCase)).Select(f => TPF.Read(f.Bytes)));
        if (tpfPath is not null) tpfs.Add(TPF.Read(Read(tpfPath)));
        if (bnd is null && tpfPath is null && File.Exists(Path.ChangeExtension(file, ".tpf"))) tpfs.Add(TPF.Read(Read(Path.ChangeExtension(file, ".tpf"))));
        var textures = TextureFiles(tpfs);
        var matbins = matbinPath is null ? null : MaterialFiles(Binder(matbinPath));
        if (flver.Nodes.Count is 0 or > 256 || flver.Nodes.Select(n => n.Name).Distinct().Count() != flver.Nodes.Count) throw new InvalidDataException("fusemesh requires 1..256 uniquely named nodes");
        Directory.CreateDirectory(output);
        foreach (var tex in textures.Values) File.WriteAllBytes(Relative(output, tex.Name + ".dds"), tex.Bytes);
        var doc = new MeshDocument { Bones = flver.Nodes.Select(n => n.Name).ToList() };
        foreach (var (m, i) in flver.Materials.Select((m, i) => (m, i))) {
            var material = new MeshMaterial { Name = $"m{i:D2}_" + Slug(m.Name), FlverName = m.Name, TemplateMatbin = Stem(m.MTD) };
            if (matbins is not null) {
                if (!matbins.TryGetValue(material.TemplateMatbin, out var mf)) throw new InvalidDataException("Missing MATBIN: " + material.TemplateMatbin);
                foreach (var sampler in MATBIN.Read(mf.Bytes).Samplers) {
                    string name = Stem(sampler.Path);
                    if (textures.ContainsKey(name)) material.Textures[Suffix(name)] = name + ".dds";
                }
            } else {
                // FLVER texture slots can be empty in ER. Export the local TPF's set;
                // build-armor resolves which suffixes each template MATBIN actually uses.
                foreach (var tex in textures.Values) material.Textures[Suffix(tex.Name)] = tex.Name + ".dds";
            }
            doc.Materials.Add(material);
        }
        var world = World(flver);
        foreach (var (mesh, mi) in flver.Meshes.Select((m, i) => (m, i))) {
            string prefix = $"mesh{mi:D3}";
            var s = new Submesh { Name = prefix, Material = mesh.MaterialIndex, VertexCount = mesh.Vertices.Count,
                NodeName = mesh.NodeIndex < 0 ? null : flver.Nodes[mesh.NodeIndex].Name };
            var verts = mesh.Vertices.Select(v => new FLVER.Vertex(v)).ToList();
            foreach (var v in verts) {
                int Resolve(int index) => mesh.BoneIndices.Count == 0 ? index : mesh.BoneIndices[index];
                if (mesh.UseBoneWeights) for (int k = 0; k < 4; k++) v.BoneIndices[k] = Resolve(v.BoneIndices[k]);
                else {
                    int bone = Resolve(v.NormalW);
                    v.Position = Vector3.Transform(v.Position, world[bone]);
                    if (!Matrix4x4.Invert(world[bone], out var inv)) throw new InvalidDataException("Singular rigid bone transform");
                    v.Normal = Vector3.Normalize(Vector3.TransformNormal(v.Normal, Matrix4x4.Transpose(inv)));
                    for (int t = 0; t < v.Tangents.Count; t++) { var a = v.Tangents[t]; var xyz = Vector3.Normalize(Vector3.TransformNormal(new Vector3(a.X, a.Y, a.Z), world[bone])); v.Tangents[t] = new Vector4(xyz, a.W); }
                    for (int k = 0; k < 4; k++) { v.BoneIndices[k] = bone; v.BoneWeights[k] = k == 0 ? 1 : 0; }
                    v.NormalW = 0;
                }
                if (v.Tangents.Count == 0 || v.UVs.Count == 0) throw new InvalidDataException("Mesh lacks tangent or UV0: " + prefix);
                for (int k = 0; k < 4; k++) if (v.BoneIndices[k] < 0 || v.BoneIndices[k] >= doc.Bones.Count) {
                    if (v.BoneWeights[k] != 0) throw new InvalidDataException("Invalid active bone index");
                    v.BoneIndices[k] = 0;
                }
            }
            s.Positions = prefix + ".pos.f32"; WriteArray(output, s.Positions, b => verts.ForEach(v => Vec(b, v.Position)));
            s.Normals = prefix + ".nrm.f32"; WriteArray(output, s.Normals, b => verts.ForEach(v => Vec(b, v.Normal)));
            s.Tangents = prefix + ".tan.f32"; WriteArray(output, s.Tangents, b => verts.ForEach(v => Vec(b, v.Tangents[0])));
            s.Uv0 = prefix + ".uv0.f32"; s.Uv1 = prefix + ".uv1.f32";
            for (int channel = 0; channel < 2; channel++) { int c = channel; WriteArray(output, c == 0 ? s.Uv0 : s.Uv1, b => verts.ForEach(v => { var uv = v.UVs[Math.Min(c, v.UVs.Count - 1)]; b.Write(uv.X); b.Write(uv.Y); })); }
            s.Colors = prefix + ".col.u8"; WriteArray(output, s.Colors, b => verts.ForEach(v => { var c = v.Colors.Count == 0 ? new FLVER.VertexColor(1f, 1f, 1f, 1f) : v.Colors[0]; b.Write(Color(c.R)); b.Write(Color(c.G)); b.Write(Color(c.B)); b.Write(Color(c.A)); }));
            s.BoneIndices = prefix + ".bi.u8"; WriteArray(output, s.BoneIndices, b => verts.ForEach(v => { for (int k = 0; k < 4; k++) b.Write(checked((byte)v.BoneIndices[k])); }));
            s.BoneWeights = prefix + ".bw.f32"; WriteArray(output, s.BoneWeights, b => verts.ForEach(v => { float sum = Enumerable.Range(0, 4).Sum(k => v.BoneWeights[k]); if (sum <= 0) throw new InvalidDataException("Zero-sum skin weights"); for (int k = 0; k < 4; k++) b.Write(v.BoneWeights[k] / sum); }));
            s.FlverBoneWeights = prefix + ".flver-bw.f32"; WriteArray(output, s.FlverBoneWeights, b => verts.ForEach(v => { for (int k = 0; k < 4; k++) b.Write(v.BoneWeights[k]); }));
            s.NormalW = prefix + ".nw.u8"; WriteArray(output, s.NormalW, b => verts.ForEach(v => b.Write(checked((byte)v.NormalW))));
            if (mesh.VertexBuffers.Count > 1) {
                if (!mesh.UseBoneWeights || !mesh.VertexBuffers.Select(v => v.LayoutIndex).SequenceEqual(new[] { 1, 5, 3 }) || verts.Any(v => v.Positions.Count != 2 || v.Normals.Count != 2 || v.Tangents.Count != 2)) throw new InvalidDataException("Unsupported multi-stream mesh; expected ER armor cloth layouts 1/5/3");
                var c = new Cloth { Positions = prefix + ".cloth-pos.f32", Normals = prefix + ".cloth-nrm.f32", Tangents = prefix + ".cloth-tan.f32", NormalW = prefix + ".cloth-nw.u8", Bitangents = prefix + ".bitan.f32" };
                WriteArray(output, c.Positions, b => verts.ForEach(v => Vec(b, v.Positions[1])));
                WriteArray(output, c.Normals, b => verts.ForEach(v => Vec(b, v.Normals[1])));
                WriteArray(output, c.Tangents, b => verts.ForEach(v => Vec(b, v.Tangents[1])));
                WriteArray(output, c.NormalW, b => verts.ForEach(v => b.Write(checked((byte)v.NormalWs[1]))));
                WriteArray(output, c.Bitangents, b => verts.ForEach(v => Vec(b, v.Bitangent))); s.FlverCloth = c;
            }
            var main = mesh.FaceSets.Find(f => f.Flags == FLVER2.FaceSet.FSFlags.None) ?? mesh.FaceSets.FirstOrDefault();
            var indices = main?.Triangulate(verts.Count < ushort.MaxValue) ?? new List<int>();
            s.Indices = prefix + ".idx.u32"; s.IndexCount = indices.Count; s.CullBackfaces = main?.CullBackfaces ?? true;
            WriteArray(output, s.Indices, b => indices.ForEach(i => b.Write(checked((uint)i))));
            s.FaceSets = new();
            foreach (var (face, fi) in mesh.FaceSets.Select((f, i) => (f, i))) {
                var tris = face.Triangulate(verts.Count < ushort.MaxValue);
                var fs = new Face { Flags = (uint)(face.Flags & ~FLVER2.FaceSet.FSFlags.EdgeCompressed), CullBackfaces = face.CullBackfaces, Unk06 = face.Unk06, Indices = $"{prefix}.face{fi:D2}.u32", IndexCount = tris.Count };
                WriteArray(output, fs.Indices, b => tris.ForEach(i => b.Write(checked((uint)i)))); s.FaceSets.Add(fs);
            }
            doc.Submeshes.Add(s);
        }
        SaveJson(Path.Combine(output, "mesh.json"), doc);
        Console.WriteLine($"Exported {doc.Submeshes.Count} meshes, {doc.Materials.Count} materials, {doc.Submeshes.Sum(s => s.VertexCount)} vertices to {output}");
    }
    static string Slug(string value) { string s = Regex.Replace(value, "[^A-Za-z0-9_]+", "_").Trim('_'); return s.Length == 0 ? "material" : s; }
    static string Suffix(string name) { var match = Regex.Match(name, @"^[A-Z]{2}_[MF]_\d{4}_(.+)$", RegexOptions.IgnoreCase); return match.Success ? match.Groups[1].Value : name; }
    static Matrix4x4[] World(FLVER2 f)
    {
        var transforms = new Matrix4x4[f.Nodes.Count]; var state = new byte[f.Nodes.Count];
        Matrix4x4 Calc(int i) {
            if (i < 0 || i >= f.Nodes.Count) throw new InvalidDataException("Invalid parent node index");
            if (state[i] == 1) throw new InvalidDataException("Cyclic node hierarchy");
            if (state[i] == 2) return transforms[i];
            state[i] = 1; var n = f.Nodes[i]; transforms[i] = n.ComputeLocalTransform() * (n.ParentIndex < 0 ? Matrix4x4.Identity : Calc(n.ParentIndex)); state[i] = 2; return transforms[i];
        }
        for (int i = 0; i < transforms.Length; i++) Calc(i); return transforms;
    }
    static float[] Floats(string dir, string file, int count)
    {
        var bytes = File.ReadAllBytes(Relative(dir, file)); if (bytes.Length != checked(count * 4)) throw new InvalidDataException($"Wrong array size: {file} (expected {count * 4}, got {bytes.Length})");
        var values = new float[count]; for (int i = 0; i < count; i++) { values[i] = System.Buffers.Binary.BinaryPrimitives.ReadSingleLittleEndian(bytes.AsSpan(i * 4, 4)); if (!float.IsFinite(values[i])) throw new InvalidDataException("Non-finite float: " + file); } return values;
    }
    static byte[] Bytes(string dir, string file, int count) { var bytes = File.ReadAllBytes(Relative(dir, file)); if (bytes.Length != count) throw new InvalidDataException("Wrong array size: " + file); return bytes; }
    static List<int> Indices(string dir, string file, int count, int vertices)
    {
        if (count < 0 || count % 3 != 0) throw new InvalidDataException("Index count must be a nonnegative multiple of 3");
        var bytes = Bytes(dir, file, checked(count * 4)); var indices = new List<int>(count);
        for (int i = 0; i < count; i++) { uint n = System.Buffers.Binary.BinaryPrimitives.ReadUInt32LittleEndian(bytes.AsSpan(i * 4, 4)); if (n >= vertices) throw new InvalidDataException("Index outside vertex array: " + file); indices.Add((int)n); } return indices;
    }
    static Vector3 V3(float[] values, int i) => new(values[i * 3], values[i * 3 + 1], values[i * 3 + 2]);
    static bool Enabled(FLVER.Node n) => (n.Flags & FLVER.Node.NodeFlags.Bone) != 0 && (n.Flags & FLVER.Node.NodeFlags.Disabled) == 0;
    static void Build(Dictionary<string, string> options, int model, string materialPath, string output, string texconv)
    {
        if (options.ContainsKey("--mesh") && options.ContainsKey("--bd-mesh")) throw new ArgumentException("Use either --mesh or --bd-mesh");
        var matbnd = Binder(materialPath);
        var templates = new Dictionary<string, BND4>();
        var oldModels = new Dictionary<string, int>();
        var payloads = new Dictionary<string, (byte[] Flver, byte[] Tpf)>();
        var audits = new List<object>(); var parts = new List<object>();
        int meshes = 0, materials = 0, vertices = 0;
        foreach (string piece in new[] { "hd", "bd", "am", "lg" }) {
            string path;
            if (options.TryGetValue($"--{piece}-template", out string? supplied)) path = supplied;
            else {
                if (!options.TryGetValue("--template-dir", out string? dir) || !options.TryGetValue("--template-model", out string? number)) throw new ArgumentException($"Specify --{piece}-template or --template-dir with --template-model");
                path = Part(dir, piece, Model(number), "");
            }
            var match = Regex.Match(Path.GetFileName(path), $@"^{piece}_m_(\d{{4}})\.partsbnd(\.dcx)?$", RegexOptions.IgnoreCase);
            if (!match.Success) throw new ArgumentException("Expected high-LOD template partsbnd name: " + path);
            int old = Model(match.Groups[1].Value); oldModels[piece] = old;
            if (old == model) throw new ArgumentException("New model number must differ from template");
            string low = path.Replace($"{piece}_m_{old:D4}.partsbnd", $"{piece}_m_{old:D4}_l.partsbnd", StringComparison.OrdinalIgnoreCase);
            templates[piece] = Binder(path); templates[piece + "_l"] = Binder(low);
            string? meshDir = options.GetValueOrDefault($"--{piece}-mesh") ?? (piece == "bd" ? options.GetValueOrDefault("--mesh") : null);
            if (meshDir is not null) {
                var built = BuildPart(templates[piece], old, meshDir, model, matbnd, output, texconv, piece);
                payloads[piece] = (built.Flver, built.Tpf); audits.AddRange(built.Audit);
                meshes += built.Meshes; materials += built.Materials; vertices += built.Vertices;
                parts.Add(new { piece, template = Path.GetFullPath(path), mesh_dir = Path.GetFullPath(meshDir), meshes = built.Meshes, materials = built.Materials, vertices = built.Vertices });
                // Low-LOD helpers are preserved, but the shared skin must address the same enabled table.
                var high = FLVER2.Read(built.Flver); var lf = FLVER2.Read(Entry(templates[piece + "_l"], ".flver").Bytes);
                if (!high.Nodes.Select(n => (n.Name, n.Flags)).SequenceEqual(lf.Nodes.Select(n => (n.Name, n.Flags)))) throw new InvalidDataException("High/low template node tables differ: " + piece);
            } else parts.Add(new { piece, template = Path.GetFullPath(path), mesh_dir = (string?)null, meshes = 0, materials = 0, vertices = 0 });
        }
        // All parts validate before any .dcx is written.
        Directory.CreateDirectory(Path.Combine(output, "parts")); Directory.CreateDirectory(Path.Combine(output, "material"));
        foreach (string piece in new[] { "hd", "bd", "am", "lg" }) foreach (string lod in new[] { "", "_l" }) {
            var bnd = templates[piece + lod];
            foreach (var file in bnd.Files) {
                if (file.Name.EndsWith(".flver", StringComparison.OrdinalIgnoreCase)) {
                    if (payloads.TryGetValue(piece, out var built)) file.Bytes = built.Flver;
                    else { var empty = FLVER2.Read(file.Bytes); empty.Meshes.Clear(); Bounds(empty); file.Bytes = empty.Write(); }
                } else if (file.Name.EndsWith(".tpf", StringComparison.OrdinalIgnoreCase) && payloads.TryGetValue(piece, out var built)) file.Bytes = built.Tpf;
                file.Name = file.Name.Replace($"_{oldModels[piece]:D4}", $"_{model:D4}", StringComparison.OrdinalIgnoreCase);
            }
            WriteKrak(bnd, Part(Path.Combine(output, "parts"), piece, model, lod));
        }
        WriteKrak(matbnd, Path.Combine(output, "material", "allmaterial.matbinbnd.dcx"));
        SaveJson(Path.Combine(output, "build-manifest.json"), new { format = "ertool-armor-build", model, material_source = Path.GetFullPath(materialPath), meshes, materials, vertices, parts, textures = audits });
        Console.WriteLine($"Built model {model:D4}: 8 partsbnd + allmaterial, {meshes} meshes, {materials} materials, {audits.Count} textures to {output}");
    }
    static (byte[] Flver, byte[] Tpf, List<object> Audit, int Meshes, int Materials, int Vertices) BuildPart(BND4 template, int templateModel, string meshDir, int model, BND4 matbnd, string output, string texconv, string piece)
    {
        var doc = JsonSerializer.Deserialize<MeshDocument>(File.ReadAllText(Path.Combine(meshDir, "mesh.json")), Json) ?? throw new InvalidDataException("Empty mesh.json");
        if (doc.Format != "fusemesh" || doc.Version != 1 || doc.Space != "flver_model") throw new InvalidDataException("Expected fusemesh v1, space flver_model");
        if (doc.Bones.Count is 0 or > 256 || doc.Bones.Distinct().Count() != doc.Bones.Count) throw new InvalidDataException("bones must have 1..256 unique names");
        if (doc.Materials.Count == 0 || doc.Submeshes.Count == 0) throw new InvalidDataException("Empty mesh/material list");
        if (doc.Materials.Any(m => !Regex.IsMatch(m.Name, "^[A-Za-z0-9_]+$")) || doc.Materials.Select(m => m.Name).Distinct(StringComparer.OrdinalIgnoreCase).Count() != doc.Materials.Count) throw new InvalidDataException("Material names must be unique ASCII letters/digits/underscores");
        var f = FLVER2.Read(Entry(template, ".flver").Bytes);
        var originals = f.Materials.ToList(); var protoMeshes = f.Meshes.ToList();
        if (f.Nodes.Count > 256) throw new InvalidDataException("Template node table exceeds UByte4 capacity");
        var nodes = f.Nodes.Select((n, i) => (n.Name, i)).ToDictionary(n => n.Name, n => n.i, StringComparer.Ordinal);
        var mapping = doc.Bones.Select(n => nodes.TryGetValue(n, out int i) ? i : throw new InvalidDataException("Bone missing from template: " + n)).ToArray();
        int layout = f.BufferLayouts.FindIndex(Layout4);
        if (layout < 0) throw new InvalidDataException("Template has no required 40-byte armor layout");
        var matfiles = MaterialFiles(matbnd);
        var tpf = TPF.Read(Entry(template, ".tpf").Bytes);
        var textureTemplates = TextureFiles(new[] { tpf });
        var builtTextures = new Dictionary<string, TPF.Texture>(StringComparer.OrdinalIgnoreCase);
        var textureSources = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        var textureAudit = new List<object>();
        f.Materials = new(); f.Meshes = new();
        int nextId = matbnd.Files.Max(m => m.ID) + 1;
        foreach (var m in doc.Materials) {
            string templateName = Stem(m.TemplateMatbin + (m.TemplateMatbin.EndsWith(".matbin", StringComparison.OrdinalIgnoreCase) ? "" : ".matbin"));
            if (!matfiles.TryGetValue(templateName, out var source)) throw new InvalidDataException("Missing template MATBIN: " + templateName);
            var mat = MATBIN.Read(source.Bytes); string newName = $"P[{piece.ToUpperInvariant()}_M_{model:D4}]_{m.Name}";
            if (matfiles.ContainsKey(newName)) throw new InvalidDataException("Target MATBIN already exists: " + newName);
            foreach (var (name, value) in m.FloatParams) {
                var parameter = mat.Params.SingleOrDefault(p => p.Name == name);
                if (parameter is null || parameter.Value is not float || !float.IsFinite(value)) throw new InvalidDataException("Expected existing finite Float MATBIN parameter: " + name);
                parameter.Value = value;
            }
            foreach (string type in m.SamplerTextures.Keys) if (!mat.Samplers.Any(s => s.Type == type)) throw new InvalidDataException("Unknown exact sampler Type: " + type);
            var used = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (var (sampler, samplerIndex) in mat.Samplers.Select((s, i) => (s, i))) {
                string old = Stem(sampler.Path);
                if (m.SamplerTextures.TryGetValue(sampler.Type, out string? explicitFile)) {
                    string role = sampler.Type.EndsWith("AlbedoMap") ? "a" : sampler.Type.EndsWith("NormalMap") ? "n" : sampler.Type.EndsWith("MetallicMap") ? "m" : throw new InvalidDataException("Only Albedo/Normal/Metallic sampler overrides are supported");
                    var encoding = textureTemplates.Values.FirstOrDefault(t => Suffix(t.Name).Equals(role, StringComparison.OrdinalIgnoreCase)) ?? throw new InvalidDataException("No local encoding template for sampler override: " + role);
                    string detailTarget = $"{piece.ToUpperInvariant()}_M_{model:D4}_{m.Name}_detail{samplerIndex}_{role}";
                    string input = Relative(meshDir, explicitFile);
                    byte[] dds = ConvertTexture(input, encoding, texconv, output);
                    builtTextures.Add(detailTarget, new TPF.Texture(detailTarget, encoding.Format, encoding.Flags1, dds, TPF.TPFPlatform.PC));
                    textureAudit.Add(new { name = detailTarget, template = sampler.Path, source = input, dds = DdsInfo(dds), tpf_format = encoding.Format });
                    sampler.Path = sampler.Path.Length == 0 ? detailTarget + ".tif" : sampler.Path.Replace(old, detailTarget, StringComparison.OrdinalIgnoreCase);
                    continue;
                }
                if (!textureTemplates.TryGetValue(old, out var texture)) {
                    if (old.StartsWith($"{piece.ToUpperInvariant()}_M_{templateModel:D4}_", StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("Missing local template texture: " + old);
                    continue; // Shared AAT/detail assets retain their original paths and parameters.
                }
                string suffix = Suffix(old); used.Add(suffix);
                string? supplied = m.Textures.GetValueOrDefault(suffix);
                string sourceKey = supplied is null ? "template:" + old : Relative(meshDir, supplied);
                string target = $"{piece.ToUpperInvariant()}_M_{model:D4}_{suffix}";
                if (textureSources.TryGetValue(target, out string? prior) && prior != sourceKey) target = $"{piece.ToUpperInvariant()}_M_{model:D4}_{m.Name}_{suffix}";
                if (textureSources.TryGetValue(target, out prior) && prior != sourceKey) throw new InvalidDataException("Texture name collision: " + target);
                if (!builtTextures.ContainsKey(target)) {
                    byte[] dds = supplied is null ? texture.Bytes : ConvertTexture(sourceKey, texture, texconv, output);
                    var converted = new TPF.Texture(target, texture.Format, texture.Flags1, dds, TPF.TPFPlatform.PC);
                    builtTextures[target] = converted; textureSources[target] = sourceKey;
                    textureAudit.Add(new { name = target, template = old, source = sourceKey, dds = DdsInfo(dds), tpf_format = texture.Format });
                }
                sampler.Path = sampler.Path.Replace(old, target, StringComparison.OrdinalIgnoreCase);
            }
            // export without MATBIN supplies the whole TPF set; accept those extra known suffixes.
            foreach (string key in m.Textures.Keys) if (!used.Contains(key) && !textureTemplates.Values.Any(t => Suffix(t.Name).Equals(key, StringComparison.OrdinalIgnoreCase))) throw new InvalidDataException("Unknown texture suffix for material: " + key);
            mat.SourcePath = mat.SourcePath.Replace(templateName, newName, StringComparison.OrdinalIgnoreCase);
            matbnd.Files.Add(new BinderFile(source.Flags, nextId++, source.Name.Replace(templateName, newName, StringComparison.OrdinalIgnoreCase), mat.Write()) { CompressionInfo = source.CompressionInfo });
            var proto = originals.FirstOrDefault(p => Stem(p.MTD).Equals(templateName, StringComparison.OrdinalIgnoreCase)) ?? throw new InvalidDataException("MATBIN not represented in part template FLVER: " + templateName);
            f.Materials.Add(new FLVER2.Material { Name = m.FlverName ?? m.Name, MTD = proto.MTD.Replace(templateName, newName, StringComparison.OrdinalIgnoreCase), GXIndex = proto.GXIndex, Index = proto.Index, Textures = proto.Textures.Select(t => new FLVER2.Texture(t.ParamName, t.Path, t.TilingScale, t.TilingTypeU, t.TilingTypeV, t.Unk14, t.Unk18, t.Unk1C)).ToList() });
        }
        foreach (var s in doc.Submeshes) {
            if (s.Material < 0 || s.Material >= doc.Materials.Count || s.VertexCount <= 0) throw new InvalidDataException("Invalid submesh material/vertex count");
            int n = s.VertexCount;
            var pos = Floats(meshDir, s.Positions, checked(n * 3)); var nrm = Floats(meshDir, s.Normals, checked(n * 3)); var tan = Floats(meshDir, s.Tangents, checked(n * 4));
            var uv0 = Floats(meshDir, s.Uv0, checked(n * 2)); var uv1 = Floats(meshDir, s.Uv1, checked(n * 2)); var bw = Floats(meshDir, s.BoneWeights, checked(n * 4)); var bi = Bytes(meshDir, s.BoneIndices, checked(n * 4));
            var rawWeights = s.FlverBoneWeights is null ? null : Floats(meshDir, s.FlverBoneWeights, checked(n * 4));
            var colors = s.Colors is null ? Enumerable.Repeat((byte)255, checked(n * 4)).ToArray() : Bytes(meshDir, s.Colors, checked(n * 4));
            var normalW = s.NormalW is null ? new byte[n] : Bytes(meshDir, s.NormalW, n);
            float[]? clothPos = null, clothNrm = null, clothTan = null, bitan = null; byte[]? clothW = null;
            if (s.FlverCloth is not null) {
                if (!protoMeshes.Any(m => m.VertexBuffers.Select(v => v.LayoutIndex).SequenceEqual(new[] { 1, 5, 3 }))) throw new InvalidDataException("Template has no compatible cloth streams");
                clothPos = Floats(meshDir, s.FlverCloth.Positions, checked(n * 3)); clothNrm = Floats(meshDir, s.FlverCloth.Normals, checked(n * 3)); clothTan = Floats(meshDir, s.FlverCloth.Tangents, checked(n * 4)); bitan = Floats(meshDir, s.FlverCloth.Bitangents, checked(n * 4)); clothW = Bytes(meshDir, s.FlverCloth.NormalW, n);
                if (clothNrm.Concat(clothTan).Concat(bitan).Any(x => x < -1 || x > 128f / 127f)) throw new InvalidDataException("Cloth direction exceeds biased-u8 range");
            } else if (doc.Materials[s.Material].TemplateMatbin.Contains("_Cloth", StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("Cloth MATBIN requires flver_cloth streams; use the non-cloth template for a new ordinary skinned mesh");
            if (nrm.Concat(tan).Any(x => x < -1 || x > 128f / 127f)) throw new InvalidDataException("Normal/tangent exceeds biased-u8 range");
            if (uv0.Concat(uv1).Any(x => x * 2048 < short.MinValue || x * 2048 > short.MaxValue)) throw new InvalidDataException("UV exceeds Short4 range");
            var mesh = new FLVER2.Mesh { UseBoneWeights = true, MaterialIndex = s.Material, NodeIndex = s.NodeName is null ? protoMeshes[0].NodeIndex : nodes.GetValueOrDefault(s.NodeName, -1), VertexBuffers = new() { new FLVER2.VertexBuffer(layout) } };
            if (s.FlverCloth is not null) mesh.VertexBuffers = new() { new FLVER2.VertexBuffer(1), new FLVER2.VertexBuffer(5), new FLVER2.VertexBuffer(3) };
            if (s.NodeName is not null && mesh.NodeIndex < 0) throw new InvalidDataException("Mesh node missing from template: " + s.NodeName);
            for (int i = 0; i < n; i++) {
                var v = new FLVER.Vertex(); v.Positions.Add(V3(pos, i)); v.Normals.Add(V3(nrm, i)); v.NormalWs.Add(normalW[i]);
                v.Tangents.Add(new Vector4(tan[i * 4], tan[i * 4 + 1], tan[i * 4 + 2], tan[i * 4 + 3]));
                if (clothPos is not null) { v.Positions.Add(V3(clothPos, i)); v.Normals.Add(V3(clothNrm!, i)); v.NormalWs.Add(clothW![i]); v.Tangents.Add(new Vector4(clothTan![i * 4], clothTan[i * 4 + 1], clothTan[i * 4 + 2], clothTan[i * 4 + 3])); v.Bitangent = new Vector4(bitan![i * 4], bitan[i * 4 + 1], bitan[i * 4 + 2], bitan[i * 4 + 3]); }
                v.UVs.Add(new Vector3(uv0[i * 2], uv0[i * 2 + 1], 0)); v.UVs.Add(new Vector3(uv1[i * 2], uv1[i * 2 + 1], 0));
                v.Colors.Add(new FLVER.VertexColor(colors[i * 4 + 3], colors[i * 4], colors[i * 4 + 1], colors[i * 4 + 2]));
                float sum = 0;
                for (int k = 0; k < 4; k++) {
                    int index = bi[i * 4 + k]; float weight = bw[i * 4 + k];
                    if (index >= mapping.Length) throw new InvalidDataException("Bone index outside bones table");
                    if (weight < 0 || weight > 1) throw new InvalidDataException("Weight must be 0..1");
                    if (weight > 0 && !Enabled(f.Nodes[mapping[index]])) throw new InvalidDataException($"Bone is not enabled (Bone and non-Disabled) in {piece} template: {doc.Bones[index]}");
                    v.BoneIndices[k] = mapping[index]; v.BoneWeights[k] = weight; sum += weight;
                }
                if (Math.Abs(sum - 1) > 0.0001f) throw new InvalidDataException($"Weights do not sum to 1 at {s.Name} vertex {i}: {sum}");
                if (rawWeights is null) QuantizeWeights(v, sum);
                else {
                    // Original ER byte weights sum to 252..255 in this armor. Keep them
                    // only when the optional original data agrees with normalized v1.
                    float rawSum = Enumerable.Range(0, 4).Sum(k => rawWeights[i * 4 + k]);
                    if (Math.Abs(rawSum - 1) > 4f / 255 + 0.00001f) throw new InvalidDataException("Invalid original FLVER weights");
                    for (int k = 0; k < 4; k++) {
                        float raw = rawWeights[i * 4 + k];
                        if (raw < 0 || raw > 1 || Math.Abs(raw * 255 - Math.Round(raw * 255)) > 0.0001 || Math.Abs(raw / rawSum - bw[i * 4 + k]) > 0.00001) throw new InvalidDataException("Original FLVER weights disagree with v1 weights; remove flver_bone_weights after editing skin weights");
                        v.BoneWeights[k] = raw;
                    }
                }
                mesh.Vertices.Add(v);
            }
            var main = Indices(meshDir, s.Indices, s.IndexCount, n);
            if (s.FaceSets is { Count: > 0 }) {
                foreach (var face in s.FaceSets) {
                    const uint validFlags = 0x87000000;
                    if ((face.Flags & ~validFlags) != 0) throw new InvalidDataException("Unsupported face flags");
                    var indices = Indices(meshDir, face.Indices, face.IndexCount, n);
                    mesh.FaceSets.Add(new FLVER2.FaceSet((FLVER2.FaceSet.FSFlags)face.Flags, false, face.CullBackfaces, face.Unk06, indices));
                }
                var baseFace = mesh.FaceSets.Find(face => face.Flags == FLVER2.FaceSet.FSFlags.None) ?? mesh.FaceSets[0];
                if (!baseFace.Indices.SequenceEqual(main)) throw new InvalidDataException("Primary indices disagree with face_sets");
            } else {
                foreach (var flags in new[] { FLVER2.FaceSet.FSFlags.None, FLVER2.FaceSet.FSFlags.LodLevel1, FLVER2.FaceSet.FSFlags.LodLevel2, FLVER2.FaceSet.FSFlags.MotionBlur, FLVER2.FaceSet.FSFlags.LodLevel1 | FLVER2.FaceSet.FSFlags.MotionBlur, FLVER2.FaceSet.FSFlags.LodLevel2 | FLVER2.FaceSet.FSFlags.MotionBlur }) mesh.FaceSets.Add(new FLVER2.FaceSet(flags, false, s.CullBackfaces, 0, new List<int>(main)));
            }
            f.Meshes.Add(mesh);
        }
        Bounds(f);
        byte[] bytes = f.Write(); var reread = FLVER2.Read(bytes);
        if (reread.Meshes.Count != doc.Submeshes.Count || reread.Materials.Count != doc.Materials.Count) throw new InvalidDataException("FLVER serialization check failed");
        tpf.Textures = builtTextures.Values.ToList(); byte[] textureBytes = tpf.Write(); TPF.Read(textureBytes);
        return (bytes, textureBytes, textureAudit, f.Meshes.Count, f.Materials.Count, f.Meshes.Sum(m => m.Vertices.Count));
    }
    static bool Layout4(FLVER2.BufferLayout l)
    {
        var expected = new[] { (FLVER.LayoutSemantic.Position, FLVER.LayoutType.Float3), (FLVER.LayoutSemantic.Normal, FLVER.LayoutType.UByte4), (FLVER.LayoutSemantic.Tangent, FLVER.LayoutType.UByte4), (FLVER.LayoutSemantic.BoneIndices, FLVER.LayoutType.UByte4), (FLVER.LayoutSemantic.BoneWeights, FLVER.LayoutType.UByte4Norm), (FLVER.LayoutSemantic.VertexColor, FLVER.LayoutType.UByte4Norm), (FLVER.LayoutSemantic.UV, FLVER.LayoutType.Short4) };
        return l.Size == 40 && l.Count == expected.Length && l.Select(x => (x.Semantic, x.Type)).SequenceEqual(expected) && l[5].Index == 1;
    }
    static void QuantizeWeights(FLVER.Vertex v, float sum)
    {
        var scaled = Enumerable.Range(0, 4).Select(k => v.BoneWeights[k] / sum * 255).ToArray();
        var ints = scaled.Select(x => (int)Math.Floor(x)).ToArray();
        foreach (int k in Enumerable.Range(0, 4).OrderByDescending(k => scaled[k] - ints[k]).Take(255 - ints.Sum())) ints[k]++;
        for (int k = 0; k < 4; k++) v.BoneWeights[k] = ints[k] / 255f;
    }
    static void Bounds(FLVER2 f)
    {
        var world = World(f); var inverse = new Matrix4x4[world.Length];
        for (int i = 0; i < world.Length; i++) if (!Matrix4x4.Invert(world[i], out inverse[i])) throw new InvalidDataException("Singular template node: " + f.Nodes[i].Name);
        var min = Enumerable.Repeat(new Vector3(float.PositiveInfinity), world.Length).ToArray(); var max = Enumerable.Repeat(new Vector3(float.NegativeInfinity), world.Length).ToArray();
        Vector3 globalMin = new(float.PositiveInfinity), globalMax = new(float.NegativeInfinity);
        void Include(int i, Vector3 position) { if (i < 0 || i >= world.Length) return; var p = Vector3.Transform(position, inverse[i]); min[i] = Vector3.Min(min[i], p); max[i] = Vector3.Max(max[i], p); }
        foreach (var mesh in f.Meshes) {
            Vector3 lo = new(float.PositiveInfinity), hi = new(float.NegativeInfinity);
            foreach (var v in mesh.Vertices) foreach (var position in v.Positions) {
                lo = Vector3.Min(lo, position); hi = Vector3.Max(hi, position); Include(mesh.NodeIndex, position);
                for (int k = 0; k < 4; k++) if (v.BoneWeights[k] > 0) Include(v.BoneIndices[k], position);
            }
            // ER's 0x2001A 9-float mesh bounds are extent/rotation/center,
            // despite the upstream Min/Max/Unk names. Use an axis-aligned OBB.
            // The original data has positive extents and rotations where Min > Max;
            // writing AABB min/max here can create negative extents and bad culling.
            mesh.BoundingBox = f.Header.Version >= 0x2001A
                ? new FLVER2.Mesh.BoundingBoxes { Min = (hi - lo) * 0.5f, Max = Vector3.Zero, Unk = (hi + lo) * 0.5f }
                : new FLVER2.Mesh.BoundingBoxes { Min = lo, Max = hi };
            globalMin = Vector3.Min(globalMin, lo); globalMax = Vector3.Max(globalMax, hi);
        }
        f.Header.BoundingBoxMin = f.Meshes.Count == 0 ? Vector3.Zero : globalMin;
        f.Header.BoundingBoxMax = f.Meshes.Count == 0 ? Vector3.Zero : globalMax;
        for (int i = 0; i < f.Nodes.Count; i++) { f.Nodes[i].BoundingBoxMin = float.IsPositiveInfinity(min[i].X) ? Vector3.Zero : min[i]; f.Nodes[i].BoundingBoxMax = float.IsNegativeInfinity(max[i].X) ? Vector3.Zero : max[i]; }
    }
    static void WriteKrak(BND4 bnd, string path)
    {
        byte[] raw = bnd.Write(new DCX.NoCompressionInfo()); var written = DCX.Compress(raw, new DCX.DcxKrakCompressionInfo(DCX.KrakCompressionPreset.EldenRing));
        var reread = BND4.Read(DCX.Decompress(written));
        if (reread.Files.Count != bnd.Files.Count) throw new InvalidDataException("BND serialization check failed");
        for (int i = 0; i < bnd.Files.Count; i++) {
            var a = bnd.Files[i]; var b = reread.Files[i];
            if (a.ID != b.ID || a.Name != b.Name || a.Flags != b.Flags || !a.Bytes.SequenceEqual(b.Bytes)) throw new InvalidDataException("BND entry changed during serialization: " + a.Name);
        }
        File.WriteAllBytes(path, written);
    }
    static object DdsInfo(byte[] bytes) { var d = new DDS(bytes); return new { width = d.dwWidth, height = d.dwHeight, mipmaps = d.dwMipMapCount, four_cc = d.ddspf.dwFourCC, dxgi = d.GetDXGIFormat().ToString(), srgb = d.GetDXGIFormat().ToString().EndsWith("_SRGB") }; }
    static byte[] ConvertTexture(string input, TPF.Texture template, string texconv, string output)
    {
        string ext = Path.GetExtension(input).ToLowerInvariant(); if (ext is not ".dds" and not ".png") throw new InvalidDataException("Texture must be PNG or DDS: " + input);
        var expected = new DDS(template.Bytes).GetDXGIFormat();
        if (ext == ".dds") { var raw = File.ReadAllBytes(input); var dds = new DDS(raw); if (dds.GetDXGIFormat() == expected && dds.dwMipMapCount > 0) return raw; }
        if (!File.Exists(texconv)) throw new FileNotFoundException("Texture conversion requires texconv", texconv);
        string temp = Path.Combine(output, ".ertool-textures", Guid.NewGuid().ToString("N")); Directory.CreateDirectory(temp);
        var psi = new ProcessStartInfo(texconv) { UseShellExecute = false, RedirectStandardOutput = true, RedirectStandardError = true, CreateNoWindow = true };
        // BC4 PNG inputs otherwise produce legacy BC4U, which this pinned DDS
        // reader does not recognize. DX10 also states sRGB unambiguously.
        foreach (string arg in new[] { "-nologo", "-y", "-dx10", "-f", expected.ToString(), "-m", "0", "-o", temp, input }) psi.ArgumentList.Add(arg);
        // WIC reports ordinary color PNGs as UNORM. Without this, texconv treats
        // their stored sRGB bytes as linear and gamma-encodes them a second time.
        if (ext == ".png" && expected.ToString().EndsWith("_SRGB")) psi.ArgumentList.Add("-srgb");
        using var process = Process.Start(psi) ?? throw new InvalidOperationException("Could not start texconv");
        var stdout = process.StandardOutput.ReadToEndAsync(); var stderr = process.StandardError.ReadToEndAsync(); process.WaitForExit();
        string log = stdout.GetAwaiter().GetResult() + stderr.GetAwaiter().GetResult(); File.WriteAllText(Path.Combine(temp, "texconv.log"), log);
        if (process.ExitCode != 0) throw new InvalidDataException("texconv failed: " + log);
        var result = File.ReadAllBytes(Directory.GetFiles(temp, "*.dds").Single());
        if (new DDS(result).GetDXGIFormat() != expected) throw new InvalidDataException("texconv format mismatch"); return result;
    }
    static void Evidence(string templateDir, int[] models, string materialPath, string output)
    {
        Directory.CreateDirectory(output); var matfiles = MaterialFiles(Binder(materialPath)); var materials = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase); var textures = new List<object>(); var parts = new List<object>();
        foreach (int model in models) foreach (string piece in new[] { "hd", "bd", "am", "lg" }) {
            string path = Part(templateDir, piece, model, ""); var bnd = Binder(path); var f = FLVER2.Read(Entry(bnd, ".flver").Bytes);
            parts.Add(new { source = path, model, piece, materials = f.Materials.Select(m => new { m.Name, m.MTD }).ToArray() });
            foreach (string name in f.Materials.Select(m => Stem(m.MTD)).Distinct(StringComparer.OrdinalIgnoreCase)) {
                if (materials.ContainsKey(name)) continue;
                if (!matfiles.TryGetValue(name, out var entry)) throw new InvalidDataException("Missing material: " + name);
                var mat = MATBIN.Read(entry.Bytes); materials[name] = new { binder = materialPath, entry = entry.Name, data = mat };
            }
            foreach (var entry in bnd.Files.Where(e => e.Name.EndsWith(".tpf", StringComparison.OrdinalIgnoreCase))) foreach (var t in TPF.Read(entry.Bytes).Textures) textures.Add(new { source = path, entry = entry.Name, t.Name, t.Format, t.Flags1, t.Type, t.Mipmaps, dds = DdsInfo(t.Bytes) });
        }
        SaveJson(Path.Combine(output, "matbins.json"), materials); SaveJson(Path.Combine(output, "textures.json"), textures); SaveJson(Path.Combine(output, "parts.json"), parts);
        Console.WriteLine($"Dumped {parts.Count} parts, {materials.Count} unique MATBINs, {textures.Count} textures to {output}");
    }
}
