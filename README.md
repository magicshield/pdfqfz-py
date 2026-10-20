# pdfqfz-py — 跨平台 PDF 骑缝章工具

[PDFQFZ](https://github.com/flytkgl/PDFQFZ)（Windows WinForms 版）的 Python 跨平台重写，
macOS / Windows / Linux 可用。提供 **命令行** 与 **带实时预览的图形界面** 两种用法。

功能：骑缝章（全页/奇/偶/自定义页，超页数自动分组循环）、普通定位章（点击预览定位、
随机参数）、白底转透明、不透明度、任意角度旋转、目录/文件批量、多章连盖、
光栅化合并、AES-256 加密输出（仅打印权限）、PKCS#12 数字签名（含印章外观）与签名校验。

## 安装

```bash
# 需要 Python >= 3.11（macOS Intel 用户注意 PyMuPDF 2.0 无 x86_64 wheel，已 pin <2）
python3 -m venv .venv && source .venv/bin/activate
pip install -e .            # CLI
pip install -e ".[gui,sign]"  # + GUI 与数字签名
```

## 命令行

```bash
# 目录批量盖骑缝章（递归找 *.pdf，输出到 out/）
pdfqfz stamp --dir ./合同目录 --out ./已盖章 --image 印章.png --seam all --size 40

# 指定文件 + 普通章 + 随机参数 + 加密输出
pdfqfz stamp --files a.pdf b.pdf --image 印章.png --seam odd \
    --stamp all --px 0.77 --py 0.88 --jitter \
    --encrypt-password 123456

# 数字签名（自动生成自签证书）+ 预览计划（不写盘）
pdfqfz stamp --files a.pdf --image 印章.png --stamp all --sign self --cn 张三 --dry-run

# 校验签名
pdfqfz verify 输出.pdf
```

常用参数：`--edge top|bottom|left|right`（骑缝位置边）、`--wz 50`（距边百分比）、
`--opacity 60`、`--tolerance 20`（白转透明容差）、`--rotate 15`（正角顺时针）、
`--blend merge --merge-dpi 300`（光栅化压扁）、`--multi-pass`（对已有输出再盖一层）、
`--in-source` / `--fix-str 已盖章` / `--fix-mode prefix`（就地命名）。
完整列表见 `pdfqfz stamp --help`。

## 图形界面

```bash
pdfqfz gui          # 或双击/右键"打开方式"传入 PDF：pdfqfz gui 文件1.pdf ...
```

- 左侧全部参数；右侧预览当前页并叠加印章，参数改动即时刷新。
- **骑缝章预览体现真实切条**：翻页可逐页看到该页将盖到的竖条（含超页数分组循环）。
- 印章类型为"自定义(点击定位)"时：**单击**预览图放置印章，**双击**删除该页定位。
- 骑缝章选"随意骑缝章"时：单击预览图把该页加入/移出骑缝页集合。
- "取消"按钮或 ESC 中断批量任务。

## 配置

- `~/Library/Application Support/pdfqfz/config.ini`（macOS）持久化表单参数；
  首次运行会自动迁移同目录下的旧 C# 版 `config.ini`。
- 印章图片库在 `~/Library/Application Support/pdfqfz/yz.log`（每行一个路径）。
- 任何密码（PDF 密码/证书密码）都不会写入配置。

## 与 C# 原版的行为差异（有意修正）

| # | 差异 |
|---|---|
| 1 | 修复双重缩放 bug：印章实际宽度精确等于设定 mm 值 |
| 2 | 修复"加密"后缀命名 bug（fixStr2） |
| 3 | 页数恰为每组最大分割数整数倍时不再多盖一遍（40页/20 → 20+20，原 14+13+13） |
| 4 | 执行顺序改为 盖章→合并→签名，合并模式不再抹掉签名 |
| 5 | 数字签名与加密输出互斥（同时指定会报错，原版签名会被加密作废） |
| 6 | 随机参数可 `--jitter-seed` 复现；原版每页 new Random() |
| 7 | 页面尺寸以 CropBox 为准（原版 MediaBox，扫描 PDF 章可能跑出可见区） |
| 8 | 目录模式递归同名文件输出镜像子目录，不再互相覆盖 |
| 9 | 容差、白转透明开关、随机参数开关持久化；证书密码不持久化（原版明文落盘） |
| 10 | 正角=顺时针（与 GDI+ 视觉一致）；随机角度旋转围绕章心（原版绕左下角） |
| 11 | 单页文件跳过骑缝时输出明确提示（原版静默） |

保留的原版行为：单页文件不盖骑缝、px/py 为"自由区(页面-印章)"分数、不透明度为
覆盖语义、切条规则（首条 1/3 宽 + 均分 + 末条吸收余数）。改进：预览现已体现
骑缝真实切条（原版只叠加整章）。

## 开发

```bash
pip install -e ".[dev]"
python -m pytest            # 76 项测试（含从 C# 版移植的行为基准）
```

模块：`core/policies.py`（纯函数策略层，对应 C# Library/*）、`core/geometry.py`（坐标/
缩放，与 PyMuPDF derotation_matrix 有交叉验证测试）、`core/imageops.py`（Pillow 管线）、
`core/pdfio.py` + `pipeline.py`（盖章/合并/加密）、`core/signing.py`（pyHanko 签名）、
`gui/`（PySide6）。

## 打包

```bash
pip install pyinstaller
pyinstaller --windowed --name pdfqfz --collect-all pymupdf \
    --collect-all pyhanko --collect-submodules PySide6 src/pdfqfz/__main__.py
```
