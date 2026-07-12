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

`--check` 플래그를 주면 표 출력에 더해, 측정된 N_basic/N_standard/N_premium과
실제 팔레트 색상 수가 docs/pricing-tiers.md 4장/5장의 하드 컨스트레인트
(단조 증가, STANDARD<=BASIC*1.35, PREMIUM<=BASIC*1.55, 팔레트 색상 수 단조 증가)를
만족하는지 스크립트가 스스로 판정해서 PASS/FAIL과 위반 항목을 출력한다.
위반 시(혹은 3개 등급이 모두 갖춰지지 않아 판정 자체가 불가능할 때) 0이 아닌
종료 코드를 반환하므로 CI 등에서 게이트로 사용할 수 있다:

    python -m segmentation.qa_baseline --image static/uploads/211_36_147_192.jpg --check
"""
import argparse
import sys

import cv2
import numpy as np
from PIL import Image

from . import PipoPainter

# docs/pricing-tiers.md 4장의 배율 상한 (하드 컨스트레인트 2를 수치화한 값).
# 파라미터를 바꿔서 재측정한 뒤 이 상한을 다시 조정할 때는 반드시 그 문서도 함께 갱신한다.
STANDARD_RATIO_MAX = 1.35
PREMIUM_RATIO_MAX = 1.55


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


def check_hard_constraints(rows):
    """docs/pricing-tiers.md 4장/5장의 하드 컨스트레인트를 스스로 판정한다.

    rows에 basic/standard/premium 3개 등급이 모두 있어야 판정할 수 있다
    (등급 간 비율/단조 증가를 따지는 지표라 일부 등급만으로는 판정 불가).

    반환: (passed: bool, violations: list[str])
        violations가 비어 있으면 통과, 아니면 위반 항목 설명 목록.
    """
    by_tier = {r["tier"]: r for r in rows}
    required = ("basic", "standard", "premium")
    missing = [t for t in required if t not in by_tier]
    if missing:
        raise ValueError(
            "--check는 basic/standard/premium 3개 등급이 모두 있어야 판정할 수 있습니다 "
            f"(누락: {', '.join(missing)})"
        )

    basic, standard, premium = by_tier["basic"], by_tier["standard"], by_tier["premium"]
    violations = []

    n_b, n_s, n_p = basic["n_regions"], standard["n_regions"], premium["n_regions"]

    # 4장 - 단조 증가: N_basic <= N_standard <= N_premium (역전 없음)
    if not (n_b <= n_s <= n_p):
        violations.append(
            "단조 증가 위반 (N_basic <= N_standard <= N_premium 이어야 함): "
            f"N_basic={n_b}, N_standard={n_s}, N_premium={n_p}"
        )

    # 4장 - STANDARD 상한: N_standard <= N_basic * 1.35
    if n_b and n_s > n_b * STANDARD_RATIO_MAX:
        violations.append(
            f"STANDARD 상한 위반 (N_standard <= N_basic * {STANDARD_RATIO_MAX}): "
            f"N_standard/N_basic={n_s / n_b:.3f} (N_standard={n_s}, N_basic={n_b})"
        )

    # 4장 - PREMIUM 상한: N_premium <= N_basic * 1.55
    if n_b and n_p > n_b * PREMIUM_RATIO_MAX:
        violations.append(
            f"PREMIUM 상한 위반 (N_premium <= N_basic * {PREMIUM_RATIO_MAX}): "
            f"N_premium/N_basic={n_p / n_b:.3f} (N_premium={n_p}, N_basic={n_b})"
        )

    # 5장 - 실제 팔레트 색상 수 단조 증가: BASIC < STANDARD < PREMIUM
    c_b, c_s, c_p = basic["n_colors"], standard["n_colors"], premium["n_colors"]
    if not (c_b < c_s < c_p):
        violations.append(
            "실제 팔레트 색상 수 단조 증가 위반 (BASIC < STANDARD < PREMIUM 이어야 함): "
            f"n_colors basic={c_b}, standard={c_s}, premium={c_p}"
        )

    return (len(violations) == 0, violations)


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
    parser.add_argument("--check", action="store_true",
                         help="표 출력에 더해 docs/pricing-tiers.md 4장/5장의 하드 컨스트레인트"
                              "(단조 증가, STANDARD<=BASIC*1.35, PREMIUM<=BASIC*1.55, "
                              "팔레트 색상 수 단조 증가)를 자동 판정한다. "
                              "basic/standard/premium 3개 등급이 모두 필요하며, "
                              "위반 시 0이 아닌 종료 코드를 반환한다.")
    args = parser.parse_args()

    if args.check:
        missing = [t for t in ("basic", "standard", "premium") if t not in args.tiers]
        if missing:
            print(
                "--check는 --tiers에 basic/standard/premium이 모두 포함돼야 합니다 "
                f"(누락: {', '.join(missing)})",
                file=sys.stderr,
            )
            sys.exit(2)

    try:
        rows = run_qa(args.image, tuple(args.tiers), args.width)
    except FileNotFoundError:
        print(f"이미지를 찾을 수 없습니다: {args.image}", file=sys.stderr)
        sys.exit(1)

    print_table(rows)

    if args.check:
        print()
        passed, violations = check_hard_constraints(rows)
        if passed:
            print("[PASS] 하드 컨스트레인트 충족: 단조 증가 / STANDARD<=BASIC*"
                  f"{STANDARD_RATIO_MAX} / PREMIUM<=BASIC*{PREMIUM_RATIO_MAX} / "
                  "팔레트 색상 수 단조 증가")
        else:
            print("[FAIL] 하드 컨스트레인트 위반:")
            for v in violations:
                print(f"  - {v}")
            sys.exit(1)


if __name__ == "__main__":
    main()
