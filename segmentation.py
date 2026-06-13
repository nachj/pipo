import cv2
import json
import os
import numpy as np
from PIL import Image
from skimage.color import rgb2lab, deltaE_cie76,lab2rgb
from skimage.segmentation import slic, watershed
from skimage.filters import sobel
from sklearn.cluster import KMeans
from skimage import graph
from tqdm.auto import tqdm
from PIL import Image
import csv

class PipoPainter:
    def __init__(self, k_colors=24, n_segments=3000):
        self.k_colors = k_colors
        self.n_segments = n_segments
        self.palette_rgb = None

    def stylize_image(self, img_rgb):
        """[Step 2 수정] 강력한 유화 효과 및 포스터화 적용"""
        # 1. 노이즈 제거 및 색상 단순화 (MeanShift 필터링)
        # sp: 공간 창 크기, sr: 색상 창 크기. 값을 높일수록 더 '그림' 같아집니다.
        stylized = cv2.pyrMeanShiftFiltering(cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR),
                                             sp=15, sr=30)
        stylized = cv2.cvtColor(stylized, cv2.COLOR_BGR2RGB)

        # 2. 명도 및 대비 최적화 (이목구비 사수)
        lab = cv2.cvtColor(stylized, cv2.COLOR_RGB2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
        l = clahe.apply(l)
        stylized = cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2RGB)

        # 3. 에지 보존 블러 (Median Filter) - 자잘한 픽셀 정리
        stylized = cv2.medianBlur(stylized, 5)

        # 4. 포스터화 효과 (색상 단계 강제 축소)
        # 이 과정을 거쳐야 3단계 Rendering에서 색이 예쁘게 뭉칩니다.
        n = 8 # 색상 단계 (낮을수록 더 그림 같음)
        stylized = np.uint8(np.floor(stylized / (256/n)) * (256/n))

        return stylized

    def process_rendering(self, stylized_img):
        """[Step 3 수정] 강력한 색상 덩어리 형성 후 렌더링"""
        # 1. 시각적으로 비슷한 색들을 강제로 묶음 (MeanShift)
        # sp(공간 거리)와 sr(색상 거리)을 조절하여 뭉침 정도를 결정합니다.
        shifted = cv2.pyrMeanShiftFiltering(cv2.cvtColor(stylized_img, cv2.COLOR_RGB2BGR),
                                            sp=20, sr=40)
        shifted = cv2.cvtColor(shifted, cv2.COLOR_BGR2RGB)

        # 2. K-Means로 물감 색상 제한
        h, w, c = shifted.shape
        pixels = shifted.reshape(-1, 3)
        pixels_lab = rgb2lab(pixels / 255.0)

        kmeans = KMeans(n_clusters=self.k_colors, n_init="auto", random_state=42).fit(pixels_lab)
        self.palette_rgb = (lab2rgb(kmeans.cluster_centers_.reshape(-1, 1, 3)) * 255).astype(np.uint8).reshape(-1, 3)

        # 3. 렌더링 이미지 생성
        render_pixels = self.palette_rgb[kmeans.labels_]
        render_img = render_pixels.reshape(h, w, c)

        return render_img, kmeans.labels_.reshape(h, w)

    def generate_and_merge_segments(self, stylized_img):
        """[Step 3&4 통합] 세그멘테이션 후 유사 색상 구획 병합"""
        # 1. 초기 분할 (SLIC + Watershed)
        gray = cv2.cvtColor(stylized_img, cv2.COLOR_RGB2GRAY)
        gradient = sobel(gray)
        segments = slic(stylized_img, n_segments=self.n_segments,
                        compactness=0.1, start_label=1, enforce_connectivity=True)
        labels = watershed(gradient, segments)

        # 2. RAG(Region Adjacency Graph) 생성
        # 구획 간의 인접성과 색상 차이를 계산합니다.
        g = graph.rag_mean_color(stylized_img, labels)

        # 3. 색상 차이가 5 이하인 인접 구획 병합
        # 여기서 '5'는 LAB 색공간 혹은 RGB 차이 임계값으로 작동합니다.
        # 사용자님의 요청대로 차이가 적은 인접 구역을 하나로 합칩니다.
        labels_merged = graph.cut_threshold(labels, g, thresh=5)

        # 4. 병합된 구획의 대표 색상 결정 (가장 많이 등장하는 색상 혹은 평균 색상)
        # 실제 도안에는 구획별 평균 RGB를 사용합니다.
        final_label_map = labels_merged
        return final_label_map

    def refine_layout_and_label(self, final_segments, stylized_img):
        """[Step 5] 통합된 구획 기반으로 도안, 번호, 21색 채우기 결과 생성"""

        # 팔레트 정보가 없으면 기본값 반환
        if self.palette_rgb is None:
            return stylized_img, np.zeros_like(stylized_img) + 255, stylized_img

        overlay_out = stylized_img.copy()
        paper_design = np.zeros_like(stylized_img) + 255
        # [추가] 지정된 팔레트 색상으로 채워진 결과물을 담을 이미지
        rendered_res = np.zeros_like(stylized_img)

        seg_ids = np.unique(final_segments)

        for sid in seg_ids:
            if sid <= 0: continue  # 배경 또는 유효하지 않은 ID 제외

            # 현재 구역 마스크 생성
            mask = (final_segments == sid).astype(np.uint8)

            # 1. 팔레트 매칭: 구역의 평균 색상 계산
            avg_color = cv2.mean(stylized_img, mask=mask)[:3]
            avg_color_np = np.array(avg_color)

            # 2. 가장 가까운 팔레트 색상 찾기 (Euclidean distance)
            diff = self.palette_rgb.astype(np.float64) - avg_color_np.astype(np.float64)
            distances = np.linalg.norm(diff, axis=1)
            color_idx = np.argmin(distances)

            # 3. [중요] 해당 마스크 영역을 선택된 팔레트 색상으로 채우기
            best_color = self.palette_rgb[color_idx]
            rendered_res[mask == 1] = best_color

            # 4. 윤곽선 및 번호 로직
            cnts, _ = cv2.findContours(mask * 255, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not cnts: continue

            c = max(cnts, key=cv2.contourArea)
            # 면적이 너무 작은 구역은 도안 가독성을 위해 제외 (기존 50 -> 100 등 조절 가능)
            if cv2.contourArea(c) < 50: continue

            # 윤곽선 그리기
            cv2.drawContours(overlay_out, [c], -1, (0, 0, 0), 1)
            cv2.drawContours(paper_design, [c], -1, (180, 180, 180), 1)

            # 번호 표시 (중심점 계산)
            M = cv2.moments(c)
            if M["m00"] > 40:
                cx, cy = int(M["m10"] / M["m00"]), int(M["m01"] / M["m00"])

                # 가독성을 위해 color_idx + 1 사용 (1번부터 시작)
                label = str(color_idx + 1)

                cv2.putText(overlay_out, label, (cx-5, cy+5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 0), 1, cv2.LINE_AA)
                cv2.putText(paper_design, label, (cx-5, cy+5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.35, (80, 80, 80), 1, cv2.LINE_AA)

        return overlay_out, paper_design, rendered_res
    
    
if __name__ == "__main__":
    # --- 실행부 ---
    result_dir = "static/results/"
    if not os.path.exists(result_dir):
        os.makedirs(result_dir)
        
    painter = PipoPainter(k_colors=24, n_segments=3000)
    pbar = tqdm(total=5, desc="피포페인팅 도안 제작 중")

    # 1. 사진 로드 및 업사이징
    img_pil = Image.open("static/uploads/test.jpg").convert("RGB")
    w, h = img_pil.size
    target_w = 1800 # 고해상도 작업
    target_h = int(h * (target_w / w))
    raw_img = np.array(img_pil.resize((target_w, target_h), Image.LANCZOS))
    pbar.update(1)

    # 2. 그림처럼 변환 (Stylize)
    stylized_img = painter.stylize_image(raw_img)
    pbar.update(1)
    print("\n[2단계] 스타일 변환 완료")
    # display(Image.fromarray(stylized_img).resize((400, int(400 * h/w))))
    Image.fromarray(stylized_img).save(f"{result_dir}/step2_stylized.jpg")


    # 3. 렌더링 (Rendering - 색상 덩어리 확정)
    render_img, _ = painter.process_rendering(stylized_img)
    pbar.update(1)
    print("\n[3단계] 렌더링 완료 (색상 단순화)")
    # display(Image.fromarray(render_img).resize((400, int(400 * h/w))))
    Image.fromarray(render_img).save(f"{result_dir}/step3_rendered_base.jpg")

    # 4. 구획 분할 (Segmentation - 렌더링 기반)
    final_segments = painter.generate_and_merge_segments(stylized_img)
    pbar.update(1)

    # # 5. 최종 결과물 생성 (Overlay & Paper)
    # overlay_res, paper_res = painter.refine_layout_and_label(final_segments, render_img)
    # pbar.update(1)
    # pbar.close()

    # # 최종 출력
    # print("\n[최종 결과 1] 그림 위에 Overlay (검토용)")
    # display(Image.fromarray(overlay_res).resize((800, int(800 * h/w))))

    # print("\n[최종 결과 2] 흰 배경 구획 도안 (인쇄용)")
    # display(Image.fromarray(paper_res).resize((800, int(800 * h/w))))



    # 5. 최종 결과물 생성 (Overlay & Paper)
    overlay_res, paper_res, rendered_res = painter.refine_layout_and_label(final_segments, stylized_img)
    pbar.update(1)
    pbar.close()

    # 최종 출력
    print("\n[최종 결과 1] 그림 위에 Overlay (검토용)")
    # display(Image.fromarray(overlay_res).resize((800, int(800 * h/w))))
    Image.fromarray(overlay_res).save(f"{result_dir}/final_overlay.jpg")

    print("\n[최종 결과 2] 흰 배경 구획 도안 (인쇄용)")
    # display(Image.fromarray(paper_res).resize((800, int(800 * h/w))))
    Image.fromarray(paper_res).save(f"{result_dir}/final_paper_pattern.jpg")


    # 5. 최종 결과물 생성 (반환값 3개)


    # 결과 출력
    print("\n[최종 완성 예상도] 21색 팔레트 채우기 결과")
    # display(Image.fromarray(rendered_res).resize((800, int(800 * h/w))))
    Image.fromarray(rendered_res).save(f"{result_dir}/final_completed_preview.jpg")
    
    palette_csv_path = f"{result_dir}/palette_info.csv"
    
    try:
        with open(palette_csv_path, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            # 헤더 작성 (번호, R, G, B)
            writer.writerow(['Number', 'R', 'G', 'B', 'Hex_Code'])
            
            for i, rgb in enumerate(painter.palette_rgb):
                r, g, b = rgb
                # 가독성을 위해 1번부터 시작 (코드의 label과 일치)
                label = i + 1
                # 헥사 코드도 추가하면 나중에 색 찾기 편합니다
                hex_code = '#{:02x}{:02x}{:02x}'.format(r, g, b)
                writer.writerow([label, r, g, b, hex_code.upper()])
                
        print(f"\n🎨 팔레트 정보가 '{palette_csv_path}'에 저장되었습니다.")
        
    except Exception as e:
        print(f"\n❌ CSV 저장 중 오류 발생: {e}")


    print(f"\n✨ 모든 작업이 완료되었습니다. 결과물은 '{result_dir}' 폴더에서 확인하세요!")