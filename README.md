# 超级特摄大战2001 · 简体中文汉化

《超级特摄大战2001》（Super Tokusatsu Taisen 2001，PS1，SLPS-02863）简体中文机翻汉化源码，由 **ezmbles（GitHub: scholarsblip）**维护，欢迎校对、术语修正和实机测试。

本项目基于 [retro-trans/Super-Tokusatsu-Taisen-2001](https://github.com/retro-trans/Super-Tokusatsu-Taisen-2001) 的英文翻译与逆向工具。上游由 **binhlt0402 / retro-trans** 主持；原说明完整保存在 [README.upstream.md](README.upstream.md)。中文主要从已修正的英文参考机器翻译，并做人物名、特摄作品术语及界面修正，尚未经完整人工逐句校对。

## 当前版本：0.2.5

| 内容 | 覆盖及验证 |
| --- | --- |
| 剧情、战斗台词、图鉴、数据库和可提取界面 | 21,508 个文本单元，41,437 个原盘坐标 |
| 字体 | 四位平面中文点阵字体，17 个原生字体资源；保留原生图标 |
| 图片界面 | 100 个目标，含 90 张关卡标题卡 |
| 影片 | 28/74 段加入中文覆盖字幕；沿用已识别的 71 段字幕，未重新听写所有语音 |
| 运行检查 | 冷启动进入首场战斗通过；字体与调色板检查通过；补丁解码回环通过 |

**质量说明：**这是可继续改进的机器翻译测试版。未完成全流程、所有分支及自然解锁后的完整图鉴验证，部分名称和台词仍需校对。EVENT230 被原文字遮挡的背景使用近似重建；源码只保存稀疏修复差分，由使用者的原盘恢复其余图像。历史版本和详细修正在 [中文 CHANGELOG](work/translation/zh_CN/CHANGELOG.md)。

本仓库提供代码、中文目标文本、来源校验索引和字体许可。**不提供游戏镜像、BIOS、原始日文剧本或模拟器存档。**构建需要自行准备匹配的原版日文光盘镜像。

## 从原盘构建

需要 Python **3.11+**。已验证环境为 Python 3.12.14、numpy 2.3.5、Pillow 12.3.0 / FreeType 2.14.3。不同字体渲染库版本可能影响位图；若追求一致结果，请使用这些版本。

```sh
python -m venv .venv
# macOS / Linux
source .venv/bin/activate
python -m pip install -r requirements-zh.txt
```

在 Windows 使用 `.venv\Scripts\activate`。以下 `original.bin` 必须是单轨 MODE2/2352 原版：

- 大小：`725316816` 字节
- SHA-256：`219d9c4f64caf670b5e400612fa19677ed9a3f59a7ebdb72c12c425412795465`

先检查计划，再实际初始化。初始化从原盘提取本地数据、重建带校验的输入，并安装仓库自带的授权字体到 `incoming/`；不改写原盘。

```sh
python tools/setup_zh_public.py --source-bin /path/to/original.bin
python tools/setup_zh_public.py --source-bin /path/to/original.bin --write
python tools/build_zh_full.py 0.2.5 --source-bin /path/to/original.bin --preflight
python tools/build_zh_full.py 0.2.5 --source-bin /path/to/original.bin
python tools/build_zh_full.py 0.2.5 --source-bin /path/to/original.bin --write
```

构建器默认只准备资源和报告；`--write` 才生成 `work/output/STT2001_ZH_v0.2.5.bin/.cue`。核心构建包含文字、字体、图片界面，影片随后单独处理。详见 [初始化与来源验证](docs/public_source_bootstrap.md)。

## 影片字幕（可选）

需另装 PyAV 及 [jPSXdec 2.1 beta](https://github.com/m35/jpsxdec)、Java 17+。这些外部运行时不随源码分发。配置 `STT2001_JPSXDEC_JAR`（JAR 绝对路径），必要时配置 `STT2001_JAVA` 或 `JAVA_HOME`。

```sh
python -m pip install -r requirements-zh-movies.txt
python tools/zh_movie_insert.py dependencies
python tools/zh_movie_insert.py extract --baseline /path/to/original.bin --dry-run
python tools/zh_movie_insert.py extract --baseline /path/to/original.bin
python tools/zh_movie_insert.py encode
python tools/zh_movie_insert.py validate
python tools/zh_movie_insert.py patch --path work/output/STT2001_ZH_v0.2.5.bin --dry-run
python tools/zh_movie_insert.py patch --path work/output/STT2001_ZH_v0.2.5.bin
```

影片插入会修改上述新构建的输出，先保留核心 BIN 副本以供 `verify-disc --baseline <core-copy> --path <final-bin>` 比对。使用者原盘、既有基线受保护；不要把唯一副本用作输出。

| 0.2.5 构建阶段 | 参考 BIN SHA-256 |
| --- | --- |
| 文字、字体与图片核心 | `2e6ad5a1a3116fcee9ad85a3f8160764b4b1a56901b5518442594eecc2d15527` |
| 核心加影片字幕（本地交付版） | `775632e181373ba49a0d6f8132cb2e6d8aaccc3fe40743713af99087f7e4aba5` |

## 参与改进

- [中文目标文本](work/translation/zh_CN/translations.zh_CN.json)：按 `uid` 校对正文和说话者。
- [中文界面、图片与影片清单](work/translation/zh_CN/full_ui/)：修改显示文字，保留坐标、时间与资源 ID。
- [人物名与术语](work/glossary/zh_CN_canonical_terms.flat.json)：特摄作品译名优先，存疑译法请附来源。
- [贡献说明](CONTRIBUTING.md)：校对格式、控制码约束和测试要求。

提交 Issue 或 Pull Request 时请说明章节、战斗场景、UID（如有）、当前文字与建议译法。若能提供截图或复现步骤更好。不要上传 ROM、BIOS、原始日文对白批次或存档转储。

## 署名与使用条件

本项目是非官方爱好者翻译，游戏 © BANPRESTO 2001，角色与作品归各自权利人所有。保留上游“不出售、不收费、不设广告下载门槛”的要求。上游未提供覆盖全仓库的正式许可证，本 fork 不为其重新授权。Cubic11、Misaki 字体及其他依赖按各自许可使用，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

中文机翻、术语处理、字体和构建工作由 ezmbles 借助 Google Translate 与 OpenAI Codex 完成。欢迎通过公开的校对与测试继续改善。
