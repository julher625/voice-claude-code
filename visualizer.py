#!/usr/bin/env python3
"""
Voice orb — Liquid Glass effect (Medium article by @aghajari) + Siri plasma.
GTK3 + Cairo + numpy/PIL for background lens distortion.

Physics from article:
  distortion(r) = 1 - sqrt(1 - r_norm²)      ← lens curve
  offset = distortion * direction * R * scale  ← pixel displacement
  chromatic: R shifted inward, B shifted outward ±ca_px
  gaussian blur: sigma ∝ (1 - r_norm*0.5)
"""

import argparse
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib

import cairo
import math
import sys
import threading

import numpy as np
from PIL import Image, ImageFilter

SIZE   = 340
SMOOTH = 0.13
R_FRAC = 0.80   # orb radius = R_FRAC * half_window

def _precompute_lighting(size: int, R: int):
    """
    Per-pixel physically-based lighting for a glass sphere.

    Math:
      N(x,y) = normalize(dx/R, dy/R, sqrt(1-(dx/R)²-(dy/R)²))  ← sphere normals
      V       = (0, 0, 1)                                         ← view direction
      L       = normalize(-0.45, -0.75, 0.48)                    ← light (top-left)
      H       = normalize(L + V)                                  ← Blinn-Phong half
      NdotL   = max(0, N·L)
      NdotH   = max(0, N·H)
      NdotV   = max(0, N·V) = nz
      Fresnel = F0 + (1-F0)*(1-NdotV)^5   [Schlick, F0=0.04 for glass]
      specular = Fresnel * NdotH^96
      diffuse  = 0.06 * NdotL * (1-Fresnel)
      shadow   = 0.20 * max(0, -NdotL)

    Returns (bright_surf, shadow_surf) as premultiplied ARGB32 Cairo surfaces.
    bright_surf → blend with OPERATOR_ADD  (adds white highlights)
    shadow_surf → blend with OPERATOR_OVER (darkens shadow hemisphere)
    """
    h = w = size
    cx = cy = size / 2.0

    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    dx = xx - cx
    dy = yy - cy
    mask = (dx*dx + dy*dy) <= (R * R)

    # ── Surface normals of a sphere ───────────────────────────────────
    nx_n = np.where(mask, dx / R, 0.0)
    ny_n = np.where(mask, dy / R, 0.0)
    nz_n = np.where(mask, np.sqrt(np.maximum(0.0, 1.0 - nx_n**2 - ny_n**2)), 1.0)

    # ── Light direction L (normalized) ────────────────────────────────
    Lx, Ly, Lz = -0.45, -0.75, 0.48
    lm = math.sqrt(Lx**2 + Ly**2 + Lz**2)
    Lx, Ly, Lz = Lx/lm, Ly/lm, Lz/lm

    # ── Blinn-Phong half-vector H = normalize(L + V), V=(0,0,1) ──────
    Hx, Hy, Hz = Lx, Ly, Lz + 1.0
    hm = math.sqrt(Hx**2 + Hy**2 + Hz**2)
    Hx, Hy, Hz = Hx/hm, Hy/hm, Hz/hm

    # ── Dot products ──────────────────────────────────────────────────
    NdotL = nx_n * Lx + ny_n * Ly + nz_n * Lz
    NdotH = np.maximum(0.0, nx_n * Hx + ny_n * Hy + nz_n * Hz)
    NdotV = np.maximum(0.0, nz_n)  # V=(0,0,1) so N·V = nz

    # ── Fresnel–Schlick: F0=0.04 for glass (n≈1.5) ───────────────────
    fresnel = 0.04 + 0.96 * np.power(1.0 - NdotV, 5)

    # ── BRDF terms ────────────────────────────────────────────────────
    specular = fresnel * np.power(NdotH, 64)   # wider highlight
    diffuse  = 0.14 * np.maximum(0.0, NdotL) * (1.0 - fresnel)
    shadow   = 0.32 * np.maximum(0.0, -NdotL)

    # AA fade at sphere edge — eliminates Cairo clip artifacts
    r_arr = np.sqrt(dx**2 + dy**2)
    aa    = 1.5
    aa_f  = np.clip((R - r_arr) / aa, 0.0, 1.0)

    bright = np.where(mask, np.clip(specular + diffuse, 0.0, 1.0), 0.0) * aa_f
    dark   = np.where(mask, np.clip(shadow, 0.0, 1.0), 0.0) * aa_f

    def _surf(r, g, b, a):
        # ARGB32 premultiplied: stored_rgb = color * alpha
        s = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        buf = np.frombuffer(s.get_data(), dtype=np.uint8).reshape(h, w, 4)
        buf[:,:,2] = np.clip(r * 255, 0, 255).astype(np.uint8)
        buf[:,:,1] = np.clip(g * 255, 0, 255).astype(np.uint8)
        buf[:,:,0] = np.clip(b * 255, 0, 255).astype(np.uint8)
        buf[:,:,3] = np.clip(a * 255, 0, 255).astype(np.uint8)
        s.mark_dirty()
        return s

    # Bright: premultiplied white → rgb = alpha = bright
    bright_surf = _surf(bright, bright, bright, bright)
    # Shadow: black at shadow alpha (rgb=0 premultiplied = black)
    zero = np.zeros_like(dark)
    shadow_surf = _surf(zero, zero, zero, dark)
    return bright_surf, shadow_surf


def _precompute_drop_shadow(size: int, R: int) -> "cairo.ImageSurface":
    """
    Mathematically computed drop shadow outside the sphere.

    Physics: parallel light from direction L casts a shadow on the
    background plane. The shadow center is offset opposite to L's
    screen-space projection by a small amount (simulating depth).
    Intensity uses Gaussian falloff: I = A · exp(-d / σ)
    where d = distance from the shadow-sphere edge.
    """
    h = w = size
    cx = cy = size / 2.0

    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    dx = xx - cx
    dy = yy - cy

    # Light screen-space direction (x,y components of L, normalized)
    Lx, Ly = -0.45, -0.75
    lm = math.sqrt(Lx**2 + Ly**2)
    Lx, Ly = Lx/lm, Ly/lm

    # Shadow projected slightly away from light (opposite direction)
    offset = R * 0.06
    sdx = dx + Lx * offset
    sdy = dy + Ly * offset

    r_shadow = np.sqrt(sdx**2 + sdy**2)
    dist_from_edge = np.maximum(0.0, r_shadow - R)

    # Gaussian falloff — σ = 12% of R
    sigma = R * 0.12
    intensity = 0.38 * np.exp(-dist_from_edge / sigma)

    # Zero inside the sphere (handled by the clip + glass)
    r_real = np.sqrt(dx**2 + dy**2)
    intensity = np.where(r_real > R, intensity, 0.0)

    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    buf  = np.frombuffer(surf.get_data(), dtype=np.uint8).reshape(h, w, 4)
    a    = (np.clip(intensity, 0, 1) * 255).astype(np.uint8)
    buf[:,:,0] = 0;  buf[:,:,1] = 0;  buf[:,:,2] = 0;  buf[:,:,3] = a
    surf.mark_dirty()
    return surf


def _build_bg_surface(bg_path: str, size: int, R: int,
                      screen_w: int, screen_h: int) -> "cairo.ImageSurface | None":
    """
    Exact port of the article's GLSL shader to numpy/PIL.

    Article formulas (GLSL):
      inversedSDF   = clamp((R - r) / R, 0, 1)          // 0 at edge, 1 at center
      distFromCenter = 1 - clamp(inversedSDF / 0.3, 0, 1) // only outer 30% band
      distortion    = 1 - sqrt(1 - distFromCenter²)
      offset        = distortion * dir * R * 0.5
      edge          = smoothstep(0.0, 0.02, inversedSDF)  // 0 at rim, 1 inside
      shift         = dir * edge * 3.0                    // chromatic px shift
      R_ch = sample(coord - offset - shift)
      G_ch = sample(coord - offset)
      B_ch = sample(coord - offset + shift)
      color *= 0.90
    """
    try:
        bg = Image.open(bg_path).convert("RGBA")
    except Exception:
        return None

    # If grim captured the exact region already, use as-is; otherwise crop
    if bg.width == size and bg.height == size:
        bg_crop = bg
    else:
        ox = (screen_w - size) // 2
        oy = (screen_h - size) // 2
        bg_crop = bg.crop((ox, oy, ox + size, oy + size))

    h = w = size
    bg_arr = np.array(bg_crop, dtype=np.float32)   # (H, W, 4) RGBA

    # Coordinate grids (pixel centres)
    cy_g, cx_g = h / 2.0, w / 2.0
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    dx = xx - cx_g
    dy = yy - cy_g
    r  = np.sqrt(dx * dx + dy * dy)

    # ── Article eq 1: inversedSDF ─────────────────────────────────────
    # For a circle: SDF = r - R, inversedSDF = -SDF / R = (R - r) / R
    inversedSDF = np.clip((R - r) / R, 0.0, 1.0)   # 0 at edge, 1 at center
    mask = r <= R                                    # circle mask

    # ── Article eq 2: distFromCenter ──────────────────────────────────
    # Outer 45% band distorted (wider than article's 30% for complex backgrounds)
    distFromCenter = 1.0 - np.clip(inversedSDF / 0.45, 0.0, 1.0)

    # ── Lens distortion ───────────────────────────────────────────────
    distortion = 1.0 - np.sqrt(np.maximum(0.0, 1.0 - distFromCenter ** 2))

    # Unit direction (safe divide at centre)
    safe_r = np.where(r > 0.5, r, 1.0)
    nx = dx / safe_r
    ny = dy / safe_r

    # ── Pixel offset — stronger scale so distortion is visible ────────
    off_x = distortion * nx * R * 0.72
    off_y = distortion * ny * R * 0.72

    # ── Chromatic aberration — wider band, stronger shift ─────────────
    # smoothstep over 8% instead of 2% → wider rainbow band at edge
    t    = np.clip(inversedSDF / 0.08, 0.0, 1.0)
    edge = t * t * (3.0 - 2.0 * t)
    shift_x = nx * (1.0 - edge) * 8.0   # max shift AT the rim (edge=0), fades inward
    shift_y = ny * (1.0 - edge) * 8.0

    # ── Sample RGB channels ───────────────────────────────────────────
    def sample(src, sx_arr, sy_arr):
        sx = np.clip(sx_arr.astype(np.int32), 0, w - 1)
        sy = np.clip(sy_arr.astype(np.int32), 0, h - 1)
        return src[sy, sx]

    r_ch = sample(bg_arr[:,:,0], xx - off_x - shift_x, yy - off_y - shift_y)
    g_ch = sample(bg_arr[:,:,1], xx - off_x,            yy - off_y)
    b_ch = sample(bg_arr[:,:,2], xx - off_x + shift_x, yy - off_y + shift_y)

    # ── Darken interior slightly ──────────────────────────────────────
    r_ch = np.where(mask, r_ch * 0.88, 0.0)
    g_ch = np.where(mask, g_ch * 0.88, 0.0)
    b_ch = np.where(mask, b_ch * 0.88, 0.0)

    # ── Gaussian blur — strong frosted-glass effect ───────────────────
    from PIL import ImageFilter as IF
    def blur_ch(arr):
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
        return np.array(img.filter(IF.GaussianBlur(radius=2.8)), dtype=np.float32)

    r_ch = blur_ch(r_ch)
    g_ch = blur_ch(g_ch)
    b_ch = blur_ch(b_ch)

    # ── Build Cairo ARGB32 premultiplied surface ─────────────────────
    # ARGB32 is premultiplied: stored_rgb = color * alpha/255
    # AA fade over 1.5px eliminates Cairo clip artifacts.
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    buf  = np.frombuffer(surf.get_data(), dtype=np.uint8).reshape(h, w, 4)

    aa   = 1.5
    af   = np.clip((R - r) / aa, 0.0, 1.0)          # 0→1 smooth fade at edge

    # Premultiply: stored = color * af
    buf[:,:,0] = np.clip(b_ch * af, 0, 255).astype(np.uint8)  # B premult
    buf[:,:,1] = np.clip(g_ch * af, 0, 255).astype(np.uint8)  # G premult
    buf[:,:,2] = np.clip(r_ch * af, 0, 255).astype(np.uint8)  # R premult
    buf[:,:,3] = (af * 255).astype(np.uint8)                   # A

    surf.mark_dirty()
    return surf


class OrbWindow(Gtk.Window):
    def __init__(self, bg_path=None):
        super().__init__()
        self._amp        = 0.0
        self._raw        = 0.0
        self._t          = 0.0
        self._show_alpha = 0.0
        self._bg_surf    = None

        self.set_decorated(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_app_paintable(True)
        self.set_accept_focus(False)
        self.set_default_size(SIZE, SIZE)
        self.set_title("voice-visualizer")

        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)
        css = Gtk.CssProvider()
        css.load_from_data(b"window { background: transparent; }")
        Gtk.StyleContext.add_provider_for_screen(
            screen, css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor()
        screen_w, screen_h = 1920, 1080
        mon_x, mon_y = 0, 0
        if monitor:
            geo = monitor.get_geometry()
            screen_w, screen_h = geo.width, geo.height
            mon_x, mon_y = geo.x, geo.y
            self.move(
                mon_x + (screen_w - SIZE) // 2,
                mon_y + (screen_h - SIZE) // 2,
            )

        # Take screenshot BEFORE showing the window so the background is clean.
        R_px = int(SIZE / 2 * R_FRAC)

        # Try --bg first, then self-shoot; always fall back to shoot if surf=None
        self._bg_surf = None
        for candidate in [bg_path, self._shoot_bg(mon_x, mon_y, screen_w, screen_h)]:
            if candidate:
                surf = _build_bg_surface(candidate, SIZE, R_px, screen_w, screen_h)
                if surf:
                    self._bg_surf = surf
                    break

        # Pre-compute per-pixel Phong lighting (static geometry, computed once)
        self._light_bright, self._light_shadow = _precompute_lighting(SIZE, R_px)
        # Pre-compute Gaussian drop shadow outside sphere
        self._drop_shadow = _precompute_drop_shadow(SIZE, R_px)

        da = Gtk.DrawingArea()
        da.connect('draw', self._draw)
        self.add(da)
        self.show_all()

        GLib.timeout_add(16, self._tick)
        threading.Thread(target=self._read_stdin, daemon=True).start()

    def _shoot_bg(self, mon_x, mon_y, screen_w, screen_h) -> "str | None":
        """Capture the orb region from Wayland before the window is visible."""
        import os, subprocess
        tmp = "/tmp/orb_bg_auto.png"
        ox = mon_x + (screen_w - SIZE) // 2
        oy = mon_y + (screen_h - SIZE) // 2
        env = {**os.environ}
        if "WAYLAND_DISPLAY" not in env:
            env["WAYLAND_DISPLAY"] = "wayland-1"
        if "XDG_RUNTIME_DIR" not in env:
            env["XDG_RUNTIME_DIR"] = f"/run/user/{os.getuid()}"

        log_lines = [f"shoot_bg: ox={ox} oy={oy} env_wayland={env.get('WAYLAND_DISPLAY')}"]
        for cmd in [
            ["grim", "-g", f"{ox},{oy} {SIZE}x{SIZE}", tmp],
            ["grim", tmp],
        ]:
            try:
                r = subprocess.run(cmd, timeout=3, capture_output=True, text=True, env=env)
                log_lines.append(f"cmd={cmd[0:2]} rc={r.returncode} stderr={r.stderr.strip()!r}")
                if r.returncode == 0:
                    with open("/tmp/viz_debug.log", "a") as f:
                        f.write("\n".join(log_lines) + "\n")
                    return tmp
            except Exception as e:
                log_lines.append(f"cmd={cmd[0:2]} exception={e}")

        with open("/tmp/viz_debug.log", "a") as f:
            f.write("\n".join(log_lines) + "\nshoot_bg FAILED\n")
        return None

    def _read_stdin(self):
        for line in sys.stdin:
            try:
                self._raw = float(line.strip())
            except ValueError:
                pass
        GLib.idle_add(Gtk.main_quit)

    def _tick(self):
        self._amp        += (self._raw - self._amp) * SMOOTH
        self._t          += 0.016
        self._show_alpha  = min(1.0, self._show_alpha + 0.04)
        self.get_child().queue_draw()
        return True

    # ──────────────────────────────────────────────────────────────────
    def _draw(self, da, cr):
        w  = da.get_allocated_width()
        h  = da.get_allocated_height()
        cx, cy = w / 2, h / 2
        R  = min(w, h) / 2 * R_FRAC

        fa  = self._show_alpha
        t   = self._t
        amp = self._amp

        # ── 0. Clear ────────────────────────────────────────────────
        cr.set_operator(cairo.OPERATOR_CLEAR)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)

        # No cr.clip() — all surfaces carry their own AA alpha (premultiplied).
        # This eliminates Cairo clip boundary artifacts entirely.

        # ── 1. Drop shadow (Gaussian, outside sphere) ─────────────────
        cr.set_source_surface(self._drop_shadow, 0, 0)
        cr.paint_with_alpha(fa)

        # ── 2. Distorted background (circle shape in alpha channel) ───
        if self._bg_surf:
            cr.set_source_surface(self._bg_surf, 0, 0)
            cr.paint_with_alpha(fa)
        else:
            cr.save()
            cr.arc(cx, cy, R, 0, 2 * math.pi)
            cr.set_source_rgba(0.12, 0.12, 0.14, fa * 0.85)
            cr.fill()
            cr.restore()

        # ── 3. Plasma waves (additive color over glass) ───────────────
        waves = [
            (0.18, 0.50, 1.00,  0.72, 0.00,  0.38, 0.56,  0.00,  0.068),
            (0.55, 0.12, 0.98,  0.58, 2.09,  0.36, 0.52,  1.05,  0.053),
            (1.00, 0.06, 0.30,  0.67, 4.19,  0.37, 0.54,  2.10,  0.062),
            (1.00, 0.38, 0.06,  0.51, 1.05,  0.35, 0.50,  3.15,  0.046),
            (0.06, 0.80, 1.00,  0.63, 3.14,  0.36, 0.52,  4.20,  0.058),
        ]
        range_boost = 0.88 + amp * 0.28
        cr.save()
        cr.arc(cx, cy, R, 0, 2 * math.pi)
        cr.clip()
        cr.set_operator(cairo.OPERATOR_ADD)
        for r, g, b, omega, phase, A, half_W, th_base, th_rate in waves:
            W = half_W * R
            d = (math.sin(t * omega + phase) * A +
                 math.sin(t * omega * 1.77 + phase * 1.31) * A * 0.28) * R * range_boost
            th = th_base + t * th_rate + math.sin(t * 0.24 + phase) * 0.10
            cos_th, sin_th = math.cos(th), math.sin(th)
            x0 = cx + cos_th * (d - W);  y0 = cy + sin_th * (d - W)
            x1 = cx + cos_th * (d + W);  y1 = cy + sin_th * (d + W)
            av = 0.22 * fa * (0.45 + amp * 0.55)
            grad = cairo.LinearGradient(x0, y0, x1, y1)
            grad.add_color_stop_rgba(0.00, r, g, b, 0.00)
            grad.add_color_stop_rgba(0.30, r, g, b, av * 0.60)
            grad.add_color_stop_rgba(0.50, r, g, b, av)
            grad.add_color_stop_rgba(0.70, r, g, b, av * 0.60)
            grad.add_color_stop_rgba(1.00, r, g, b, 0.00)
            cr.set_source(grad)
            cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        cr.restore()

        # ── 4. Physics lighting (Phong + Fresnel, circle shape in alpha)
        cr.set_source_surface(self._light_shadow, 0, 0)
        cr.paint_with_alpha(fa)

        cr.set_operator(cairo.OPERATOR_ADD)
        cr.set_source_surface(self._light_bright, 0, 0)
        cr.paint_with_alpha(fa * (0.8 + amp * 0.4))
        cr.set_operator(cairo.OPERATOR_OVER)



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--bg', default=None, help='Background screenshot path')
    args = parser.parse_args()

    win = OrbWindow(bg_path=args.bg)
    win.connect('destroy', Gtk.main_quit)
    Gtk.main()


if __name__ == '__main__':
    main()
