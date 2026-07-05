import cv2
import numpy as np


def refine_layout_and_label(final_segments, stylized_img, palette_rgb):
    """[Step 5] 통합된 구획 기반으로 도안, 번호, 팔레트 채우기 결과 생성"""
    overlay_out = stylized_img.copy()
    paper_design = np.zeros_like(stylized_img) + 255
    # 지정된 팔레트 색상으로 채워진 결과물을 담을 이미지
    rendered_res = np.zeros_like(stylized_img)

    # 주의: final_segments의 값은 0부터 시작하는 그룹 번호일 뿐이며, 0이
    # "배경"을 의미하지 않는다. 모든 값을 동일하게 취급해야 한다.
    seg_ids = np.unique(final_segments)

    for sid in seg_ids:
        # 현재 구역 마스크 생성
        mask = (final_segments == sid).astype(np.uint8)

        # 1. 팔레트 매칭: 구역의 평균 색상 계산
        avg_color = cv2.mean(stylized_img, mask=mask)[:3]
        avg_color_np = np.array(avg_color)

        # 2. 가장 가까운 팔레트 색상 찾기 (Euclidean distance)
        diff = palette_rgb.astype(np.float64) - avg_color_np.astype(np.float64)
        distances = np.linalg.norm(diff, axis=1)
        color_idx = np.argmin(distances)

        # 3. 해당 마스크 영역을 선택된 팔레트 색상으로 채우기
        best_color = palette_rgb[color_idx]
        rendered_res[mask == 1] = best_color

        # 4. 윤곽선 및 번호 로직
        # 같은 sid라도 서로 떨어진 조각으로 나뉘어 있을 수 있으므로, 가장 큰
        # 조각 하나만 쓰지 않고 충분히 큰 조각 전부에 윤곽선과 번호를 표시한다.
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
            M = cv2.moments(c)
            if M["m00"] > 40:
                cx, cy = int(M["m10"] / M["m00"]), int(M["m01"] / M["m00"])

                cv2.putText(overlay_out, label, (cx - 5, cy + 5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 0), 1, cv2.LINE_AA)
                cv2.putText(paper_design, label, (cx - 5, cy + 5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.35, (80, 80, 80), 1, cv2.LINE_AA)

    return overlay_out, paper_design, rendered_res
