using SoulsFormats;
using static TestArena.Program;

namespace TestArena;

internal static class Arena
{
    internal sealed record Sources(MSBE Map, EMEVD Emevd, MSBE TemplateMap, MSBE ReferenceMap,
        MSBE.Part.Enemy Template, MSBE.Event.Generator Generator, MSBE.Region Region, MSBE.Part.Enemy ReferencePart);

    internal static Sources ReadSources(Config config)
    {
        MSBE map = MSBE.Read(Original(MapPath(config.TargetMap)));
        EMEVD emevd = EMEVD.Read(Original(EventPath(config.TargetMap)));
        MSBE sourceMap = MSBE.Read(Original(MapPath(config.Template.Map)));
        MSBE referenceMap = MSBE.Read(Original(MapPath(config.Reference.Map)));
        MSBE.Part.Enemy template = sourceMap.Parts.Enemies.Single(e => e.Name == config.Template.PartName && e.NPCParamID == config.Template.NpcParamId);
        MSBE.Event.Generator generator = referenceMap.Events.Generators.Single(g => g.EntityID == config.Reference.GeneratorEntityId);
        Require(generator.GenType == 3 && generator.InitialSpawnCount == 0 && generator.LimitNum == -1, "Reference must be an on-demand, initially empty generator with no finite spawn limit");
        string regionName = generator.SpawnRegionNames.First(n => n != null);
        string partName = generator.SpawnPartNames.First(n => n != null);
        MSBE.Region region = referenceMap.Regions.GetEntries().Single(r => r.Name == regionName);
        MSBE.Part.Enemy referencePart = referenceMap.Parts.Enemies.Single(p => p.Name == partName);
        // The selected retail soldier carries DisableInNetworkTest in Stormveil.
        // Prepare a copy with the vanilla generator template's edition setting;
        // the original source map remains untouched and the appearance check below is retained.
        template = (MSBE.Part.Enemy)template.DeepCopy();
        template.GameEditionDisable = referencePart.GameEditionDisable;
        Require(region is MSBE.Region.Other && region.Shape is MSB.Shape.Sphere { Radius: 1 }, "Unexpected reference spawn region layout");
        Require(referencePart.ChrActivateCondParamID == 0 && referencePart.GameEditionDisable == template.GameEditionDisable, "Reference/template appearance conditions differ");
        Require(template.ChrActivateCondParamID == 0 && template.WalkRouteName == null && template.BackupEventAnimID == -1 && template.EntityGroupIDs.All(id => id == 0), "Choose an ungrouped standing soldier without a patrol route or event animation");
        return new(map, emevd, sourceMap, referenceMap, template, generator, region, referencePart);
    }

    internal static MSBE.Part.Enemy NewPart(Sources sources, SpawnConfig spawn)
    {
        var part = (MSBE.Part.Enemy)sources.Template.DeepCopy();
        part.Name = spawn.PartName;
        part.EntityID = spawn.PartEntityId;
        part.InstanceID = spawn.InstanceId;
        part.Position = spawn.PositionVector;
        part.Rotation = spawn.RotationVector;
        // All vanilla overworld enemies in this tile use no per-part collision binding;
        // keep the source NPC/think/model fields, adopt this tile's draw-group membership.
        var local = sources.Map.Parts.Enemies.Single(p => p.EntityID == 1042360951);
        part.CollisionPartName = null;
        part.Unk1.DisplayGroups = (uint[])local.Unk1.DisplayGroups.Clone();
        return part;
    }

    internal static MSBE.Region NewRegion(Sources sources, SpawnConfig spawn)
    {
        MSBE.Region region = sources.Region.DeepCopy();
        region.Name = spawn.RegionName;
        region.EntityID = spawn.RegionEntityId;
        region.RegionID = spawn.RegionId;
        region.Position = spawn.PositionVector;
        region.Rotation = spawn.RotationVector;
        return region;
    }

    internal static MSBE.Event.Generator NewGenerator(Sources sources, Config config)
    {
        var generator = (MSBE.Event.Generator)sources.Generator.DeepCopy();
        generator.Name = config.Generator.Name;
        generator.EntityID = config.Generator.EntityId;
        generator.EventID = config.Generator.MsbEventId;
        generator.MaxNum = checked((byte)config.SpawnPoints.Length);
        generator.MinGenNum = generator.MaxGenNum = checked((short)config.WaveSize);
        generator.SpawnRegionNames = new string[8];
        generator.SpawnPartNames = new string[32];
        for (int i = 0; i < config.SpawnPoints.Length; i++)
        {
            generator.SpawnRegionNames[i] = config.SpawnPoints[i].RegionName;
            generator.SpawnPartNames[i] = config.SpawnPoints[i].PartName;
        }
        return generator;
    }

    internal static void Build(Config config, string configPath)
    {
        Sources sources = ReadSources(config);
        MSBE map = sources.Map;
        EMEVD emevd = sources.Emevd;
        foreach (SpawnConfig spawn in config.SpawnPoints)
        {
            Require(map.Parts.GetEntries().All(p => p.Name != spawn.PartName), "Part name already exists: " + spawn.PartName);
            Require(map.Parts.GetEntries().All(p => p.ModelName != sources.Template.ModelName || p.InstanceID != spawn.InstanceId), "Model instance ID already exists");
            Require(map.Regions.GetEntries().All(r => r.Name != spawn.RegionName && r.RegionID != spawn.RegionId), "Spawn region name/internal ID already exists");
        }
        Require(map.Events.GetEntries().All(e => e.Name != config.Generator.Name && e.EventID != config.Generator.MsbEventId), "Generator name/internal ID already exists");
        bool addedModel = map.Models.GetEntries().All(m => m.Name != sources.Template.ModelName);
        if (addedModel)
            map.Models.Add(sources.TemplateMap.Models.GetEntries().Single(m => m.Name == sources.Template.ModelName).DeepCopy());
        foreach (SpawnConfig spawn in config.SpawnPoints)
        {
            map.Parts.Add(NewPart(sources, spawn));
            map.Regions.Add(NewRegion(sources, spawn));
        }
        map.Events.Add(NewGenerator(sources, config));
        var ev = new EMEVD.Event(config.EventId, EMEVD.Event.RestBehaviorType.Restart);
        ev.Instructions.Add(Instructions.WaitForFlag(config.TestFlag));
        ev.Instructions.Add(Instructions.Invoke(config.Generator.EntityId));
        ev.Instructions.Add(Instructions.ClearFlag(config.TestFlag));
        ev.Instructions.Add(Instructions.Restart());
        emevd.Events.Add(ev);
        emevd.Events.Single(e => e.ID == 0).Instructions.Add(Instructions.Initialize(config.EventId));
        string mapOutput = Output("package/" + MapPath(config.TargetMap));
        string eventOutput = Output("package/" + EventPath(config.TargetMap));
        map.Write(mapOutput);
        emevd.Write(eventOutput);
        Evidence.Write(config);
        WriteJson("build-manifest.json", new
        {
            ConfigPath = Path.GetFullPath(configPath), ConfigSha256 = Sha256(configPath),
            Config = config, AddedModel = addedModel,
            Template = new { Map = config.Template.Map, sources.Template.Name, sources.Template.NPCParamID, sources.Template.ThinkParamID, sources.Template.ModelName },
            Outputs = new[]
            {
                new { Path = "package/" + MapPath(config.TargetMap), Sha256 = Sha256(mapOutput), Compression = (object)map.Compression },
                new { Path = "package/" + EventPath(config.TargetMap), Sha256 = Sha256(eventOutput), Compression = (object)emevd.Compression }
            },
            Trigger = $"setflag {config.TestFlag} 1"
        });
        Console.WriteLine($"Built {mapOutput}\nBuilt {eventOutput}");
    }
}
