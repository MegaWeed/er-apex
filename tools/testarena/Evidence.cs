using System.Text.Json;
using SoulsFormats;
using static TestArena.Program;

namespace TestArena;

internal static class Evidence
{
    internal static void Write(Config config)
    {
        Arena.Sources sources = Arena.ReadSources(config);
        var generator = sources.Generator;
        WriteJson("evidence/reference.json", new
        {
            File = Original(MapPath(config.Reference.Map)), Sha256 = Sha256(Original(MapPath(config.Reference.Map))),
            Generator = generator, TemplatePart = sources.ReferencePart, SpawnRegion = sources.Region,
            FieldInterpretation = new
            {
                MaxNum = "Active template capacity (inferred); reference 1, arena 3.",
                GenType = "3: explicit invocation mode (inferred from matching vanilla Invoke Enemy Generator). Preserved.",
                LimitNum = "-1: no finite generation limit (inferred). Preserved.",
                MinGenNum = "Minimum generated count for one invocation (inferred); arena waveSize.",
                MaxGenNum = "Maximum generated count for one invocation (inferred); arena waveSize.",
                MinInterval = "Minimum interval, reference 5 seconds; preserved. Effect on explicit invocation needs in-game validation.",
                MaxInterval = "Maximum interval, reference 5 seconds; preserved. Effect on explicit invocation needs in-game validation.",
                InitialSpawnCount = "0: no initial wave; preserve ordinary Enemy part membership in the generator.",
                UnkT14 = "Unknown float, reference 0; preserved.",
                UnkT18 = "Unknown float, reference 0; preserved.",
                SpawnRegionNames = "8 name references serialized as region indices; first 3 arena slots populated, others null.",
                SpawnPartNames = "32 name references serialized as part indices; first 3 ordinary Enemy slots populated, others null.",
                OtherFields = "EventID is an internal MSB event identifier; EntityID is the script-visible generator identifier. Other common/unknown fields copied unchanged."
            },
            AppearanceEvidence = "Vanilla m30_16_00_00 uses ordinary Enemy, GenType=3, InitialSpawnCount=0, ChrActivateCondParamID=0, NeverDisable; EMEVD event 30162621 instruction 47 invokes this generator. No added disable/enable instructions are needed for this vanilla pattern; engine behavior must be confirmed in game.",
            SourceSoldier = new { Map = config.Template.Map, Part = sources.TemplateMap.Parts.Enemies.Single(p => p.Name == config.Template.PartName) },
            LocalAdaptations = "GameEditionDisable set to the reference generator template's NeverDisable (source has DisableInNetworkTest). CollisionPartName=null and DisplayGroups copied from untouched grace character 1042360951, matching the target overworld tile. Identity/transform changed by config; NPC/think/model and other source fields retained."
        });

        var samples = new[]
        {
            Sample("m10_00_00_00", 10002500, 9, 3, 0),
            Sample(config.Reference.Map, 30162621, 47, 2003, 54),
            Sample("common", 50, 7, 2003, 66),
            Sample("common", 50, 254, 1000, 4),
            Sample(config.TargetMap, 1042360690, 15, 1000, 4),
            Sample("m10_00_00_00", 0, 16, 2000, 0)
        };
        EMEVD referenceEmevd = EMEVD.Read(Original(EventPath(config.Reference.Map)));
        EMEVD.Instruction invoke = referenceEmevd.Events.Single(e => e.ID == 30162621).Instructions[47];
        Require(BitConverter.ToUInt32(invoke.ArgData) == config.Reference.GeneratorEntityId, "Reference EMEVD does not invoke the configured generator");
        object? secondarySource = null;
        string emedf = Path.Combine(FindRepository(), "scratch", "ref", "er-common.emedf.json");
        if (File.Exists(emedf))
        {
            CheckEmedf(emedf);
            secondarySource = new { Path = emedf, Sha256 = Sha256(emedf), Note = "Existing local DarkScript3 ER EMEDF; no network download used for instruction layouts." };
        }
        WriteJson("evidence/instruction-evidence.json", new
        {
            ByteOrder = "little endian",
            Alignment = "Natural argument alignment, total padded to 4 bytes; all padding checked as zero.",
            InstructionIndexConvention = "zero based",
            Layouts = Instructions.Definitions, Samples = samples, SecondarySource = secondarySource,
            EnumValues = new { ConditionMain = 0, FlagOn = 1, FlagOff = 0, FlagTypeEventFlag = 0, EndTypeEnd = 0, EndTypeRestart = 1 }
        });
    }

    static object Sample(string map, long eventId, int index, int bank, int id)
    {
        string file = Original(EventPath(map));
        EMEVD.Instruction instruction = EMEVD.Read(file).Events.Single(e => e.ID == eventId).Instructions[index];
        Require(instruction.Bank == bank && instruction.ID == id, $"Vanilla instruction evidence differs at {map}:{eventId}:{index}");
        return new { File = file, FileSha256 = Sha256(file), EventId = eventId, InstructionIndex = index, Decoded = Instructions.Decode(instruction) };
    }

    static void CheckEmedf(string file)
    {
        using var json = JsonDocument.Parse(File.ReadAllText(file));
        foreach (Instructions.Definition definition in Instructions.Definitions)
        {
            JsonElement bank = json.RootElement.GetProperty("main_classes").EnumerateArray().Single(c => c.GetProperty("index").GetInt32() == definition.Bank);
            JsonElement instruction = bank.GetProperty("instrs").EnumerateArray().Single(i => i.GetProperty("index").GetInt32() == definition.Id);
            var args = instruction.GetProperty("args").EnumerateArray().ToArray();
            Require(args.Length == definition.Args.Length, "EMEDF argument count disagrees with " + definition.Name);
            int offset = 0;
            for (int i = 0; i < args.Length; i++)
            {
                string type = args[i].GetProperty("type").GetInt32() switch
                {
                    0 => "u8", 2 => "u32", 3 => "s8", 5 => "s32", _ => throw new InvalidDataException("Unexpected EMEDF argument type")
                };
                int size = type.EndsWith("32") ? 4 : 1;
                offset = (offset + size - 1) / size * size;
                Require(type == definition.Args[i].Type && offset == definition.Args[i].Offset, "EMEDF layout disagrees with " + definition.Name);
                offset += size;
            }
            Require((offset + 3) / 4 * 4 == definition.Size, "EMEDF instruction size disagrees");
        }
    }
}
