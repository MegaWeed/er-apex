using System.Numerics;
using System.Text;
using SoulsFormats;

// Independent negative-check fixture: mutate only the generated package, never vanilla inputs.
Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);
Oodle.Oodle6Ptr = System.Runtime.InteropServices.NativeLibrary.Load(args[3]);
foreach (string file in args.Take(2))
    if (!Path.GetFullPath(file).Contains(@"\er-data\test_arena\package\", StringComparison.OrdinalIgnoreCase))
        throw new InvalidDataException("Mutation is restricted to the assigned generated package");
switch (args[2])
{
    case "original-part":
    {
        var map = MSBE.Read(args[0]);
        var part = map.Parts.Enemies.Single(p => p.EntityID == 1042360951);
        part.Position += new Vector3(0, 0.25f, 0);
        map.Write(args[0]);
        break;
    }
    case "original-event":
    {
        var emevd = EMEVD.Read(args[1]);
        emevd.Events.Single(e => e.ID == 0).Instructions[0].ArgData[0] ^= 1;
        emevd.Write(args[1]);
        break;
    }
    case "generator-reference":
    {
        var map = MSBE.Read(args[0]);
        map.Events.Generators.Single(g => g.EntityID == 1042363900).SpawnPartNames[0] = map.Parts.Enemies.Single(p => p.EntityID == 1042360951).Name;
        map.Write(args[0]);
        break;
    }
    case "duplicate-id":
    {
        var map = MSBE.Read(args[0]);
        map.Parts.Enemies.Single(p => p.EntityID == 1042360850).EntityID = 1042360951;
        map.Write(args[0]);
        break;
    }
    case "new-instruction":
    {
        var emevd = EMEVD.Read(args[1]);
        emevd.Events.Single(e => e.ID == 1042363990).Instructions[2].ArgData[8] = 1;
        emevd.Write(args[1]);
        break;
    }
    default: throw new ArgumentException("Unknown mutation");
}
