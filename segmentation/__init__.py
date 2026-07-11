import numpy as np

from .stylize import stylize_image
from .render import process_rendering
from .segment import generate_and_merge_segments
from .layout import refine_layout_and_label

__all__ = ["PipoPainter"]


class PipoPainter:
    # 가격대(등급)별 프리셋. "정교함은 색상 수(k_colors)에서만 나온다"는 원칙에 따라
    # 등급 간에는 k_colors만 뚜렷하게 벌리고, n_segments는 등급과 무관하게 고정값을
    # 쓴다(docs/pricing-tiers.md 1장/3장). min_area / color_merge_threshold(공간
    # 분할·병합 파라미터)도 여기 포함하지 않는다 — 등급과 무관하게 아래 클래스
    # 기본값을 그대로 쓴다. k_colors만 늘려도 공간 병합 후 서로 다른 팔레트 번호가
    # 맞닿을 확률이 높아져 총 영역 개수가 의도치 않게 늘어날 수 있으므로, 공간
    # 분할 파라미터를 등급별로 따로 키우면 그 효과가 배가되어 버린다.
    TIER_PRESETS = {
        "basic": {"k_colors": 16, "n_segments": 3000},
        "standard": {"k_colors": 24, "n_segments": 3000},
        "premium": {"k_colors": 32, "n_segments": 3000},
    }

    # 공간 분할 파라미터의 등급 공통 기본값. 등급이 올라가도 이 값들은 그대로
    # 유지하거나(기본) 필요 시 더 보수적으로(min_area를 키우는 방향으로만) 조정한다.
    # 절대 등급이 올라간다고 min_area를 줄이거나 threshold를 완화해서는 안 된다 —
    # 그러면 k_colors 증가와 겹쳐 영역이 과도하게 잘게 쪼개진다.
    DEFAULT_COLOR_MERGE_THRESHOLD = 5
    DEFAULT_MIN_AREA = 300

    def __init__(self, tier=None, k_colors=None, n_segments=None,
                 color_merge_threshold=None, min_area=None):
        """등급(tier) 또는 (k_colors, n_segments) 조합을 명시적으로 주입한다.

        - tier="basic"/"standard"/"premium": 등급별 프리셋(k_colors, n_segments)을 사용.
        - k_colors/n_segments를 직접 넘기면 tier 프리셋보다 우선한다(개별 override).
        - color_merge_threshold/min_area는 tier와 무관하게 항상 클래스 기본값을
          쓰며, 명시적으로 넘긴 경우에만 바뀐다(등급표에는 존재하지 않는 값).
        """
        if tier is not None:
            if tier not in self.TIER_PRESETS:
                raise ValueError(
                    f"알 수 없는 tier: {tier!r} (허용값: {sorted(self.TIER_PRESETS)})"
                )
            preset = self.TIER_PRESETS[tier]
        else:
            preset = {}

        self.tier = tier
        self.k_colors = k_colors if k_colors is not None else preset.get("k_colors", 24)
        self.n_segments = n_segments if n_segments is not None else preset.get("n_segments", 3000)
        # 색상 차이(LAB deltaE)가 이 값 미만이면 같은 번호로 병합한다. (등급 무관, 고정)
        self.color_merge_threshold = (
            color_merge_threshold if color_merge_threshold is not None
            else self.DEFAULT_COLOR_MERGE_THRESHOLD
        )
        # 이보다 작은 자투리 구획은 이웃 구획에 흡수시킨다(픽셀 단위). (등급 무관, 고정)
        self.min_area = min_area if min_area is not None else self.DEFAULT_MIN_AREA
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
