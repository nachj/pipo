import cv2
import numpy as np
from skimage.color import rgb2lab
from skimage.segmentation import slic, watershed
from skimage.filters import sobel
from skimage import graph


def _absorb_small_regions(label_map, min_area, max_passes=3):
    """min_area보다 작은 구획을 가장 많이 맞닿아 있는 이웃 구획에 흡수시킨다.

    이렇게 하지 않으면 자잘한 조각들이 번호판(도안)에 남아, 번호를 표시하기엔
    너무 작은데도 자기 번호를 고집해 다른 번호와 겹쳐 보이거나(중첩), 반대로
    너무 작아서 번호 자체가 안 찍히는(공백 구획) 문제가 생긴다.
    """
    labels = label_map.copy()
    kernel = np.ones((3, 3), np.uint8)

    for _ in range(max_passes):
        ids, counts = np.unique(labels, return_counts=True)
        small_ids = ids[counts < min_area]
        if len(small_ids) == 0:
            break

        for sid in small_ids:
            mask = (labels == sid).astype(np.uint8)
            if not mask.any():
                continue  # 이전 반복에서 이미 다른 구획에 흡수됨

            dilated = cv2.dilate(mask, kernel, iterations=2)
            neighbor_mask = (dilated > 0) & (labels != sid)
            neighbor_labels = labels[neighbor_mask]
            if neighbor_labels.size == 0:
                continue  # 맞닿은 다른 구획이 없음 (이미지 전체가 한 구획인 경우 등)

            values, freq = np.unique(neighbor_labels, return_counts=True)
            best_neighbor = values[np.argmax(freq)]
            labels[labels == sid] = best_neighbor

    return labels


def generate_and_merge_segments(stylized_img, n_segments, color_merge_threshold=5, min_area=300):
    """[Step 4] 세그멘테이션 후 유사 색상 구획 병합

    인접한 구획끼리 LAB 색공간 기준 색상 차이(deltaE)가 color_merge_threshold
    미만이면 하나의 구획으로 합치고, 그러고도 남은 min_area보다 작은 자투리
    구획은 가장 가까운 이웃 구획에 흡수시켜서 비슷한 색은 같은 번호로
    관리되게 한다.
    """
    # 1. 초기 분할 (SLIC + Watershed)
    gray = cv2.cvtColor(stylized_img, cv2.COLOR_RGB2GRAY)
    gradient = sobel(gray)
    segments = slic(stylized_img, n_segments=n_segments,
                    compactness=0.1, start_label=1, enforce_connectivity=True)
    labels = watershed(gradient, segments)

    # 2. RAG(Region Adjacency Graph) 생성
    # 사람이 느끼는 색 차이와 비교 가능하도록 RGB가 아닌 LAB 색공간에서 비교한다.
    # (RGB 0~255 값 기준으로 비교하면 threshold=5가 지나치게 엄격해 거의 병합되지 않는다.)
    img_lab = rgb2lab(stylized_img / 255.0)
    g = graph.rag_mean_color(img_lab, labels)

    # 3. 색상 차이(deltaE)가 threshold 미만인 인접 구획 병합
    # 주의: cut_threshold가 매기는 번호는 0부터 시작하는 임의의 그룹 번호일 뿐,
    # 0이 "배경"이나 "무효"를 의미하지 않는다. 이후 단계에서 0번 구획도 다른
    # 번호와 동일하게 처리해야 한다.
    labels_merged = graph.cut_threshold(labels, g, thresh=color_merge_threshold)

    # 4. 병합 후에도 남은 자투리 구획을 이웃에 흡수시켜 정리
    labels_merged = _absorb_small_regions(labels_merged, min_area)

    return labels_merged
