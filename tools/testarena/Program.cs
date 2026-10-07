using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using SoulsFormats;

namespace TestArena;

internal static class Program
{
    internal static readonly JsonSerializerOptions Json = new()
    {
        WriteIndented = true,
        IncludeFields = true,
        PropertyNameCaseInsensitive = true,
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow,
        NumberHandling = JsonNumberHandling.AllowNamedFloatingPointLiterals,
        Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        Converters = { new JsonStringEnumConverter(), new ShapeConverter() }
    };
    internal static string DataDir = "";
    internal static readonly DCX.CompressionInfo Uncompressed = new DCX.NoCompressionInfo();

    static int Main(string[] args)
    {
        Console.OutputEncoding = new UTF8Encoding(false);
        bool outputAuthorized = false;
        try
        {
            Require(args.Length >= 2, "Usage: testarena <build|verify|scan|research> <config.json> --data-dir <directory> [--game-dir <directory>]");
            string game = Environment.GetEnvironmentVariable("ELDEN_RING_DIR") is { Length: > 0 } erDir ? erDir : @"E:\SteamLibrary\steamapps\common\ELDEN RING\Game";
            for (int i = 2; i < args.Length; i += 2)
            {
                Require(i + 1 < args.Length, "Missing option value");
                switch (args[i])
                {
                    case "--data-dir": DataDir = Path.GetFullPath(args[i + 1]); break;
                    case "--game-dir": game = Path.GetFullPath(args[i + 1]); break;
                    default: throw new ArgumentException("Unknown option: " + args[i]);
                }
            }
            Require(DataDir.Length > 0, "--data-dir is required");
            // This task's outputs must remain in the assigned root, even with an alternate config path.
            string repository = FindRepository();
            string assigned = Path.Combine(repository, "er-data", "test_arena");
            Require(IsInside(DataDir, assigned), "Output must stay in the exclusive er-data/test_arena root: " + assigned);
            outputAuthorized = true;
            Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);
            string oodle = Path.Combine(game, "oo2core_6_win64.dll");
            Require(File.Exists(oodle), "Required game's Oodle DLL is missing: " + oodle);
            Oodle.Oodle6Ptr = System.Runtime.InteropServices.NativeLibrary.Load(oodle);
            Config config = JsonSerializer.Deserialize<Config>(File.ReadAllText(args[1]), Json) ?? throw new InvalidDataException("Empty config");
            config.Validate();
            Directory.CreateDirectory(DataDir);
            switch (args[0])
            {
                case "build":
                    var scan = Corpus.Scan(config);
                    Arena.Build(config, args[1]);
                    Verification.Verify(config, scan);
                    break;
                case "verify": Verification.Verify(config, Corpus.Scan(config)); break;
                case "scan": Corpus.Scan(config); break;
                case "research": Evidence.Write(config); break;
                default: throw new ArgumentException("Unknown command: " + args[0]);
            }
            return 0;
        }
        catch (Exception exception)
        {
            if (outputAuthorized && args[0] is "build" or "verify")
                WriteJson("verify-report.json", new { Status = "FAIL", Error = exception.Message, Command = args[0] });
            Console.Error.WriteLine("FAIL: " + exception.Message);
            if (Environment.GetEnvironmentVariable("TESTARENA_DEBUG") == "1") Console.Error.WriteLine(exception);
            return 1;
        }
    }

    internal static string FindRepository()
    {
        for (var directory = new DirectoryInfo(AppContext.BaseDirectory); directory != null; directory = directory.Parent)
            if (File.Exists(Path.Combine(directory.FullName, "tools", "testarena", "testarena.csproj"))) return directory.FullName;
        throw new InvalidDataException("Cannot locate the repository containing tools/testarena");
    }

    internal static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidDataException(message);
    }

    internal static bool IsInside(string path, string root) =>
        Path.GetFullPath(path).Equals(Path.GetFullPath(root), StringComparison.OrdinalIgnoreCase) ||
        Path.GetFullPath(path).StartsWith(Path.TrimEndingDirectorySeparator(Path.GetFullPath(root)) + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase);

    internal static string Output(string relative)
    {
        string path = Path.GetFullPath(Path.Combine(DataDir, relative));
        Require(IsInside(path, DataDir), "Output path escapes exclusive root");
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        return path;
    }

    internal static string Original(string relative)
    {
        string root = Path.Combine(DataDir, "originals");
        string path = Path.GetFullPath(Path.Combine(root, relative.TrimStart('/').Replace('/', Path.DirectorySeparatorChar)));
        Require(IsInside(path, root), "Input path escapes originals directory");
        Require(File.Exists(path), "Missing vanilla input: " + path);
        return path;
    }

    internal static string MapPath(string map) => $"map/mapstudio/{map}.msb.dcx";
    internal static string EventPath(string map) => $"event/{map}.emevd.dcx";
    internal static void WriteJson(string path, object value) => File.WriteAllText(Output(path), JsonSerializer.Serialize(value, value.GetType(), Json) + "\n", new UTF8Encoding(false));
    internal static string Snapshot(object value) => JsonSerializer.Serialize(value, value.GetType(), Json);
    internal static string Sha256(string path) => Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(File.ReadAllBytes(path))).ToLowerInvariant();

    sealed class ShapeConverter : JsonConverter<MSB.Shape>
    {
        public override MSB.Shape Read(ref Utf8JsonReader reader, Type type, JsonSerializerOptions options) => throw new NotSupportedException();
        public override void Write(Utf8JsonWriter writer, MSB.Shape value, JsonSerializerOptions options)
        {
            writer.WriteStartObject();
            writer.WriteString("Type", value.GetType().Name);
            writer.WritePropertyName("Data");
            JsonSerializer.Serialize(writer, value, value.GetType(), options);
            writer.WriteEndObject();
        }
    }
}
