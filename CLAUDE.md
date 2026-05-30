# anime-rss 寮€鍙戣鑼?
## 1. 杩愯涓庢祴璇?
- 鎵€鏈?Python 鐩稿叧鍛戒护缁熶竴浣跨敤 `uv`銆?- 鎺ㄨ崘鍛戒护锛?  - `uv run python -m pytest tests/ -q`
  - `uv run ruff check <files>`

## 2. 鍘嬬缉鍖呭鐞?
- 鎵€鏈夊帇缂╁寘锛坄.zip` / `.tar.gz` / `.rar` 绛夛級缁熶竴浣跨敤 **Bandzip** 瑙ｅ帇銆?- 涓嶄娇鐢ㄥ懡浠よ瑙ｅ帇宸ュ叿锛坄unzip` / `tar` / `7z`锛夈€?
## 3. 鎵撳寘

- PyInstaller 鎵撳寘鍛戒护锛?  - `uv run --group gui --group dev pyinstaller --noconfirm --clean zhuifanji.spec`
- 浜х墿鐩綍锛歚dist/zhuifanji`

## 4. 杩愯鏃舵暟鎹洰褰?
- dev 妯″紡锛氳繍琛屾椂鏁版嵁浠嶅湪椤圭洰鏍圭洰褰曘€?- frozen/exe 妯″紡锛氳繍琛屾椂鏁版嵁鍦?`%APPDATA%\\zhuifanji`銆?- 鍚姩鏃朵細浠庢棫 exe 鐩綍杩佺Щ缂哄け鏁版嵁鍒?`%APPDATA%\\zhuifanji`锛屼笉浼氳鐩栧凡瀛樺湪鏁版嵁銆?- 杩愯鏃舵暟鎹寘鎷細
  - `config.yaml`
  - `state.json`
  - `watch_history.json`
  - `potplayer_plays.txt`
  - `.mikan_cache.json`
  - `.pending_checks.json`
  - `crash.log`
  - `.cover_cache/`
  - `assets/covers/`

## 5. GUI 绾跨▼绾﹀畾

- 鍚庡彴浠诲姟浣跨敤 `gui/qt/workers.py::Worker`锛坄QThreadPool`锛夈€?- 缁撴灉閫氳繃 signal 鍥炰富绾跨▼澶勭悊銆?- 涓嶅湪 worker 绾跨▼鐩存帴鎿嶄綔 Qt 鎺т欢銆?
## 6. 缂撳瓨涓庣姸鎬佸啓鍏?
- 灏侀潰/鐣崟浼樺厛璧扮紦瀛橈紝缃戠粶璇锋眰鍦ㄥ悗鍙拌ˉ榻愩€?- `state.json` 鐨勫啓鍏ヤ繚鎸佷覆琛岋紝閬垮厤骞跺彂鍐欏鑷存崯鍧忋€?
## 7. scrapling 鍏煎

- 褰撳墠浣跨敤 `scrapling 0.4.x`銆?- `Selector` 浠呬娇鐢?`.css()`锛堣繑鍥炲垪琛級锛屼笉瑕佷娇鐢?`.css_first()`銆?
## 8. 鍙戝竷绾﹀畾锛堣嚜鏇存柊渚濊禆锛?
- 姣忎釜妗岄潰鐗?release 蹇呴』涓婁紶锛?  - `anime-rss-vX.Y.Z-windows-x64.zip`
  - 鍚屽悕 `.sha256` 鏂囦欢

