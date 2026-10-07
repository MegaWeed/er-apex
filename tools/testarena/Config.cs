using System.Numerics;
using System.Text.RegularExpressions;
using static TestArena.Program;

namespace TestArena;

internal sealed class Config
{
    public required string TargetMap { get; init; }
    public required TemplateConfig Template { get; init; }
    public required ReferenceConfig Reference { get; init; }
    public required float[] GracePosition { get; init; }
    public required int WaveSize { get; init; }
    public required uint TestFlag { get; init; }
    public required uint EventId { get; init; }
    public required GeneratorConfig Generator { get; init; }
    public required SpawnConfig[] SpawnPoints { get; init; }

    public uint[] ReservedIds => SpawnPoints.Select(s => s.PartEntityId).Concat(SpawnPoints.Select(s => s.RegionEntityId))
        .Concat(new[] { Generator.EntityId, EventId, TestFlag }).ToArray();

    public void Validate()
    {
        Require(TargetMap == "m60_42_36_00", "T013 target map must be m60_42_36_00");
        Require(Regex.IsMatch(Template.Map, @"^m\d{2}_\d{2}_\d{2}_\d{2}$") && Regex.IsMatch(Reference.Map, @"^m\d{2}_\d{2}_\d{2}_\d{2}$"), "Invalid map name");
        Require(Template.NpcParamId == 30001014, "T013 requires NpcParam 30001014");
        Require(SpawnPoints.Length == 3, "T013 requires three spawn points");
        Require(WaveSize >= 1 && WaveSize <= SpawnPoints.Length, "Wave size must be 1..3, the configured template/region capacity");
        Require(GracePosition.Length == 3 && GracePosition.All(float.IsFinite), "Invalid grace position");
        Require(ReservedIds.Distinct().Count() == ReservedIds.Length, "Configured flags/entity/event IDs must all differ");
        Require(ReservedIds.All(id => id >= 1042360000 && id <= 1042369999), "Configured IDs must stay in the m60_42_36_00 range 1042360000..1042369999");
        Require(!string.IsNullOrWhiteSpace(Generator.Name) && !string.IsNullOrWhiteSpace(Template.PartName), "Names cannot be empty");
        Require(SpawnPoints.Select(s => s.PartName).Distinct().Count() == 3 && SpawnPoints.Select(s => s.RegionName).Distinct().Count() == 3, "New names must be unique within their category");
        Require(SpawnPoints.Select(s => s.RegionId).Distinct().Count() == 3 && SpawnPoints.Select(s => s.InstanceId).Distinct().Count() == 3, "Internal region/instance IDs must be unique");
        Require(Generator.MsbEventId >= 0, "Invalid MSB event ID");
        foreach (SpawnConfig spawn in SpawnPoints)
        {
            Require(spawn.Position.Length == 3 && spawn.Position.All(float.IsFinite) && float.IsFinite(spawn.Yaw), "Invalid spawn position/yaw");
            float dx = spawn.Position[0] - GracePosition[0], dz = spawn.Position[2] - GracePosition[2];
            double distance = Math.Sqrt(dx * dx + dz * dz);
            Require(distance >= 8 && distance <= 12, "Spawn point must be 8..12 metres horizontally from the grace");
            Require(spawn.RegionId >= 0 && spawn.InstanceId >= 0, "Invalid internal region/instance ID");
            Require(!string.IsNullOrWhiteSpace(spawn.PartName) && !string.IsNullOrWhiteSpace(spawn.RegionName), "Names cannot be empty");
        }
        // Height is intentionally configurable: Claude will replace the provisional 91.7 with measured ground height + clearance.
    }
}

internal sealed class TemplateConfig
{
    public required string Map { get; init; }
    public required int NpcParamId { get; init; }
    public required string PartName { get; init; }
}

internal sealed class ReferenceConfig
{
    public required string Map { get; init; }
    public required uint GeneratorEntityId { get; init; }
}

internal sealed class GeneratorConfig
{
    public required uint EntityId { get; init; }
    public required int MsbEventId { get; init; }
    public required string Name { get; init; }
}

internal sealed class SpawnConfig
{
    public required float[] Position { get; init; }
    public required float Yaw { get; init; }
    public required string PartName { get; init; }
    public required uint PartEntityId { get; init; }
    public required int InstanceId { get; init; }
    public required string RegionName { get; init; }
    public required uint RegionEntityId { get; init; }
    public required int RegionId { get; init; }
    public Vector3 PositionVector => new(Position[0], Position[1], Position[2]);
    public Vector3 RotationVector => new(0, Yaw, 0);
}
