using System.Numerics;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using SoulsFormats;
using SoulsFormats.Cryptography;
using HKLib.hk2018;
using HKLib.Serialization.hk2018.Binary;

internal static class Program
{
    static readonly JsonSerializerOptions JsonOptions = new() {
        WriteIndented = true, IncludeFields = true, NumberHandling = JsonNumberHandling.AllowNamedFloatingPointLiterals,
        Converters = { new JsonStringEnumConverter(), new ShapeConverter() }, Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping
    };
    static string GameDir = Environment.GetEnvironmentVariable("ELDEN_RING_DIR") is { Length: > 0 } erDir ? erDir : @"E:\SteamLibrary\steamapps\common\ELDEN RING\Game";
    static string Paramdex = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../../../../../third_party/Paramdex"));
    static int Main(string[] args)
    {
        try {
            Console.OutputEncoding = new UTF8Encoding(false);
            if (args.Contains("--help")) args = new[] { "help" };
            if (args.Length > 0 && args[0] is "export-mesh" or "build-armor" or "armor-evidence" or "unpack-bnd") {
                Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);
                return ArmorBuilder.Run(args);
            }
            var positional = new List<string>(); string? output = null, compendium = null; int samples = 3;
            for (int i = 0; i < args.Length; i++) {
                switch(args[i]) {
                    case "--json": break;
                    case "--game-dir": GameDir = args[++i]; break;
                    case "--paramdex": Paramdex = args[++i]; break;
                    case "--out": output = args[++i]; break;
                    case "--compendium": compendium = args[++i]; break;
                    case "--samples": samples = int.Parse(args[++i]); if (samples < 0 || samples > 100) throw new ArgumentException("samples must be 0..100"); break;
                    default: if (args[i].StartsWith("--")) throw new ArgumentException("Unknown option: "+args[i]); positional.Add(args[i]); break;
                }
            }
            if (positional.Count == 0 || positional[0] is "help" or "-h") {
                Console.WriteLine("ertool <flver|hkx-skeleton|msb|emevd|param|fmg|matbin|tpf|bnd|dcx> <file> [param-name] --json [--out file] [--game-dir dir] [--paramdex dir] [--compendium file] [--samples 0..100]\nertool export-mesh <flver|partsbnd.dcx> --out <directory> [--matbin-bnd file] [--tpf file]\nertool build-armor --template-dir <parts directory> --template-model 1280 --mesh <fusemesh directory> --model 999 --matbin-bnd <file> --out <package directory> [--texconv file] [--hd-mesh dir --hd-template file] [--bd-mesh dir --bd-template file] [--am-mesh dir --am-template file] [--lg-mesh dir --lg-template file]\nertool armor-evidence --template-dir <parts directory> --models 1280,1010,1500,1600 --matbin-bnd <file> --out <directory>"); return 0;
            }
            if (positional.Count < 2) throw new ArgumentException("Input file required");
            Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);
            var dll = Path.Combine(GameDir, "oo2core_6_win64.dll");
            if (File.Exists(dll)) Oodle.Oodle6Ptr = System.Runtime.InteropServices.NativeLibrary.Load(dll);
            string command=positional[0], file=positional[1];
            var bytes = command == "param" ? Array.Empty<byte>() : Input(file);
            object result = command switch {
                "flver" => DumpFlver(file, bytes, samples),
                "hkx-skeleton" => DumpSkeleton(file, bytes, compendium),
                "msb" => DumpMsb(file, bytes),
                "emevd" => DumpEmevd(file, bytes),
                "param" => positional.Count == 3 ? DumpParam(file, positional[2]) : throw new ArgumentException("param requires table name"),
                "fmg" => DumpFmg(file, bytes),
                "matbin" => new { Source = file, Format = "MATBIN", Data = MATBIN.Read(bytes) },
                "tpf" => DumpTpf(file, bytes),
                "bnd" => new { Source = file, Files = BND4.Read(bytes).Files.Select(f=>new { f.ID, f.Name, f.Flags, Size=f.Bytes.Length }) },
                "dcx" => new { Source = file, DecompressedSize = bytes.Length, Magic = Convert.ToHexString(bytes.Take(16).ToArray()) },
                _ => throw new ArgumentException("Unknown command: "+command)
            };
            string json = JsonSerializer.Serialize(result, JsonOptions);
            if (output is null) Console.WriteLine(json);
            else { Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output))!); File.WriteAllText(output, json+"\n", new UTF8Encoding(false)); }
            return 0;
        } catch (Exception ex) { Console.Error.WriteLine("ertool: "+ex.Message); if (Environment.GetEnvironmentVariable("ERTOOL_DEBUG") == "1") Console.Error.WriteLine(ex); return 1; }
    }
    static byte[] Input(string file) => Decompress(File.ReadAllBytes(file));
    static byte[] Decompress(byte[] bytes) => DCX.Is(bytes) ? DCX.Decompress(bytes) : bytes;
    static int InternalInt(object obj, string name) => (int)obj.GetType().GetField(name, BindingFlags.NonPublic|BindingFlags.Instance)!.GetValue(obj)!;
    static float[] V3(Vector3 v) => new[] {v.X,v.Y,v.Z};
    static float[] V4(Vector4 v) => new[] {v.X,v.Y,v.Z,v.W};
    static float[] Q(Quaternion v) => new[] {v.X,v.Y,v.Z,v.W};
    static object DumpFlver(string file, byte[] bytes, int samples)
    {
        var f = FLVER2.Read(bytes);
        int dataOffset = f.Header.BigEndian ? System.Buffers.Binary.BinaryPrimitives.ReadInt32BigEndian(bytes.AsSpan(12,4)) : BitConverter.ToInt32(bytes,12);
        return new {
            Source=file, Format="FLVER2", f.Header, NodeCount=f.Nodes.Count, f.Skeletons, DummyCount=f.Dummies.Count, f.GXLists,
            Nodes=f.Nodes.Select((n,i)=>new {Index=i,n.Name,n.ParentIndex,n.FirstChildIndex,n.NextSiblingIndex,n.PreviousSiblingIndex,Translation=V3(n.Translation),RotationEulerXZY=V3(n.Rotation),RotationQuaternion=Q(Quaternion.CreateFromRotationMatrix(Matrix4x4.CreateRotationX(n.Rotation.X)*Matrix4x4.CreateRotationZ(n.Rotation.Z)*Matrix4x4.CreateRotationY(n.Rotation.Y))),Scale=V3(n.Scale),BoundingBoxMin=V3(n.BoundingBoxMin),BoundingBoxMax=V3(n.BoundingBoxMax),n.Flags}),
            Materials=f.Materials.Select((m,i)=>new { Index=i,m.Name,m.MTD,m.Textures }),
            BufferLayouts=f.BufferLayouts.Select((l,i)=>new {Index=i,Stride=l.Size,Members=Members(l)}),
            Meshes=f.Meshes.Select((m,i)=>new {
                Index=i,m.MaterialIndex,m.NodeIndex,m.Dynamic,m.UseBoneWeights,m.BoundingBox,VertexCount=m.Vertices.Count,
                PaletteSize=m.BoneIndices.Count,m.BoneIndices,
                PaletteNames=m.BoneIndices.Select(n=> n >= 0 && n < f.Nodes.Count ? f.Nodes[n].Name : null),
                BoneIndexRange=IndexRange(m),
                FaceSets=m.FaceSets.Select(s=>new {s.Flags,s.TriangleStrip,s.CullBackfaces,s.Unk06,IndexCount=s.Indices.Count}),
                VertexBuffers=m.VertexBuffers.Select(b=>new { b.BufferIndex,b.LayoutIndex,b.EdgeCompressed,Stride=InternalInt(b,"VertexSize"),VertexCount=InternalInt(b,"VertexCount"),AbsoluteOffset=dataOffset+InternalInt(b,"BufferOffset"),Members=Members(f.BufferLayouts[b.LayoutIndex]),
                    RawSamples=Enumerable.Range(0,Math.Min(samples,m.Vertices.Count)).Select(v=>new {Vertex=v,BytesHex=Convert.ToHexString(bytes.AsSpan(dataOffset+InternalInt(b,"BufferOffset")+v*InternalInt(b,"VertexSize"),InternalInt(b,"VertexSize")))}) }),
                VertexSamples=m.Vertices.Take(samples).Select((v,j)=>new {Index=j,Position=V3(v.Position),Positions=v.Positions.Select(V3),Normal=V3(v.Normal),Normals=v.Normals.Select(V3),v.NormalW,v.NormalWs,Tangents=v.Tangents.Select(V4),Bitangent=V4(v.Bitangent),UVs=v.UVs.Select(V3),BoneIndices=Enumerable.Range(0,4).Select(k=>v.BoneIndices[k]),BoneWeights=Enumerable.Range(0,4).Select(k=>v.BoneWeights[k]),v.Colors})
            })
        };
    }
    static object IndexRange(FLVER2.Mesh m) {
        var all=(m.UseBoneWeights ? m.Vertices.SelectMany(v=>Enumerable.Range(0,4).Where(k=>v.BoneWeights[k]>0).Select(k=>v.BoneIndices[k])) : m.Vertices.Select(v=>v.NormalW)).Distinct().Order().ToArray();
        return new { ActiveIndices=all, Min=all.Length>0?all[0]:-1,Max=all.Length>0?all[^1]:-1, AllFitPalette=all.All(i=>i>=0&&i<m.BoneIndices.Count), IndexStorage=m.UseBoneWeights ? "BoneIndices" : "NormalW" };
    }
    static object[] Members(FLVER2.BufferLayout layout) {
        int offset=0; return layout.Select(m=> {var result=new {Offset=offset,m.Size,Semantic=m.Semantic.ToString(),Type=m.Type.ToString(),TypeCode=(int)m.Type,m.Index,m.Stream,m.SpecialModifier};offset+=m.Size;return (object)result;}).ToArray();
    }
    static object DumpSkeleton(string file, byte[] bytes, string? compendium) {
        var serializer=new HavokBinarySerializer();
        if (compendium is not null) serializer.LoadCompendium(new MemoryStream(Input(compendium)));
        var skeletons=serializer.ReadAllObjects(new MemoryStream(bytes)).OfType<hkaSkeleton>().ToArray();
        if (skeletons.Length==0) throw new InvalidDataException("No hkaSkeleton in tagfile");
        var s=skeletons[0];
        if(s.m_bones.Count!=s.m_parentIndices.Count || s.m_bones.Count!=s.m_referencePose.Count) throw new InvalidDataException("Skeleton array lengths differ");
        return new {Source=file,Format="hkaSkeleton",Name=s.m_name,SkeletonCount=skeletons.Length,BoneCount=s.m_bones.Count,
            Bones=s.m_bones.Select((b,i)=>new {Index=i,Name=b.m_name,ParentIndex=s.m_parentIndices[i],Translation=V4(s.m_referencePose[i].m_translation),Rotation=Q(s.m_referencePose[i].m_rotation),Scale=V4(s.m_referencePose[i].m_scale),b.m_lockTranslation})};
    }
    static object DumpMsb(string file, byte[] bytes) {
        var m=MSBE.Read(bytes);
        return new {Source=file,Format="MSBE",Models=m.Models.GetEntries().Select(e=>new {Type=e.GetType().Name,Data=(object)e}),Parts=m.Parts.GetEntries().Select(e=>new {Type=e.GetType().Name,Data=(object)e}),Regions=m.Regions.GetEntries().Select(e=>new {Type=e.GetType().Name,Data=(object)e}),Events=m.Events.GetEntries().Select(e=>new {Type=e.GetType().Name,Data=(object)e})};
    }
    static object DumpEmevd(string file, byte[] bytes) {
        var e=EMEVD.Read(bytes);
        return new {Source=file,Format="EMEVD",e.StringData,Events=e.Events.Select(ev=>new {ev.ID,ev.RestBehavior,ev.Parameters,Instructions=ev.Instructions.Select((i,j)=>new {Index=j,i.Bank,i.ID,ArgDataHex=Convert.ToHexString(i.ArgData),ArgDataBytes=i.ArgData.Select(b=>(int)b),i.Layer})})};
    }
    static string Basename(string name) => name.Replace('\\','/').Split('/').Last();
    static object DumpParam(string file, string name) {
        var binder=RegulationDecryptor.DecryptERRegulation(file);
        var entry=binder.Files.Single(f=>string.Equals(Basename(f.Name),name+".param",StringComparison.OrdinalIgnoreCase));
        var p=PARAM.Read(entry.Bytes);
        ulong version=ulong.Parse(binder.Version);
        // Binder table names are not always definition filenames (SpEffectParam -> SpEffect).
        // Match the actual param type, version and detected row size; never relax layout checks.
        var defsDir=Path.Combine(Paramdex,"ER","Defs");
        var preferred=Path.Combine(defsDir,name+".xml");
        var candidates=Directory.EnumerateFiles(defsDir,"*.xml")
            .OrderBy(path=>string.Equals(path,preferred,StringComparison.OrdinalIgnoreCase)?0:1)
            .ThenBy(path=>path,StringComparer.Ordinal);
        string? defPath=null;
        foreach(var candidate in candidates) {
            var header=System.Xml.Linq.XDocument.Load(candidate).Root;
            if(header?.Element("ParamType")?.Value != p.ParamType) continue;
            var def=PARAMDEF.XmlDeserialize(candidate,versionAware:true);
            // Pinned SpEffect.xml names bits 0..4 at 0x353, but leaves 5..7 implicit.
            // Row 835 has nonzero data there. Preserve it as opaque bits rather than
            // disabling the reader's orphan-bit check or assigning guessed semantics.
            int unknown=def.Fields.FindIndex(f=>f.InternalName=="unk353_4" && f.BitSize==1);
            if(def.ParamType=="SP_EFFECT_PARAM_ST" && unknown>=0
               && unknown+1<def.Fields.Count && def.Fields[unknown+1].InternalName=="pad2") {
                def.Fields.Insert(unknown+1,new PARAMDEF.Field(def,PARAMDEF.DefType.u8,"raw353_bits5_7") { BitSize=3 });
            }
            if(p.ApplyRegulationVersionedParamdefCarefully(def,version)) { defPath=candidate; break; }
        }
        if(defPath is null) throw new InvalidDataException($"No matching Paramdef: {p.ParamType}, data version {p.ParamdefDataVersion}, row size {p.DetectedSize}, regulation {version}");
        var names=new Dictionary<int,string>(); var namesPath=Path.Combine(Paramdex,"ER","Names",name+".txt");
        if (File.Exists(namesPath)) foreach(var line in File.ReadLines(namesPath)) {int split=line.IndexOf(' ');if(split>0&&int.TryParse(line[..split],out int id)) names[id]=line[(split+1)..];}
        return new {Source=file,Format="PARAM",Table=name,p.ParamType,RegulationVersion=version,Paramdef=defPath,RowNames=namesPath,RowCount=p.Rows.Count,
            Fields=p.AppliedParamdef.Fields.Select(f=>new {f.InternalName,f.DisplayName,f.DisplayType,f.ArrayLength,f.BitSize}),
            Rows=p.Rows.Select(r=>new {r.ID,Name=names.GetValueOrDefault(r.ID,r.Name),InternalName=r.Name,Cells=r.Cells.Select(c=>new {Name=c.Def.InternalName,Value=c.Value})})};
    }
    static object DumpFmg(string file, byte[] bytes) {
        if (BND4.Is(bytes)) return new {Source=file,Format="FMG-binder",Tables=BND4.Read(bytes).Files.Where(f=>Basename(f.Name).EndsWith(".fmg",StringComparison.OrdinalIgnoreCase)).Select(f=>new {f.ID,f.Name,Entries=FMG.Read(f.Bytes).Entries})};
        return new {Source=file,Format="FMG",Entries=FMG.Read(bytes).Entries};
    }
    static object DumpTpf(string file, byte[] bytes) { var t=TPF.Read(bytes);return new {Source=file,Format="TPF",t.Platform,Textures=t.Textures.Select(x=>new {x.Name,x.Format,x.Type,x.Mipmaps,Size=x.Bytes.Length,x.Header})}; }
}



// Shape.Type is internal upstream; serialize the concrete shape's public dimensions explicitly.
internal sealed class ShapeConverter : JsonConverter<MSB.Shape>
{
    public override MSB.Shape Read(ref Utf8JsonReader reader, Type type, JsonSerializerOptions options) => throw new NotSupportedException();
    public override void Write(Utf8JsonWriter writer, MSB.Shape value, JsonSerializerOptions options)
    {
        writer.WriteStartObject(); writer.WriteString("Type", value.GetType().Name); writer.WritePropertyName("Data");
        JsonSerializer.Serialize(writer, value, value.GetType(), options); writer.WriteEndObject();
    }
}
