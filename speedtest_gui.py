#!/usr/bin/env python3
"""
PULSE — Speed Test
"""

import sys
import threading
import time
import math
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFrame, QGraphicsDropShadowEffect, QSizePolicy
)
from PyQt6.QtCore import (
    Qt, QTimer, QThread, pyqtSignal, QPropertyAnimation,
    QEasingCurve, QRect, QPoint, QSize, pyqtProperty
)
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QFontDatabase,
    QLinearGradient, QRadialGradient, QConicalGradient,
    QPainterPath, QPixmap, QPalette
)


# ── Colours ──────────────────────────────────────────────────────────────────
BG         = QColor("#090b10")
SURFACE    = QColor("#0f1219")
BORDER     = QColor(255, 255, 255, 14)
ACCENT     = QColor("#00d4ff")
ACCENT2    = QColor("#8b5cf6")
TEXT       = QColor("#dde2f0")
MUTED      = QColor(221, 226, 240, 90)
GOOD       = QColor("#22d3a5")
WARN       = QColor("#f59e0b")
DANGER     = QColor("#f43f5e")
WHITE      = QColor("#ffffff")


def lerp_color(c1, c2, t):
    r = int(c1.red()   + (c2.red()   - c1.red())   * t)
    g = int(c1.green() + (c2.green() - c1.green()) * t)
    b = int(c1.blue()  + (c2.blue()  - c1.blue())  * t)
    return QColor(r, g, b)


def speed_color(mbps):
    if mbps >= 100:
        return GOOD
    if mbps >= 30:
        return lerp_color(WARN, GOOD, (mbps - 30) / 70)
    if mbps >= 5:
        return lerp_color(DANGER, WARN, (mbps - 5) / 25)
    return DANGER


# ── Worker thread ─────────────────────────────────────────────────────────────
class SpeedTestWorker(QThread):
    progress      = pyqtSignal(str, float)
    phase_changed = pyqtSignal(str)
    phase_result  = pyqtSignal(str, float)
    finished      = pyqtSignal(dict)
    error         = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._stop       = False
        self._live_bytes = 0
        self._lock       = threading.Lock()

    def _add(self, n):
        with self._lock:
            self._live_bytes += n

    def _get(self):
        with self._lock:
            return self._live_bytes

    def _reset(self):
        with self._lock:
            self._live_bytes = 0

    def _poll(self, phase, interval=0.25):
        prev_b = 0
        prev_t = time.monotonic()
        smooth = 0.0
        ALPHA  = 0.45
        while not self._stop:
            time.sleep(interval)
            now   = time.monotonic()
            cur_b = self._get()
            db    = cur_b - prev_b
            dt    = now - prev_t
            if dt > 0 and db > 0:
                instant = (db * 8) / (dt * 1e6)
                smooth  = ALPHA * instant + (1 - ALPHA) * smooth
                self.progress.emit(phase, round(smooth, 2))
            prev_b = cur_b
            prev_t = now

    def run(self):
        try:
            import speedtest as st_lib

            # Patch HTTPDownloader.run — fires our counter on every 10 KB chunk
            _orig_dl_run = st_lib.HTTPDownloader.run
            worker_self  = self

            def _patched_dl_run(dl_thread):
                try:
                    import timeit
                    if (timeit.default_timer() - dl_thread.starttime) <= dl_thread.timeout:
                        f = dl_thread._opener(dl_thread.request)
                        while (not dl_thread._shutdown_event.isSet() and
                               (timeit.default_timer() - dl_thread.starttime) <= dl_thread.timeout):
                            chunk = f.read(10240)
                            n = len(chunk)
                            dl_thread.result.append(n)
                            if n:
                                worker_self._add(n)
                            else:
                                break
                        f.close()
                except Exception:
                    pass

            st_lib.HTTPDownloader.run = _patched_dl_run

            # Patch HTTPUploaderData.read — fires our counter on every chunk sent
            _orig_ud_read = st_lib.HTTPUploaderData.read

            def _patched_ud_read(ud_self, n=10240):
                chunk = _orig_ud_read(ud_self, n)
                if chunk:
                    worker_self._add(len(chunk))
                return chunk

            st_lib.HTTPUploaderData.read = _patched_ud_read

            s = st_lib.Speedtest()

            # ── Ping — measure multiple servers, animate needle live ──
            self.phase_changed.emit("ping")
            s.get_servers()
            best = s.get_best_server()
            # Ping the best server 8 times and emit each result live
            import urllib.request as _ur
            ping_url = best["url"].replace("upload.php", "latency.txt")
            samples  = []
            for _ in range(8):
                try:
                    t0 = time.monotonic()
                    _ur.urlopen(ping_url, timeout=3).read()
                    ms = (time.monotonic() - t0) * 1000
                    samples.append(ms)
                    self.progress.emit("ping", ms)
                    time.sleep(0.08)
                except Exception:
                    pass
            ping = s.results.ping if s.results.ping else (sum(samples) / len(samples) if samples else 0)
            self.phase_result.emit("ping", round(ping, 1))

            # ── Download ──
            self.phase_changed.emit("download")
            self._reset()
            self._stop = False
            poll = threading.Thread(target=self._poll, args=("download",), daemon=True)
            poll.start()
            s.download()
            self._stop = True
            poll.join(timeout=1)
            dl = s.results.download / 1e6
            self.phase_result.emit("download", dl)

            # ── Upload ──
            self.phase_changed.emit("upload")
            self._reset()
            self._stop = False
            poll2 = threading.Thread(target=self._poll, args=("upload",), daemon=True)
            poll2.start()
            s.upload()
            self._stop = True
            poll2.join(timeout=1)
            ul = s.results.upload / 1e6
            self.phase_result.emit("upload", ul)

            st_lib.HTTPDownloader.run    = _orig_dl_run
            st_lib.HTTPUploaderData.read = _orig_ud_read

            self.finished.emit({
                "ping":     round(ping, 1),
                "download": round(dl, 2),
                "upload":   round(ul, 2),
                "server":   s.results.server.get("name", ""),
                "isp":      s.results.client.get("isp", ""),
            })
        except ImportError:
            self.error.emit("speedtest-cli not installed.\nRun: pip install speedtest-cli")
        except Exception as e:
            self.error.emit(str(e))


# ── Animated arc gauge ────────────────────────────────────────────────────────
class GaugeWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(260, 260)
        self._value   = 0.0       # displayed value (Mbps or ms)
        self._max     = 200.0
        self._phase   = "idle"    # idle | ping | download | upload | done
        self._anim_t  = 0.0       # 0..1 fill fraction for arc
        self._pulse   = 0.0       # breathing animation
        self._spin    = 0.0       # ring spin angle
        self._target  = 0.0
        self._display = 0.0       # smoothly animated display number

        # Pulse timer
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    # ── animation tick ──
    def _tick(self):
        self._pulse = (self._pulse + 0.03) % (2 * math.pi)
        self._spin  = (self._spin  + 1.2)  % 360

        # Smooth number towards target — fast rise, slower fall (real speedometer feel)
        diff = self._target - self._display
        factor = 0.22 if diff > 0 else 0.10
        self._display += diff * factor
        if abs(diff) < 0.05:
            self._display = self._target

        self.update()

    def set_value(self, v, phase=None):
        self._target = v
        if phase:
            self._phase = phase

    def set_phase(self, phase):
        prev = self._phase
        self._phase = phase
        if phase != prev:
            self._target = 0.0
            # Snap to 0 immediately on idle/done; animate down otherwise
            if phase in ("idle",):
                self._display = 0.0
            # "done" lets needle sweep back smoothly (display animates via _tick)

    # ── paint ──
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h   = self.width(), self.height()
        cx, cy = w / 2, h / 2
        r      = min(w, h) / 2 - 18

        # Arc geometry: starts at 225°, sweeps -270° (clockwise)
        ARC_START = 225.0   # degrees (Qt: CCW from 3 o'clock)
        ARC_SWEEP = 270.0   # total sweep

        def frac_to_angle_rad(frac):
            """Map 0..1 fraction to painter angle in radians (standard math CCW)."""
            deg = ARC_START - ARC_SWEEP * frac
            return math.radians(deg)

        color = ACCENT if self._phase == "download" else \
                ACCENT2 if self._phase == "upload"   else \
                GOOD    if self._phase == "ping"      else \
                QColor(60, 70, 90) if self._phase == "idle" else \
                getattr(self, "_last_color", GOOD)  # done: use last active color

        if self._phase not in ("idle", "done"):
            self._last_color = color  # remember for done phase

        frac = min(self._display / max(self._max, 1.0), 1.0)

        # ─── 1. Subtle radial bg glow ───
        p.setPen(Qt.PenStyle.NoPen)
        bg = QRadialGradient(cx, cy, r * 0.9)
        bg.setColorAt(0, QColor(15, 20, 38, 160))
        bg.setColorAt(1, QColor(9,  11, 16,   0))
        p.setBrush(bg)
        p.drawEllipse(int(cx - r), int(cy - r), int(r * 2), int(r * 2))

        arc_r    = r - 16         # inner arc (thin track)
        rim_r    = r - 4          # outer thick rim (Ookla style)
        arc_rect = QRect(int(cx - arc_r + 4), int(cy - arc_r + 4),
                         int(arc_r * 2 - 8),  int(arc_r * 2 - 8))
        rim_rect = QRect(int(cx - rim_r + 4), int(cy - rim_r + 4),
                         int(rim_r * 2 - 8),  int(rim_r * 2 - 8))

        # ─── 2. Dim track rings ───
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 10), 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(arc_rect, int(ARC_START * 16), int(-ARC_SWEEP * 16))
        p.setPen(QPen(QColor(255, 255, 255, 6), 10, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(rim_rect, int(ARC_START * 16), int(-ARC_SWEEP * 16))

        # ─── 3. Ookla-style outer rim fill + inner arc fill ───
        if frac > 0.005:
            span = int(-ARC_SWEEP * frac * 16)

            # Thick outer rim — uniform solid colour all the way (Ookla style)
            solid_c = QColor(color); solid_c.setAlpha(220)
            p.setPen(QPen(solid_c, 12, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawArc(rim_rect, int(ARC_START * 16), span)

            # Soft inner echo arc — matches colour at lower opacity
            inner_c = QColor(color); inner_c.setAlpha(45)
            p.setPen(QPen(inner_c, 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(arc_rect, int(ARC_START * 16), span)

            # Bright glowing tip dot on outer rim
            tip_angle = math.radians(ARC_START - ARC_SWEEP * frac)
            tip_x2 = cx + rim_r * math.cos(tip_angle)
            tip_y2 = cy - rim_r * math.sin(tip_angle)
            pulse_s = 0.5 + 0.5 * math.sin(self._pulse * 3)
            glow_r2 = 14 + 5 * pulse_s
            tg = QRadialGradient(tip_x2, tip_y2, glow_r2)
            tc = QColor(color); tc.setAlpha(200)
            tc2 = QColor(color); tc2.setAlpha(0)
            tg.setColorAt(0, tc); tg.setColorAt(1, tc2)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(tg)
            p.drawEllipse(int(tip_x2 - glow_r2), int(tip_y2 - glow_r2),
                          int(glow_r2 * 2), int(glow_r2 * 2))
            p.setBrush(QColor(255, 255, 255, 230))
            p.drawEllipse(int(tip_x2 - 3), int(tip_y2 - 3), 6, 6)

        # ─── 4. Tick marks ───
        NUM_MAJOR = 9
        NUM_MINOR = 4
        total_ticks = NUM_MAJOR * NUM_MINOR + NUM_MAJOR
        tick_outer = arc_r - 2   # just inside the inner arc

        for i in range(total_ticks + 1):
            tf = i / total_ticks
            angle = math.radians(ARC_START - ARC_SWEEP * tf)
            is_major = (i % (NUM_MINOR + 1) == 0)
            tick_len = 9 if is_major else 4
            tick_w   = 2 if is_major else 1

            outer = tick_outer
            inner = outer - tick_len
            x1 = cx + outer * math.cos(angle)
            y1 = cy - outer * math.sin(angle)
            x2 = cx + inner * math.cos(angle)
            y2 = cy - inner * math.sin(angle)

            if tf <= frac:
                tc = QColor(color); tc.setAlpha(180 if is_major else 100)
            else:
                tc = QColor(255, 255, 255, 35 if is_major else 18)
            p.setPen(QPen(tc, tick_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(int(x1), int(y1), int(x2), int(y2))

            # Major tick labels
            if is_major and self._phase not in ("idle",):
                label_val = int(tf * self._max)
                lx = cx + (outer - 18) * math.cos(angle)
                ly = cy - (outer - 18) * math.sin(angle)
                lc = QColor(color) if tf <= frac else QColor(255, 255, 255, 45)
                lc.setAlpha(min(lc.alpha(), 120))
                p.setFont(QFont("DM Mono", 6))
                p.setPen(lc)
                p.drawText(int(lx - 14), int(ly - 7), 28, 14,
                           Qt.AlignmentFlag.AlignCenter, str(label_val))

        # ─── 5. THE NEEDLE ───
        needle_angle = frac_to_angle_rad(frac)
        nx = math.cos(needle_angle)
        ny = -math.sin(needle_angle)

        needle_len   = rim_r - 6   # reaches outer rim
        needle_back  = 16
        needle_width = 2.2

        tip_x  = cx + nx * needle_len
        tip_y  = cy + ny * needle_len
        base_x = cx - nx * needle_back
        base_y = cy - ny * needle_back

        perp_x = -ny
        perp_y =  nx

        # Needle glow
        if self._phase not in ("idle",):
            glow_r = 16 + 5 * (0.5 + 0.5 * math.sin(self._pulse * 3))
            ng = QRadialGradient(tip_x, tip_y, glow_r)
            gc = QColor(color); gc.setAlpha(100)
            gc2 = QColor(color); gc2.setAlpha(0)
            ng.setColorAt(0, gc); ng.setColorAt(1, gc2)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(ng)
            p.drawEllipse(int(tip_x - glow_r), int(tip_y - glow_r),
                          int(glow_r * 2), int(glow_r * 2))

        # Needle body
        needle_path = QPainterPath()
        needle_path.moveTo(tip_x, tip_y)
        needle_path.lineTo(base_x + perp_x * needle_width, base_y + perp_y * needle_width)
        needle_path.lineTo(base_x - perp_x * needle_width, base_y - perp_y * needle_width)
        needle_path.closeSubpath()
        needle_grad = QLinearGradient(base_x, base_y, tip_x, tip_y)
        nc_dim = QColor(color); nc_dim.setAlpha(160)
        needle_grad.setColorAt(0, nc_dim)
        needle_grad.setColorAt(1, QColor(color))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(needle_grad)
        p.drawPath(needle_path)

        # Hub
        hub_r = 7
        hub_grad = QRadialGradient(cx, cy, hub_r)
        hub_grad.setColorAt(0,   QColor(210, 220, 240, 230))
        hub_grad.setColorAt(0.5, QColor(60,  70,  95,  255))
        hub_grad.setColorAt(1,   QColor(20,  24,  38,  255))
        p.setBrush(hub_grad)
        p.setPen(QPen(QColor(color.red(), color.green(), color.blue(), 100), 1))
        p.drawEllipse(int(cx - hub_r), int(cy - hub_r), hub_r * 2, hub_r * 2)

        # ─── 6. Value text — positioned BELOW the hub, clear of needle ───
        if self._phase == "idle":
            label_text = "PULSE"
            label_size = 20
            sub_text   = "tap to begin"
            sub_size   = 10
            num_color  = TEXT
        elif self._phase == "done":
            label_text = "DONE"
            label_size = 18
            sub_text   = ""
            sub_size   = 10
            num_color  = GOOD
        else:
            val        = self._display
            label_text = f"{val:.0f}"
            label_size = 38
            sub_text   = "Mbps" if self._phase in ("download", "upload") else "ms"
            sub_size   = 12
            num_color  = speed_color(val) if self._phase != "ping" else GOOD

        # Draw number below centre (hub is at cy, text starts at cy+20)
        text_y = int(cy + 20)
        p.setFont(QFont("Unbounded", label_size,
                        QFont.Weight.Bold if label_size > 20 else QFont.Weight.Light))
        p.setPen(num_color)
        p.drawText(int(cx - 110), text_y, 220, 48, Qt.AlignmentFlag.AlignCenter, label_text)

        if sub_text:
            p.setFont(QFont("DM Mono", sub_size))
            p.setPen(MUTED)
            p.drawText(int(cx - 70), text_y + 46, 140, 22,
                       Qt.AlignmentFlag.AlignCenter, sub_text)

        # Phase label at arc bottom
        if self._phase not in ("idle", "done"):
            phase_map = {"ping": "LATENCY", "download": "DOWNLOAD", "upload": "UPLOAD"}
            p.setFont(QFont("Unbounded", 7, QFont.Weight.Light))
            pc = QColor(color)
            pc.setAlpha(int(160 + 60 * math.sin(self._pulse)))
            p.setPen(pc)
            p.drawText(int(cx - 70), int(cy + r - 12), 140, 18,
                       Qt.AlignmentFlag.AlignCenter, phase_map.get(self._phase, ""))


# ── Stat card ─────────────────────────────────────────────────────────────────
class StatCard(QWidget):
    def __init__(self, icon, label, parent=None):
        super().__init__(parent)
        self.setFixedSize(160, 90)
        self._label = label
        self._icon  = icon
        self._value = "—"
        self._unit  = ""
        self._color = MUTED
        self._glow  = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._fade_tick)

    def set_result(self, value, unit, color):
        self._value = value
        self._unit  = unit
        self._color = color
        self._glow  = 1.0
        self._timer.start(30)
        self.update()

    def _fade_tick(self):
        self._glow -= 0.04
        if self._glow <= 0:
            self._glow = 0
            self._timer.stop()
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # Card background
        path = QPainterPath()
        path.addRoundedRect(0, 0, w, h, 12, 12)

        if self._glow > 0:
            gc = QColor(self._color); gc.setAlpha(int(30 * self._glow))
            p.fillPath(path, gc)
        else:
            p.fillPath(path, QColor(15, 18, 28, 200))

        # Border
        border_c = QColor(self._color) if self._glow > 0 else BORDER
        border_c.setAlpha(int(80 * self._glow) if self._glow > 0 else 20)
        p.setPen(QPen(border_c, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

        # Icon
        p.setFont(QFont("Segoe UI Emoji", 14))
        p.setPen(QColor(self._color))
        p.drawText(14, 0, 30, h, Qt.AlignmentFlag.AlignVCenter, self._icon)

        # Label
        p.setFont(QFont("DM Mono", 8))
        p.setPen(MUTED)
        p.drawText(46, 14, w - 50, 20, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._label)

        # Value
        p.setFont(QFont("Unbounded", 16, QFont.Weight.Bold))
        p.setPen(QColor(self._color) if self._value != "—" else MUTED)
        p.drawText(46, 34, w - 50, 32, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._value)

        # Unit
        if self._unit:
            p.setFont(QFont("DM Mono", 8))
            p.setPen(MUTED)
            p.drawText(46, 62, w - 50, 18, Qt.AlignmentFlag.AlignLeft, self._unit)


# ── Start / Stop button ───────────────────────────────────────────────────────
class PulseButton(QPushButton):
    def __init__(self, text="START", parent=None):
        super().__init__(text, parent)
        self.setFixedSize(160, 48)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hovered  = False
        self._pressed  = False
        self._pulse    = 0.0
        self._running  = False
        self._timer    = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    def set_running(self, v):
        self._running = v
        self.setText("STOP" if v else "START")
        self.update()

    def _tick(self):
        self._pulse = (self._pulse + 0.05) % (2 * math.pi)
        self.update()

    def enterEvent(self, e):
        self._hovered = True

    def leaveEvent(self, e):
        self._hovered = False

    def mousePressEvent(self, e):
        self._pressed = True
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self._pressed = False
        super().mouseReleaseEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        scale = 0.94 if self._pressed else 1.0
        ox = w * (1 - scale) / 2
        oy = h * (1 - scale) / 2
        p.translate(ox, oy)
        p.scale(scale, scale)

        path = QPainterPath()
        path.addRoundedRect(0, 0, w, h, 24, 24)

        if self._running:
            # Stop: danger outline
            c = QColor(DANGER); c.setAlpha(220 if self._hovered else 180)
            p.setPen(QPen(c, 1.5))
            c2 = QColor(DANGER); c2.setAlpha(30 if self._hovered else 15)
            p.fillPath(path, c2)
            p.drawPath(path)
            p.setPen(QColor(DANGER))
        else:
            # Start: accent fill
            pulse_a = int(200 + 50 * math.sin(self._pulse)) if self._hovered else 220
            grad = QLinearGradient(0, 0, w, h)
            c1 = QColor(ACCENT); c1.setAlpha(pulse_a)
            c2 = QColor(ACCENT2); c2.setAlpha(pulse_a)
            grad.setColorAt(0, c1)
            grad.setColorAt(1, c2)
            p.fillPath(path, grad)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawPath(path)
            p.setPen(WHITE)

        p.setFont(QFont("Unbounded", 10, QFont.Weight.Bold))
        p.drawText(0, 0, w, h, Qt.AlignmentFlag.AlignCenter, self.text())


# ── Main window ───────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PULSE — Speed Test")
        self.setFixedSize(420, 660)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._drag_pos = None
        self._worker   = None
        self._results  = {}

        self._build_ui()

    # ── UI ──
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)

        # Outer container with background
        container = _RoundedPanel(self)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(28, 20, 28, 20)
        container_layout.setSpacing(0)
        root.addWidget(container)

        # ── Title bar ──
        titlebar = QHBoxLayout()
        titlebar.setSpacing(0)

        brand = QLabel("PULSE")
        brand.setFont(QFont("Unbounded", 14, QFont.Weight.Bold))
        brand.setStyleSheet(f"color: #ffffff; letter-spacing: 6px;")

        dot = QLabel("•")
        dot.setFont(QFont("DM Mono", 14))
        dot.setStyleSheet(f"color: {ACCENT.name()}; margin: 0 10px;")

        sub = QLabel("SPEED TEST")
        sub.setFont(QFont("DM Mono", 9))
        sub.setStyleSheet(f"color: rgba(200,210,235,0.45); letter-spacing: 3px;")

        close_btn = _CloseButton()
        close_btn.clicked.connect(self.close)

        titlebar.addWidget(brand)
        titlebar.addWidget(dot)
        titlebar.addWidget(sub)
        titlebar.addStretch()
        titlebar.addWidget(close_btn)
        container_layout.addLayout(titlebar)
        container_layout.addSpacing(24)

        # ── Gauge ──
        self.gauge = GaugeWidget()
        gauge_wrapper = QHBoxLayout()
        gauge_wrapper.addStretch()
        gauge_wrapper.addWidget(self.gauge)
        gauge_wrapper.addStretch()
        container_layout.addLayout(gauge_wrapper)
        container_layout.addSpacing(20)

        # ── Status label ──
        self.status_lbl = QLabel("Ready to measure your connection")
        self.status_lbl.setFont(QFont("DM Mono", 9))
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_lbl.setStyleSheet(f"color: rgba(200,210,235,0.45);")
        container_layout.addWidget(self.status_lbl)
        container_layout.addSpacing(28)

        # ── Stat cards ──
        cards_row = QHBoxLayout()
        cards_row.setSpacing(10)
        self.card_ping = StatCard("◎", "LATENCY")
        self.card_dl   = StatCard("↓", "DOWNLOAD")
        self.card_ul   = StatCard("↑", "UPLOAD")
        for c in (self.card_ping, self.card_dl, self.card_ul):
            c.setFixedWidth(114)
        cards_row.addStretch()
        cards_row.addWidget(self.card_ping)
        cards_row.addWidget(self.card_dl)
        cards_row.addWidget(self.card_ul)
        cards_row.addStretch()
        container_layout.addLayout(cards_row)
        container_layout.addSpacing(28)

        # ── Start button ──
        btn_row = QHBoxLayout()
        self.start_btn = PulseButton("START")
        self.start_btn.clicked.connect(self._toggle)
        btn_row.addStretch()
        btn_row.addWidget(self.start_btn)
        btn_row.addStretch()
        container_layout.addLayout(btn_row)

        container_layout.addStretch()

        # ── Footer ──
        footer = QLabel("Made with ❤️ by Hrishav")
        footer.setFont(QFont("DM Mono", 8))
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.setStyleSheet("color: rgba(200,210,235,0.25);")
        container_layout.addWidget(footer)

    # ── Drag to move ──
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag_pos and e.buttons() == Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, e):
        self._drag_pos = None

    # ── Test logic ──
    def _toggle(self):
        if self._worker and self._worker.isRunning():
            self._worker.terminate()
            self._worker = None
            self._reset_ui()
            return
        self._start_test()

    def _start_test(self):
        # Reset cards
        for card in (self.card_ping, self.card_dl, self.card_ul):
            card._value = "—"
            card._unit  = ""
            card._color = MUTED
            card.update()

        self.start_btn.set_running(True)
        self.gauge.set_phase("ping")
        self.status_lbl.setText("Finding best server…")

        self._worker = SpeedTestWorker()
        self._worker.phase_changed.connect(self._on_phase)
        self._worker.progress.connect(self._on_progress)
        self._worker.phase_result.connect(self._on_phase_result)
        self._worker.finished.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_phase(self, phase):
        self.gauge.set_phase(phase)
        # For mid-test phase switches (download→upload), snap needle instantly
        if phase in ("download", "upload"):
            self.gauge._display = 0.0
        if phase == "ping":
            self.gauge._max = 300.0
        elif phase == "download":
            self.gauge._max = 200.0
        elif phase == "upload":
            self.gauge._max = 200.0
        labels = {
            "ping":     "Measuring latency…",
            "download": "Testing download speed…",
            "upload":   "Testing upload speed…",
        }
        self.status_lbl.setText(labels.get(phase, ""))

    def _on_progress(self, phase, value):
        if self.gauge._phase != phase:
            return
        self.gauge.set_value(value)
        if phase == "ping":
            # Scale so current ping fills ~60% of arc — gives nice needle sweep
            self.gauge._max = max(value * 1.7, 50.0)
        elif value > self.gauge._max * 0.85:
            self.gauge._max = value * 1.25

    def _on_phase_result(self, phase, value):
        """Called immediately when a phase finishes — updates the stat card early."""
        if phase == "download":
            self.card_dl.set_result(f"{value:.1f}", "Mbps", speed_color(value))
        elif phase == "upload":
            self.card_ul.set_result(f"{value:.1f}", "Mbps", speed_color(value))
        elif phase == "ping":
            ping_color = GOOD if value < 30 else WARN if value < 80 else DANGER
            self.card_ping.set_result(f"{value:.0f}", "ms", ping_color)

    def _on_done(self, results):
        self._results = results
        self.gauge.set_phase("done")
        # Let needle sweep back to 0 smoothly (target=0, display animates down)
        self.gauge._target = 0.0

        ping = results.get("ping", 0)
        ping_color = GOOD if ping < 30 else WARN if ping < 80 else DANGER
        self.card_ping.set_result(f"{ping:.0f}", "ms", ping_color)

        dl = results.get("download", 0)
        self.card_dl.set_result(f"{dl:.1f}", "Mbps", speed_color(dl))

        ul = results.get("upload", 0)
        self.card_ul.set_result(f"{ul:.1f}", "Mbps", speed_color(ul))

        isp    = results.get("isp", "")
        server = results.get("server", "")
        self.status_lbl.setText(f"{isp}  ·  {server}" if isp else "Test complete")
        self.start_btn.set_running(False)

    def _on_error(self, msg):
        self.status_lbl.setText(f"Error: {msg}")
        self.gauge.set_phase("idle")
        self.start_btn.set_running(False)

    def _reset_ui(self):
        self.gauge.set_phase("idle")
        self.gauge.set_value(0)
        self.status_lbl.setText("Ready to measure your connection")
        self.start_btn.set_running(False)


# ── Helpers ───────────────────────────────────────────────────────────────────
class _RoundedPanel(QWidget):
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        path = QPainterPath()
        path.addRoundedRect(0, 0, w, h, 20, 20)

        # Background
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0, QColor(13, 16, 25, 245))
        grad.setColorAt(1, QColor(9,  11, 18, 245))
        p.fillPath(path, grad)

        # Border
        p.setPen(QPen(QColor(255, 255, 255, 18), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

        # Subtle top shine
        shine = QLinearGradient(0, 0, w, 0)
        shine.setColorAt(0,   QColor(0, 212, 255, 0))
        shine.setColorAt(0.5, QColor(0, 212, 255, 12))
        shine.setColorAt(1,   QColor(139, 92, 246, 0))
        p.setPen(QPen(QBrush(shine), 1))
        p.drawLine(20, 0, w - 20, 0)


class _CloseButton(QPushButton):
    def __init__(self):
        super().__init__("✕")
        self.setFixedSize(28, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,0.05);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 14px;
                color: rgba(200,210,235,0.5);
                font-size: 11px;
            }
            QPushButton:hover {
                background: rgba(244,63,94,0.25);
                border-color: rgba(244,63,94,0.4);
                color: #f43f5e;
            }
        """)


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Dark palette for any fallback widgets
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window,          QColor("#090b10"))
    pal.setColor(QPalette.ColorRole.WindowText,      QColor("#dde2f0"))
    pal.setColor(QPalette.ColorRole.Base,            QColor("#0f1219"))
    pal.setColor(QPalette.ColorRole.Text,            QColor("#dde2f0"))
    pal.setColor(QPalette.ColorRole.Button,          QColor("#0f1219"))
    pal.setColor(QPalette.ColorRole.ButtonText,      QColor("#dde2f0"))
    pal.setColor(QPalette.ColorRole.Highlight,       QColor("#00d4ff"))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#090b10"))
    app.setPalette(pal)

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
