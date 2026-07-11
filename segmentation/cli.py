"""segmentation 패키지 단독 실행용 테스트 스크립트.

실행: python -m segmentation.cli
static/uploads/test.jpg 를 입력으로 받아 static/results/ 아래에 단계별 결과물을 저장합니다.
"""
import csv
import os

import numpy as np
from PIL import Image
from tqdm.auto import tqdm

from . import PipoPainter


def main():
    result_dir = "static/results/"
    if not os.path.exists(result_dir):
        os.makedirs(result_dir)

    # 등급별 정책 검증용: tier를 바꿔가며(basic/standard/premium) 결과를 비교해볼 수 있다.
    painter = PipoPainter(tier="standard")
    pbar = tqdm(total=5, desc="피포페인팅 도안 제작 중")

    # 1. 사진 로드 및 업사이징
    img_pil = Image.open("static/uploads/test.jpg").convert("RGB")
    w, h = img_pil.size
    target_w = 1800  # 고해상도 작업
    target_h = int(h * (target_w / w))
    raw_img = np.array(img_pil.resize((target_w, target_h), Image.LANCZOS))
    pbar.update(1)

    # 2. 그림처럼 변환 (Stylize)
    stylized_img = painter.stylize_image(raw_img)
    pbar.update(1)
    print("\n[2단계] 스타일 변환 완료")
    Image.fromarray(stylized_img).save(f"{result_dir}/step2_stylized.jpg")

    # 3. 렌더링 (Rendering - 색상 덩어리 확정)
    render_img, _ = painter.process_rendering(stylized_img)
    pbar.update(1)
    print("\n[3단계] 렌더링 완료 (색상 단순화)")
    Image.fromarray(render_img).save(f"{result_dir}/step3_rendered_base.jpg")

    # 4. 구획 분할 (Segmentation - 렌더링 기반)
    final_segments = painter.generate_and_merge_segments(stylized_img)
    pbar.update(1)

    # 5. 최종 결과물 생성 (Overlay & Paper & 완성 예상도)
    overlay_res, paper_res, rendered_res = painter.refine_layout_and_label(final_segments, stylized_img)
    pbar.update(1)
    pbar.close()

    # 최종 출력
    print("\n[최종 결과 1] 그림 위에 Overlay (검토용)")
    Image.fromarray(overlay_res).save(f"{result_dir}/final_overlay.jpg")

    print("\n[최종 결과 2] 흰 배경 구획 도안 (인쇄용)")
    Image.fromarray(paper_res).save(f"{result_dir}/final_paper_pattern.jpg")

    print("\n[최종 완성 예상도] 팔레트 채우기 결과")
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


if __name__ == "__main__":
    main()
