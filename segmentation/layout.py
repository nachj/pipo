import cv2
import numpy as np

_LABEL_FONT = cv2.FONT_HERSHEY_SIMPLEX
_LABEL_FONT_SCALE = 0.35
_LABEL_FONT_THICKNESS = 1


def _clamp_label_anchor(label, cx, cy, img_shape):
    """cv2.putText 앵커는 텍스트 baseline 좌하단 기준점이다. 지금까지는 (cx-5,
    cy+5)를 그대로 앵커로 써서, cx/cy가 이미지 가장자리에 가까우면(예:
    레이아웃 상 도형이 캔버스 끝에 걸친 구획) 실제로 그려지는 텍스트 폭/높이를
    고려하지 않은 채 캔버스 밖으로 텍스트 일부가 잘려 그려졌다.
    cv2.getTextSize로 실제 텍스트 bounding box를 구해서, 그 bounding box가
    항상 이미지 안쪽에 완전히 들어오도록 앵커 좌표를 clamp한다."""
    h_img, w_img = img_shape[:2]
    (text_w, text_h), baseline = cv2.getTextSize(
        label, _LABEL_FONT, _LABEL_FONT_SCALE, _LABEL_FONT_THICKNESS
    )

    ax, ay = cx - 5, cy + 5
    # 텍스트가 실제로 차지하는 영역: x in [ax, ax+text_w], y in [ay-text_h, ay+baseline]
    max_ax = max(0, w_img - 1 - text_w)
    ax = int(max(0, min(ax, max_ax)))
    min_ay = min(text_h, h_img - 1)
    max_ay = max(min_ay, h_img - 1 - baseline)
    ay = int(max(min_ay, min(ay, max_ay)))
    return ax, ay


def refine_layout_and_label(final_segments, stylized_img, palette_rgb):
    """[Step 5] 통합된 구획 기반으로 도안, 번호, 팔레트 채우기 결과 생성"""
    overlay_out = stylized_img.copy()
    paper_design = np.zeros_like(stylized_img) + 255

    # 주의: final_segments의 값은 0부터 시작하는 그룹 번호일 뿐이며, 0이
    # "배경"을 의미하지 않는다. 모든 값을 동일하게 취급해야 한다.
    #
    # 1. 팔레트 매칭: sid별 평균 색상으로 가장 가까운 팔레트 색상을 찾아
    # 화면 전체를 팔레트 번호(color_idx)로 채운 맵을 만든다.
    # sid는 세그멘테이션 단계의 임시 그룹일 뿐이라, 서로 다른 sid가 같은
    # 팔레트 번호로 매칭되고도 맞닿아 있으면 이 맵에서 하나의 픽셀 덩어리로
    # 합쳐진다 (윤곽선/번호는 아래에서 이 맵 기준으로 그리므로 중복 번호가
    # 나란히 찍히는 문제가 사라진다).
    #
    # sid마다 cv2.mean(mask=...)으로 전체 이미지를 훑는 파이썬 반복문은
    # 구획 수(수백 개)에 비례해 느려지므로, bincount로 sid별 평균 색상을 한
    # 번에 계산한다.
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

    # 구획별 평균 색상에 가장 가까운 팔레트 색상 찾기 (Euclidean distance)
    diff = palette_rgb.astype(np.float64)[None, :, :] - avg_colors[:, None, :]
    distances = np.linalg.norm(diff, axis=2)
    color_idx_per_seg = np.argmin(distances, axis=1)

    color_idx_map = color_idx_per_seg[inverse].reshape(final_segments.shape)
    rendered_res = palette_rgb[color_idx_map]

    # 2. 윤곽선 및 번호 로직 (팔레트 번호 단위)
    # 같은 번호라도 서로 떨어진 조각으로 나뉘어 있을 수 있으므로, 가장 큰
    # 조각 하나만 쓰지 않고 충분히 큰 조각 전부에 윤곽선과 번호를 표시한다.
    for color_idx in np.unique(color_idx_map):
        mask = (color_idx_map == color_idx).astype(np.uint8)
        cnts, _ = cv2.findContours(mask * 255, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # 가독성을 위해 color_idx + 1 사용 (1번부터 시작)
        label = str(color_idx + 1)

        for c in cnts:
            # 면적이 너무 작은 조각은 번호가 겹쳐 보이므로 제외
            # (자잘한 구획은 generate_and_merge_segments 단계에서 이웃에 흡수됨)
            if cv2.contourArea(c) < 50:
                continue

            # 윤곽선 그리기
            cv2.drawContours(overlay_out, [c], -1, (0, 0, 0), 1)
            cv2.drawContours(paper_design, [c], -1, (180, 180, 180), 1)

            # 번호 표시 (중심점 계산)
            # 주의: cv2.moments(c)는 컨투어 "다각형"이 구멍 없이 꽉 찬 도형이라고
            # 가정하고 중심을 계산한다. 오목하거나 도넛형(내부에 다른 색의 구멍이
            # 있는) 영역에서는 그 결과가 실제 마스크 바깥(=구멍 안쪽)에 찍힐 수
            # 있어, 번호 누락/다른 영역 번호와의 겹침으로 보인다.
            # 대신 이 컨투어에 해당하는 실제 이진 마스크 조각(구멍 제외)에
            # distanceTransform을 적용해 "마스크 내부에서 가장 안쪽인 점"
            # (pole of inaccessibility)을 구하면, 어떤 형상에서도 결과 좌표가
            # 항상 그 마스크 내부에 위치함이 보장된다.
            x, y, w, h = cv2.boundingRect(c)
            local_mask = np.zeros((h, w), dtype=np.uint8)
            cv2.drawContours(local_mask, [c], -1, 1, -1, offset=(-x, -y))
            # 다각형을 꽉 채운 뒤 실제 마스크와 교집합을 취해 구멍(다른 색
            # 영역)을 다시 파낸다 -> local_mask는 이 조각의 진짜 형상이 된다.
            local_mask &= mask[y:y + h, x:x + w]

            # M["m00"] <= 40 스킵과 동등하게, 실제 조각 면적(0이 아닌 픽셀 수)
            # 기준으로 너무 작으면 번호를 생략한다.
            if cv2.countNonZero(local_mask) > 40:
                # 주의: cv2.distanceTransform은 주어진 배열 "안"만 보고, 배열
                # 바깥에 배경(0) 픽셀이 있다는 사실을 전혀 모른다. local_mask는
                # 이 조각의 boundingRect에 딱 맞춘 배열이라서, 도형은 정의상
                # 이 배열 경계 중 어느 한 지점에서는 반드시 맞닿는다 — 그
                # 지점은 실제로는 도형의 진짜 가장자리인데도, distanceTransform은
                # "이 방향엔 배경이 없다(=아직 안쪽일 수 있다)"고 오인해서
                # 오히려 그쪽을 더 안전한(먼) 지점으로 잘못 판단할 수 있다.
                # 이 배열 경계가 하필 이미지 캔버스 가장자리와 겹치는
                # 구획에서는 이 편향이 극단적으로 나타나, "가장 안쪽인 점"이
                # 캔버스 맨 끝(cx=0, cy=0 등)으로 쏠려 버린다(번호가 잘려
                # 보이거나 다른 구획과의 경계에 걸쳐 보이는 원인).
                # local_mask 사방에 1픽셀 배경 테두리를 덧대면(copyMakeBorder)
                # distanceTransform이 이 배열 경계도 실제 배경(바깥)으로 인식해
                # 이 편향 없이 도형 내부의 진짜 가장 안쪽 점을 찾는다.
                padded_mask = cv2.copyMakeBorder(
                    local_mask, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0
                )
                dist = cv2.distanceTransform(padded_mask, cv2.DIST_L2, 5)
                _, _, _, max_loc = cv2.minMaxLoc(dist)
                # padding으로 밀린 좌표(+1)를 다시 원래 로컬 좌표계로 보정
                cx, cy = max_loc[0] + x - 1, max_loc[1] + y - 1

                # 위 padding 보정으로 대부분의 캔버스 가장자리 쏠림은 해소되지만,
                # 그와 무관하게 cv2.putText는 텍스트 크기를 고려하지 않고 그대로
                # 그리므로, cx/cy가 여전히 이미지 경계에 아주 가까운 경우를 대비해
                # 실제로 그려질 텍스트 폭/높이만큼 앵커를 캔버스 안쪽으로 clamp한다.
                label_pos = _clamp_label_anchor(label, cx, cy, overlay_out.shape)

                cv2.putText(overlay_out, label, label_pos,
                            cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 0), 1, cv2.LINE_AA)
                cv2.putText(paper_design, label, label_pos,
                            cv2.FONT_HERSHEY_SIMPLEX, 0.35, (80, 80, 80), 1, cv2.LINE_AA)

    return overlay_out, paper_design, rendered_res
