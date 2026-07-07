# -*- coding: utf-8 -*-
#! python3.10
"""
桌面悬浮时钟 + 实时网速 小工具
功能：
  - 大字体时间显示 (HH:MM:SS)
  - 年月日星期显示
  - 🖥 CPU + 内存监控
  - 🍅 番茄钟：25分钟专注 + 5分钟休息，自动循环
  - 实时网速上下行 (↑↓ KB/s / MB/s) — 自动合并所有网卡
  - ⏰ 闹钟提醒（支持自定义MP3/WAV铃声）
  - ⚡ 一键释放内存 / 清理系统临时文件
  - 🗂 系统托盘（关闭时最小化到托盘）
  - 鼠标拖动定位
  - 右键菜单：自定义颜色、开机自启动、鼠标穿透切换
  - 半透明/不透明调节
"""

import tkinter as tk
from tkinter import colorchooser, messagebox, filedialog
import tkinter.font as tkfont
import datetime
import psutil
import os
import sys
import json
import time
import socket
import struct
import threading
import webbrowser
import shutil
import tempfile
import ctypes
import winsound
from pathlib import Path

# ── 第三方（系统托盘） ─────────────────────────────────────
try:
    import pystray
    from PIL import Image as PILImage
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False


# ══════════════════════════════════════════════════════════════
#  Windows API 封装
# ══════════════════════════════════════════════════════════════

kernel32 = ctypes.windll.kernel32
winmm    = ctypes.windll.winmm

def _empty_working_set():
    """释放当前进程的物理内存（将工作集换出到虚拟内存）"""
    try:
        # GetCurrentProcess 返回 -1 (伪句柄)
        PROCESS_QUERY_INFORMATION = 0x0400
        PROCESS_SET_QUOTA = 0x0100
        handle = kernel32.OpenProcess(
            PROCESS_QUERY_INFORMATION | PROCESS_SET_QUOTA,
            False, os.getpid()
        )
        if handle:
            kernel32.SetProcessWorkingSetSize(handle, ctypes.c_size_t(-1),
                                              ctypes.c_size_t(-1))
            kernel32.CloseHandle(handle)
            return True
    except Exception:
        pass
    return False


def _play_mp3(filepath):
    """用 Windows MCI 播放 MP3（异步，不阻塞）"""
    try:
        # 先关闭之前的
        winmm.mciSendStringW('close alarm_sound', None, 0, 0)
        cmd = f'open "{filepath}" type mpegvideo alias alarm_sound'
        winmm.mciSendStringW(cmd, None, 0, 0)
        winmm.mciSendStringW('play alarm_sound', None, 0, 0)
        return True
    except Exception:
        return False


def _stop_mp3():
    """停止 MCI 播放"""
    try:
        winmm.mciSendStringW('stop alarm_sound', None, 0, 0)
        winmm.mciSendStringW('close alarm_sound', None, 0, 0)
    except Exception:
        pass


def _play_builtin_beep(pattern="gentle"):
    """内置提示音（更长更温和）"""
    if pattern == "gentle":
        winsound.Beep(392, 600)
        time.sleep(0.08)
        winsound.Beep(523, 600)
        time.sleep(0.08)
        winsound.Beep(659, 800)
    elif pattern == "beep":
        winsound.Beep(600, 400)
        winsound.Beep(800, 500)
    elif pattern == "chime":
        winsound.Beep(523, 300)
        winsound.Beep(659, 300)
        winsound.Beep(784, 500)
    elif pattern == "alarm":
        for _ in range(4):
            winsound.Beep(660, 250)
            time.sleep(0.12)


# ══════════════════════════════════════════════════════════════

class OutlinedLabel(tk.Canvas):
    """带白色描边的文字标签，支持 .config(text=...) / .config(fg=...)"""
    def __init__(self, master, text="", font=None, fg="white", bg="black",
                 outline_width=2, cursor="hand2"):
        self._text = text
        self._font = font or ("Microsoft YaHei", 12)
        self._fg = fg
        self._outline = outline_width

        f = tkfont.Font(font=self._font)
        self._fw = f.measure(text) + outline_width * 4 + 4
        self._fh = f.metrics("linespace") + outline_width * 2 + 4

        super().__init__(master, width=self._fw, height=self._fh,
                         bg=bg, highlightthickness=0, bd=0,
                         cursor=cursor)
        self._redraw()

    def config(self, **kwargs):
        changed = False
        if 'text' in kwargs:
            self._text = kwargs.pop('text')
            changed = True
        if 'fg' in kwargs:
            self._fg = kwargs.pop('fg')
            changed = True
        if 'font' in kwargs:
            self._font = kwargs.pop('font')
            changed = True
        if changed:
            f = tkfont.Font(font=self._font)
            self._fw = f.measure(self._text) + self._outline * 4 + 4
            self._fh = f.metrics("linespace") + self._outline * 2 + 4
            self.configure(width=self._fw, height=self._fh)
        super().config(**kwargs)
        if changed:
            self._redraw()

    configure = config

    def _redraw(self):
        self.delete("all")
        if not self._text:
            return
        cx = self.winfo_width() / 2
        cy = self.winfo_height() / 2
        if cx < 2 or cy < 2:
            cx = self._fw / 2
            cy = self._fh / 2

        ow = self._outline
        for dx in (-ow, 0, ow):
            for dy in (-ow, 0, ow):
                if dx == 0 and dy == 0:
                    continue
                self.create_text(cx + dx, cy + dy, text=self._text,
                                 font=self._font, fill="white", anchor="center")
        self.create_text(cx, cy, text=self._text, font=self._font,
                         fill=self._fg, anchor="center")


# ── 路径 ──────────────────────────────────────────────────────
if getattr(sys, 'frozen', False):
    SCRIPT_DIR = os.path.dirname(sys.executable)
else:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

SETTINGS_FILE = os.path.join(SCRIPT_DIR, "widget_settings.json")
PYTHON_PATH   = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
if not os.path.isfile(PYTHON_PATH):
    PYTHON_PATH = sys.executable

# 默认提醒铃声为内置音

# 清理旧的快捷方式自启动（已废弃）
OLD_STARTUP_DIR = os.path.join(
    os.environ.get("APPDATA", ""),
    r"Microsoft\Windows\Start Menu\Programs\Startup"
)
OLD_STARTUP_LNK = os.path.join(OLD_STARTUP_DIR, "桌面时钟.lnk")
if os.path.isfile(OLD_STARTUP_LNK):
    try:
        os.remove(OLD_STARTUP_LNK)
    except OSError:
        pass

# ── 默认设置 ─────────────────────────────────────────────────
DEFAULT_SETTINGS = {
    "color": "#FF3333",
    "opacity": 0.85,
    "auto_start": False,
    "x": 200,
    "y": 100,
    # 番茄钟
    "pomo_duration": 25,
    "pomo_break": 5,
    "pomo_long_break": 15,
    "pomo_count_target": 4,
    # 闹钟
    "alarms": [],
    "alarm_sound": "gentle",     # 内置温和提示音
    # 系统
    "show_sys_info": True,       # 是否显示CPU/内存行
    # 显示
    "font_scale": 1.0,           # 整体字号缩放（0.5x ~ 2.0x）
    "pomo_visible": True,        # 是否显示番茄钟
}


# ══════════════════════════════════════════════════════════════
class DesktopWidget:
    # ── 初始化 ──────────────────────────────────────────────
    def __init__(self):
        # 单实例
        try:
            cur_pid = os.getpid()
            for p in psutil.process_iter(['pid', 'name']):
                if p.info['pid'] == cur_pid:
                    continue
                if p.info['name'] and 'netspeed' in p.info['name'].lower():
                    try:
                        p.kill()
                        p.wait(timeout=1)
                    except Exception:
                        pass
        except Exception:
            pass

        self.root = tk.Tk()
        self.root.title("桌面时钟")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)

        # 设置
        self.settings = DEFAULT_SETTINGS.copy()
        self.load_settings()

        # 网速追踪
        self.prev_recv = 0
        self.prev_sent = 0
        self.prev_ts   = 0

        # NTP 时间偏移
        self.ntp_offset = 0
        self.ntp_updated = False

        # 番茄钟状态
        self.pomo_state = "idle"        # idle / focus / break / long_break
        self.pomo_remaining = 0
        self.pomo_count = 0
        self.pomo_running = False

        # 闹钟状态（避免重复触发）
        self._last_alarm_minute = ""

        # 系统托盘
        self._tray_icon = None

        self._build_ui()
        self._apply_font_scale()
        self.root.resizable(False, False)

        # 拦截关闭按钮 → 最小化到托盘（如果有托盘支持）
        if HAS_TRAY:
            self.root.protocol("WM_DELETE_WINDOW", self._minimize_to_tray)
            # 启动系统托盘
            self.root.after(500, self._start_tray)

        # NTP 校时
        threading.Thread(target=self._sync_ntp_time, daemon=True).start()

        # 定时器
        self.update_clock()
        self.update_system_info()
        self.update_network()
        self._pomo_tick()
        self._alarm_check()

        # 开机自启动同步
        if self.settings.get("auto_start", False):
            if not self._is_auto_start():
                self._enable_auto_start()

        self.root.after(3000, self._ensure_visible)
        self.root.mainloop()

    def _ensure_visible(self):
        """开机启动后，随机位置显示窗口"""
        import random
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        rx = random.randint(50, max(50, sw - 400))
        ry = random.randint(50, max(50, sh - 300))
        self.root.geometry(f"+{rx}+{ry}")
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.focus_force()

    # ── UI 构建 ────────────────────────────────────────────
    def _build_ui(self):
        self.root.configure(bg="black")
        self.root.attributes("-transparentcolor", "black")
        self.root.attributes("-alpha", self.settings["opacity"])

        self.main_frame = tk.Frame(self.root, bg="black")
        self.main_frame.pack(padx=24, pady=12)

        scale = self.settings.get("font_scale", 1.0)
        time_size   = int(48 * scale)
        date_size   = int(24 * scale)
        sys_size    = int(20 * scale)
        pomo_size   = int(20 * scale)
        net_size    = int(24 * scale)

        # ----- 时间 -----
        self.time_label = OutlinedLabel(
            self.main_frame,
            text="00:00:00",
            font=("Consolas", time_size, "bold"),
            fg=self.settings["color"], bg="black", cursor="hand2",
        )
        self.time_label.pack(pady=(2, 0))

        # ----- 年月日星期 -----
        self.date_label = OutlinedLabel(
            self.main_frame,
            text="----年--月--日 星期-",
            font=("Microsoft YaHei", date_size, "bold"),
            fg=self.settings["color"], bg="black",
        )
        self.date_label.pack(pady=(2, 1))

        # ----- 🖥 CPU + 内存 -----
        self.sys_label = OutlinedLabel(
            self.main_frame,
            text="🖥 CPU --%   RAM --/-- GB",
            font=("Consolas", sys_size, "bold"),
            fg=self.settings["color"], bg="black",
        )
        self.sys_label.pack(pady=(1, 1))

        # ----- 🍅 番茄钟 -----
        self.pomo_label = OutlinedLabel(
            self.main_frame,
            text="🍅 未开始",
            font=("Microsoft YaHei", pomo_size, "bold"),
            fg=self.settings["color"], bg="black",
        )
        self.pomo_label.pack(pady=(1, 1))

        # ----- 网速 -----
        self.net_label = OutlinedLabel(
            self.main_frame,
            text="↑ 0.00 KB/s  ↓ 0.00 KB/s",
            font=("Consolas", net_size, "bold"),
            fg=self.settings["color"], bg="black",
        )
        self.net_label.pack(pady=(0, 2))

        # ----- 事件绑定 -----
        for w in (self.root, self.main_frame, self.time_label,
                  self.date_label, self.sys_label, self.pomo_label, self.net_label):
            self._bind_drag(w)
        self._bind_context_menu()

    # ── NTP 授时 ──────────────────────────────────────────
    def _get_ntp_time(self, server, timeout=3):
        NTP_PORT = 123
        NTP_DELTA = 2208988800
        try:
            client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            client.settimeout(timeout)
            client.sendto(b'\x1b' + 47 * b'\0', (server, NTP_PORT))
            data, _ = client.recvfrom(1024)
            if data:
                t = struct.unpack('!12I', data)[10]
                return datetime.datetime.fromtimestamp(t - NTP_DELTA)
        except Exception:
            pass
        return None

    def _sync_ntp_time(self):
        for server in ('ntp.aliyun.com', 'ntp.ntsc.ac.cn', 'time.windows.com'):
            ntp_time = self._get_ntp_time(server)
            if ntp_time:
                self.ntp_offset = (ntp_time - datetime.datetime.now()).total_seconds()
                self.ntp_updated = True
                break

    # ── 拖拽 ──────────────────────────────────────────────
    def _bind_drag(self, widget):
        widget.bind("<Button-1>",         self._drag_start)
        widget.bind("<B1-Motion>",        self._drag_move)
        widget.bind("<ButtonRelease-1>",  self._drag_stop)
        try:
            widget.config(cursor="hand2")
        except Exception:
            pass

    def _drag_start(self, event):
        self._drag_x = event.x_root - self.root.winfo_x()
        self._drag_y = event.y_root - self.root.winfo_y()

    def _drag_move(self, event):
        self.root.geometry(f"+{event.x_root - self._drag_x}"
                           f"+{event.y_root - self._drag_y}")

    def _drag_stop(self, event):
        self.settings["x"] = self.root.winfo_x()
        self.settings["y"] = self.root.winfo_y()
        self.save_settings()

    # ── 右键菜单 ──────────────────────────────────────────
    def _bind_context_menu(self):
        MENU_BG = "#F0F0F0"
        MENU_FONT = ("Microsoft YaHei", 12)
        self._menu = tk.Menu(self.root, tearoff=0, bg=MENU_BG, fg="black",
                             activebackground="#E0E0E0", activeforeground="black",
                             borderwidth=1, relief="solid", font=MENU_FONT)
        self._menu.add_command(label="更改颜色",  command=self._choose_color)
        self._menu.add_command(label="调节透明度", command=self._adjust_opacity)
        # 字号快速切换
        size_menu = tk.Menu(self._menu, tearoff=0, bg=MENU_BG, fg="black",
                            activebackground="#E0E0E0", activeforeground="black",
                            borderwidth=1, relief="solid", font=MENU_FONT)
        size_menu.add_command(label="大 100%", command=lambda: self._set_font_scale(1.0))
        size_menu.add_command(label="中  75%", command=lambda: self._set_font_scale(0.75))
        size_menu.add_command(label="小  50%", command=lambda: self._set_font_scale(0.5))
        self._menu.add_cascade(label="调节大小", menu=size_menu)
        self._menu.add_separator()

        # 开机自启动
        self._as_var = tk.BooleanVar(value=self._is_auto_start())
        self._menu.add_checkbutton(label="开机自启动",
                                   variable=self._as_var,
                                   command=self._toggle_auto_start)
        self._menu.add_separator()

        # 🍅 番茄钟
        self._pomo_visible_var = tk.BooleanVar(
            value=self.settings.get("pomo_visible", True))
        self._pomo_menu = tk.Menu(self._menu, tearoff=0, bg=MENU_BG, fg="black",
                                  activebackground="#E0E0E0", activeforeground="black",
                                  borderwidth=1, relief="solid", font=MENU_FONT)
        self._pomo_menu.add_command(label="开始专注", command=self._pomo_start_focus)
        self._pomo_menu.add_command(label="暂停",     command=self._pomo_pause)
        self._pomo_menu.add_command(label="重置",     command=self._pomo_reset)
        self._pomo_menu.add_separator()
        self._pomo_menu.add_checkbutton(label="显示番茄钟",
                                        variable=self._pomo_visible_var,
                                        command=self._toggle_pomo_visible)
        self._pomo_menu.add_separator()
        self._pomo_menu.add_command(label="设置...",  command=self._pomo_settings)
        self._menu.add_cascade(label="🍅 番茄钟", menu=self._pomo_menu)

        # ⏰ 闹钟
        self._alarm_menu = tk.Menu(self._menu, tearoff=0, bg=MENU_BG, fg="black",
                                   activebackground="#E0E0E0", activeforeground="black",
                                   borderwidth=1, relief="solid", font=MENU_FONT)
        self._alarm_menu.add_command(label="添加闹钟", command=self._alarm_add)
        self._alarm_menu.add_command(label="管理闹钟", command=self._alarm_manager)
        self._alarm_menu.add_separator()
        self._alarm_menu.add_command(label="选择铃声...", command=self._alarm_pick_sound)
        self._alarm_menu.add_command(label="测试铃声",   command=self._alarm_test_sound)
        self._menu.add_cascade(label="⏰ 闹钟", menu=self._alarm_menu)

        # ⚡ 系统工具（直接放在主菜单）
        self._menu.add_separator()
        self._menu.add_command(label="释放内存",      command=self._clean_memory)
        self._menu.add_command(label="清理临时文件",  command=self._clean_temp_files)

        # ⚡ 系统工具子菜单（仅保留 显示CPU/内存）
        self._tools_menu = tk.Menu(self._menu, tearoff=0, bg=MENU_BG, fg="black",
                                   activebackground="#E0E0E0", activeforeground="black",
                                   borderwidth=1, relief="solid", font=MENU_FONT)
        self._sv_var = tk.BooleanVar(value=self.settings.get("show_sys_info", True))
        self._tools_menu.add_checkbutton(label="显示CPU/内存",
                                         variable=self._sv_var,
                                         command=self._toggle_sys_info)
        self._menu.add_cascade(label="⚡ 系统工具", menu=self._tools_menu)

        self._menu.add_separator()
        if HAS_TRAY:
            self._menu.add_command(label="最小化到托盘", command=self._minimize_to_tray)
        self._menu.add_command(label="关于", command=self._show_about)
        self._menu.add_separator()
        self._menu.add_command(label="退出", command=self._quit)

        for w in (self.root, self.main_frame, self.time_label,
                  self.date_label, self.sys_label, self.pomo_label, self.net_label):
            w.bind("<Button-3>", self._show_menu)
            w.bind("<Button-2>", self._show_menu)

    def _show_menu(self, event):
        self._update_pomo_menu()
        self._menu.tk_popup(event.x_root, event.y_root)

    def _update_pomo_menu(self):
        items = self._pomo_menu
        if self.pomo_state == "idle":
            items.entryconfig(0, label="开始专注", state="normal")
            items.entryconfig(1, label="暂停",     state="disabled")
        elif self.pomo_state in ("focus", "break", "long_break"):
            if self.pomo_running:
                items.entryconfig(0, label="开始专注", state="disabled")
                items.entryconfig(1, label="暂停",     state="normal")
            else:
                items.entryconfig(0, label="继续",     state="normal")
                items.entryconfig(1, label="暂停",     state="disabled")

    # ── 关于 ──────────────────────────────────────────────
    def _show_about(self):
        win = tk.Toplevel(self.root)
        win.title("关于")
        win.geometry("340x210+{}+{}".format(
            self.root.winfo_x() + 80, self.root.winfo_y() + 80))
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.configure(bg="#2D2D2D")

        # 标题
        tk.Label(win, text="桌面网速时钟", fg="white", bg="#2D2D2D",
                 font=("Microsoft YaHei", 16, "bold")).pack(pady=(24, 2))

        # 分隔线
        tk.Frame(win, bg="#555", height=1).pack(fill="x", padx=50)

        # 作者
        tk.Label(win, text="作者：朱济来", fg="#AAAAAA", bg="#2D2D2D",
                 font=("Microsoft YaHei", 10)).pack(pady=(8, 0))

        # 可点击链接
        link_lb = tk.Label(win, text="ok0735 →", fg="#5B9BD5", bg="#2D2D2D",
                           cursor="hand2", font=("Microsoft YaHei", 10, "underline"))
        link_lb.pack(pady=(0, 6))
        link_lb.bind("<Button-1>", lambda e: webbrowser.open("https://github.com/ok0735"))

        # 确认按钮
        tk.Button(win, text="确定", command=win.destroy,
                  width=12, bg="#5B9BD5", fg="white",
                  activebackground="#4A8BC8", activeforeground="white",
                  relief="raised", bd=2, padx=10, pady=4,
                  font=("Microsoft YaHei", 11)).pack(pady=(8, 0))

    # ── 颜色 ──────────────────────────────────────────────
    def _choose_color(self):
        c = colorchooser.askcolor(title="选择字体颜色",
                                  color=self.settings["color"])
        if c and c[1]:
            self.settings["color"] = c[1]
            self._apply_color()
            self.save_settings()

    def _apply_color(self):
        color = self.settings["color"]
        self.time_label.config(fg=color)
        self.date_label.config(fg=color)
        self.sys_label.config(fg=color)
        self.pomo_label.config(fg=color)
        self.net_label.config(fg=color)

    # ── 透明度 ────────────────────────────────────────────
    def _adjust_opacity(self):
        HERMES = "#E8652E"
        win = tk.Toplevel(self.root)
        win.title("透明度")
        win.geometry("300x100+{}+{}".format(
            self.root.winfo_x() + 50, self.root.winfo_y() + 100))
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.configure(bg=HERMES)
        tk.Label(win, text="透明度调节", fg="white", bg=HERMES,
                 font=("Microsoft YaHei", 11)).pack(pady=(10, 5))

        slider = tk.Scale(win, from_=30, to=100, orient="horizontal",
                          length=250, bg=HERMES, fg="white",
                          troughcolor="#D4602A")
        slider.set(int(self.settings["opacity"] * 100))
        slider.pack(pady=5)

        def apply_opacity(val):
            v = int(val) / 100.0
            self.settings["opacity"] = v
            self.root.attributes("-alpha", v)
            self.save_settings()
        slider.config(command=apply_opacity)

    # ── 开机自启动 ────────────────────────────────────────
    REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
    REG_NAME = "桌面时钟"

    def _is_auto_start(self):
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.REG_KEY, 0,
                                 winreg.KEY_READ)
            try:
                val, _ = winreg.QueryValueEx(key, self.REG_NAME)
                return val and os.path.exists(val.split('"')[1] if '"' in val else val.split()[0])
            except FileNotFoundError:
                return False
            finally:
                winreg.CloseKey(key)
        except Exception:
            return False

    def _enable_auto_start(self):
        try:
            import winreg
            if getattr(sys, 'frozen', False):
                cmd = f'"{sys.executable}"'
            else:
                script = os.path.join(SCRIPT_DIR, "desktop_widget.pyw")
                if os.path.isfile(PYTHON_PATH) and os.path.isfile(script):
                    cmd = f'"{PYTHON_PATH}" "{script}"'
                else:
                    cmd = f'"{sys.executable}" "{script}"'
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.REG_KEY, 0,
                                 winreg.KEY_SET_VALUE)
            winreg.SetValueEx(key, self.REG_NAME, 0, winreg.REG_SZ, cmd)
            winreg.CloseKey(key)
        except Exception:
            pass

    def _disable_auto_start(self):
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.REG_KEY, 0,
                                 winreg.KEY_SET_VALUE)
            try:
                winreg.DeleteValue(key, self.REG_NAME)
            except FileNotFoundError:
                pass
            winreg.CloseKey(key)
        except Exception:
            pass

    def _toggle_auto_start(self):
        if self._as_var.get():
            self._enable_auto_start()
            self.settings["auto_start"] = True
        else:
            self._disable_auto_start()
            self.settings["auto_start"] = False
        self.save_settings()

    # ── 定时更新 ─────────────────────────────────────────
    def update_clock(self):
        now = datetime.datetime.now()
        if self.ntp_updated:
            now = now + datetime.timedelta(seconds=self.ntp_offset)
        self.time_label.config(text=now.strftime("%H:%M:%S"))

        weekdays = ["星期一", "星期二", "星期三", "星期四",
                     "星期五", "星期六", "星期日"]
        self.date_label.config(
            text=f"{now.year}年{now.month:02d}月{now.day:02d}日 "
                 f"{weekdays[now.weekday()]}"
        )
        self.root.after(1000, self.update_clock)

    @staticmethod
    def _fmt_speed(bps):
        if bps >= 1024 * 1024:
            return f"{bps / 1024 / 1024:.2f} MB/s"
        if bps >= 1024:
            return f"{bps / 1024:.2f} KB/s"
        return f"{bps:.0f} B/s"

    def update_network(self):
        try:
            net = psutil.net_io_counters(pernic=False)
            ts = time.time()
            if self.prev_ts > 0:
                delta = ts - self.prev_ts
                if delta > 0:
                    down = (net.bytes_recv - self.prev_recv) / delta
                    up   = (net.bytes_sent - self.prev_sent) / delta
                    self.net_label.config(
                        text=f"↑ {self._fmt_speed(up)}  ↓ {self._fmt_speed(down)}")
            self.prev_recv = net.bytes_recv
            self.prev_sent = net.bytes_sent
            self.prev_ts   = ts
        except Exception:
            self.net_label.config(text="↑ -- KB/s  ↓ -- KB/s")
        self.root.after(1000, self.update_network)

    # ── 🖥 CPU + 内存监控 ─────────────────────────────────
    def update_system_info(self):
        try:
            cpu = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory()
            used_gb = mem.used / 1024**3
            total_gb = mem.total / 1024**3
            self.sys_label.config(
                text=f"🖥 CPU {cpu:.0f}%   RAM {used_gb:.1f}/{total_gb:.0f} GB")
            self._relayout()
        except Exception:
            pass
        self.root.after(2000, self.update_system_info)

    def _toggle_sys_info(self):
        self.settings["show_sys_info"] = self._sv_var.get()
        self.save_settings()
        self._apply_font_scale()

    # ── 📐 布局重排（统一处理显示/隐藏 + 字号） ────────────

    def _relayout(self):
        """按当前显示设置重新排列所有标签行"""
        s = self.settings.get("font_scale", 1.0)
        # 全部解包
        for w in (self.time_label, self.date_label, self.sys_label,
                  self.pomo_label, self.net_label):
            w.pack_forget()
        # 按顺序重新打包
        self.time_label.pack(pady=(int(2 * s), int(1 * s)))
        self.date_label.pack(pady=(int(2 * s), int(1 * s)))
        if self.settings.get("show_sys_info", True):
            self.sys_label.pack(pady=(int(1 * s), int(1 * s)))
        if self.settings.get("pomo_visible", True):
            self.pomo_label.pack(pady=(int(1 * s), int(1 * s)))
        self.net_label.pack(pady=(int(2 * s), int(4 * s)))

    def _apply_font_scale(self):
        """按 font_scale 重新设置所有字号、显示状态，并重算窗口大小"""
        s = self.settings.get("font_scale", 1.0)
        self.time_label.config(font=("Consolas", int(48 * s), "bold"))
        self.date_label.config(font=("Microsoft YaHei", int(24 * s), "bold"))
        self.sys_label.config(font=("Consolas", int(20 * s), "bold"))
        self.pomo_label.config(font=("Microsoft YaHei", int(20 * s), "bold"))
        self.net_label.config(font=("Consolas", int(24 * s), "bold"))

        # 刷新 visibility 变量状态
        if hasattr(self, '_pomo_visible_var'):
            self._pomo_visible_var.set(self.settings.get("pomo_visible", True))
        if hasattr(self, '_sv_var'):
            self._sv_var.set(self.settings.get("show_sys_info", True))

        # 所有标签间距由 _relayout 统一处理
        self.main_frame.pack_configure(padx=int(24 * s), pady=int(12 * s))
        self._relayout()

        # 用 update() 确保完整布局后再取尺寸
        self.root.update()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        self.root.geometry(f"{w}x{h}+{self.settings['x']}+{self.settings['y']}")

    def _toggle_pomo_visible(self):
        self.settings["pomo_visible"] = self._pomo_visible_var.get()
        self.save_settings()
        self._apply_font_scale()

    def _set_font_scale(self, scale):
        """快捷设置字号大小：1.0=大 0.75=中 0.5=小"""
        self.settings["font_scale"] = scale
        self._apply_font_scale()
        self.save_settings()


    # ════════════════════════════════════════════════════════
    #  ⚡ 系统工具
    # ════════════════════════════════════════════════════════

    def _clean_memory(self):
        """一键释放物理内存（后台线程，不卡界面）"""
        messagebox.showinfo("释放内存", "正在后台释放内存，稍后会通知结果。")
        threading.Thread(target=self._clean_memory_worker, daemon=True).start()

    def _clean_memory_worker(self):
        """内存清理工作线程"""
        try:
            before_free = psutil.virtual_memory().available / 1024**3
            _empty_working_set()
            # 所有进程 EmptyWorkingSet
            try:
                for p in psutil.process_iter(['pid']):
                    try:
                        h = kernel32.OpenProcess(0x0400 | 0x0100, False, p.info['pid'])
                        if h:
                            kernel32.SetProcessWorkingSetSize(h, ctypes.c_size_t(-1),
                                                              ctypes.c_size_t(-1))
                            kernel32.CloseHandle(h)
                    except Exception:
                        pass
            except Exception:
                pass
            # 系统备用内存列表清除
            try:
                ctypes.windll.ntdll.NtSetSystemInformation(
                    0x4D, ctypes.byref(ctypes.c_int(0x02)), ctypes.sizeof(ctypes.c_int))
            except Exception:
                pass
            after_free = psutil.virtual_memory().available / 1024**3
            freed = after_free - before_free
            def show_result():
                if freed > 0.05:
                    messagebox.showinfo("释放内存",
                        f"深度清理完成！\n释放可用内存：{freed:.2f} GB\n"
                        f"可用：{before_free:.2f} GB → {after_free:.2f} GB\n"
                        f"总内存：{psutil.virtual_memory().total / 1024**3:.0f} GB")
                else:
                    messagebox.showinfo("释放内存",
                        f"内存已优化\n当前可用：{after_free:.2f} GB / "
                        f"{psutil.virtual_memory().total / 1024**3:.0f} GB")
            self.root.after(0, show_result)
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("释放内存", f"操作失败：{e}"))

    def _clean_temp_files(self):
        """扫描并深度清理临时文件（后台线程，不卡界面）"""
        messagebox.showinfo("清理临时文件", "正在后台扫描临时文件，稍后会显示结果。")
        threading.Thread(target=self._clean_temp_worker, daemon=True).start()

    def _clean_temp_worker(self):
        """磁盘清理工作线程：扫描 + 确认 + 清理"""
        windir = os.environ.get("WINDIR", "C:\\Windows")
        localappdata = os.environ.get("LOCALAPPDATA", "")
        appdata = os.environ.get("APPDATA", "")
        clean_locations = [
            (os.environ.get("TEMP", ""),                      "用户临时文件 (%TEMP%)"),
            (os.path.join(windir, "Temp"),                    "系统临时文件 (Windows\\Temp)"),
            (os.path.join(windir, "Prefetch"),                "预读取缓存 (Prefetch)"),
            (os.path.join(windir, "SoftwareDistribution", "Download"), "Windows 更新缓存"),
            (os.path.join(localappdata, "CrashDumps"),        "程序崩溃转储"),
            (os.path.join(localappdata, "D3DSCache"),         "Direct3D 缓存"),
            (os.path.join(appdata, "Microsoft", "Windows", "Recent"), "最近文档列表"),
            (os.path.join(localappdata, "Google", "Chrome", "User Data", "Default", "Cache"), "Chrome 缓存"),
            (os.path.join(localappdata, "Google", "Chrome", "User Data", "Default", "Code Cache"), "Chrome Code Cache"),
            (os.path.join(localappdata, "Microsoft", "Edge", "User Data", "Default", "Cache"), "Edge 缓存"),
            (os.path.join(appdata, "Mozilla", "Firefox", "Profiles"), "Firefox 缓存"),
        ]
        total_size = 0
        details = []
        valid_dirs = []
        for dpath, dname in clean_locations:
            if not dpath or not os.path.isdir(dpath):
                continue
            size = 0
            count = 0
            try:
                for root_dir, dirs, files in os.walk(dpath):
                    for f in files:
                        try:
                            size += os.path.getsize(os.path.join(root_dir, f))
                            count += 1
                        except Exception:
                            pass
                    if root_dir.count(os.sep) - dpath.count(os.sep) > 4:
                        dirs.clear()
                if count > 0:
                    size_mb = size / 1024**2
                    details.append(f"  {dname}：{count} 个文件，{size_mb:.1f} MB")
                    total_size += size
                    valid_dirs.append(dpath)
            except Exception:
                pass

        total_mb = total_size / 1024**2

        def confirm_and_clean():
            if total_mb < 0.1:
                messagebox.showinfo("清理临时文件", "没有需要清理的临时文件。")
                return
            msg = f"找到约 {total_mb:.1f} MB 可清理的垃圾文件：\n\n"
            msg += "\n".join(details)
            msg += "\n\n⚠️ 建议先关闭浏览器再清理。\n确定要删除吗？"
            if not messagebox.askyesno("深度磁盘清理", msg):
                return
            # 清理
            deleted_errors = [0, 0]
            def do_clean():
                for dpath in valid_dirs:
                    try:
                        for item in Path(dpath).iterdir():
                            try:
                                if item.is_file():
                                    item.unlink()
                                elif item.is_dir():
                                    shutil.rmtree(item, ignore_errors=True)
                                deleted_errors[0] += 1
                            except Exception:
                                deleted_errors[1] += 1
                    except Exception:
                        pass
                try:
                    ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0)
                except Exception:
                    pass
                self.root.after(0, lambda: messagebox.showinfo("清理完成",
                    f"已清理 {deleted_errors[0]} 个项目（{deleted_errors[1]} 个跳过）"))
            threading.Thread(target=do_clean, daemon=True).start()

        self.root.after(0, confirm_and_clean)

    # ════════════════════════════════════════════════════════
    #  🍅 番茄钟
    # ════════════════════════════════════════════════════════

    def _pomo_update_label(self):
        if self.pomo_state == "idle":
            self.pomo_label.config(text="🍅 未开始")
            return
        mins = self.pomo_remaining // 60
        secs = self.pomo_remaining % 60
        label_map = {"focus": "专注", "break": "休息", "long_break": "长休"}
        label = label_map.get(self.pomo_state, "?")
        text = f"🍅 {label} {mins:02d}:{secs:02d}"
        if not self.pomo_running:
            text += " ⏸"
        self.pomo_label.config(text=text)

    def _pomo_play_alarm(self):
        self.root.bell()
        self.root.bell()
        self.root.bell()

    def _pomo_next_state(self):
        if self.pomo_state == "focus":
            self.pomo_count += 1
            if self.pomo_count >= self.settings["pomo_count_target"]:
                self.pomo_state = "long_break"
                self.pomo_remaining = self.settings["pomo_long_break"] * 60
                self.pomo_count = 0
            else:
                self.pomo_state = "break"
                self.pomo_remaining = self.settings["pomo_break"] * 60
        else:
            self.pomo_state = "focus"
            self.pomo_remaining = self.settings["pomo_duration"] * 60
        self.pomo_running = True
        self._pomo_update_label()

    def _pomo_start_focus(self):
        self.pomo_state = "focus"
        self.pomo_remaining = self.settings["pomo_duration"] * 60
        self.pomo_running = True
        self._pomo_update_label()

    def _pomo_pause(self):
        if self.pomo_state != "idle" and self.pomo_running:
            self.pomo_running = False
            self._pomo_update_label()

    def _pomo_reset(self):
        self.pomo_state = "idle"
        self.pomo_remaining = 0
        self.pomo_running = False
        self.pomo_count = 0
        self._pomo_update_label()

    def _pomo_tick(self):
        if self.pomo_state != "idle" and self.pomo_running:
            self.pomo_remaining -= 1
            if self.pomo_remaining <= 0:
                self._pomo_play_alarm()
                self._pomo_next_state()
            else:
                self._pomo_update_label()
        self.root.after(1000, self._pomo_tick)

    def _pomo_settings(self):
        HERMES = "#E8652E"
        win = tk.Toplevel(self.root)
        win.title("番茄钟设置")
        win.geometry("320x250+{}+{}".format(
            self.root.winfo_x() + 50, self.root.winfo_y() + 50))
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.configure(bg=HERMES)

        tk.Label(win, text="番茄钟设置", fg="white", bg=HERMES,
                 font=("Microsoft YaHei", 13, "bold")).pack(pady=(12, 5))

        fields = [
            ("专注时长（分）", "pomo_duration"),
            ("短休时长（分）", "pomo_break"),
            ("长休时长（分）", "pomo_long_break"),
            ("几个番茄后长休", "pomo_count_target"),
        ]
        entries = {}
        for label, key in fields:
            row = tk.Frame(win, bg=HERMES)
            row.pack(pady=3, fill="x", padx=20)
            tk.Label(row, text=label, fg="white", bg=HERMES,
                     font=("Microsoft YaHei", 10), width=14, anchor="w").pack(side="left")
            e = tk.Entry(row, width=6, justify="center", bd=1, relief="solid")
            e.insert(0, str(self.settings[key]))
            e.pack(side="right")
            entries[key] = e

        def save_pomo_settings():
            try:
                self.settings["pomo_duration"] = max(1, int(entries["pomo_duration"].get()))
                self.settings["pomo_break"] = max(1, int(entries["pomo_break"].get()))
                self.settings["pomo_long_break"] = max(1, int(entries["pomo_long_break"].get()))
                self.settings["pomo_count_target"] = max(1, int(entries["pomo_count_target"].get()))
                self.save_settings()
                win.destroy()
            except ValueError:
                pass

        btn_frame = tk.Frame(win, bg=HERMES)
        btn_frame.pack(pady=(10, 5))
        tk.Button(btn_frame, text="确定", command=save_pomo_settings,
                  width=10, bg="#333", fg="white",
                  activebackground="#555", activeforeground="white",
                  bd=0, padx=10, pady=3).pack(side="left", padx=5)
        tk.Button(btn_frame, text="取消", command=win.destroy,
                  width=10, bg="#555", fg="white",
                  activebackground="#777", activeforeground="white",
                  bd=0, padx=10, pady=3).pack(side="left", padx=5)

    # ════════════════════════════════════════════════════════
    #  ⏰ 闹钟
    # ════════════════════════════════════════════════════════

    def _play_alarm_sound(self):
        """播放当前设置的闹钟铃声"""
        sound = self.settings.get("alarm_sound", "beep")
        if sound in ("beep", "chime", "alarm", "gentle"):
            _play_builtin_beep(sound)
        elif sound and os.path.isfile(sound):
            ext = os.path.splitext(sound)[1].lower()
            if ext == ".wav":
                winsound.PlaySound(sound, winsound.SND_FILENAME | winsound.SND_ASYNC)
            else:
                _play_mp3(sound)
        else:
            _play_builtin_beep("beep")

    def _alarm_check(self):
        """每 30 秒检查是否有闹钟触发"""
        try:
            now = datetime.datetime.now()
            key = now.strftime("%H:%M")
            if key != self._last_alarm_minute:
                self._last_alarm_minute = key
                alarms = self.settings.get("alarms", [])
                for alarm in alarms:
                    if not alarm.get("enabled", True):
                        continue
                    if alarm.get("time") != key:
                        continue
                    # 跳过刚创建不到60秒的闹钟（防止添加时立即触发）
                    created = alarm.get("created_at", 0)
                    if created and time.time() - created < 60:
                        continue
                    days = alarm.get("days", [])
                    if days and now.weekday() not in days:
                        continue
                    msg = alarm.get("message", "闹钟")
                    threading.Thread(target=self._alarm_trigger, args=(msg,), daemon=True).start()
        except Exception:
            pass
        self.root.after(30000, self._alarm_check)

    def _alarm_trigger(self, message):
        """闹钟触发：播放铃声 + 显示窗口 + 3秒后自动关闭的提醒"""
        self._play_alarm_sound()
        self.root.after(0, self._show_window)
        self.root.after(0, lambda: self._alarm_popup(message))

    def _alarm_popup(self, message):
        """闹钟弹出提示（3秒自动关闭，不要求点击确定）"""
        win = tk.Toplevel(self.root)
        win.title("⏰")
        x = self.root.winfo_x() + 60
        y = self.root.winfo_y() + 120
        win.geometry(f"280x90+{x}+{y}")
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg="#2D2D2D")
        tk.Label(win, text="⏰", fg="white", bg="#2D2D2D",
                 font=("Microsoft YaHei", 24)).pack(pady=(8, 0))
        tk.Label(win, text=message, fg="#5B9BD5", bg="#2D2D2D",
                 font=("Microsoft YaHei", 14, "bold")).pack(pady=(2, 4))
        win.after(3000, win.destroy)

    def _show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.focus_force()

    def _alarm_add(self):
        """添加闹钟对话框（macOS 风格）"""
        BG = "#2D2D2D"
        CARD = "#3A3A3A"
        BLUE = "#5B9BD5"
        win = tk.Toplevel(self.root)
        win.title("添加闹钟")
        win.geometry("340x280+{}+{}".format(
            self.root.winfo_x() + 50, self.root.winfo_y() + 50))
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.configure(bg=BG)

        tk.Label(win, text="⏰ 添加闹钟", fg="white", bg=BG,
                 font=("Microsoft YaHei", 14, "bold")).pack(pady=(14, 6))
        tk.Frame(win, bg="#555", height=1).pack(fill="x", padx=40)

        # 时间
        tf = tk.Frame(win, bg=BG)
        tf.pack(pady=8)
        tk.Label(tf, text="时间", fg="#AAAAAA", bg=BG,
                 font=("Microsoft YaHei", 14)).pack(side="left", padx=(0, 8))
        hour_var = tk.StringVar(value="08")
        min_var  = tk.StringVar(value="00")
        tk.Spinbox(tf, from_=0, to=23, width=3, textvariable=hour_var,
                   format="%02.0f", justify="center",
                   bd=1, relief="solid", bg=CARD, fg="white").pack(side="left")
        tk.Label(tf, text=":", fg="white", bg=BG,
                 font=("Microsoft YaHei", 14, "bold")).pack(side="left")
        tk.Spinbox(tf, from_=0, to=59, width=3, textvariable=min_var,
                   format="%02.0f", justify="center",
                   bd=1, relief="solid", bg=CARD, fg="white").pack(side="left")

        # 消息
        mf = tk.Frame(win, bg=BG)
        mf.pack(pady=5)
        tk.Label(mf, text="提醒", fg="#AAAAAA", bg=BG,
                 font=("Microsoft YaHei", 14)).pack(side="left", padx=(0, 8))
        msg_entry = tk.Entry(mf, width=22, bd=1, relief="solid", bg=CARD, fg="white")
        msg_entry.insert(0, "该做事了！")
        msg_entry.pack(side="left")

        # 重复
        rf = tk.Frame(win, bg=BG)
        rf.pack(pady=5)
        tk.Label(rf, text="重复", fg="#AAAAAA", bg=BG,
                 font=("Microsoft YaHei", 14)).pack(side="left", padx=(0, 8))
        days_map = {"一": 0, "二": 1, "三": 2, "四": 3,
                    "五": 4, "六": 5, "日": 6}
        day_vars = {}
        for dn, dv in days_map.items():
            var = tk.BooleanVar(value=False)
            day_vars[dn] = var
            tk.Checkbutton(rf, text=dn, variable=var,
                           bg=BG, fg="white", selectcolor=CARD,
                           activebackground="#444",
                           activeforeground="white").pack(side="left")

        def save_alarm():
            hour = hour_var.get().zfill(2)
            minute = min_var.get().zfill(2)
            time_str = f"{hour}:{minute}"
            msg = msg_entry.get() or "闹钟"
            days = [day_vars[dn].get() for dn in days_map]
            active_days = [i for i, v in enumerate(days) if v]
            alarm = {
                "time": time_str, "message": msg, "days": active_days,
                "enabled": True, "created_at": time.time(),
            }
            alarms = self.settings.get("alarms", [])
            alarms.append(alarm)
            self.settings["alarms"] = alarms
            self.save_settings()
            win.destroy()

        # 标准按钮
        btn_f = tk.Frame(win, bg=BG)
        btn_f.pack(pady=(10, 5))
        tk.Button(btn_f, text="确定", command=save_alarm,
                  width=10, bg="#5B9BD5", fg="white",
                  activebackground="#4A8BC8", activeforeground="white",
                  relief="raised", bd=2, padx=10, pady=4,
                  font=("Microsoft YaHei", 11)).pack(side="left", padx=6)
        tk.Button(btn_f, text="取消", command=win.destroy,
                  width=10, bg="#555", fg="white",
                  activebackground="#666", activeforeground="white",
                  relief="raised", bd=2, padx=10, pady=4,
                  font=("Microsoft YaHei", 11)).pack(side="left", padx=6)

    def _alarm_manager(self):
        """管理闹钟列表"""
        HERMES = "#E8652E"
        win = tk.Toplevel(self.root)
        win.title("管理闹钟")
        win.geometry("380x300+{}+{}".format(
            self.root.winfo_x() + 50, self.root.winfo_y() + 50))
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.configure(bg=HERMES)

        tk.Label(win, text="闹钟列表", fg="white", bg=HERMES,
                 font=("Microsoft YaHei", 14, "bold")).pack(pady=(8, 2))

        alarms = self.settings.get("alarms", [])
        if not alarms:
            tk.Label(win, text="暂无闹钟", fg="white", bg=HERMES,
                     font=("Microsoft YaHei", 10)).pack(pady=20)
            tk.Button(win, text="关闭", command=win.destroy,
                      width=10, bg="#333", fg="white",
                      activebackground="#555", activeforeground="white",
                      bd=0, padx=10, pady=3).pack(pady=10)
            return

        lb = tk.Listbox(win, bg="#222", fg="white",
                        selectbackground="#D4602A", selectforeground="white",
                        bd=1, relief="solid", height=8,
                        font=("Microsoft YaHei", 14))
        lb.pack(pady=5, padx=10, fill="both", expand=True)

        day_names = ["一", "二", "三", "四", "五", "六", "日"]
        for i, alarm in enumerate(alarms):
            time_str = alarm.get("time", "??:??")
            msg = alarm.get("message", "")
            days = alarm.get("days", [])
            enabled = alarm.get("enabled", True)
            prefix = "🔔" if enabled else "🔇"
            if days:
                day_str = " ".join(day_names[d] for d in sorted(days))
            else:
                day_str = "每天"
            lb.insert("end", f"{prefix} {time_str}  {msg}  ({day_str})")

        def toggle_alarm():
            sel = lb.curselection()
            if not sel:
                return
            idx = int(sel[0])
            alarms[idx]["enabled"] = not alarms[idx].get("enabled", True)
            self.settings["alarms"] = alarms
            self.save_settings()
            win.destroy()
            self._alarm_manager()

        def delete_alarm():
            sel = lb.curselection()
            if not sel:
                return
            idx = int(sel[0])
            if messagebox.askyesno("删除闹钟", "确定删除该闹钟？"):
                new_list = [a for i, a in enumerate(self.settings.get("alarms", [])) if i != idx]
                self.settings["alarms"] = new_list
                self.save_settings()
                win.destroy()
                self._alarm_manager()

        btn_f = tk.Frame(win, bg=HERMES)
        btn_f.pack(pady=5)
        tk.Button(btn_f, text="启用/禁用", command=toggle_alarm,
                  width=10, bg="#333", fg="white",
                  activebackground="#555", activeforeground="white",
                  bd=0, padx=5, pady=2).pack(side="left", padx=3)
        tk.Button(btn_f, text="删除", command=delete_alarm,
                  width=8, bg="#822", fg="white",
                  activebackground="#a33", activeforeground="white",
                  bd=0, padx=5, pady=2).pack(side="left", padx=3)
        tk.Button(btn_f, text="关闭", command=win.destroy,
                  width=8, bg="#555", fg="white",
                  activebackground="#777", activeforeground="white",
                  bd=0, padx=5, pady=2).pack(side="left", padx=3)

    def _alarm_pick_sound(self):
        """选择自定义铃声文件（支持 WAV / MP3）"""
        f = filedialog.askopenfilename(
            title="选择铃声文件",
            filetypes=[("音频文件", "*.wav *.mp3"), ("所有文件", "*.*")]
        )
        if f:
            self.settings["alarm_sound"] = f
            self.save_settings()
            messagebox.showinfo("铃声", f"已设置铃声：\n{os.path.basename(f)}")

    def _alarm_test_sound(self):
        """测试当前铃声"""
        self._play_alarm_sound()

    # ════════════════════════════════════════════════════════
    #  🗂 系统托盘
    # ════════════════════════════════════════════════════════

    def _start_tray(self):
        """启动系统托盘图标"""
        if not HAS_TRAY or self._tray_icon:
            return
        try:
            # 用 netspeed.png 作为图标
            icon_path = os.path.join(SCRIPT_DIR, "netspeed.png")
            if os.path.isfile(icon_path):
                img = PILImage.open(icon_path)
                img = img.resize((64, 64), PILImage.NEAREST)
            else:
                # 创建简易图标
                img = PILImage.new('RGBA', (64, 64), (232, 101, 46, 255))

            menu = pystray.Menu(
                pystray.MenuItem("显示", self._tray_show),
                pystray.MenuItem("退出", self._tray_quit),
            )
            self._tray_icon = pystray.Icon("桌面时钟", img, "桌面时钟", menu)
            threading.Thread(target=self._tray_icon.run, daemon=True).start()
        except Exception:
            self._tray_icon = None

    def _minimize_to_tray(self):
        """关闭时隐藏到系统托盘"""
        if HAS_TRAY:
            self.root.withdraw()
        else:
            self._quit()

    def _tray_show(self, icon=None, item=None):
        """托盘菜单：显示窗口"""
        self.root.after(0, self._show_window)

    def _tray_quit(self, icon=None, item=None):
        """托盘菜单：退出"""
        if self._tray_icon:
            self._tray_icon.stop()
        self.root.after(0, self._quit)

    def _quit(self):
        self.settings["x"] = self.root.winfo_x()
        self.settings["y"] = self.root.winfo_y()
        self.save_settings()
        _stop_mp3()
        if self._tray_icon:
            try:
                self._tray_icon.stop()
            except Exception:
                pass
        self.root.quit()
        self.root.destroy()
        os._exit(0)

    # ── 持久化 ────────────────────────────────────────────
    def load_settings(self):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                for k, v in data.items():
                    if k in self.settings:
                        self.settings[k] = v
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def save_settings(self):
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

        content = final.get("content", "")
        if content:
            self.history.append({"role": "assistant", "content": content})

        # 如果AI又返回了新的tool_calls（多轮，例如先列表再读文件），递归处理
        if final.get("tool_calls") and content == "":
            new_result = self.chat("请继续根据已有信息分析")
            return new_result.get("content", content)
        return content


# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    DesktopWidget()
