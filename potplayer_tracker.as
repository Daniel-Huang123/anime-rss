// ============================================================
// Anime RSS - PotPlayer playback tracker template
//
// Optional helper. Copy this file into PotPlayer's AngelScript
// extension directory and replace the two placeholder paths below.
// The app also reads PotPlayer's standard playlist history, so this
// script is only needed if you want an explicit append-only play log.
// ============================================================

// Must match qbittorrent.save_path in config.yaml.
const string MEDIA_ROOT = "D:\\Anime";

// Recommended: project-root\\potplayer_plays.txt.
const string LOG_FILE = "C:\\Path\\To\\zhuifanji\\potplayer_plays.txt";

bool StartsWithPath(const string &in path, const string &in root)
{
    string normalizedPath = path.replace("/", "\\").toLower();
    string normalizedRoot = root.replace("/", "\\").toLower();
    if (normalizedRoot.length() == 0) return false;
    if (!normalizedRoot.endsWith("\\")) normalizedRoot += "\\";
    return normalizedPath.findFirst(normalizedRoot) == 0;
}

bool IsVideo(const string &in path)
{
    string lower = path.toLower();
    return lower.endsWith(".mkv")
        || lower.endsWith(".mp4")
        || lower.endsWith(".avi")
        || lower.endsWith(".mov")
        || lower.endsWith(".wmv")
        || lower.endsWith(".flv")
        || lower.endsWith(".ts")
        || lower.endsWith(".m2ts");
}

void OnOpen()
{
    string mrl = GetMRL();
    if (mrl.length() == 0) return;
    if (mrl.findFirst("://") >= 0) return;

    string path = mrl.replace("/", "\\");
    if (!StartsWithPath(path, MEDIA_ROOT)) return;
    if (!IsVideo(path)) return;

    file f;
    if (f.open(LOG_FILE, "a") == 0)
    {
        f.writeString(path + "\n");
        f.close();
    }
}
