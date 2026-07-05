import cv2
from skimage.segmentation import slic, watershed
from skimage.filters import sobel
from skimage import graph


def generate_and_merge_segments(stylized_img, n_segments):
    """[Step 4] 세그멘테이션 후 유사 색상 구획 병합"""
    # 1. 초기 분할 (SLIC + Watershed)
    gray = cv2.cvtColor(stylized_img, cv2.COLOR_RGB2GRAY)
    gradient = sobel(gray)
    segments = slic(stylized_img, n_segments=n_segments,
                    compactness=0.1, start_label=1, enforce_connectivity=True)
    labels = watershed(gradient, segments)

    # 2. RAG(Region Adjacency Graph) 생성
    # 구획 간의 인접성과 색상 차이를 계산합니다.
    g = graph.rag_mean_color(stylized_img, labels)

    # 3. 색상 차이가 5 이하인 인접 구획 병합
    # 여기서 '5'는 LAB 색공간 혹은 RGB 차이 임계값으로 작동합니다.
    labels_merged = graph.cut_threshold(labels, g, thresh=5)

    # 4. 병합된 구획의 대표 색상은 refine_layout_and_label 단계에서 결정됩니다.
    final_label_map = labels_merged
    return final_label_map
