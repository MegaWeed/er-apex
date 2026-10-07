using System.Buffers.Binary;
using SoulsFormats;
using static TestArena.Program;

namespace TestArena;

// ER argument layouts: little endian, natural argument alignment, total padded to four bytes.
// Each layout is checked against a vanilla instruction by Evidence.Write; EMEDF is a secondary source.
internal static class Instructions
{
    internal sealed record Arg(string Name, string Type, int Offset);
    internal sealed record Definition(int Bank, int Id, string Name, int Size, Arg[] Args);
    internal static readonly Definition[] Definitions =
    {
        new(3, 0, "IF Event Flag", 8, new[] { new Arg("conditionGroup", "s8", 0), new Arg("desiredState", "u8", 1), new Arg("flagType", "u8", 2), new Arg("flagId", "u32", 4) }),
        new(2003, 54, "Invoke Enemy Generator", 4, new[] { new Arg("generatorEntityId", "u32", 0) }),
        new(2003, 66, "Set Event Flag", 12, new[] { new Arg("flagType", "u8", 0), new Arg("flagId", "u32", 4), new Arg("desiredState", "u8", 8) }),
        new(1000, 4, "END Unconditionally", 4, new[] { new Arg("endType", "u8", 0) }),
        new(2000, 0, "Initialize Event", 12, new[] { new Arg("slot", "s32", 0), new Arg("eventId", "u32", 4), new Arg("argument0", "u32", 8) })
    };

    internal static EMEVD.Instruction WaitForFlag(uint flag) => new(3, 0, new object[] { (sbyte)0, (byte)1, (byte)0, flag });
    internal static EMEVD.Instruction Invoke(uint generator) => new(2003, 54, new object[] { generator });
    internal static EMEVD.Instruction ClearFlag(uint flag) => new(2003, 66, new object[] { (byte)0, flag, (byte)0 });
    internal static EMEVD.Instruction Restart() => new(1000, 4, new object[] { (byte)1 });
    internal static EMEVD.Instruction Initialize(uint eventId) => new(2000, 0, new object[] { 0, eventId, 0u });

    internal static object Decode(EMEVD.Instruction instruction)
    {
        Definition definition = Definitions.Single(d => d.Bank == instruction.Bank && d.Id == instruction.ID);
        Require(instruction.ArgData.Length == definition.Size, "Unexpected argument length for " + definition.Name);
        Dictionary<string, long> arguments = new();
        bool[] occupied = new bool[definition.Size];
        foreach (Arg argument in definition.Args)
        {
            arguments[argument.Name] = argument.Type switch
            {
                "u8" => instruction.ArgData[argument.Offset],
                "s8" => (sbyte)instruction.ArgData[argument.Offset],
                "u32" => BinaryPrimitives.ReadUInt32LittleEndian(instruction.ArgData.AsSpan(argument.Offset, 4)),
                "s32" => BinaryPrimitives.ReadInt32LittleEndian(instruction.ArgData.AsSpan(argument.Offset, 4)),
                _ => throw new InvalidDataException("Unknown argument type")
            };
            for (int i = 0; i < (argument.Type.EndsWith("32") ? 4 : 1); i++) occupied[argument.Offset + i] = true;
        }
        Require(instruction.ArgData.Where((b, i) => !occupied[i]).All(b => b == 0), "Nonzero instruction argument padding");
        string name = definition.Name;
        if (instruction.Bank == 1000 && instruction.ID == 4) name = arguments["endType"] == 1 ? "Restart Event" : "End Event";
        return new { instruction.Bank, Id = instruction.ID, Name = name, Arguments = arguments, ArgDataHex = Convert.ToHexString(instruction.ArgData), instruction.Layer };
    }
}
