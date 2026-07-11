"""등급별(BASIC/STANDARD/PREMIUM) 파이프라인 결과를 한 번에 비교하는 QA 스크립트.

동일한 원본 이미지에 대해 세 등급(tier)을 모두 돌려서
docs/pricing-tiers.md 4장/5장의 대리 지표(총 영역 개수, 최소 영역 면적,
평균 영역 면적, 작은 영역 비율, 실제 팔레트 색상 수)를 표로 뽑아준다.

n_segments / min_area / color_merge_threshold 같은 공간 분할 파라미터를
바꿀 때마다 이 스크립트를 다시 돌려서 docs/pricing-tiers.md 4장의 실측
기준선(baseline)과 배율 상한이 여전히 유효한지 확인하는 용도다. 사람이
매번 손으로 3개 등급을 따로 돌려 눈으로 비교하지 않아도 되게 하는 것이
목적이며, 파이프라인 실행 로직(segment.py/layout.py/render.py) 자체는
전혀 건드리지 않는다.

실행 예:
    python -m segmentation.qa_baseline --image static/uploads/211_36_147_192.jpg
    python -m segmentation.qa_baseline --image static/uploads/test.jpg --tiers basic premium
"""
import argparse
import sys

import cv2
import numpy as np
from PIL import Image

from . import PipoPainter


def _count_labeled_regions(final_segments, stylized_img, palette_rgb):
    """실제로 번호가 매겨지는 영역들의 픽셀 면적 목록을 반환한다.

    layout.py::refine_layout_and_label과 동일한 팔레트 매칭
    (구획별 평균 색상 -> 최근접 팔레트 색상) + 번호 생략 임계값
    (`cv2.contourArea < 50` 또는 `M["m00"] <= 40`, docs/pricing-tiers.md 3장)을
    그대로 재현한 것이다. layout.py는 렌더링 이미지(overlay/paper/preview)를
    만드는 게 목적이라 영역 개수/면적 리스트를 따로 반환하지 않으므로,
    QA 측정에 필요한 부분만 여기서 읽기 전용으로 다시 계산한다
    (layout.py 자체는 수정하지 않는다 — 로직이 바뀌면 이 함수도 맞춰 갱신해야 함).
    """
    flat_segments = final_segments.ravel()
    seg_ids, inverse = np.unique(flat_segments, return_inverse=True)
    inverse = inverse.reshape(final_segments.shape).ravel()
    n_segs = len(seg_ids)

    flat_img = stylized_img.reshape(-1, 3).astype(np.float64)
    counts = np.bincount(inverse, minlength=n_segs).astype(np.float64)
    avg_colors = np.empty((n_segs, 3))
    for c in range(3):
        sums = np.bincount(inverse, weights=flat_img[:, c], minlength=n_segs)
        avg_colors[:, c] = sums / np.maximum(counts, 1)

    diff = palette_rgb.astype(np.float64)[None, :, :] - avg_colors[:, None, :]
    distances = np.linalg.norm(diff, axis=2)
    color_idx_per_seg = np.argmin(distances, axis=1)
    color_idx_map = color_idx_per_seg[inverse].reshape(final_segments.shape)

    areas = []
    for color_idx in np.unique(color_idx_map):
        mask = (color_idx_map == color_idx).astype(np.uint8)
        cnts, _ = cv2.findContours(mask * 255, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in cnts:
            if cv2.contourArea(c) < 50:
                continue
            M = cv2.moments(c)
            if M["m00"] > 40:
                areas.append(M["m00"])

    return areas


def _load_image(path, target_w):
    img_pil = Image.open(path).convert("RGB")
    w, h = img_pil.size
    target_h = int(h * (target_w / w))
    return np.array(img_pil.resize((target_w, target_h), Image.LANCZOS))


def run_qa(image_path, tiers=("basic", "standard", "premium"), target_w=1800):
    """tiers에 지정된 등급을 모두 돌려서 등급별 측정치 딕셔너리 리스트를 반환한다."""
    raw_img = _load_image(image_path, target_w)
    rows = []

    for tier in tiers:
        painter = PipoPainter(tier=tier)
        stylized = painter.stylize_image(raw_img)
        painter.process_rendering(stylized)
        final_segments = painter.generate_and_merge_segments(stylized)
        areas = _count_labeled_regions(final_segments, stylized, painter.palette_rgb)

        n_regions = len(areas)
        min_area = min(areas) if areas else 0
        avg_area = (raw_img.shape[0] * raw_img.shape[1] / n_regions) if n_regions else 0
        small_ratio = (sum(1 for a in areas if a <= 450) / n_regions) if n_regions else 0
        n_colors = len(painter.palette_rgb)

        rows.append({
            "tier": tier,
            "n_regions": n_regions,
            "min_area_px": round(min_area, 1),
            "avg_area_px": round(avg_area, 1),
            "small_ratio": round(small_ratio, 4),
            "n_colors": n_colors,
        })

    return rows


def print_table(rows):
    headers = ["tier", "n_regions", "min_area_px", "avg_area_px", "small_ratio", "n_colors"]
    widths = {h: max(len(h), *(len(str(r[h])) for r in rows)) for h in headers}

    def fmt_row(values):
        return " | ".join(str(v).ljust(widths[h]) for h, v in zip(headers, values))

    print(fmt_row(headers))
    print("-+-".join("-" * widths[h] for h in headers))
    for r in rows:
        print(fmt_row([r[h] for h in headers]))

    by_tier = {r["tier"]: r for r in rows}
    basic, standard, premium = by_tier.get("basic"), by_tier.get("standard"), by_tier.get("premium")

    print()
    if basic and standard and basic["n_regions"]:
        print(f"N_standard / N_basic = {standard['n_regions'] / basic['n_regions']:.3f}")
    if basic and premium and basic["n_regions"]:
        print(f"N_premium / N_basic  = {premium['n_regions'] / basic['n_regions']:.3f}")
    if basic and standard and premium:
        gap1 = standard["n_regions"] - basic["n_regions"]
        gap2 = premium["n_regions"] - standard["n_regions"]
        if gap1:
            print(f"(N_premium - N_standard) / (N_standard - N_basic) = {gap2 / gap1:.3f}  (목표: <= 1.5)")
        else:
            print("(N_premium - N_standard) / (N_standard - N_basic) = N/A (N_standard == N_basic)")


def main():
    parser = argparse.ArgumentParser(
        description="동일 이미지에 대해 BASIC/STANDARD/PREMIUM을 모두 돌려 "
                     "docs/pricing-tiers.md 4장/5장의 대리 지표(총 영역 개수, "
                     "최소/평균 영역 면적, 작은 영역 비율, 실제 팔레트 색상 수)를 표로 출력한다."
    )
    parser.add_argument("--image", default="static/uploads/test.jpg",
                         help="원본 이미지 경로 (기본: static/uploads/test.jpg)")
    parser.add_argument("--tiers", nargs="+", default=["basic", "standard", "premium"],
                         choices=["basic", "standard", "premium"],
                         help="측정할 등급 목록 (기본: 3개 등급 전부)")
    parser.add_argument("--width", type=int, default=1800,
                         help="처리 전 업사이징할 가로 폭 (기본 1800, cli.py와 동일)")
    args = parser.parse_args()

    try:
        rows = run_qa(args.image, tuple(args.tiers), args.width)
    except FileNotFoundError:
        print(f"이미지를 찾을 수 없습니다: {args.image}", file=sys.stderr)
        sys.exit(1)

    print_table(rows)


if __name__ == "__main__":
    main()
