import numpy as np

from .stylize import stylize_image
from .render import process_rendering
from .segment import generate_and_merge_segments
from .layout import refine_layout_and_label

__all__ = ["PipoPainter"]


class PipoPainter:
    def __init__(self, k_colors=24, n_segments=3000):
        self.k_colors = k_colors
        self.n_segments = n_segments
        self.palette_rgb = None

    def stylize_image(self, img_rgb):
        return stylize_image(img_rgb)

    def process_rendering(self, stylized_img):
        render_img, labels, self.palette_rgb = process_rendering(stylized_img, self.k_colors)
        return render_img, labels

    def generate_and_merge_segments(self, stylized_img):
        return generate_and_merge_segments(stylized_img, self.n_segments)

    def refine_layout_and_label(self, final_segments, stylized_img):
        # 팔레트 정보가 없으면(process_rendering을 먼저 호출하지 않은 경우) 기본값 반환
        if self.palette_rgb is None:
            return stylized_img, np.zeros_like(stylized_img) + 255, stylized_img

        return refine_layout_and_label(final_segments, stylized_img, self.palette_rgb)
