using System.Numerics;
using System.Text;
using System.Text.Json;
using SoulsFormats;
using SoulsFormats.Cryptography;

// T020: exclusively staged HD/LG templates. No original templates are overwritten.
//
// 2026-10-05 rework (Claude, after the in-game failure): the first version removed the nodes whose
// names are not in the live skeleton and appended the Xtra bones under the disabled Master, after
// all other nodes, and left the FLVER2 skeleton set (BaseSkeleton/AllSkeletons) as it was: its
// node indices then pointed at other nodes, the Xtra bones were in neither list, and the meshes lost
// their mesh node. In game the props never showed in the hands and the screen flickered. Now the
// template is laid out as vanilla parts are (HD_M_1280, LG_M_1280, AM_M_1500 checked):
//   - nodes: the enabled bones first, then the mesh nodes, then the disabled ones. Every template
//     node stays; the 20 Xtra bones go right after the template's bones. The top of each Xtra chain
//     (live parent Master) is a root with its model-space bind, as vanilla parts' top bones are
//     (AM: L_UpperArm, HD: Spine2) and as c0000.flver has them; the others keep their live parent.
//   - BaseSkeleton: one entry per node (NodeIndex i, the node's own links).
//   - AllSkeletons: the template's entries (the character hierarchy under Master, then the mesh
//     nodes as roots), node indices remapped, the Xtra bones under their live parents.
internal static class Program
{
    static Vector3 Vec(JsonElement v) => new(v[0].GetSingle(), v[1].GetSingle(), v[2].GetSingle());
    static Vector3 Euler(JsonElement r) =>
        Euler(new Quaternion(r[0].GetSingle(), r[1].GetSingle(), r[2].GetSingle(), r[3].GetSingle()));
    static Vector3 Euler(Quaternion r)
    {
        var q = Quaternion.Normalize(r);
        var m = Matrix4x4.CreateFromQuaternion(q);
        // FLVER uses row-vector Rx * Rz * Ry. Xtra references are nonsingular.
        float z = MathF.Asin(Math.Clamp(m.M12, -1f, 1f));
        if (MathF.Abs(MathF.Cos(z)) < 1e-5f) throw new InvalidDataException("Singular XZY reference");
        return new(MathF.Atan2(-m.M32, m.M22), MathF.Atan2(-m.M13, m.M11), z);
    }
    static BND4 Read(string path)
    {
        byte[] bytes = File.ReadAllBytes(path);
        return BND4.Read(DCX.Is(bytes) ? DCX.Decompress(bytes) : bytes);
    }
    static void Require(bool ok, string message) { if (!ok) throw new InvalidDataException(message); }

    /// Child and sibling links from the parents, children (and roots) in list order.
    static void Link(int count, Func<int, int> parent, Action<int, short> firstChild, Action<int, short> next, Action<int, short> previous)
    {
        var last = new Dictionary<int, int>();
        for (int i = 0; i < count; i++) { firstChild(i, -1); next(i, -1); previous(i, -1); }
        for (int i = 0; i < count; i++) {
            int p = parent(i);
            if (last.TryGetValue(p, out int prev)) { next(prev, checked((short)i)); previous(i, checked((short)prev)); }
            else if (p >= 0) firstChild(p, checked((short)i));
            last[p] = i;
        }
    }

    static Matrix4x4 World(IList<FLVER.Node> nodes, int i)
    {
        var n = nodes[i];
        var local = n.ComputeLocalTransform();
        return n.ParentIndex >= 0 ? local * World(nodes, n.ParentIndex) : local;
    }

    static bool IsMesh(FLVER.Node n) => (n.Flags & FLVER.Node.NodeFlags.Mesh) != 0;

    static int Main(string[] args)
    {
        try {
            Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);
            Oodle.Oodle6Ptr = System.Runtime.InteropServices.NativeLibrary.Load(Path.Combine(Environment.GetEnvironmentVariable("ELDEN_RING_DIR") is { Length: > 0 } erDir ? erDir : @"E:\SteamLibrary\steamapps\common\ELDEN RING\Game", "oo2core_6_win64.dll"));
            string output = Path.GetFullPath(args[2]);
            Require(output.Contains(@"\er-data\s3\octane_pov_ability\", StringComparison.OrdinalIgnoreCase), "Template output outside task root");
            var live = JsonDocument.Parse(File.ReadAllText(args[0])).RootElement.GetProperty("bones").EnumerateArray().ToArray();
            var bnd = Read(args[1]);
            var changes = new List<object>();
            foreach (var entry in bnd.Files.Where(f => f.Name.EndsWith(".flver", StringComparison.OrdinalIgnoreCase))) {
                var flver = FLVER2.Read(entry.Bytes);
                var old = flver.Nodes.ToList();
                int count = old.Count;
                var skel = flver.Skeletons;
                Require(skel != null && skel.BaseSkeleton.Count == count && skel.AllSkeletons.Count == count, "Template skeleton set is not one entry per node");
                // the vanilla pattern this relies on: BaseSkeleton mirrors the nodes, the enabled bones first
                for (int i = 0; i < count; i++) {
                    var b = skel!.BaseSkeleton[i]; var n = old[i];
                    Require(b.NodeIndex == i && b.ParentIndex == n.ParentIndex && b.FirstChildIndex == n.FirstChildIndex && b.NextSiblingIndex == n.NextSiblingIndex && b.PreviousSiblingIndex == n.PreviousSiblingIndex, "Template BaseSkeleton differs from its nodes at " + i);
                }
                int bones = 0;
                while (bones < count && old[bones].Flags == FLVER.Node.NodeFlags.Bone) bones++;
                Require(bones > 0 && old.Skip(bones).All(n => n.Flags != FLVER.Node.NodeFlags.Bone), "Template's enabled bones are not a prefix");
                var oldWorld = Enumerable.Range(0, count).Select(i => World(old, i)).ToArray();
                var xtra = live.Where(b => b.GetProperty("name").GetString()!.StartsWith("Xtra_Multipurpose_Bone", StringComparison.Ordinal)).ToArray();
                int x = xtra.Length;
                Require(x == 20, "Expected 20 live Xtra bones");
                int Remap(int i) => i < bones ? i : i + x;
                var oldByName = old.Select((n, i) => (n.Name, i)).ToDictionary(n => n.Name, n => n.i);
                // the Xtra nodes, binds from the live reference (chain tops: model space, as roots)
                var xnodes = new List<FLVER.Node>();
                var xByName = new Dictionary<string, int>();
                var added = new List<object>();
                foreach (var bone in xtra) {
                    string name = bone.GetProperty("name").GetString()!;
                    Require(!oldByName.ContainsKey(name), "Xtra already in template: " + name);
                    string parentName = live[bone.GetProperty("parent").GetInt32()].GetProperty("name").GetString()!;
                    var reference = bone.GetProperty("ref");
                    var node = new FLVER.Node { Name = name,
                        Translation = Vec(reference.GetProperty("t")), Rotation = Euler(reference.GetProperty("r")),
                        Scale = Vec(reference.GetProperty("s")), Flags = FLVER.Node.NodeFlags.Bone,
                        BoundingBoxMin = Vector3.Zero, BoundingBoxMax = Vector3.Zero };
                    bool top = !xByName.ContainsKey(parentName);
                    if (top) {
                        Require(oldByName.ContainsKey(parentName), "Live parent missing: " + parentName);
                        var world = node.ComputeLocalTransform() * oldWorld[oldByName[parentName]];
                        Require(Matrix4x4.Decompose(world, out var scale, out var rotation, out var translation), "Xtra root bind does not decompose: " + name);
                        node.ParentIndex = -1;
                        node.Translation = translation;
                        node.Rotation = Euler(rotation);
                        node.Scale = scale;
                    } else {
                        node.ParentIndex = checked((short)(bones + xByName[parentName]));
                    }
                    xByName[name] = xnodes.Count;
                    xnodes.Add(node);
                    added.Add(new { name, index = bones + xByName[name], node_parent = top ? null : parentName, live_parent = parentName, source_live_index = bone.GetProperty("i").GetInt32() });
                }
                // the old links, remapped, to compare after relinking
                var before = old.Select(n => (Remap2(n.FirstChildIndex), Remap2(n.NextSiblingIndex), Remap2(n.PreviousSiblingIndex))).ToArray();
                short Remap2(short i) => i < 0 ? i : checked((short)Remap(i));
                // the new node list: template bones, Xtra, the rest; indices remapped
                foreach (var n in old) if (n.ParentIndex >= 0) n.ParentIndex = checked((short)Remap(n.ParentIndex));
                var nodes = old.Take(bones).Concat(xnodes).Concat(old.Skip(bones)).ToList();
                foreach (var mesh in flver.Meshes) {
                    if (mesh.NodeIndex >= 0) mesh.NodeIndex = Remap(mesh.NodeIndex);
                    Require(mesh.BoneIndices.Count == 0, "Template mesh uses a bone palette");
                    foreach (var v in mesh.Vertices) for (int k = 0; k < 4; k++) v.BoneIndices[k] = Remap(v.BoneIndices[k]);
                }
                foreach (var dummy in flver.Dummies) {
                    if (dummy.ParentBoneIndex >= 0) dummy.ParentBoneIndex = checked((short)Remap(dummy.ParentBoneIndex));
                    if (dummy.AttachBoneIndex >= 0) dummy.AttachBoneIndex = checked((short)Remap(dummy.AttachBoneIndex));
                }
                flver.Nodes = nodes;
                Link(nodes.Count, i => nodes[i].ParentIndex, (i, v) => nodes[i].FirstChildIndex = v, (i, v) => nodes[i].NextSiblingIndex = v, (i, v) => nodes[i].PreviousSiblingIndex = v);
                // the template's own links are unchanged (bar the roots' chain, which the Xtra roots join)
                for (int i = 0; i < count; i++) {
                    var n = old[i];
                    Require((n.FirstChildIndex, n.NextSiblingIndex, n.PreviousSiblingIndex) == before[i] || n.ParentIndex == -1, "Template node links changed at " + n.Name);
                }
                // and their binds in model space
                for (int i = 0; i < count; i++) {
                    var d = World(nodes, Remap(i)) - oldWorld[i];
                    Require(new[] { d.M11, d.M12, d.M13, d.M21, d.M22, d.M23, d.M31, d.M32, d.M33, d.M41, d.M42, d.M43 }.All(v => MathF.Abs(v) < 1e-5f), "Template bind moved: " + old[i].Name);
                }
                skel!.BaseSkeleton = nodes.Select((n, i) => new FLVER2.SkeletonSet.Bone(i) { ParentIndex = n.ParentIndex, FirstChildIndex = n.FirstChildIndex, NextSiblingIndex = n.NextSiblingIndex, PreviousSiblingIndex = n.PreviousSiblingIndex }).ToList();
                // AllSkeletons: the character hierarchy, then the mesh nodes
                var all = skel.AllSkeletons;
                int firstMeshEntry = all.FindIndex(b => IsMesh(old[b.NodeIndex]));
                Require(firstMeshEntry > 0 && all.Skip(firstMeshEntry).All(b => IsMesh(old[b.NodeIndex]) && b.ParentIndex == -1), "AllSkeletons: mesh nodes are not the trailing roots");
                var newAll = all.Take(firstMeshEntry).Select(b => new FLVER2.SkeletonSet.Bone(Remap(b.NodeIndex)) { ParentIndex = b.ParentIndex }).ToList();
                var xEntry = new Dictionary<string, int>();
                var xParentEntries = new HashSet<int>();
                foreach (var bone in xtra) {
                    string name = bone.GetProperty("name").GetString()!;
                    string parentName = live[bone.GetProperty("parent").GetInt32()].GetProperty("name").GetString()!;
                    int parentEntry;
                    if (xEntry.TryGetValue(parentName, out int pe)) parentEntry = pe;
                    else { parentEntry = all.FindIndex(b => old[b.NodeIndex].Name == parentName); xParentEntries.Add(parentEntry); }
                    Require(parentEntry >= 0, "Xtra parent not in AllSkeletons: " + parentName);
                    xEntry[name] = newAll.Count;
                    newAll.Add(new FLVER2.SkeletonSet.Bone(bones + xByName[name]) { ParentIndex = checked((short)parentEntry) });
                }
                foreach (var b in all.Skip(firstMeshEntry)) newAll.Add(new FLVER2.SkeletonSet.Bone(Remap(b.NodeIndex)) { ParentIndex = -1 });
                var allBefore = all.Take(firstMeshEntry).Select(b => (b.FirstChildIndex, b.NextSiblingIndex, b.PreviousSiblingIndex)).ToArray();
                Link(newAll.Count, i => newAll[i].ParentIndex, (i, v) => newAll[i].FirstChildIndex = v, (i, v) => newAll[i].NextSiblingIndex = v, (i, v) => newAll[i].PreviousSiblingIndex = v);
                // the old entries keep their links, but for the roots (the mesh entries moved) and the
                // last child of each Xtra parent (Master: the Xtra chains come after it)
                var lastChildren = xParentEntries.Select(p => Enumerable.Range(0, firstMeshEntry).Where(i => all[i].ParentIndex == p).DefaultIfEmpty(-1).Max()).ToHashSet();
                var changedAt = Enumerable.Range(0, firstMeshEntry).Where(i => (newAll[i].FirstChildIndex, newAll[i].NextSiblingIndex, newAll[i].PreviousSiblingIndex) != allBefore[i]).ToArray();
                Require(changedAt.All(i => newAll[i].ParentIndex == -1 || lastChildren.Contains(i)), "AllSkeletons links changed at old entries " + string.Join(",", changedAt));
                skel.AllSkeletons = newAll;
                Require(skel.BaseSkeleton.Count == nodes.Count && skel.AllSkeletons.Count == nodes.Count, "Skeleton set size differs from the nodes");
                Require(skel.AllSkeletons.Select(b => b.NodeIndex).OrderBy(i => i).SequenceEqual(Enumerable.Range(0, nodes.Count)), "AllSkeletons is not a permutation of the nodes");
                Require(nodes.Count <= 256, "FLVER byte indices overflow");
                entry.Bytes = flver.Write();
                changes.Add(new { file = entry.Name, removed_nodes = Array.Empty<string>(), template_bones = bones, added_nodes = added, nodes = nodes.Count,
                    skeleton_set = new { base_entries = skel.BaseSkeleton.Count, all_entries = skel.AllSkeletons.Count } });
            }
            Directory.CreateDirectory(Path.GetDirectoryName(output)!);
            File.WriteAllBytes(output, DCX.Compress(bnd.Write(new DCX.NoCompressionInfo()), new DCX.DcxKrakCompressionInfo(DCX.KrakCompressionPreset.EldenRing)));
            File.WriteAllText(args[3], JsonSerializer.Serialize(new { status = "PASS", source = Path.GetFullPath(args[1]), output, live_source = Path.GetFullPath(args[0]), changes }, new JsonSerializerOptions { WriteIndented = true }) + "\n");
            Console.WriteLine("Staged template: 20 enabled Xtra bones after the template's bones, skeleton set rebuilt: " + Path.GetFileName(output));
            return 0;
        } catch (Exception e) { Console.Error.WriteLine(e); return 1; }
    }
}
