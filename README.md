# 桌面网速时钟 (netspeed-widget)

一款 Windows 桌面悬浮窗工具，显示实时时钟 + 上下行网速，支持拖拽、颜色自定义、透明度调节、开机自启动。

## 效果预览

<!-- 截图示例（以后替换） -->
```
┌──────────────────┐
│  14:23:45        │
│  2026年07月07日 星期二 │
│  ↑ 1.2 MB/s    ↓ 3.4 MB/s │
└──────────────────┘
```

## 功能

- ⏰ **大字体数字时钟**（HH:MM:SS，自动校时）
- 📅 **日期 + 星期显示**
- 📶 **实时网速监控**（上行↑ / 下行↓，自动合并所有网卡）
- 🖱️ **鼠标拖拽定位**
- 🎨 **右键菜单**：更改颜色、调节透明度、开机自启动、关于
- 🪟 **鼠标穿透模式**（开发中）

## 系统要求

- Windows 7 / 10 / 11
- Python 3.8+（仅脚本运行方式，详见下方）

## 快速使用

### 方式一：直接下载 exe（推荐）

从 [Releases](https://github.com/ok0735/netspeed-widget/releases) 下载最新版 `netspeed.exe`，双击运行即可。

### 方式二：源码运行

```bash
# 1. 克隆仓库
git clone https://github.com/ok0735/netspeed-widget.git
cd netspeed-widget

# 2. 安装依赖（仅 psutil 需要安装）
pip install psutil

# 3. 运行
pythonw desktop_widget.pyw
```

也可双击 `启动桌面时钟.bat` 或 `desktop_widget.ps1` 一键启动。

### 打包 exe

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --icon=netspeed.ico --name=netspeed desktop_widget.pyw
# 产物在 dist/netspeed.exe
```

## 设置

程序首次运行会在同目录生成 `widget_settings.json`，可手动修改：

```json
{
    "color": "#00FFAA",
    "opacity": 0.85,
    "auto_start": false,
    "x": 200,
    "y": 100
}
```

> **注意**：`widget_settings.json` 仅本地使用，不上传到仓库。

## 项目结构

```
netspeed/
├── desktop_widget.pyw      # 主程序（源码）
├── gen_icon.py             # 图标生成脚本
├── netspeed.ico            # 程序图标
├── netspeed.png            # 图标 PNG
├── desktop_widget.ps1      # PowerShell 启动脚本
├── 启动桌面时钟.bat        # 批处理启动脚本
├── releases/               # 预编译 exe 下载
│   └── v1.0.0/
│       └── netspeed.exe
├── README.md
├── LICENSE
└── .gitignore
```

## 技术栈

- **语言**：Python 3.10+
- **GUI**：tkinter（标准库）
- **监控**：psutil
- **打包**：PyInstaller

## 开源协议

[MIT](LICENSE)

## 作者

- **ok0735** — [GitHub](https://github.com/ok0735)
