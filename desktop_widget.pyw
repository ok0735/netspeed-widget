# -*- coding: utf-8 -*-
#! python3.10
"""
桌面悬浮时钟 + 实时网速 小工具
功能：
  - 大字体时间显示 (HH:MM:SS)
  - 年月日星期显示
  - 实时网速上下行 (↑↓ KB/s / MB/s) — 自动合并所有网卡
  - 鼠标拖动定位
  - 右键菜单：自定义颜色、开机自启动、鼠标穿透切换
  - 半透明/不透明调节
"""

import tkinter as tk
from tkinter import colorchooser, messagebox
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


class SafeLabel(tk.Label):
    """稳定的文字标签，用法兼容 OutlinedLabel（支持 .config(text=...)/.config(fg=...)）"""
    def __init__(self, master, text="", font=None, fg="white", bg="black",
                 cursor="hand2"):
        super().__init__(master, text=text, font=font, fg=fg, bg=bg,
                         cursor=cursor, bd=0, highlightthickness=0)

    def config(self, **kwargs):
        super().config(**kwargs)

    configure = config

# ── 路径 ──────────────────────────────────────────────────────
# PyInstaller 打包的 exe 用 sys.executable（exe 真实路径）
# 普通脚本用 __file__（脚本所在目录）
if getattr(sys, 'frozen', False):
    SCRIPT_DIR = os.path.dirname(sys.executable)
else:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

SETTINGS_FILE = os.path.join(SCRIPT_DIR, "widget_settings.json")
PYTHON_PATH   = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
# 如果 pyw 不存在，回退到当前解释器
if not os.path.isfile(PYTHON_PATH):
    PYTHON_PATH = sys.executable

# 清理旧的快捷方式自启动（已废弃），避免与新注册表方式冲突
OLD_STARTUP_DIR = os.path.join(
    os.environ["APPDATA"],
    r"Microsoft\Windows\Start Menu\Programs\Startup"
)
OLD_STARTUP_LNK = os.path.join(OLD_STARTUP_DIR, "桌面时钟.lnk")
try:
    if os.path.isfile(OLD_STARTUP_LNK):
        os.remove(OLD_STARTUP_LNK)
except OSError:
    pass

# ── 默认设置 ─────────────────────────────────────────────────
DEFAULT_SETTINGS = {
    "color": "#00FFAA",
    "opacity": 0.85,
    "auto_start": False,
    "x": 200,
    "y": 100,
}


# =============================================================
class DesktopWidget:
    # ── 初始化 ──────────────────────────────────────────────
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("桌面时钟")
        self.root.overrideredirect(True)          # 无边框
        self.root.attributes("-topmost", True)     # 置顶

        # 设置
        self.settings = DEFAULT_SETTINGS.copy()
        self.load_settings()

        # 网速追踪
        self.prev_recv = 0
        self.prev_sent = 0
        self.prev_ts   = 0

        # NTP 时间偏移（秒）
        self.ntp_offset = 0
        self.ntp_updated = False

        self._build_ui()
        self.root.geometry(f"+{self.settings['x']}+{self.settings['y']}")

        # 固定窗口不可调整大小，并锁定尺寸，防止文本更新导致窗口尺寸变化而跳动
        self.root.resizable(False, False)
        self.root.update_idletasks()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        self.root.geometry(f"{w}x{h}+{self.settings['x']}+{self.settings['y']}")

        # 后台 NTP 校时
        threading.Thread(target=self._sync_ntp_time, daemon=True).start()

        # 启动定时器
        self.update_clock()
        self.update_network()

        # 开机自启动同步：如果设置中开启了但注册表中没有，则补上
        if self.settings.get("auto_start", False):
            if not self._is_auto_start():
                self._enable_auto_start()

        # 启动后延迟 3 秒将窗口置前（解决开机登录时窗口不显示的问题）
        self.root.after(3000, self._ensure_visible)

        self.root.mainloop()

    def _ensure_visible(self):
        """开机启动后，确保窗口在桌面可见"""
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.focus_force()
        self.root.update_idletasks()

    # ── UI 构建 ────────────────────────────────────────────
    def _build_ui(self):
        self.root.configure(bg="black")
        self.root.attributes("-transparentcolor", "black")
        self.root.attributes("-alpha", self.settings["opacity"])

        # 主容器 - 居中对齐
        self.main_frame = tk.Frame(self.root, bg="black")
        self.main_frame.pack(padx=12, pady=6)

        # ----- 时间（48px） -----
        self.time_label = SafeLabel(
            self.main_frame,
            text="00:00:00",
            font=("Consolas", 48, "bold"),
            fg=self.settings["color"],
            bg="black",
            cursor="hand2",
        )
        self.time_label.pack(fill="x", pady=(2, 0))

        # ----- 年月日星期（24px，居中） -----
        self.date_label = SafeLabel(
            self.main_frame,
            text="----年--月--日 星期-",
            font=("Microsoft YaHei", 24, "bold"),
            fg=self.settings["color"],
            bg="black",
        )
        self.date_label.pack(fill="x", pady=(2, 1))

        # ----- 网速（24px，一行显示上下行，居中） -----
        self.net_label = SafeLabel(
            self.main_frame,
            text="↑ 0.00 KB/s  ↓ 0.00 KB/s",
            font=("Consolas", 24, "bold"),
            fg=self.settings["color"],
            bg="black",
        )
        self.net_label.pack(fill="x", pady=(0, 2))

        # ----- 事件绑定 -----
        self._bind_drag(self.root)
        self._bind_drag(self.time_label)
        self._bind_drag(self.date_label)
        self._bind_drag(self.main_frame)
        self._bind_drag(self.net_label)
        self._bind_context_menu()

    # ── NTP 授时同步 ─────────────────────────────────────
    def _get_ntp_time(self, server, timeout=3):
        """查询 NTP 服务器，返回当前 datetime"""
        NTP_PORT = 123
        NTP_DELTA = 2208988800  # 1900-01-01 → 1970-01-01
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
        """后台线程：依次尝试多个 NTP 服务器获取准确时间"""
        for server in ('ntp.aliyun.com', 'ntp.ntsc.ac.cn', 'time.windows.com'):
            ntp_time = self._get_ntp_time(server)
            if ntp_time:
                local_now = datetime.datetime.now()
                self.ntp_offset = (ntp_time - local_now).total_seconds()
                self.ntp_updated = True
                break

    # ── 事件绑定 ─────────────────────────────────────────

    def _bind_drag(self, widget):
        """绑定拖拽事件"""
        widget.bind("<Button-1>",      self._drag_start)
        widget.bind("<B1-Motion>",     self._drag_move)
        widget.bind("<ButtonRelease-1>", self._drag_stop)
        # SafeLabel (tk.Label) 默认 cursor 不为手型时也设为 hand2
        try:
            widget.config(cursor="hand2")
        except Exception:
            pass

    def _drag_start(self, event):
        self._drag_x = event.x_root - self.root.winfo_x()
        self._drag_y = event.y_root - self.root.winfo_y()

    def _drag_move(self, event):
        x = event.x_root - self._drag_x
        y = event.y_root - self._drag_y
        self.root.geometry(f"+{x}+{y}")

    def _drag_stop(self, event):
        self.settings["x"] = self.root.winfo_x()
        self.settings["y"] = self.root.winfo_y()
        self.save_settings()

    # ── 右键菜单 ───────────────────────────────────────────
    def _bind_context_menu(self):
        self._menu = tk.Menu(self.root, tearoff=0)
        self._menu.add_command(label="更改颜色",          command=self._choose_color)
        self._menu.add_command(label="调节透明度",         command=self._adjust_opacity)
        self._menu.add_separator()

        # 开机自启动（注册表方式，比快捷方式更可靠）
        self._as_var = tk.BooleanVar(value=self._is_auto_start())
        self._menu.add_checkbutton(label="开机自启动",
                                   variable=self._as_var,
                                   command=self._toggle_auto_start)
        self._menu.add_separator()
        self._menu.add_command(label="关于", command=self._show_about)
        self._menu.add_separator()
        self._menu.add_command(label="退出", command=self._quit)

        for w in (self.root, self.main_frame, self.time_label,
                  self.date_label, self.net_label):
            w.bind("<Button-3>", self._show_menu)
            # 部分系统上右键也可能是 <Button-2>
            w.bind("<Button-2>", self._show_menu)

    def _show_menu(self, event):
        self._menu.tk_popup(event.x_root, event.y_root)

    # ── 关于 ───────────────────────────────────────────────
    def _show_about(self):
        win = tk.Toplevel(self.root)
        win.title("关于")
        win.geometry("360x180+{}+{}".format(
            self.root.winfo_x() + 80, self.root.winfo_y() + 80))
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.configure(bg="#222")

        # 标题
        tk.Label(win, text="桌面网速时钟", fg="#00FFAA", bg="#222",
                 font=("Microsoft YaHei", 14, "bold")).pack(pady=(20, 5))

        # 描述
        tk.Label(win, text="桌面网速时钟小部件程序", fg="white", bg="#222",
                 font=("Microsoft YaHei", 10)).pack(pady=2)

        # 作者（可点击链接）
        author_frame = tk.Frame(win, bg="#222")
        author_frame.pack(pady=10)
        tk.Label(author_frame, text="作者：", fg="white", bg="#222",
                 font=("Microsoft YaHei", 10)).pack(side="left")
        author_link = tk.Label(author_frame, text="ok0735",
                               fg="#4A9EFF", bg="#222", cursor="hand2",
                               font=("Microsoft YaHei", 10, "underline"))
        author_link.pack(side="left")
        author_link.bind("<Button-1>", lambda e: webbrowser.open("https://github.com/ok0735"))

        # 关闭按钮
        tk.Button(win, text="确定", command=win.destroy,
                  width=10, bg="#444", fg="white",
                  activebackground="#555", activeforeground="white",
                  bd=0, padx=10, pady=3).pack(pady=10)

    # ── 颜色 ───────────────────────────────────────────────
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
        self.net_label.config(fg=color)

    # ── 透明度 ─────────────────────────────────────────────
    def _adjust_opacity(self):
        win = tk.Toplevel(self.root)
        win.title("透明度")
        win.geometry("300x100+{}+{}".format(
            self.root.winfo_x() + 50, self.root.winfo_y() + 100))
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.configure(bg="#222")
        tk.Label(win, text="透明度调节", fg="white", bg="#222",
                 font=("Microsoft YaHei", 11)).pack(pady=(10, 5))

        slider = tk.Scale(win, from_=30, to=100, orient="horizontal",
                          length=250, bg="#333", fg="white",
                          troughcolor="#555")
        slider.set(int(self.settings["opacity"] * 100))
        slider.pack(pady=5)

        def apply_opacity(val):
            v = int(val) / 100.0
            self.settings["opacity"] = v
            self.root.attributes("-alpha", v)
            self.save_settings()

        slider.config(command=apply_opacity)

    # ── 开机自启动（注册表方式） ──────────────────────────
    REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
    REG_NAME = "桌面时钟"

    def _is_auto_start(self):
        """检查注册表中是否有自启动项"""
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
        """在注册表 HKCU Run 中添加自启动项"""
        try:
            import winreg
            # 判断运行模式，使用正确的可执行路径
            if getattr(sys, 'frozen', False):
                # 打包的 exe：直接指向 exe 本身
                cmd = f'"{sys.executable}"'
            else:
                # 脚本模式：pythonw + pyw
                script = os.path.join(SCRIPT_DIR, "desktop_widget.pyw")
                if os.path.isfile(PYTHON_PATH) and os.path.isfile(script):
                    cmd = f'"{PYTHON_PATH}" "{script}"'
                else:
                    cmd = f'"{sys.executable}" "{script}"'
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.REG_KEY, 0,
                                 winreg.KEY_SET_VALUE)
            winreg.SetValueEx(key, self.REG_NAME, 0, winreg.REG_SZ, cmd)
            winreg.CloseKey(key)
        except Exception as e:
            print(f"设置开机自启动失败: {e}")

    def _disable_auto_start(self):
        """从注册表中移除自启动项"""
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

    # ── 定时更新 ───────────────────────────────────────────
    def update_clock(self):
        now = datetime.datetime.now()

        # 如果已经获取了 NTP 时间，显示 NTP 校准后的时间
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
            ts  = time.time()

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

    # ── 退出 ───────────────────────────────────────────────
    def _quit(self):
        self.settings["x"] = self.root.winfo_x()
        self.settings["y"] = self.root.winfo_y()
        self.save_settings()
        self.root.destroy()

    # ── 持久化 ─────────────────────────────────────────────
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


# =============================================================
if __name__ == "__main__":
    DesktopWidget()
