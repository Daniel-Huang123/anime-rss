// ============================================================
//  Anime Watch Tracker - PotPlayer AngelScript
//  只记录媒体库目录下的视频播放，写入 potplayer_plays.txt
//  安装方法：将此文件放进 PotPlayer 扩展目录，勾选启用
// ============================================================

// ★ 与 config.yaml 的 save_path 保持一致
const string MEDIA_ROOT = "C:\\Users\\Danielove\\Desktop\\番";
const string LOG_FILE   = "C:\\Users\\Danielove\\Desktop\\番\\anime-rss\\potplayer_plays.txt";

// ── 路径在媒体库内？（大小写不敏感）────────────────────────
bool InMediaRoot(const string &in path)
{
    if (path.length() < MEDIA_ROOT.length()) return false;
    string prefix = path.substr(0, MEDIA_ROOT.length());
    // toLower() 做大小写不敏感比较
    return prefix.toLower() == MEDIA_ROOT.toLower();
}

// ── 是视频文件？ ────────────────────────────────────────────
bool IsVideo(const string &in path)
{
    if (path.length() < 4) return false;
    string ext = path.substr(path.length() - 4).toLower();
    return ext == ".mkv" || ext == ".mp4" || ext == ".avi"
        || ext == ".mov" || ext == ".ts " || ext == "m2ts";
}

// ── PotPlayer 打开文件时触发 ────────────────────────────────
void OnOpen()
{
    string mrl = GetMRL();
    if (mrl.length() == 0) return;

    // 忽略网络流（含 :// 的字符串）
    if (mrl.findFirst("://") >= 0) return;

    // 统一路径分隔符
    string path = mrl.replace("/", "\\");

    // 不在媒体库 / 不是视频文件 → 跳过
    if (!InMediaRoot(path)) return;
    if (!IsVideo(path)) return;

    // 追加写入日志（一行一个路径）
    file f;
    if (f.open(LOG_FILE, "a") == 0)
    {
        f.writeString(path + "\n");
        f.close();
    }
}
