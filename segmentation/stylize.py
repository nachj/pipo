import cv2
import numpy as np


def stylize_image(img_rgb):
    """[Step 2] 강력한 유화 효과 및 포스터화 적용"""
    # 1. 노이즈 제거 및 색상 단순화 (MeanShift 필터링)
    # sp: 공간 창 크기, sr: 색상 창 크기. 값을 높일수록 더 '그림' 같아집니다.
    # pyrMeanShiftFiltering은 원본 해상도(예: 1800px 폭)에서 돌리면 이 파이프라인
    # 전체에서 가장 느린 구간(수 초~10초)이 된다. 절반 크기로 축소해 처리한 뒤
    # 다시 확대해도 결과가 거의 동일해서(뭉치는 색 덩어리 크기가 목적이라 픽셀
    # 단위 정밀도가 중요하지 않음), 품질 손해 없이 속도만 크게 아낀다.
    bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
    small_bgr = cv2.resize(bgr, (bgr.shape[1] // 2, bgr.shape[0] // 2), interpolation=cv2.INTER_AREA)
    small_stylized = cv2.pyrMeanShiftFiltering(small_bgr, sp=15, sr=30)
    stylized = cv2.resize(small_stylized, (bgr.shape[1], bgr.shape[0]), interpolation=cv2.INTER_LINEAR)
    stylized = cv2.cvtColor(stylized, cv2.COLOR_BGR2RGB)

    # 2. 명도 및 대비 최적화 (이목구비 사수)
    lab = cv2.cvtColor(stylized, cv2.COLOR_RGB2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    l = clahe.apply(l)
    stylized = cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2RGB)

    # 3. 에지 보존 블러 (Median Filter) - 자잘한 픽셀 정리
    stylized = cv2.medianBlur(stylized, 5)

    # 4. 포스터화 효과 (색상 단계 강제 축소)
    # 이 과정을 거쳐야 3단계 Rendering에서 색이 예쁘게 뭉칩니다.
    n = 8  # 색상 단계 (낮을수록 더 그림 같음)
    stylized = np.uint8(np.floor(stylized / (256 / n)) * (256 / n))

    return stylized
