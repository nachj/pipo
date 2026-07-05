import cv2
import numpy as np
from scipy.cluster.hierarchy import linkage, fcluster
from scipy.spatial.distance import pdist
from skimage.color import rgb2lab, lab2rgb
from sklearn.cluster import KMeans


def _merge_similar_colors(centers_lab, labels, threshold):
    """LAB 색공간에서 색상 차이(deltaE)가 threshold 미만인 클러스터끼리 하나로 묶는다.

    KMeans는 색이 비슷해도 서로 다른 번호를 매길 수 있어서, 사람 눈에 거의
    같은 색인데 번호(팔레트 항목)만 다른 결과가 나온다. 여기서 그 클러스터들을
    합쳐 하나의 번호로 관리되게 한다.

    (단순 union-find/단일연결 방식은 그러데이션이 있는 사진에서 색이 점진적으로
    이어지며 서로 연쇄적으로 묶여버려("chaining") 전혀 다른 색까지 하나로
    뭉치는 문제가 있다. complete-linkage 계층적 군집화를 사용해 그룹 내 모든
    색상 쌍의 차이가 threshold 이내로 보장되게 한다.)
    """
    n = len(centers_lab)

    if n <= 1:
        return np.zeros_like(labels), centers_lab.copy()

    # deltaE_cie76 = LAB 공간에서의 유클리드 거리와 동일하다.
    distances = pdist(centers_lab, metric='euclidean')
    linkage_matrix = linkage(distances, method='complete')
    groups = fcluster(linkage_matrix, t=threshold, criterion='distance') - 1  # 0부터 시작

    n_groups = groups.max() + 1
    remap = groups  # 원본 클러스터 인덱스 -> 병합 그룹 인덱스

    merged_labels = remap[labels]

    # 병합된 그룹의 대표 색상 = 그룹에 속한 원본 클러스터 중심들의 평균
    merged_centers_lab = np.zeros((n_groups, 3))
    counts = np.zeros(n_groups)
    for i in range(n):
        g = remap[i]
        merged_centers_lab[g] += centers_lab[i]
        counts[g] += 1
    merged_centers_lab /= counts[:, None]

    return merged_labels, merged_centers_lab


def process_rendering(stylized_img, k_colors, color_merge_threshold=5):
    """[Step 3] 강력한 색상 덩어리 형성 후 렌더링

    비슷한 색(LAB deltaE < color_merge_threshold)의 팔레트 항목은 하나의
    번호로 병합해서 반환한다.

    반환값: (render_img, labels, palette_rgb)
    """
    # 1. 시각적으로 비슷한 색들을 강제로 묶음 (MeanShift)
    # sp(공간 거리)와 sr(색상 거리)을 조절하여 뭉침 정도를 결정합니다.
    shifted = cv2.pyrMeanShiftFiltering(cv2.cvtColor(stylized_img, cv2.COLOR_RGB2BGR),
                                        sp=20, sr=40)
    shifted = cv2.cvtColor(shifted, cv2.COLOR_BGR2RGB)

    # 2. K-Means로 물감 색상 제한
    h, w, c = shifted.shape
    pixels = shifted.reshape(-1, 3)
    pixels_lab = rgb2lab(pixels / 255.0)

    kmeans = KMeans(n_clusters=k_colors, n_init="auto", random_state=42).fit(pixels_lab)

    # 3. 비슷한 팔레트 색상끼리 병합해서 번호 개수를 줄임
    merged_labels, merged_centers_lab = _merge_similar_colors(
        kmeans.cluster_centers_, kmeans.labels_, color_merge_threshold
    )
    palette_rgb = (lab2rgb(merged_centers_lab.reshape(-1, 1, 3)) * 255).astype(np.uint8).reshape(-1, 3)

    # 4. 렌더링 이미지 생성
    render_pixels = palette_rgb[merged_labels]
    render_img = render_pixels.reshape(h, w, c)

    return render_img, merged_labels.reshape(h, w), palette_rgb
