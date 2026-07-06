Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class NativeMethods {
    [DllImport("user32.dll")]
    public static extern int SetWindowLong(IntPtr hWnd, int nIndex, int dwNewLong);
    [DllImport("user32.dll")]
    public static extern int GetWindowLong(IntPtr hWnd, int nIndex);
    [DllImport("user32.dll")]
    public static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int x, int y, int cx, int cy, uint flags);
    public const int GWL_EXSTYLE = -20;
    public const int WS_EX_LAYERED = 0x80000;
    public const int WS_EX_TRANSPARENT = 0x20;
    public static readonly IntPtr HWND_TOPMOST = new IntPtr(-1);
    public const uint SWP_NOSIZE = 1;
    public const uint SWP_NOMOVE = 2;
    public const uint SWP_SHOWWINDOW = 0x40;
}
"@

# ── 配置 ──────────────────────────────────────────────────
$Script:ConfigFile = Join-Path $PSScriptRoot "widget_settings.json"
$Script:Settings = @{
    color        = "#00FFAA"
    opacity      = 0.85
    clickThrough = $true
    autoStart    = $false
    x            = 200
    y            = 100
}

function Load-Settings {
    if (Test-Path $Script:ConfigFile) {
        try {
            $json = Get-Content $Script:ConfigFile -Raw -Encoding UTF8 | ConvertFrom-Json
            foreach ($prop in $json.PSObject.Properties) {
                if ($Script:Settings.ContainsKey($prop.Name)) {
                    $Script:Settings[$prop.Name] = $prop.Value
                }
            }
        } catch {}
    }
}

function Save-Settings {
    try {
        $Script:Settings | ConvertTo-Json | Set-Content $Script:ConfigFile -Encoding UTF8
    } catch {}
}

Load-Settings

# ── 主窗口 ──────────────────────────────────────────────────
$Form = New-Object System.Windows.Forms.Form
$Form.Text = "桌面时钟"
$Form.FormBorderStyle = "None"
$Form.StartPosition = "Manual"
$Form.Location = New-Object System.Drawing.Point($Script:Settings.x, $Script:Settings.y)
$Form.Size = New-Object System.Drawing.Size(400, 160)
$Form.MaximumSize = New-Object System.Drawing.Size(600, 300)
$Form.BackColor = "Black"
$Form.TransparencyKey = [System.Drawing.Color]::Black
$Form.TopMost = $true
$Form.ShowInTaskbar = $false
$Form.MaximizeBox = $false
$Form.MinimizeBox = $false
$Form.Opacity = $Script:Settings.opacity

# ── 控件 ──────────────────────────────────────────────────
$Color = [System.Drawing.ColorTranslator]::FromHtml($Script:Settings.color)

$TimeLabel = New-Object System.Windows.Forms.Label
$TimeLabel.Text = "00:00:00"
$TimeLabel.Font = New-Object System.Drawing.Font("Consolas", 72, [System.Drawing.FontStyle]::Bold)
$TimeLabel.ForeColor = $Color
$TimeLabel.BackColor = "Black"
$TimeLabel.AutoSize = $true
$TimeLabel.Cursor = "Hand"

$DateLabel = New-Object System.Windows.Forms.Label
$DateLabel.Font = New-Object System.Drawing.Font("Microsoft YaHei", 14, [System.Drawing.FontStyle]::Bold)
$DateLabel.ForeColor = $Color
$DateLabel.BackColor = "Black"
$DateLabel.AutoSize = $true

$UpLabel = New-Object System.Windows.Forms.Label
$UpLabel.Text = "↑ 0.00 KB/s"
$UpLabel.Font = New-Object System.Drawing.Font("Consolas", 12, [System.Drawing.FontStyle]::Bold)
$UpLabel.ForeColor = $Color
$UpLabel.BackColor = "Black"
$UpLabel.AutoSize = $true

$DownLabel = New-Object System.Windows.Forms.Label
$DownLabel.Text = "↓ 0.00 KB/s"
$DownLabel.Font = New-Object System.Drawing.Font("Consolas", 12, [System.Drawing.FontStyle]::Bold)
$DownLabel.ForeColor = $Color
$DownLabel.BackColor = "Black"
$DownLabel.AutoSize = $true

# 布局
$PadPanel = New-Object System.Windows.Forms.FlowLayoutPanel
$PadPanel.AutoSize = $true
$PadPanel.AutoSizeMode = "GrowAndShrink"
$PadPanel.FlowDirection = "TopDown"
$PadPanel.BackColor = "Black"
$PadPanel.Padding = New-Object System.Windows.Forms.Padding(12, 6, 12, 6)

$PadPanel.Controls.Add($TimeLabel)
$PadPanel.Controls.Add($DateLabel)
$PadPanel.Controls.Add($UpLabel)
$PadPanel.Controls.Add($DownLabel)
$Form.Controls.Add($PadPanel)

# ── 拖动 ──────────────────────────────────────────────────
$Script:Dragging = $false
$Script:MouseX = 0
$Script:MouseY = 0

function On-MouseDown {
    param($sender, $e)
    if ($e.Button -eq "Left") {
        $Script:Dragging = $true
        $Script:MouseX = $e.X
        $Script:MouseY = $e.Y
        # 拖动时临时关闭鼠标穿透
        Set-ClickThrough $false
    }
}

function On-MouseMove {
    param($sender, $e)
    if ($Script:Dragging) {
        $Form.Left = $Form.Left + ($e.X - $Script:MouseX)
        $Form.Top  = $Form.Top  + ($e.Y - $Script:MouseY)
    }
}

function On-MouseUp {
    param($sender, $e)
    if ($Script:Dragging) {
        $Script:Dragging = $false
        # 保存位置
        $Script:Settings.x = $Form.Left
        $Script:Settings.y = $Form.Top
        Save-Settings
        # 恢复鼠标穿透
        if ($Script:Settings.clickThrough) {
            Set-ClickThrough $true
        }
    }
}

# 绑定拖动到所有label
foreach ($ctrl in @($TimeLabel, $DateLabel, $UpLabel, $DownLabel, $PadPanel)) {
    $ctrl.Add_MouseDown({ param($s,$e) On-MouseDown $s $e })
    $ctrl.Add_MouseMove({ param($s,$e) On-MouseMove $s $e })
    $ctrl.Add_MouseUp({ param($s,$e) On-MouseUp $s $e })
}

# ── 鼠标穿透 (Windows API) ─────────────────────────────
function Set-ClickThrough {
    param([bool]$enabled)
    $hwnd = $Form.Handle
    $style = [NativeMethods]::GetWindowLong($hwnd, [NativeMethods]::GWL_EXSTYLE)
    if ($enabled) {
        [NativeMethods]::SetWindowLong($hwnd, [NativeMethods]::GWL_EXSTYLE,
            $style -bor [NativeMethods]::WS_EX_LAYERED -bor [NativeMethods]::WS_EX_TRANSPARENT)
    } else {
        [NativeMethods]::SetWindowLong($hwnd, [NativeMethods]::GWL_EXSTYLE,
            $style -band -bnot [NativeMethods]::WS_EX_TRANSPARENT)
    }
    # 强制保持窗口位置，防止 SetWindowLong 触发重排导致闪烁
    [NativeMethods]::SetWindowPos($hwnd, [IntPtr]::Zero,
        $Form.Left, $Form.Top, 0, 0,
        [NativeMethods]::SWP_NOSIZE -bor [NativeMethods]::SWP_NOZORDER -bor 0x10)
}

# ── 右键菜单 ────────────────────────────────────────────
$ContextMenu = New-Object System.Windows.Forms.ContextMenuStrip

# 颜色
$ColorItem = New-Object System.Windows.Forms.ToolStripMenuItem
$ColorItem.Text = "更改颜色"
$ColorItem.Add_Click({
    $cd = New-Object System.Windows.Forms.ColorDialog
    $cd.Color = [System.Drawing.ColorTranslator]::FromHtml($Script:Settings.color)
    if ($cd.ShowDialog() -eq "OK") {
        $Script:Settings.color = "#{0:X2}{1:X2}{2:X2}" -f $cd.Color.R, $cd.Color.G, $cd.Color.B
        $c = $cd.Color
        $TimeLabel.ForeColor = $c
        $DateLabel.ForeColor = $c
        $UpLabel.ForeColor = $c
        $DownLabel.ForeColor = $c
        Save-Settings
    }
})

# 透明度
$OpacityItem = New-Object System.Windows.Forms.ToolStripMenuItem
$OpacityItem.Text = "调节透明度"
$OpacityItem.Add_Click({
    $tb = New-Object System.Windows.Forms.TrackBar
    $tb.Minimum = 30; $tb.Maximum = 100; $tb.Value = [int]($Script:Settings.opacity * 100)
    $tb.TickFrequency = 10
    $lb = New-Object System.Windows.Forms.Label
    $lb.Text = "透明度: $($tb.Value)%"
    $lb.AutoSize = $true
    $frm = New-Object System.Windows.Forms.Form
    $frm.Text = "透明度"
    $frm.Size = New-Object System.Drawing.Size(350, 120)
    $frm.StartPosition = "CenterParent"
    $frm.FormBorderStyle = "FixedDialog"
    $frm.MaximizeBox = $false
    $frm.MinimizeBox = $false
    $frm.Controls.Add($lb)
    $frm.Controls.Add($tb)
    $tb.Location = New-Object System.Drawing.Point(20, 30)
    $tb.Size = New-Object System.Drawing.Size(290, 50)
    $lb.Location = New-Object System.Drawing.Point(20, 5)
    $tb.Add_ValueChanged({
        $v = $tb.Value / 100.0
        $Form.Opacity = $v
        $lb.Text = "透明度: $($tb.Value)%"
        $Script:Settings.opacity = $v
        Save-Settings
    })
    $frm.ShowDialog()
})

# 鼠标穿透
$CTItem = New-Object System.Windows.Forms.ToolStripMenuItem
$CTItem.Text = "鼠标穿透（点击透过）"
$CTItem.CheckOnClick = $true
$CTItem.Checked = $Script:Settings.clickThrough
$CTItem.Add_CheckedChanged({
    $Script:Settings.clickThrough = $CTItem.Checked
    Set-ClickThrough $CTItem.Checked
    Save-Settings
})

# 开机自启动
$ASItem = New-Object System.Windows.Forms.ToolStripMenuItem
$ASItem.Text = "开机自启动"
$ASItem.CheckOnClick = $true
$StartupDir = [Environment]::GetFolderPath("Startup")
$StartupLnk = Join-Path $StartupDir "桌面时钟.lnk"
$ExePath = Join-Path $PSScriptRoot "netspeed.exe"
$ASItem.Checked = (Test-Path $StartupLnk)
$ASItem.Add_CheckedChanged({
    if ($ASItem.Checked) {
        $wshell = New-Object -ComObject WScript.Shell
        $sc = $wshell.CreateShortcut($StartupLnk)
        $sc.TargetPath = $ExePath
        $sc.WorkingDirectory = $PSScriptRoot
        $sc.Description = "桌面时钟小工具"
        $sc.WindowStyle = 7  # 最小化启动，无窗口闪烁
        $sc.Save()
    } else {
        if (Test-Path $StartupLnk) { Remove-Item $StartupLnk -Force }
    }
})

# 退出
$ExitItem = New-Object System.Windows.Forms.ToolStripMenuItem
$ExitItem.Text = "退出"
$ExitItem.Add_Click({ $Form.Close() })

$ContextMenu.Items.AddRange(@($ColorItem, $OpacityItem, $CTItem, $ASItem, $ExitItem))

$Form.ContextMenuStrip = $ContextMenu

# ── 时钟更新 ────────────────────────────────────────────
$ClockTimer = New-Object System.Windows.Forms.Timer
$ClockTimer.Interval = 1000
$ClockTimer.Add_Tick({
    $now = Get-Date
    $TimeLabel.Text = $now.ToString("HH:mm:ss")
    $weekday = @("星期日","星期一","星期二","星期三","星期四","星期五","星期六")[[int]$now.DayOfWeek]
    $DateLabel.Text = "{0}年{1:00}月{2:00}日 {3}" -f $now.Year, $now.Month, $now.Day, $weekday
})
$ClockTimer.Start()

# ── 网速更新 ────────────────────────────────────────────
$Script:PrevRecv = 0
$Script:PrevSent = 0
$Script:PrevTs   = 0

function Get-FormatSpeed {
    param([double]$bps)
    if ($bps -ge 1MB) { return "{0:N2} MB/s" -f ($bps / 1MB) }
    if ($bps -ge 1KB) { return "{0:N2} KB/s" -f ($bps / 1KB) }
    return "{0:N0} B/s" -f $bps
}

function Update-Network {
    try {
        # 使用 WMI 获取所有网卡总流量
        $adapters = Get-WmiObject Win32_PerfRawData_Tcpip_NetworkInterface -ErrorAction Stop
        $totalRecv = ($adapters | Measure-Object -Property BytesReceivedPersec -Sum).Sum
        $totalSent = ($adapters | Measure-Object -Property BytesSentPersec -Sum).Sum

        # WMI 的 BytesReceivedPersec / BytesSentPersec 已经是每秒速率
        $DownLabel.Text = "↓ " + (Get-FormatSpeed $totalRecv)
        $UpLabel.Text   = "↑ " + (Get-FormatSpeed $totalSent)
    } catch {
        # 备用方案：用 netstat -e 计算差值
        try {
            $ts = [Environment]::TickCount64
            $output = & netstat -e 2>$null
            $bytesLine = $output | Select-String -Pattern "(\d[\d,]*)\s+(\d[\d,]*)"
            if ($bytesLine) {
                $parts = $bytesLine.Matches[0].Groups
                $recv = [long]($parts[1].Value -replace ',','')
                $sent = [long]($parts[2].Value -replace ',','')
                if ($Script:PrevTs -gt 0) {
                    $deltaMs = $ts - $Script:PrevTs
                    if ($deltaMs -gt 0) {
                        $down = ($recv - $Script:PrevRecv) / $deltaMs * 1000
                        $up   = ($sent - $Script:PrevSent) / $deltaMs * 1000
                        $DownLabel.Text = "↓ " + (Get-FormatSpeed $down)
                        $UpLabel.Text   = "↑ " + (Get-FormatSpeed $up)
                    }
                }
                $Script:PrevRecv = $recv
                $Script:PrevSent = $sent
                $Script:PrevTs   = $ts
            }
        } catch {
            $DownLabel.Text = "↓ -- KB/s"
            $UpLabel.Text   = "↑ -- KB/s"
        }
    }
}

$NetTimer = New-Object System.Windows.Forms.Timer
$NetTimer.Interval = 1000
$NetTimer.Add_Tick({ Update-Network })
$NetTimer.Start()

# ── 窗口显示后设置鼠标穿透 ──────────────────────────────
$Form.Add_Shown({
    [System.Windows.Forms.Application]::DoEvents()
    if ($Script:Settings.clickThrough) {
        Set-ClickThrough $true
    }
})

# ── 启动 ──────────────────────────────────────────────────
[System.Windows.Forms.Application]::Run($Form)
