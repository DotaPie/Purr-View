import cv2

def draw_hud(   frame,
                bl: str,          # bottom-left  (required)
                br: str,          # bottom-right (required)
                tl: str = "",     # top-left
                tr: str = "",     # top-right
                tc: str = "",     # top-center
                bc: str = "",     # bottom-center
                height_ratio:   float = 0.05,
                margin_ratio:    float = 0.02,
                font = cv2.FONT_HERSHEY_SIMPLEX,
                color_fg = (255, 255, 255),   # white
                color_bg = (0, 0, 0)):         # black

    h, w = frame.shape[:2]
    margin = int(h * margin_ratio)
    
    # Scale thickness and background outline with resolution
    scaled_thickness = max(2, int(h * 0.005))  # Moderate thickness (about 4px at 720p, 5px at 1080p, 7px at 1440p)
    scaled_bg_extra = max(3, int(h * 0.008))   # Moderate outline (about 6px at 720p, 9px at 1080p, 11px at 1440p)

    # helper (width, height, baseline) at a given scale
    def _metrics(text, scale):
        (tw, th), base = cv2.getTextSize(text, font, scale, scaled_thickness)
        return tw, th, base

    # helper: draw outlined text
    def _draw(text, x, y, scale):
        if not text:
            return
        cv2.putText(frame, text, (x, y), font,
                    scale, color_bg, scaled_thickness + scaled_bg_extra, cv2.LINE_AA)
        cv2.putText(frame, text, (x, y), font,
                    scale, color_fg, scaled_thickness, cv2.LINE_AA)

    # Simple fixed scale for all text
    ((_, glyph_h), _) = cv2.getTextSize("Hg", font, 1, scaled_thickness)
    fixed_scale = (h * height_ratio) / glyph_h
    
    # Simple data collection - same scale for everything
    labels = {"TL": tl, "TR": tr, "BL": bl, "BR": br, "TC": tc, "BC": bc}
    data = {}
    
    for key, txt in labels.items():
        if txt:
            tw, th, base = _metrics(txt, fixed_scale)
            data[key] = dict(scale=fixed_scale, width=tw, height=th, base=base)
        else:
            data[key] = dict(scale=fixed_scale, width=0, height=0, base=0)

    # No collision detection - just use fixed scale

    # 5 render
    # top-left: y = margin + text-height  (keeps glyph top == margin)
    _draw(tl,
          margin,
          margin + data["TL"]["height"],
          data["TL"]["scale"])

    # top-right
    _draw(tr,
          w - data["TR"]["width"] - margin,
          margin + data["TR"]["height"],
          data["TR"]["scale"])

    # bottom-left: y = frame-height − baseline − margin
    _draw(bl,
          margin,
          h - data["BL"]["base"] - margin,
          data["BL"]["scale"])

    # bottom-right
    _draw(br,
          w - data["BR"]["width"] - margin,
          h - data["BR"]["base"] - margin,
          data["BR"]["scale"])

    # top-center
    _draw(tc,
          (w - data["TC"]["width"]) // 2,
          margin + data["TC"]["height"],
          data["TC"]["scale"])

    # bottom-center
    _draw(bc,
          (w - data["BC"]["width"]) // 2,
          h - data["BC"]["base"] - margin,
          data["BC"]["scale"])

    return frame