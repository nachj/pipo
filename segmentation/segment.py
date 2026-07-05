import cv2
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from skimage.color import rgb2lab
from skimage.segmentation import slic, watershed
from skimage.filters import sobel


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


def _merge_adjacent_by_color(labels, img_lab, threshold):
    """인접 구획 중 색상 차이(deltaE)가 threshold 미만인 것들을 하나로 합친다.

    skimage.graph.rag_mean_color + cut_threshold와 동일한 결과를 내지만,
    그 구현은 각 픽셀마다 파이썬 콜백을 호출하는 scipy.ndimage.generic_filter를
    써서 이미지 한 장에도 10초 이상 걸릴 만큼 느리다. 여기서는 같은 일을
    bincount(구획별 평균 색상)와 배열 시프트 비교(인접 쌍 탐색)만으로
    벡터화해서 처리한다.
    """
    n = int(labels.max()) + 1
    flat_labels = labels.ravel()

    # 1. 구획별 평균 색상 (LAB) 계산
    counts = np.bincount(flat_labels, minlength=n).astype(np.float64)
    mean_colors = np.empty((n, 3))
    for c in range(3):
        sums = np.bincount(flat_labels, weights=img_lab[..., c].ravel(), minlength=n)
        mean_colors[:, c] = sums / np.maximum(counts, 1)

    # 2. 인접한 구획 쌍 탐색 (상하좌우 + 대각선), 배열을 밀어서 비교하는 방식이라
    # 픽셀 수에 비례해 한 번에(벡터 연산으로) 끝난다.
    shifts = (
        (labels[:, :-1], labels[:, 1:]),
        (labels[:-1, :], labels[1:, :]),
        (labels[:-1, :-1], labels[1:, 1:]),
        (labels[:-1, 1:], labels[1:, :-1]),
    )
    a = np.concatenate([s[0].ravel() for s in shifts])
    b = np.concatenate([s[1].ravel() for s in shifts])
    diff = a != b
    a, b = a[diff], b[diff]

    lo = np.minimum(a, b).astype(np.int64)
    hi = np.maximum(a, b).astype(np.int64)
    edge_codes = np.unique(lo * n + hi)
    lo_u, hi_u = edge_codes // n, edge_codes % n

    # 3. 색상 차이가 threshold 미만인 변만 남겨서 그래프를 만들고,
    # 연결된 성분(connected components)을 새 그룹 번호로 사용한다.
    delta_e = np.linalg.norm(mean_colors[lo_u] - mean_colors[hi_u], axis=1)
    keep = delta_e < threshold
    edges = coo_matrix(
        (np.ones(keep.sum()), (lo_u[keep], hi_u[keep])), shape=(n, n)
    )
    _, group_ids = connected_components(edges, directed=False)

    return group_ids[labels]


def generate_and_merge_segments(stylized_img, n_segments, color_merge_threshold=5, min_area=300):
    """[Step 4] 세그멘테이션 후 유사 색상 구획 병합

    인접한 구획끼리 LAB 색공간 기준 색상 차이(deltaE)가 color_merge_threshold
    미만이면 하나의 구획으로 합치고, 그러고도 남은 min_area보다 작은 자투리
    구획은 가장 가까운 이웃 구획에 흡수시켜서 비슷한 색은 같은 번호로
    관리되게 한다.
    """
    # 1. 초기 분할 (SLIC + Watershed)
    # SLIC은 전체 파이프라인에서 가장 무거운 단계 중 하나라, 구획 경계 계산은
    # 절반 해상도에서 수행하고 결과 라벨맵만 원본 크기로 최근접(nearest) 확대한다.
    # 어차피 색상 병합/번호 매기기 단계에서 자잘한 경계는 다시 정리되므로, 구획
    # 경계가 약간 거칠어지는 정도는 최종 도안 품질에 영향을 주지 않는다.
    h, w = stylized_img.shape[:2]
    small = cv2.resize(stylized_img, (w // 2, h // 2), interpolation=cv2.INTER_AREA)

    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
    gradient = sobel(gray)
    segments = slic(small, n_segments=n_segments,
                    compactness=0.1, start_label=1, enforce_connectivity=True)
    small_labels = watershed(gradient, segments)
    labels = cv2.resize(small_labels.astype(np.int32), (w, h), interpolation=cv2.INTER_NEAREST)

    # 2~3. 인접 구획 중 색상 차이(deltaE)가 threshold 미만인 것들을 병합
    # 사람이 느끼는 색 차이와 비교 가능하도록 RGB가 아닌 LAB 색공간에서 비교한다.
    # (RGB 0~255 값 기준으로 비교하면 threshold=5가 지나치게 엄격해 거의 병합되지 않는다.)
    # 주의: 병합 후 매겨지는 번호는 0부터 시작하는 임의의 그룹 번호일 뿐,
    # 0이 "배경"이나 "무효"를 의미하지 않는다. 이후 단계에서 0번 구획도 다른
    # 번호와 동일하게 처리해야 한다.
    img_lab = rgb2lab(stylized_img / 255.0)
    labels_merged = _merge_adjacent_by_color(labels, img_lab, color_merge_threshold)

    # 4. 병합 후에도 남은 자투리 구획을 이웃에 흡수시켜 정리
    labels_merged = _absorb_small_regions(labels_merged, min_area)

    return labels_merged
