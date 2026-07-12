import cv2
import numpy as np


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
                dist = cv2.distanceTransform(local_mask, cv2.DIST_L2, 5)
                _, _, _, max_loc = cv2.minMaxLoc(dist)
                cx, cy = max_loc[0] + x, max_loc[1] + y

                cv2.putText(overlay_out, label, (cx - 5, cy + 5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 0), 1, cv2.LINE_AA)
                cv2.putText(paper_design, label, (cx - 5, cy + 5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.35, (80, 80, 80), 1, cv2.LINE_AA)

    return overlay_out, paper_design, rendered_res
