import cv2
import numpy as np
from skimage.color import rgb2lab, lab2rgb
from sklearn.cluster import KMeans


def process_rendering(stylized_img, k_colors):
    """[Step 3] 강력한 색상 덩어리 형성 후 렌더링

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
    palette_rgb = (lab2rgb(kmeans.cluster_centers_.reshape(-1, 1, 3)) * 255).astype(np.uint8).reshape(-1, 3)

    # 3. 렌더링 이미지 생성
    render_pixels = palette_rgb[kmeans.labels_]
    render_img = render_pixels.reshape(h, w, c)

    return render_img, kmeans.labels_.reshape(h, w), palette_rgb
