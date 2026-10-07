using System.Buffers.Binary;
using System.Security.Cryptography;
using SoulsFormats;
using static TestArena.Program;

namespace TestArena;

internal static class Verification
{
    internal static void Verify(Config config, Corpus.Result scan)
    {
        Arena.Sources sources = Arena.ReadSources(config);
        MSBE original = sources.Map;
        EMEVD originalEmevd = sources.Emevd;
        string mapOutput = Output("package/" + MapPath(config.TargetMap));
        string eventOutput = Output("package/" + EventPath(config.TargetMap));
        Require(File.Exists(mapOutput) && File.Exists(eventOutput), "Missing generated package files");
        MSBE output = MSBE.Read(mapOutput);
        EMEVD outputEmevd = EMEVD.Read(eventOutput);
        bool addedModel = original.Models.GetEntries().All(m => m.Name != sources.Template.ModelName);

        CompareEntries("models", original.Models.GetEntries(), output.Models.GetEntries(), addedModel ? new[] { sources.Template.ModelName } : Array.Empty<string>());
        CompareEntries("parts", original.Parts.GetEntries(), output.Parts.GetEntries(), config.SpawnPoints.Select(s => s.PartName).ToArray());
        CompareEntries("regions", original.Regions.GetEntries(), output.Regions.GetEntries(), config.SpawnPoints.Select(s => s.RegionName).ToArray());
        CompareEntries("MSB events", original.Events.GetEntries(), output.Events.GetEntries(), new[] { config.Generator.Name });
        CompareEntries("routes", original.Routes.GetEntries(), output.Routes.GetEntries(), Array.Empty<string>());
        var instanceCountField = typeof(MSBE.Model).GetField("InstanceCount", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)
            ?? throw new InvalidDataException("SoulsFormats model instance-count field is missing");
        foreach (MSBE.Model model in original.Models.GetEntries())
        {
            MSBE.Model actual = output.Models.GetEntries().Single(m => m.Name == model.Name);
            int originalCount = (int)instanceCountField.GetValue(model)!;
            int expectedCount = originalCount + (model.Name == sources.Template.ModelName ? config.SpawnPoints.Length : 0);
            Require((int)instanceCountField.GetValue(actual)! == expectedCount, "Serialized model instance count differs: " + model.Name);
        }
        Require(Snapshot(original.Layers) == Snapshot(output.Layers), "Original layers changed");
        Require(original.Models.Version == output.Models.Version && original.Parts.Version == output.Parts.Version &&
            original.Regions.Version == output.Regions.Version && original.Events.Version == output.Events.Version &&
            original.Routes.Version == output.Routes.Version && original.Layers.Version == output.Layers.Version, "MSB section version changed");

        foreach (SpawnConfig spawn in config.SpawnPoints)
        {
            MSBE.Part part = output.Parts.GetEntries().Single(p => p.Name == spawn.PartName);
            MSBE.Region region = output.Regions.GetEntries().Single(r => r.Name == spawn.RegionName);
            Require(part is MSBE.Part.Enemy, "Generator template must be an ordinary Enemy, matching vanilla");
            Require(Snapshot(part) == Snapshot(Arena.NewPart(sources, spawn)), "New enemy differs from source/config: " + spawn.PartName);
            Require(Snapshot(region) == Snapshot(Arena.NewRegion(sources, spawn)), "Spawn region differs from vanilla/config: " + spawn.RegionName);
            Require(output.Parts.GetEntries().Count(p => p.EntityID == spawn.PartEntityId) == 1, "Enemy entity ID ownership is not unique");
            Require(output.Regions.GetEntries().Count(r => r.EntityID == spawn.RegionEntityId) == 1, "Region entity ID ownership is not unique");
            Require(output.Parts.GetEntries().Count(p => p.ModelName == sources.Template.ModelName && p.InstanceID == spawn.InstanceId) == 1, "Enemy model instance ID is not unique");
            Require(output.Regions.GetEntries().Count(r => r.RegionID == spawn.RegionId) == 1, "Internal region ID is not unique");
        }
        MSBE.Event.Generator generator = output.Events.Generators.Single(g => g.Name == config.Generator.Name);
        Require(Snapshot(generator) == Snapshot(Arena.NewGenerator(sources, config)), "New generator fields/references differ from vanilla/config");
        Require(generator.SpawnPartNames.Length == 32 && generator.SpawnRegionNames.Length == 8, "Generator reference array capacity changed");
        Require(generator.SpawnPartNames.Where(n => n != null).SequenceEqual(config.SpawnPoints.Select(s => s.PartName)) &&
            generator.SpawnRegionNames.Where(n => n != null).SequenceEqual(config.SpawnPoints.Select(s => s.RegionName)), "Generator references wrong parts/regions");
        Require(generator.InitialSpawnCount == 0 && generator.GenType == 3 && generator.LimitNum == -1, "Generator initial/manual/repeat settings changed");
        Require(output.Events.GetEntries().Count(e => e.EventID == config.Generator.MsbEventId) == 1 &&
            output.Events.GetEntries().Count(e => e.EntityID == config.Generator.EntityId) == 1, "Generator IDs are not unique");
        if (addedModel)
        {
            Require(Snapshot(output.Models.GetEntries().Single(m => m.Name == sources.Template.ModelName)) ==
                Snapshot(sources.TemplateMap.Models.GetEntries().Single(m => m.Name == sources.Template.ModelName)), "Added model differs from template source");
            Require((int)instanceCountField.GetValue(output.Models.GetEntries().Single(m => m.Name == sources.Template.ModelName))! == config.SpawnPoints.Length,
                "Added model's serialized instance count is incorrect");
        }

        Require(outputEmevd.Format == originalEmevd.Format && outputEmevd.StringData.SequenceEqual(originalEmevd.StringData) &&
            outputEmevd.LinkedFileOffsets.SequenceEqual(originalEmevd.LinkedFileOffsets), "EMEVD format/string/linked-file data changed");
        Require(outputEmevd.Events.Count == originalEmevd.Events.Count + 1 && outputEmevd.Events.Select(e => e.ID).Distinct().Count() == outputEmevd.Events.Count, "Unexpected or duplicate EMEVD events");
        Require(outputEmevd.Events.Take(originalEmevd.Events.Count).Select(e => e.ID).SequenceEqual(originalEmevd.Events.Select(e => e.ID)), "Original EMEVD event order changed");
        foreach (EMEVD.Event ev in originalEmevd.Events)
        {
            EMEVD.Event actual = outputEmevd.Events.Single(e => e.ID == ev.ID);
            if (ev.ID == 0)
            {
                Require(actual.RestBehavior == ev.RestBehavior && Snapshot(actual.Parameters) == Snapshot(ev.Parameters), "Event 0 rest behavior/parameters changed");
                Require(actual.Instructions.Count == ev.Instructions.Count + 1, "Event 0 must have exactly one appended initialization");
                for (int i = 0; i < ev.Instructions.Count; i++)
                    Require(Snapshot(actual.Instructions[i]) == Snapshot(ev.Instructions[i]), $"Original event 0 instruction {i} changed");
                Require(Snapshot(actual.Instructions[^1]) == Snapshot(Instructions.Initialize(config.EventId)), "Incorrect event initialization");
            }
            else Require(Snapshot(actual) == Snapshot(ev), "Original EMEVD event changed: " + ev.ID);
        }
        EMEVD.Event newEvent = outputEmevd.Events.Single(e => e.ID == config.EventId);
        Require(newEvent.Parameters.Count == 0 && newEvent.RestBehavior == EMEVD.Event.RestBehaviorType.Restart, "New event parameter/rest behavior differs");
        var expectedInstructions = new[] { Instructions.WaitForFlag(config.TestFlag), Instructions.Invoke(config.Generator.EntityId), Instructions.ClearFlag(config.TestFlag), Instructions.Restart() };
        Require(newEvent.Instructions.Count == expectedInstructions.Length, "New event must contain exactly four instructions");
        for (int i = 0; i < expectedInstructions.Length; i++)
            Require(Snapshot(newEvent.Instructions[i]) == Snapshot(expectedInstructions[i]), "Incorrect new event instruction: " + i);

        // Independent explicit offset decoder; it does not call SoulsFormats.UnpackArgs or mirror its packing routine.
        var decoded = newEvent.Instructions.Select((instruction, index) => new { Index = index, Instruction = Instructions.Decode(instruction) }).ToArray();
        Console.WriteLine($"Event {config.EventId} (Restart on rest):");
        var compact = new System.Text.Json.JsonSerializerOptions(Json) { WriteIndented = false };
        foreach (var instruction in decoded) Console.WriteLine(System.Text.Json.JsonSerializer.Serialize(instruction, compact));
        object initialized = Instructions.Decode(outputEmevd.Events.Single(e => e.ID == 0).Instructions[^1]);
        Console.WriteLine($"Event 0 instruction {originalEmevd.Events.Single(e => e.ID == 0).Instructions.Count}: " + System.Text.Json.JsonSerializer.Serialize(initialized, compact));

        byte[] mapRaw = DCX.Decompress(File.ReadAllBytes(mapOutput));
        byte[] eventRaw = DCX.Decompress(File.ReadAllBytes(eventOutput));
        foreach (uint id in config.ReservedIds)
        {
            int mapCount = id == config.TestFlag || id == config.EventId ? 0 : 1;
            int eventCount = id == config.EventId || id == config.TestFlag ? 2 : id == config.Generator.EntityId ? 1 : 0;
            Require(CountLiteral(mapRaw, id) == mapCount, $"MSB reserved ID {id} used outside its configured owner");
            Require(CountLiteral(eventRaw, id) == eventCount, $"EMEVD reserved ID {id} used outside the new event/initialization");
        }

        Require(Snapshot(original.Compression) == Snapshot(output.Compression), "MSB DCX compression differs from original");
        Require(Snapshot(originalEmevd.Compression) == Snapshot(outputEmevd.Compression), "EMEVD DCX compression differs from original");

        // Remove additions and reserialize both sides. This also checks hidden serialized fields,
        // model instance counts, names and all regenerated reference indices after restoring original entry lists.
        MSBE restored = MSBE.Read(mapOutput);
        restored.Parts.Enemies.RemoveAll(p => config.SpawnPoints.Any(s => s.PartName == p.Name));
        restored.Regions.Others.RemoveAll(r => config.SpawnPoints.Any(s => s.RegionName == r.Name));
        restored.Events.Generators.RemoveAll(g => g.Name == config.Generator.Name);
        if (addedModel) restored.Models.Enemies.RemoveAll(m => m.Name == sources.Template.ModelName);
        byte[] normalizedMap = original.Write(Uncompressed);
        Require(normalizedMap.SequenceEqual(restored.Write(Uncompressed)), "Restored MSB bytes differ from normalized original");
        EMEVD restoredEmevd = EMEVD.Read(eventOutput);
        restoredEmevd.Events.RemoveAll(e => e.ID == config.EventId);
        restoredEmevd.Events.Single(e => e.ID == 0).Instructions.RemoveAt(originalEmevd.Events.Single(e => e.ID == 0).Instructions.Count);
        byte[] normalizedEmevd = originalEmevd.Write(Uncompressed);
        Require(normalizedEmevd.SequenceEqual(restoredEmevd.Write(Uncompressed)), "Restored EMEVD bytes differ from normalized original");

        WriteJson("verify-report.json", new
        {
            Status = "PASS", CollisionScan = scan,
            OriginalEntries = new { Models = original.Models.GetEntries().Count, Parts = original.Parts.GetEntries().Count, Regions = original.Regions.GetEntries().Count, Events = original.Events.GetEntries().Count, EmevdEvents = originalEmevd.Events.Count },
            AddedEntries = new { Models = addedModel ? 1 : 0, Parts = config.SpawnPoints.Length, Regions = config.SpawnPoints.Length, Generators = 1, EmevdEvents = 1, Event0Initializations = 1 },
            OriginalPropertiesUnchanged = true, ModelInstanceCountsVerified = true, RestoredSerializedBytesEqual = true, ReservedIdOwnershipUnique = true,
            GeneratorReferences = new { generator.EntityID, generator.SpawnPartNames, generator.SpawnRegionNames },
            NewEvent = new { newEvent.ID, newEvent.RestBehavior, Instructions = decoded }, Initialization = initialized,
            Compression = new { Msb = (object)output.Compression, Emevd = (object)outputEmevd.Compression },
            NormalizedOriginalSha256 = new { Msb = Convert.ToHexString(SHA256.HashData(normalizedMap)), Emevd = Convert.ToHexString(SHA256.HashData(normalizedEmevd)) },
            OutputSha256 = new { Msb = Sha256(mapOutput), Emevd = Sha256(eventOutput) },
            InGameValidation = "Not performed. Check initial invisibility, exact wave count/positions/resources, AI, repeated triggers after killing the prior wave, grace rest and map reload."
        });
        Console.WriteLine($"PASS unchanged MSB: {original.Models.GetEntries().Count} models, {original.Parts.GetEntries().Count} parts, {original.Regions.GetEntries().Count} regions, {original.Events.GetEntries().Count} events");
        Console.WriteLine($"PASS unchanged EMEVD: {originalEmevd.Events.Count} original events; event 0 only appends one initialization");
        Console.WriteLine("PASS generator references, configured IDs, hidden template pattern, DCX compression, restored serialized bytes");
        Console.WriteLine("PASS");
    }

    static void CompareEntries<T>(string category, List<T> original, List<T> output, string[] additions) where T : MSBE.Entry
    {
        Require(output.Count == original.Count + additions.Length, "Unexpected count of " + category);
        var remaining = output.Where(e => !additions.Contains(e.Name)).ToList();
        Require(remaining.Count == original.Count, "Unexpected added names in " + category);
        for (int i = 0; i < original.Count; i++)
            Require(Snapshot(original[i]) == Snapshot(remaining[i]), $"Original {category} entry changed: {original[i].Name}");
        foreach (string name in additions) Require(output.Count(e => e.Name == name) == 1, "Added entry name is not unique: " + name);
    }

    static int CountLiteral(byte[] data, uint id)
    {
        int count = 0;
        for (int i = 0; i <= data.Length - 4; i++)
            if (BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(i, 4)) == id) count++;
        return count;
    }
}
