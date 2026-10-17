# 晶粒尺寸分析（Grain Size Analyzer）

面向 SEM **取向衬度**图（ESD1 等）的晶粒尺寸统计工具。

输入一批电镜图，逐图独立标定（nm/px），分割晶界，剔除不可分辨的薄片和巨块，
输出逐颗晶粒数据、晶界叠加图、着色图和分布图表。

方法刻意偏保守：低于可分辨下限的结构一律判为"不可分辨"并排除，
**不会并入邻居**。因此报告的中位粒径是偏保守（略偏大）的估计。

## 功能

- **逐图标定**：TIFF 私有标签 34118 / 自动识别的比例尺条 / HFW / 手动 nm/px，四级回退。
- **自动裁掉底部信息栏**（高度自动检测，不写死）。
- **均值漂移 + 分水岭分割**，种子取 h-maxima ∪ h-minima，避免漏掉暗晶粒。
- **不可分辨区剔除**：宽度 < 3 px 的薄片、以及比任何晶粒都大的连通块，均置空。
- **团簇模式**（可选）：统计表面亮球状特征。
- 输出 CSV、叠加图、着色图、4 张分布图表和 Markdown 报告。

## 安装

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
```

Python 3.10–3.13，OpenCV 用 headless 版（不需要图形界面库）。

## 快速开始

```bash
python scripts/run_grain.py --input ./images --output ./results
```

如果图里有标签 34118，不需要任何标定参数。否则：

```bash
# 已知比例尺标称长度（自动在底部信息栏里找条）
python scripts/run_grain.py -i ./images --bar-um 1.0

# 已知水平视场宽度
python scripts/run_grain.py -i ./images --hfw-um 20.7

# 所有图共用一个值
python scripts/run_grain.py -i ./images --nm-per-px 8.26
```

Windows 下也可以用 `run.bat -i .\images -o .\results`。

## 标定顺序

1. `--nm-per-px`（显式覆盖）
2. TIFF 标签 34118 第 1 项（自动判断单位是 m / µm / nm）
3. `--bar-um` + 自动检测比例尺条长度
4. `--hfw-um`
5. 以上都不成立 → 拒绝该图，**绝不猜**

每张图实际用的标定来源会写进 `summary.csv` 和 `report.md`。

## 输出

```
01_enhanced/    去噪 + 增强图
02_plateaus/    均值漂移台阶图（晶界最清楚）
03_overlay/     增强图 + 红色晶界线   ← 重点核对
04_colored/     每颗晶粒随机着色
05_csv/         <样品>_grains.csv、summary.csv、_diameters.json
06_charts/      直方图、分布折线、累积曲线、均值-中位对比
report.md       标定表、结果、警告
```

逐颗晶粒字段：面积、等效圆直径、长轴/短轴、长宽比、内切宽度、是否接触边缘、灰度均值/标准差。

主统计只使用**不接触图像边缘**的晶粒（被裁掉一部分的晶粒会偏小）。

## 质量检查

报告会标出：

- 薄片剔除面积占比 > 15%；
- 已分析面积 < 50%；
- 噪声 σ > 6 灰阶；
- 有效晶粒数 < 30。

这些是警告不是错误。被警告的结果仍可使用，但必须连同警告一起汇报。

## 限制

- 只适用于**取向衬度**图（晶粒靠亮度差异区分）；表面形貌图分不准。
- 可分辨下限约 **3–4 px**，更细的结构被剔除。正确做法是提高放大倍数，而不是调低阈值。
- 表面亮球是**生长团簇，不是晶粒**。请用 `--mode cluster` 单独统计，两种尺寸不可混比。
- 分割是半自动的：必须打开 `03_overlay/` 目视核对。红边贴合灰度台阶才对；
  若边界穿过视觉上均匀的晶粒内部，就是过分割。
- 弱衬度图（噪声与晶界台阶同量级）的绝对数值可信度较低。

## 团簇模式

```bash
python scripts/run_grain.py -i ./surface_images --mode cluster --nm-per-px 76.9
```

顶帽变换 → 高斯平滑 → 局部极大值。输出计数、按总面积折算的等效间距，
以及一张标点图供目视核对。**这个模式测的不是晶粒。**

## 演示

仓库不含任何实验数据。用脚本生成合成图：

```bash
python scripts/make_demo.py
python scripts/run_grain.py -i examples/demo_input --nm-per-px 8.0
```

合成晶粒图里画了一根 1 µm 比例尺条，也可以改用 `--bar-um 1.0` 来演示自动识条。

## 测试

```bash
python tests/test_smoke.py
# 或者装了 pytest 的话
python -m pytest tests/ -q
```

冒烟测试会生成合成图，跑完两种模式，检查 CSV、JSON、叠加图和图表。

## 作为 agent skill 使用

本仓库同时是一个可移植的 agent skill：`SKILL.md` 说明了何时调用、如何标定、
跑完要检查什么、报告时必须附带哪些口径。把整个目录放进 agent 的用户级
skills 目录即可自动加载；脚本本身自包含，也可以完全不经过 skill 层直接用命令行。

## 一次安装两个 skill

提供了一个一键安装脚本，会同时安装本 skill 和配套的力学性能 skill：

```sh
curl -fsSL https://raw.githubusercontent.com/ArthurEccleston/grain-size-analyzer/main/install/install-skills.sh \
  | sh -s -- "$HOME/.claude/skills"
```

Windows PowerShell：

```powershell
irm https://raw.githubusercontent.com/ArthurEccleston/grain-size-analyzer/main/install/install-skills.ps1 | iex
```

给 agent 读的安装说明、手动步骤和依赖清单见
[install/AGENT_INSTALL.md](install/AGENT_INSTALL.md)。

## 许可证

MIT，见 [LICENSE](LICENSE)。
