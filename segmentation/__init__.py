import numpy as np

from .stylize import stylize_image
from .render import process_rendering
from .segment import generate_and_merge_segments
from .layout import refine_layout_and_label

__all__ = ["PipoPainter"]


class PipoPainter:
    def __init__(self, k_colors=24, n_segments=3000, color_merge_threshold=5, min_area=300):
        self.k_colors = k_colors
        self.n_segments = n_segments
        # 색상 차이(LAB deltaE)가 이 값 미만이면 같은 번호로 병합한다.
        self.color_merge_threshold = color_merge_threshold
        # 이보다 작은 자투리 구획은 이웃 구획에 흡수시킨다(픽셀 단위).
        self.min_area = min_area
        self.palette_rgb = None

    def stylize_image(self, img_rgb):
        return stylize_image(img_rgb)

    def process_rendering(self, stylized_img):
        render_img, labels, self.palette_rgb = process_rendering(
            stylized_img, self.k_colors, self.color_merge_threshold
        )
        return render_img, labels

    def generate_and_merge_segments(self, stylized_img):
        return generate_and_merge_segments(
            stylized_img, self.n_segments, self.color_merge_threshold, self.min_area
        )

    def refine_layout_and_label(self, final_segments, stylized_img):
        # 팔레트 정보가 없으면(process_rendering을 먼저 호출하지 않은 경우) 기본값 반환
        if self.palette_rgb is None:
            return stylized_img, np.zeros_like(stylized_img) + 255, stylized_img

        return refine_layout_and_label(final_segments, stylized_img, self.palette_rgb)
