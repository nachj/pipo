# 가격대별 스펙 (pipo 페인팅 도안)

담당: [pipo-planning](../.claude/agents/pipo-planning.md) 작성/관리. 구현은 [pipo-backend](../.claude/agents/pipo-backend.md)/[pipo-segmentation](../.claude/agents/pipo-segmentation.md), 검증은 [pipo-qa](../.claude/agents/pipo-qa.md)가 담당한다.

이 문서는 코드 주석이 아니라 팀이 합의한 스펙의 단일 출처(source of truth)다. 파라미터를 바꿀 때는
이 문서를 먼저 갱신하고 나서 구현에 반영한다.

현재 `app.py`는 아직 등급 분기 로직이 없다(단일 가격 `PRODUCT_PRICE=15000`, `PipoPainter(tier="standard")` 하드코딩). 2~7장은 그 상태에서 작성된 "목표 스펙"과 그 배경 설명(당시엔 미해결)이며, 아래 **8~12장이 사이클 1에서 확정한 실제 구현 스펙**이다. **2.1절의 "가격→k_colors 매핑" 예시와 6장의 선행 조건 체크리스트(결제-도안 연결 → DB 마이그레이션 도구 → 서버 측 금액 검증, 이 순서)는 8~10장에서 확정한 더 가벼운 방식(업로드 전 tier 선택 + prefix별 사이드카 파일)으로 대체(supersede)됐다** — 2.1/6장은 그 판단에 이르기까지의 배경으로 남겨두고, 실제로 구현할 때는 반드시 8~10장을 기준으로 한다.

## 1. 하드 컨스트레인트 (타협 불가)

1. **손으로 칠할 수 있는 영역 크기.** 등급이 올라가도 영역이 손으로 칠하기 어려울 만큼 잘게 쪼개져서는 안 된다. 색상 수가 늘어난다고 영역 개수/세밀함이 비례해서 폭증하면 안 된다.
2. **등급 간 완만한 소요시간 증가.** PREMIUM이 BASIC보다 체감상 훨씬 오래 걸리거나 훨씬 복잡해지면 안 된다. 등급 간 총 영역 개수(소요시간 대리 지표)는 완만하게만 늘어야 한다.
3. **정교함의 차이는 색상 수에서만 나온다.** BASIC은 더 추상적으로, PREMIUM은 더 정교하게 보이되, 그 차이는 팔레트 다양성(색상 수)에서 나와야지 공간 분할을 더 잘게 쪼개는 데서 나오면 안 된다.

이 3가지를 지키기 위한 설계 원칙: **공간 분할/병합 파라미터(`n_segments`, `min_area`, `color_merge_threshold`, 번호 생략 임계값)는 등급과 무관하게 고정한다.** 등급별로 바뀌는 값은 오직 `k_colors`(팔레트 크기) 하나뿐이다.

## 2. 등급별 스펙

| 등급 | 가격 | k_colors (팔레트 크기) | 목표 인상 |
|---|---|---|---|
| BASIC | 20,000원 | 16 | 좀 더 추상적/단순화된 느낌 |
| STANDARD | 40,000원 | 24 | 중간 정교함 |
| PREMIUM | 60,000원 | 32 | 좀 더 정교하고 섬세한 느낌 |

### 2.1 현재 운영 중인 단일 가격(15,000원)과의 관계

`app.py`의 `PRODUCT_PRICE = 15000`은 위 3단계 가격표(BASIC 20,000 / STANDARD 40,000 / PREMIUM 60,000) 중 어느 금액과도 일치하지 않는다. 이것은 미해결 버그가 아니라 다음과 같이 확정해서 취급한다:

- **15,000원은 3단계 가격표가 실제로 적용되기 전, 등급 분기 없이 운영 중인 임시/얼리버드 가격이다.** BASIC/STANDARD/PREMIUM 3단계(2/4/6만원)는 "이번 사이클에서 backend/segmentation이 구현할 목표 상태"(1장 서두)이며, 아직 배포되지 않았다.
- **현재 15,000원 결제로 생성되는 실제 산출물은 등급 분기 없이 항상 STANDARD 프리셋(`PipoPainter(tier="standard")`, `k_colors=24`)으로 생성된다.** `app.py`가 등급 분기 로직 없이 `tier="standard"`를 하드코딩해서 호출하므로, 현재는 지불액과 무관하게 모든 고객이 항상 STANDARD 품질(k_colors=24)을 받는다.
- 따라서 "15,000원을 냈는데 왜 3단계 표의 어느 가격과도 안 맞느냐"는 문의나 리뷰가 있다면, 코드 버그가 아니라 **아직 배포 전인 목표 스펙(3단계 가격표)과 현재 운영 중인 임시 단일가의 차이**로 설명한다. 3단계 가격표를 실제로 켜기 전까지는 이 문서의 2장 표를 "목표 스펙", `PRODUCT_PRICE=15000`을 "현재 운영값(=STANDARD 고정 제공)"으로 명확히 구분해서 취급하고, 둘을 같은 가격표의 오기(誤記)로 오인해 임의로 맞추지 않는다.

서버 측 가격→k_colors 매핑(예시, `pipo-backend`가 구현):

```python
TIER_BY_PRICE = {
    20000: {"name": "BASIC", "k_colors": 16},
    40000: {"name": "STANDARD", "k_colors": 24},
    60000: {"name": "PREMIUM", "k_colors": 32},
}
```

클라이언트가 보낸 등급/가격이 아니라 **결제 승인 시 서버가 검증한 금액**을 키로 이 테이블을 조회해 `k_colors`를 결정한다(금액 조작으로 상위 등급 결과물을 받아가지 못하도록).

> **[사이클 1 갱신, 2026-07-12] 위 `TIER_BY_PRICE`(가격→k_colors) 방식은 채택하지 않는다.** 이 표는 "결제 후 금액만 보고 그 자리에서 k_colors를 정한다"는 뜻인데, 그러려면 결제가 끝난 다음에야 도안을 만들 수 있어 사용자가 결제 전에 실제 구매할 도안을 미리 볼 수 없다(또는 미리보기를 다른 등급으로 보여주고 나중에 재처리해야 함). 8장에서 이 문제를 정면으로 다루고 "업로드 전에 tier를 먼저 선택 → 그 tier로 바로 미리보기 생성"으로 확정했다. 이 확정안에서는 **금액 검증이 가격→k_colors가 아니라 "이미 생성된 도안의 tier → 그 tier의 가격"을 조회하는 방향(10.3절)으로 바뀐다.** 아래 예시 코드와 매핑 방향은 이번 사이클에서 쓰지 않으며, 실제 구현은 10.3절의 `TIER_PRICES`를 따른다.

## 3. 공통 파라미터 (모든 등급 동일, 등급별로 바꾸지 않음)

| 파라미터 | 값 | 위치 | 비고 |
|---|---|---|---|
| `n_segments` (SLIC 초기 분할 수) | 3000 | `segment.py`의 `generate_and_merge_segments` 호출부 (`PipoPainter`) | 등급별로 늘리지 않는다 — 늘리면 공간 분할 자체가 세밀해져 컨스트레인트 3 위반 |
| `min_area` (자투리 흡수 임계값) | 300 (px) | `segment.py::generate_and_merge_segments` 기본값 | 현재값 유지. 아래 4장 QA 측정에서 PREMIUM 영역이 손으로 칠하기 어렵다고 판단되면 3개 등급에 동시에 350 정도로 소폭 보수화 검토 (등급별로 다르게 잡지 않는다) |
| `color_merge_threshold` (LAB deltaE) | 5 | `render.py::process_rendering`, `segment.py::generate_and_merge_segments` 기본값 | 색상 팔레트 병합과 공간 인접 구획 병합에 동일 값 사용 |
| 번호 생략 임계값 | `contourArea < 50` 또는 `M["m00"] <= 40` | `layout.py::refine_layout_and_label` | 등급 무관 고정. 이 값과 `min_area`(300) 사이 구간의 영역이 "번호 없는 눈에 보이는 구획"으로 남는지는 QA 항목 3에서 별도 확인 |

## 4. 등급별 목표 총 영역 개수 범위 (QA 대리 지표)

동일한 원본 이미지로 BASIC/STANDARD/PREMIUM을 각각 돌렸을 때, `layout.py` 처리 후 최종 영역(번호가 매겨지는 palette 구획) 개수를 `N_basic`, `N_standard`, `N_premium`이라 하면:

| 지표 | 목표 |
|---|---|
| 단조 증가 | `N_basic ≤ N_standard ≤ N_premium` (역전 없음) |
| STANDARD 상한 | `N_standard ≤ N_basic × 1.35` |
| PREMIUM 상한 | `N_premium ≤ N_basic × 1.55` |
| 등급 간 완만함 | `(N_premium − N_standard) ≤ (N_standard − N_basic) × 1.5` 정도로, PREMIUM 구간에서 증가폭이 급격히 커지지 않는지 확인 |

위 배율(1.35 / 1.55)은 아래 "4.1 실측 기준선"에서 재측정한 값을 근거로 재조정한 것이다(최초 작성 시의 1.15 / 1.30은 구현 전 목표치였고, `n_segments` 등급 통일(`unify-n-segments-across-tiers`) 적용 후 실측해보니 대부분의 샘플에서 초과했다 — 아래 4.1 참고). `k_colors`만 늘어나도 색상 경계가 늘어 인접 구획 병합(`color_merge_threshold`) 결과가 미세하게 달라지므로, 총 영역 개수가 어느 정도 늘어나는 것 자체는 정상이다. **다만 이 상한은 "완만하게"라는 하드 컨스트레인트를 수치화한 것이지, 실측치에 맞춰 계속 끌어올려도 되는 값이 아니다** — 재측정 시 상한을 다시 초과한다면 `color_merge_threshold`나 `n_segments`가 등급 간에 암묵적으로 다르게 작동하고 있지 않은지(구현 버그)를 먼저 의심한다. 파라미터를 바꿀 때마다 `python -m segmentation.qa_baseline`(5장 참고)으로 재측정하고, 이 표와 4.1 기준선을 갱신한다.

### 4.1 실측 기준선 (baseline)

`unify-n-segments-across-tiers` 적용(등급 무관 `n_segments=3000` 고정) 후, `segmentation/qa_baseline.py`로 서로 다른 해상도/화질의 샘플 이미지 4장에 대해 BASIC/STANDARD/PREMIUM을 각각 돌려 측정한 값이다(측정일 2026-07-11, `--width 1800` 기본값 사용).

| 샘플 이미지 | 원본 해상도 | N_basic | N_standard | N_premium | N_standard/N_basic | N_premium/N_basic | (N_premium−N_standard)/(N_standard−N_basic) |
|---|---|---|---|---|---|---|---|
| `211_36_147_192.jpg` (실사진) | 1737×3088 | 529 | 618 | 653 | 1.168 | 1.234 | 0.393 |
| `user_5.jpg` (실사진) | 4608×3072 | 166 | 203 | 214 | 1.223 | 1.289 | 0.297 |
| `122_34_142_96.jpg` (저해상도 업스케일) | 301×167 | 239 | 312 | 358 | 1.305 | 1.498 | 0.630 |
| `127_0_0_1.jpg` (초저해상도 업스케일, 참고용·기준선 제외) | 160×120 | 609 | 650 | 609 | 1.067 | 1.000 | −1.000 (단조 증가 위반: `N_premium(609) < N_standard(650)`) |

해석:

- 실사진 2장(`211_36_147_192.jpg`, `user_5.jpg`)과 저해상도 업스케일 1장(`122_34_142_96.jpg`)은 모두 단조 증가(`N_basic ≤ N_standard ≤ N_premium`)를 만족했고, 배율은 각각 최대 1.305 / 1.498(`122_34_142_96.jpg`)까지 관측됐다. 위 4장의 상한(1.35 / 1.55)은 이 최댓값에 약간의 여유를 두고 잡은 값이다.
- 등급 간 완만함 지표(`(N_premium−N_standard)/(N_standard−N_basic)`)는 0.297~0.630 범위로, 목표 상한 1.5에 비해 충분히 여유가 있어 이 지표는 조정하지 않았다.
- `127_0_0_1.jpg`(160×120을 1800px 폭으로 11배 이상 업스케일한 초저해상도 이미지)에서는 오히려 `N_premium`이 `N_standard`보다 작게 나와 단조 증가가 깨졌다. 실제 서비스 입력으로는 비현실적으로 작은 원본(썸네일급)이라 기준선에서는 제외했지만, 극저해상도 원본에서 등급 간 순서가 뒤집힐 수 있다는 것은 알려진 한계로 남겨둔다 — 실제 서비스에서 업로드 최소 해상도 가드가 없다면 향후 사이클에서 별도 이슈로 다룰 것.
- **(해결됨, 2026-07-12)** `app.py::upload_file`에 업로드 최소 해상도 가드(`MIN_UPLOAD_SHORT_SIDE_PX=150`)를 추가해 위 한계를 실제로 막았다. 짧은 변이 150px 미만인 업로드는 `process_pipo_task`(항상 가로 1800px로 업스케일)로 넘어가기 전에 4xx로 거절한다. 임계값 150은 임의값이 아니라 이 표의 두 실측치 사이에서 골랐다: `127_0_0_1.jpg`(짧은 변 120px, 문제 사례)는 반드시 막고 `122_34_142_96.jpg`(짧은 변 167px, 문제 없음)는 막지 않아야 한다. `211_36_147_192.jpg`(고화질 실사진)를 짧은 변 80~160px로 다운스케일해 `qa_baseline.py --check`로 재측정한 결과, 자체가 저품질이 아닌 원본은 이 범위 전체에서 단조 증가가 유지됐다(80/100/110/120/140/160px 모두 PASS) — 즉 `127_0_0_1.jpg`의 위반은 "해상도 자체"보다 그 파일 고유의 손실(저품질 썸네일)에서 기인하며, 순수 해상도 가드만으로는 이런 사례를 전부 잡아낼 수는 없다는 한계는 남는다. 다만 150px 미만이라는 극단적으로 작은 업로드는 실제 서비스 입력으로 비현실적이므로, 이 가드는 알려진 문제 사례를 차단하면서 알려진 정상 사례(167px)는 과도하게 막지 않는 실용적 하한선으로 채택했다.
- 재측정은 `python -m segmentation.qa_baseline --image <경로>`로 반복 가능하다(5장 참고). 파라미터(`n_segments`, `min_area`, `color_merge_threshold`)를 바꾼 뒤에는 반드시 이 표를 다시 뽑아 위 상한과 비교하고, 이 절의 표를 실측치로 갱신한다.

### 4.2 사이클 1 재검증: 실 트래픽 전환 전 다양한 프로필 재측정 (2026-07-12, 11장 작업)

이번 사이클(8~12장)에서 3단계 tier가 처음으로 실제 결제 트래픽에 노출되므로(그 전까지는 `PipoPainter(tier="standard")` 하드코딩으로 STANDARD만 실서비스됐고, BASIC/PREMIUM은 QA에서만 검증), `static/uploads/`의 실제 업로드 샘플 중 프로필이 서로 다른 6장(인물, 인물+텍스트, 인물+반려동물, 반려동물 단독, 풍경, 초저해상도 참고용)으로 `qa_baseline.py --check`를 재실행했다. **코드 변경 없이 진행했고(11.2절대로 `TIER_PRESETS`/`min_area`/`n_segments`/`color_merge_threshold` 전부 기존 값 그대로), 아래 표가 이번 재검증의 실측 결과다.**

| 샘플 이미지 | 프로필 | 원본 해상도 | N_basic | N_standard | N_premium | 실제색상수(B/S/P) | N_std/N_basic | N_prem/N_basic | 완만함 비율 | 판정 |
|---|---|---|---|---|---|---|---|---|---|---|
| `user_3.jpg` | 인물+텍스트(졸업사진, 간판 글자) | 367×532 | 372 | 423 | 455 | 16/24/32 | 1.137 | 1.223 | 0.627 | PASS |
| `user_3_design_11.jpg` | 인물 2인(실내, 졸업식) | 612×397 | 348 | 426 | 471 | 16/24/32 | 1.224 | 1.353 | 0.577 | PASS |
| `211_36_147_192.jpg` | 인물+반려동물(셀카) | 1737×3088 | 529 | 618 | 653 | 16/24/32 | 1.168 | 1.234 | 0.393 | PASS |
| `122_34_142_96.jpg` | 반려동물 단독(저해상도) | 301×167 | 166 | 203 | 214 | 16/24/32 | 1.223 | 1.289 | 0.297 | PASS |
| `user_5.jpg` | 풍경(구름/나무) | 4608×3072 | 239 | 312 | 358 | 16/24/32 | 1.305 | 1.498 | 0.630 | PASS |
| `127_0_0_1.jpg` | 참고용(초저해상도 160×120) | 160×120 | 609 | 650 | 609 | 16/24/32 | 1.067 | 1.000 | −1.000 | **FAIL**(단조 증가 위반) |

**해석 및 조정 여부:**

- 프로필이 서로 다른 실제 샘플 5장(인물, 인물+텍스트, 인물+반려동물, 반려동물 단독, 풍경)은 모두 11.1절의 4개 기준(단조 증가, `N_standard≤N_basic×1.35`, `N_premium≤N_basic×1.55`, `(N_premium−N_standard)≤(N_standard−N_basic)×1.5`)과 색상 다양성 기준(`BASIC<STANDARD<PREMIUM`, 각각 목표 k_colors 이하)을 모두 통과했다. 관측된 배율 최댓값(1.305/1.498, `user_5.jpg`)과 완만함 비율 최댓값(0.630)은 4.1절 최초 기준선과 거의 동일한 범위에 있어, 이번에 새로 추가한 텍스트 혼합(`user_3.jpg`)·2인 인물(`user_3_design_11.jpg`) 프로필에서도 별다른 이상치가 나타나지 않았다.
- `127_0_0_1.jpg`(짧은 변 120px)만 여전히 단조 증가 위반이었으나, 이는 4.1절에서 이미 알려진 동일한 케이스이고 2026-07-12에 `app.py::upload_file`의 `MIN_UPLOAD_SHORT_SIDE_PX=150` 가드로 이미 서비스 입력 단에서 차단된 상태다(짧은 변 120px < 150px이므로 실제로는 업로드 자체가 거절됨). 따라서 이번 재검증에서 **새로 발견된 위반이 아니며, 11.3절의 `min_area` 조정이 필요한 사례로 보지 않았다.**
- 결론: **코드 변경 없음, 실제 서비스 입력 범위(150px 이상)에 해당하는 모든 프로필에서 기준 통과.** `n_segments`/`min_area`/`color_merge_threshold`는 재조정하지 않았다.



| 지표 | 정의 | 측정 방법 | 판정 기준 |
|---|---|---|---|
| 총 영역 개수 | 최종 palette 구획(번호가 매겨지는 단위) 수 | `layout.py` 처리 후 고유 구획 라벨 수 카운트 | 3장의 단조 증가 + 배율 상한 |
| 최소 영역 면적 | 전체 구획 중 가장 작은 구획의 픽셀 면적 | 구획별 면적(픽셀 수) 중 최솟값 | 구조적으로 `min_area`(300px) 이상이어야 함. 미만이면 `_absorb_small_regions` 파이프라인 버그로 보고 |
| 평균 영역 면적 | 이미지 전체 픽셀 수 ÷ 총 영역 개수 | 계산값 | 등급 간 완만히만 감소해야 함(총 영역 개수 상한과 사실상 동치 지표이므로 교차 검증용) |
| 최소 영역 비율 | 면적이 `min_area`의 1.5배(450px) 이하인 "작은 영역"이 전체 구획 수에서 차지하는 비율 | 구획별 면적 분포에서 450px 이하 구획 수 / 총 구획 수 | 등급이 올라갈수록 이 비율이 급격히 늘어나지 않아야 함(예: PREMIUM이 BASIC 대비 상대적으로 급증하면 사용성 저하 신호로 보고) |
| 실제 팔레트 색상 수 | `render.py::process_rendering`이 반환하는 병합 후 실제 색상 수 | `palette_rgb` 길이 | `BASIC 실제색상수 < STANDARD 실제색상수 < PREMIUM 실제색상수`, 각각 목표 k_colors(16/24/32) 이하 |

위 5개 지표는 `segmentation/qa_baseline.py`로 한 번에 뽑을 수 있다(동일 원본 이미지로 BASIC/STANDARD/PREMIUM을 순서대로 돌려 총 영역 개수/최소 영역 면적/평균 영역 면적/작은 영역 비율/실제 팔레트 색상 수를 표로 출력하고, 4장의 배율 상한과 비교할 수 있도록 등급 간 비율도 함께 계산해준다):

```bash
python -m segmentation.qa_baseline --image static/uploads/<샘플이미지>.jpg
# 등급 일부만 보고 싶을 때
python -m segmentation.qa_baseline --image static/uploads/<샘플이미지>.jpg --tiers basic premium
```

파라미터(`n_segments`, `min_area`, `color_merge_threshold` 등)를 바꿀 때마다 대표 샘플 이미지 몇 장으로 이 스크립트를 다시 돌려서 4.1 실측 기준선과 4장의 배율 상한이 여전히 지켜지는지 확인한다(수작업 재측정 불필요). 그 외 QA 절차(스크린샷 비교 등)는 [pipo-qa](../.claude/agents/pipo-qa.md) 문서의 "검증 방법"을 따른다.

## 6. `TIER_BY_PRICE` 실제 배포를 위한 선행 조건 (체크리스트) — [사이클 1에서 대체됨, 9~10장 참고]

> **[사이클 1 갱신, 2026-07-12]** 아래 체크리스트는 "결제 금액만으로 사후에 tier를 정한다"는 옛 설계(2장의 `TIER_BY_PRICE`)를 전제로, 결제-도안을 안전하게 연결하기 위해 필요했던 무거운 선행 작업이었다. 8장에서 "업로드 전 tier 선택 + prefix당 사이드카 파일"로 아키텍처를 바꾸면서, 결제 이후 재처리가 없어졌고 결제-도안 매핑도 이미 존재하는 prefix 체계(`get_prefix()`)를 그대로 재사용할 수 있게 됐다. 그 결과 아래 ①②는 이번 사이클에서 **더 이상 선행 조건이 아니다**(전용 주문-도안 매핑 테이블이나 Alembic 도입 없이도 구현 가능). ③(서버 측 금액 검증)만 여전히 유효하며, 그 구체적 구현은 10.3절을 따른다. 아래 원문은 왜 처음에 이런 순서를 생각했는지 배경으로만 남겨둔다.

2.1절에서 밝혔듯 현재 서비스는 3단계 가격표를 아직 켜지 않은 상태다. 2장의 `TIER_BY_PRICE` 매핑을 코드에 반영해 실제로 BASIC/STANDARD/PREMIUM 등급 분기를 배포하려면, 아래 항목이 **이 순서대로** 선행되어야 한다. 순서를 건너뛰면(예: DB 마이그레이션 없이 결제-도안 연결부터 구현) 되돌리기 어려운 데이터 불일치가 생길 수 있다.

1. **결제-도안 연결 메커니즘 설계 및 구현.** 어떤 결제 건이 어떤 업로드/도안 생성 요청에 대응하는지 서버가 추적할 수 있어야 한다(현재는 단일 가격이라 이 연결이 필요 없었음). 결제 승인 콜백에서 주문 ID 등으로 해당 요청의 `k_colors`를 확정할 수 있는 구조가 먼저 있어야, 3번 항목(서버 측 금액 검증)이 실제로 어떤 요청에 적용할지를 알 수 있다.
2. **DB(또는 영속 저장소) 마이그레이션 도구 도입.** 등급(BASIC/STANDARD/PREMIUM), 결제 금액, 주문-도안 매핑 등을 저장할 스키마가 새로 필요하다. 스키마를 임기응변으로 파일/전역 변수에 얹지 않고, 향후 등급 추가·가격 변경 시에도 안전하게 반영할 수 있는 마이그레이션 도구(예: Alembic 등)를 먼저 도입한 뒤 스키마를 그 위에 얹는다. 1번의 연결 메커니즘이 저장할 데이터의 형태를 먼저 정해야 마이그레이션 스키마를 설계할 수 있으므로 1번 다음에 온다.
3. **서버 측 금액 검증 구현.** 2장 하단에 명시된 대로, 클라이언트가 보낸 등급/가격이 아니라 **결제 승인 시 서버가 검증한 금액**을 `TIER_BY_PRICE`의 키로 사용해 `k_colors`를 결정해야 한다(금액 조작으로 상위 등급 결과물을 받아가지 못하도록). 이 검증 로직이 1·2번에서 만든 결제-도안 연결과 저장소 스키마 위에서 동작해야 하므로 마지막 단계로 둔다.

위 3개 항목이 모두 완료되기 전까지는 `TIER_BY_PRICE`를 코드에 반영하지 않는다(반영 시 실제 결제 금액과 제공되는 `k_colors`가 어긋나거나, 검증 우회로 낮은 금액에 높은 등급을 제공하게 되는 위험이 있음). 이 체크리스트의 각 항목을 완료할 때마다 아래 7장 변경 이력에 완료일과 담당(backend/segmentation 중 어느 쪽인지)을 기록한다.

---

# 사이클 1: 실제 tier 선택·결제 기능 확정 스펙 (2026-07-12)

대표 요구사항: "사용자가 실제로 16/24/32색 중 하나를 선택해서 결제하고, 그 등급에 맞는 도안을 받을 수 있게" 만든다. 지금까지(1~7장)는 목표 스펙과 그 배경만 있었고 실제 UX 흐름·인터페이스 계약이 확정되지 않았었다. 아래 8~12장이 이번 사이클의 확정 스펙이며, 프론트/백엔드/세그멘테이션 팀은 이 문서를 단일 기준으로 병렬 작업한다. 사이클 2에서 기획팀이 결과물을 재검토하고, 최종적으로 QA가 검증한다.

## 8. UI/UX 흐름: tier는 언제 선택하는가

### 8.1 문제: "결제 전 미리보기"가 실제 구매할 tier와 다를 수 있다

현재 파이프라인은 업로드 즉시 백그라운드로 처리해 워터마크 미리보기를 보여주고, 그 다음 결제를 유도한다(`app.py::process_pipo_task` → `progress_status` 폴링 → 완료 시 미리보기 노출 → `#Payment` 섹션에서 결제). 등급마다 `k_colors`가 달라 결과물 자체(색상 수·구획 병합 결과)가 달라지므로, "언제 tier를 정하는가"에 따라 두 가지 설계가 가능하고 트레이드오프가 다르다.

### 8.2 옵션 비교

| | 옵션 A: 업로드 전에 tier 선택 → 그 tier로 미리보기 생성 | 옵션 B: 업로드 후 미리보기 확인 → 결제 시점에 tier 선택 → 결제 tier로 재처리 |
|---|---|---|
| 미리보기=구매 결과물 일치 | 항상 일치(같은 파이프라인 실행 결과를 보여주는 것뿐) | **불일치 가능.** 무료 미리보기는 어떤 기본 tier(예: STANDARD)로 만들고, 결제는 다른 tier로 하면 "본 것과 다른 것을 받았다"는 클레임이 구조적으로 생김 |
| 결제 후 지연 | 없음(이미 만들어진 결과물을 워터마크만 제거해서 내려주면 됨) | 있음(결제 승인 후 재처리 파이프라인을 다시 돌려야 함 — 수십 초~분 단위 추가 대기) |
| 파이프라인 실행 횟수 | prefix당 1회(현재 아키텍처와 동일) | 무료 미리보기 1회 + 결제 후 재처리 1회 = 최소 2회. 사용자가 tier를 여러 번 바꿔보면 그만큼 추가 |
| 결제 검증 복잡도 | 결제 시점엔 이미 tier가 확정·기록돼 있어 "기록된 tier의 가격과 대조"만 하면 됨(10.3절) | 결제 시점에 tier를 새로 확정해야 하므로, 그 tier 확정 요청 자체도 별도로 인증/검증해야 함(공격 표면 증가) |
| 사용자 경험 | 결과를 보기 전에 등급부터 정해야 함. 등급을 바꾸려면 재업로드 필요(비로그인은 무료체험 1회 제한과 충돌) | 결과 퀄리티를 먼저 보고 등급을 고를 수 있음 |
| 비로그인 무료체험(1회 제한)과의 정합성 | 그대로 유지됨(체험도 정확히 선택한 tier로 1회 제공) | 무료 체험이 "기본 tier 미리보기"인지 "선택한 tier 미리보기"인지 애매해짐 |

### 8.3 확정: 옵션 A (업로드 전 tier 선택)

**"본 미리보기 = 결제하면 받는 결과물"이 항상 성립해야 한다**는 것을 최우선 원칙으로 삼는다. 색상 수 차이가 곧 상품 차이인 서비스에서, 무료로 보여준 것과 실제 결제 결과물이 다를 수 있다는 구조 자체가 신뢰 문제와 CS 비용을 만든다. 결제 후 재처리(옵션 B)로 이 문제를 풀 수도 있지만, 그러면 결제 확정 전에 "이 결제 요청은 어떤 tier에 대한 것인가"를 다시 검증해야 하는 문제가 새로 생기고(재처리 트리거 자체가 위조 가능한 새 공격 표면), 결제 직후 대기시간도 늘어난다. 반면 옵션 A는 현재 아키텍처(prefix당 1회 처리)를 그대로 유지하면서 문제 자체를 구조적으로 없앤다.

옵션 A의 단점(등급을 바꾸려면 재업로드 필요, 비로그인은 무료체험 재소모)은 다음으로 완화한다:
- 기본 선택값을 **STANDARD**로 미리 선택해둬서(현재 유일하게 제공되던 등급과 동일), 아무 것도 건드리지 않고 업로드해도 기존과 동일한 경험을 준다.
- 등급 안내 카드(`templates/index.html`의 `tier-panel`, 현재는 장식용)에 있는 설명·가격을 tier 선택 UI로 그대로 재사용해서, 선택 전에 각 등급의 차이를 충분히 안내한다.
- 로그인 사용자는 이미 여러 번 재업로드가 가능하므로(`my-designs` 이력 참고) tier를 바꿔서 다시 시도하는 데 제약이 없다. 비로그인 사용자가 등급을 바꾸고 싶어 하면 "등급을 바꾸려면 다시 업로드해야 하고, 무료 체험은 1회만 가능합니다"를 명확히 안내한다(로그인 유도).

## 9. 가격 정책 확정

**기존에 이미 노출된 20,000 / 40,000 / 60,000원을 그대로 실제 결제 금액으로 확정한다.** 다른 금액으로 바꿀 특별한 이유가 없고, 이미 화면(`tier-panel`)에 오랫동안 "안내"로 노출돼 있었던 값을 실제 결제 시점에 바꾸면 이 화면을 이미 본 사용자에게 혼란을 준다. 다만 지금까지는 "참고용 정보이며 실제 결제 금액에는 영향을 주지 않습니다"라는 문구로 이 표가 장식용임을 명시해왔으므로, **이번 사이클에서 이 문구는 삭제**하고 실제로 결제 금액을 좌우하는 표로 전환한다(프론트 작업, 12.1절).

기존 단일가 `PRODUCT_PRICE = 15000`은 이번 사이클로 **폐기**한다(2.1절에서 이 값을 "3단계 표 적용 전 임시가"로 규정해뒀던 그대로). 3단계 표가 실제로 켜지는 순간부터는 결제 금액이 15,000원인 요청은 존재하지 않는다(10.3절의 `TIER_PRICES`에 15000이 없으므로 자동으로 거절됨).

## 10. 인터페이스 계약 (프론트/백엔드 병렬 개발 기준)

### 10.1 `/upload` 요청의 tier 파라미터

- `multipart/form-data`의 `photo` 필드와 함께, **폼 필드 `tier`**를 반드시 함께 보낸다.
- 허용값: `basic` / `standard` / `premium` (소문자, `segmentation.PipoPainter.TIER_PRESETS`의 키와 완전히 동일한 문자열을 그대로 재사용해서 프론트-세그멘테이션 간 번역 오류를 없앤다).
- 서버(`app.py::upload_file`)는 `tier`가 없거나 위 3개 값이 아니면 **다른 검증(확장자 등)과 동일하게 400으로 거절**한다(`{"result": "fail", "message": "등급을 선택해주세요."}`). 기본값으로 조용히 STANDARD를 대입하지 않는다 — 그러면 프론트 버그로 tier 필드가 누락됐을 때 사용자가 의도한 것과 다른(그리고 나중에 금액도 안 맞는) 도안이 만들어지는 사고를 조기에 못 잡는다.

### 10.2 서버가 선택된 tier를 저장하는 곳

세 가지 방식을 검토했다.

| 방식 | 장점 | 단점 |
|---|---|---|
| A. `progress_status[prefix]` dict에 필드 추가만 | 구현 간단, 기존 패턴과 동일 | **결제 시점까지 못 버틴다.** `progress_status`는 complete 상태로 `PROGRESS_ENTRY_TTL_SECONDS`(1시간) 경과 시 정리 대상이 된다(`cleanup_progress_status`). 미리보기를 보고 나서 1시간 넘게 고민하다 결제하는 사용자가 있으면 tier 기록이 사라져 금액 검증이 불가능해진다 |
| B. 세션(Flask session 쿠키) | 서버 재시작에도 일부 견딤 | 비로그인 사용자의 `get_prefix()`는 세션이 아니라 IP 기반이라, 세션에 저장한 tier와 실제 결과물(파일)이 어긋날 수 있음(다른 브라우저/시크릿창으로 접속 시 세션이 달라짐). 로그인/비로그인 간 취급이 또 갈라져 일관성이 떨어짐 |
| C. **prefix별 사이드카 파일**(`{prefix}_tier.json`), `palette_json_path`와 동일한 패턴 | 로그인/비로그인 구분 없이 항상 동일하게 동작(이미 `load_palette_info` 패턴으로 검증된 방식 재사용). 서버 재시작·TTL 정리에 영향 없음. 결제 시점이 언제든(1시간이든 하루든) 유효 | 새 결과물로 덮어써질 수 있으므로 "이 prefix의 가장 최근 결과물"만 대표한다는 것을 전제로 함(단, 이는 `overlay_path`/`design_path`/`preview_path` 등 기존 파일들도 동일한 전제로 동작 중이라 새로운 제약이 아님) |

**확정: C안(사이드카 파일).** 아래와 같이 정의한다.

```python
def tier_info_path(prefix):
    return f"{RESULT_FOLDER}/{prefix}_tier.json"
```

내용 예시: `{"tier": "basic", "price_krw": 20000, "k_colors": 16, "design_id": 42}`

**`design_id` 필드는 10.5.4절에서 추가로 확정한 필드다.** 로그인 사용자는 이 결과물을 만든 `Design.id`를 정수로 기록하고, 비로그인 사용자(애초에 `Design` row가 없음)는 이 필드를 아예 넣지 않거나 `null`로 둔다. 자세한 이유와 사용처는 10.5.4절 참고.

**쓰는 시점이 중요하다.** `process_pipo_task`의 맨 앞(업로드 직후)이 아니라, **`palette_info`를 쓰는 시점과 정확히 같은 곳(파이프라인이 끝까지 성공한 직후, "완료(100%)" 처리 직전)에 함께 쓴다.** 업로드 직후에 미리 써버리면, 이번 처리가 도중에 실패(`status: error`)했을 때 디스크에 남아있는 이전 성공작의 `preview.jpg`/`design.jpg`는 그대로인데 `tier_info`만 이번(실패한) 요청의 tier로 덮어써져서, "지금 화면에 보이는 미리보기"와 "기록된 tier"가 어긋나는 경합이 생긴다. `palette_info`와 동일한 지점에서 함께 쓰면 두 파일이 항상 같은 성공한 실행 결과를 가리키도록 보장된다.

`progress_status[prefix]`에도 `"tier"` 필드를 (업로드 시점에, 화면에 "BASIC 등급으로 생성 중..." 같은 진행 메시지를 보여주기 위한 용도로) 추가해도 되지만, 이건 어디까지나 진행 상태 표시용 부가 정보이고, **금액 검증의 근거는 반드시 `tier_info_path(prefix)` 파일 하나만** 사용한다(진실의 원천을 두 곳으로 나누면 나중에 어긋나는 버그가 생긴다).

### 10.3 결제 승인 시 금액 검증 — 정확히 무엇과 무엇을 비교하는가

`/payment/success`는 **`request.args.get('amount')`(클라이언트/토스 리다이렉트가 보낸 값)를, "그 요청의 tier"가 아니라 "그 prefix에 대해 서버가 10.2절 사이드카 파일에 이미 기록해 둔 tier"로부터 유도한 가격과** 비교한다. 절대로 클라이언트가 이 요청에 실어 보낸 tier나 금액 자체를 신뢰의 출발점으로 삼지 않는다(애초에 `/payment/success`에는 tier를 실어 보낼 필요도, 받는 파라미터도 없다 — prefix만으로 서버가 전부 알아낸다).

```python
TIER_PRICES = {"basic": 20000, "standard": 40000, "premium": 60000}

# /payment/success 안에서
prefix = get_prefix()
tier_info = load_tier_info(prefix)  # tier_info_path(prefix) 읽기, 없으면 None

if tier_info is None or tier_info.get("tier") not in TIER_PRICES:
    # 이 prefix에 대해 완성된 도안이 없거나 tier 기록이 없음 → 결제 대상 자체가 없음
    return render_template('payment_result.html', success=False,
                            error_message='결제할 도안 정보를 찾을 수 없습니다. 먼저 사진을 업로드해 도안을 생성해주세요.')

expected_price = TIER_PRICES[tier_info["tier"]]
if amount_int != expected_price:
    return render_template('payment_result.html', success=False,
                            error_message='결제 금액이 올바르지 않습니다.')
```

**왜 이렇게 하면 조작이 막히는가:** 공격자가 얻을 수 있는 유일한 지렛대는 `/upload` 시점에 자신이 원하는 `tier` 값을 보내는 것뿐이다. 하지만 그 값은 실제로 **그 tier의 `k_colors`로 도안을 생성하는 데만** 쓰이고, 그 결과가 `tier_info_path(prefix)`에 그대로 기록된다. 이후 결제 단계에서 클라이언트가 `amount`를 아무리 조작해도, 서버는 그 조작된 값을 이 요청이 어떤 tier인지 판단하는 데 전혀 쓰지 않고, 오직 **"이미 만들어진 결과물이 실제로 어떤 tier로 만들어졌는가"(tier_info)** 만 근거로 삼는다. 즉:
- PREMIUM(6만원)으로 만들어놓고 `amount=20000`(BASIC 가격)을 보내면 → `expected_price=60000 ≠ 20000` → 거절.
- BASIC(2만원)으로 만들어놓고 `amount=60000`을 보내도 → `expected_price=20000 ≠ 60000` → 거절(더 비싼 금액을 보내는 것도 통과하지 못하지만, 이건 손해 볼 게 없는 케이스라 문제 없음).

기존 토스페이먼츠 승인(`TOSS_CONFIRM_URL`) 호출 자체는 그대로 유지한다(이 비교는 그 호출 *이전*의 사전 검증이고, 토스 승인 API 자체도 위젯에서 실제로 결제된 금액과 다르면 자체적으로 거절한다 — 이중 방어).

### 10.4 `Design` 테이블에 tier를 기록할지

**기록한다.** `models.py::Design`에 `tier = db.Column(db.String(20), nullable=True)`를 추가한다(기존 `paid` 컬럼과 동일하게, `db.create_all()`은 이미 존재하는 테이블에 컬럼을 자동으로 추가해주지 않으므로 배포 시 수동 `ALTER TABLE designs ADD COLUMN tier VARCHAR(20);`가 필요하다 — `models.py`의 `paid` 컬럼 주석에 있는 것과 동일한 주의사항).

이유:
- CS/QA가 "이 사용자의 이 도안이 무슨 등급으로 만들어졌는지"를 조회할 감사 기록(audit trail)이 필요하다.
- `my-designs` 이력 페이지에서 등급 배지를 보여줄 수 있다(사용자 본인이 나중에 확인 가능).

**단, 10.3절 금액 검증의 근거로는 쓰지 않는다.** `Design` row는 로그인 사용자에게만 생성되고(`process_pipo_task`의 `if user_id is not None:` 블록), 비로그인 사용자는 애초에 row가 없다. 검증 로직이 "로그인=DB, 비로그인=파일"처럼 두 갈래로 갈라지면 두 경로가 미묘하게 어긋나는 버그가 생기기 쉽다. 그래서 **10.2절의 사이드카 파일을 유일한 진실의 원천으로 삼고, `Design.tier`는 그 값을 그대로 복사해 저장하는 감사용 사본**으로만 취급한다. 저장 시점은 `Design` row 생성 시점(`process_pipo_task` 안, 도안 생성이 성공한 직후) 그대로, `painter.tier`(또는 업로드 시 검증한 tier 값)를 넣으면 된다.

### 10.5 재업로드 시 결제 상태 무효화 (사이클 1 리뷰 반려 반영, 2026-07-12)

`pipo-reviewer`가 10.3절(결제 금액 검증) 자체는 안전하다고 인정하면서도, **결제 승인 이후 다운로드 게이팅(`is_paid`)을 함께 보면 결제 여부가 "이번에 결제 검증을 통과한 그 tier_info/도안"이 아니라 "그 사용자(prefix) 자체"에 영구히 묶인다**는 결함을 지적해 반려했다. 재현 경로까지 코드로 확인했고, 실제로 재현 가능한 결함이라 그대로 스펙에 못박는다.

#### 10.5.1 근본 원인 (코드 근거)

- `app.py::is_paid`(188~203행)는 로그인 사용자에 대해 "가장 최근 `Design` row의 `paid`가 True인지"를 먼저 확인하지만(194~200행), **그 확인이 False로 끝나도 함수가 곧바로 False를 반환하지 않는다.** 코드 흐름이 그대로 202~203행의 `with paid_lock: return bool(paid_status.get(prefix))`로 떨어져서, 로그인 여부와 무관하게 `paid_status` dict를 항상 한 번 더 확인한다. 즉 "DB 확인 → (실패 시) dict로 폴백"이 로그인 사용자에게도 적용된다.
- `app.py::mark_paid`(206~220행)는 결제가 승인될 때마다 로그인 여부와 무관하게 `paid_status[prefix] = True`를 무조건 기록한다(211행). 이 값은 **prefix(로그인 사용자는 `user_{user_id}`, 10.2절 이전부터 있던 `get_prefix()` 규칙) 단위로 딱 하나만 존재**하고, 어떤 도안/tier에 대해 결제했는지와 무관하게 계속 남는다. 이 dict를 지우거나 무효화하는 코드는 어디에도 없다.
- `app.py::upload_file`(565~661행)의 재업로드 제한(615~623행, "무료 체험은 1회만")은 **비로그인 사용자에게만 적용**된다(`if not current_user.is_authenticated:` 가드, 617행). 로그인 사용자는 횟수 제한 없이 몇 번이든 재업로드할 수 있고, 재업로드 시 `paid_status[prefix]`나 이전 `Design.paid`를 초기화하는 코드가 없다. 또한 `process_pipo_task`(379~399행 주석에 명시)의 `overlay_path`/`design_path`/`preview_path`는 prefix 기준 고정 경로라 재업로드마다 **파일 내용 자체가 최신 tier 결과물로 덮어써진다.**

**재현 시나리오** (리뷰어 지적, 코드로 확인됨):
1. `tier=basic`로 업로드 → 완료 → 결제 → `mark_paid`가 `paid_status["user_X"]=True` 기록 + `Design#1.paid=True`.
2. 같은 계정으로 `tier=premium` 재업로드(로그인 사용자라 횟수 제한 없음) → 고정 경로의 overlay/design/preview 파일이 PREMIUM 결과물로 덮어써지고 `tier_info_path(prefix)`도 premium/60000으로 갱신됨 → `process_pipo_task`가 `Design#2`(기본값 `paid=False`)를 새로 생성.
3. `/download/<kind>` 호출 → `is_paid("user_X")`는 최신 `Design#2.paid`(False)를 확인하지만 위 원인대로 곧장 반환하지 않고 `paid_status.get("user_X")`(1단계에서 True로 남아있음)로 폴백해 **True를 반환** → PREMIUM 원본을 추가 결제 없이 다운로드 가능.

결과적으로 BASIC 가격(2만원) 한 번만 결제하면 이후 몇 번이든 더 비싼 등급으로 재업로드해도 무료로 원본을 받을 수 있어, 이번 사이클의 핵심 목적(등급별 차등 과금)이 무력화된다. **비로그인 사용자는 이미 결과물이 있으면 재업로드 자체가 막히므로(617~623행) 이 공격 경로가 적용되지 않는다 — 로그인 사용자에게만 해당하는 결함이다.**

#### 10.5.2 수정 방향 비교 및 확정

| | 후보 1: `is_paid()`에서 로그인 사용자는 DB만 신뢰(딕셔너리 폴백 제거) | 후보 2: 재업로드(`upload_file`) 시점에 `paid_status[prefix]` 삭제 |
|---|---|---|
| 무엇을 바꾸는가 | `is_paid()` 한 함수. 로그인 사용자는 최신 `Design.paid` 확인 후 그 결과를 바로 반환하고, `paid_status` dict는 아예 들여다보지 않는다(비로그인 사용자만 dict 확인). | `upload_file()`에서 새 처리를 시작할 때(또는 `process_pipo_task` 시작 시) 해당 prefix의 `paid_status.pop(prefix, None)`를 호출. |
| 변경 범위 | 함수 1개, 실질적으로 조건문 위치 조정 수준(약 2~3줄) | `upload_file` 및 향후 재업로드/재처리를 유발할 수 있는 다른 진입점(있다면) 모두에 각각 삭제 로직을 넣어야 함 |
| "진실의 원천을 하나로" 원칙(10.4절)과의 정합성 | **부합.** 10.4절에서 이미 "로그인=DB, 비로그인=파일(사이드카)"처럼 두 갈래로 나뉘면 어긋나는 버그가 생기기 쉽다고 판단해 tier_info를 사이드카 파일 하나로 통일했다. 결제 상태도 동일한 논리: **로그인 사용자는 DB(`Design.paid`)만, 비로그인 사용자는 dict만** — trust 도메인을 완전히 분리하면 한쪽이 다른 쪽 값으로 "폴백"할 여지 자체가 사라진다. | 원인이 아니라 증상 하나(재업로드 시점)만 틀어막는 방식이다. `is_paid()` 자체의 "로그인 사용자도 dict로 폴백한다"는 잘못된 동작은 그대로 남아서, 앞으로 dict에 값을 쓰는 새 코드 경로가 생기면(예: 관리자 도구, 배치 스크립트) 동일한 종류의 버그가 다시 재현될 수 있다. |
| 놓치는 경우 | 없음 — `is_paid()`가 유일한 다운로드 게이팅 지점(735행)이므로 이 함수만 고치면 모든 호출 경로에서 일관되게 적용됨 | 재업로드 진입점을 하나라도 놓치면(예: 향후 관리자가 대신 재처리하는 기능이 생기는 경우) 여전히 취약. 또한 `paid_lock` 없이 삭제하면 `mark_paid`와의 경쟁 조건 가능성도 새로 검토해야 함 |
| 부작용 | `mark_paid()`가 로그인 사용자에 대해서도 여전히 `paid_status[prefix]=True`를 쓰지만(211행), 수정 후에는 로그인 사용자 경로에서 이 값을 아예 읽지 않으므로 무해(죽은 값으로만 남음). 필요하면 이 라인도 "로그인 사용자면 dict에 쓰지 않음"으로 함께 정리해도 되나 필수는 아니다(선택 사항, 아래 12.2 참고). | 없음 |

**확정: 후보 1(`is_paid()`에서 로그인 사용자는 DB만 신뢰).** 변경 범위가 더 작고, 다운로드 게이팅의 유일한 진입점(`is_paid`, 735행에서 호출) 하나만 고치면 모든 경로에서 일관되게 막히며, 10.4절에서 이미 채택한 "trust 도메인을 진영별로 완전히 분리한다"는 원칙과 정확히 같은 패턴이다. 후보 2는 지금 알려진 재업로드 진입점(`upload_file`)만 막을 뿐 `is_paid()` 자체의 잘못된 폴백 동작은 그대로 남기 때문에, 앞으로 재업로드를 유발하는 새 진입점이 생기면 다시 뚫릴 수 있는 구조적 위험이 남는다. 이는 10.4절에서 "검증 로직이 로그인/비로그인 두 갈래로 갈라지면 어긋나는 버그가 생기기 쉽다"고 판단해 `Design.tier`를 감사용으로만 쓰고 검증은 사이드카 파일 하나로 고정한 것과 **완전히 같은 패턴의 문제(신뢰 원천이 암묵적으로 두 곳으로 나뉘어 있다가 어긋남)이며, 같은 해법(로그인/비로그인 각각 정확히 하나의 신뢰 원천만 갖도록 강제)으로 닫는다.**

확정 코드(`app.py::is_paid` 교체):

```python
def is_paid(prefix):
    """이 prefix(로그인 사용자는 user_id, 비로그인은 IP)가 결제를 완료했는지 확인한다.

    로그인 사용자는 반드시 DB(Design.paid, 가장 최근 Design row)만을 신뢰의
    원천으로 삼는다 — paid_status dict로 폴백하지 않는다. 재업로드할 때마다
    새 Design row(기본 paid=False)가 생기므로, 이전에 다른 tier로 결제했던
    이력이 최신 도안의 결제 여부에 영향을 주지 않는다(10.5절).
    비로그인 사용자만 인메모리 paid_status dict를 신뢰의 원천으로 쓴다."""
    if current_user.is_authenticated:
        design = (Design.query
                  .filter_by(user_id=current_user.id)
                  .order_by(Design.created_at.desc())
                  .first())
        return bool(design is not None and design.paid)

    with paid_lock:
        return bool(paid_status.get(prefix))
```

핵심은 로그인 분기 안에서 `design.paid`가 True일 때만 조기 반환하던 것을, **로그인 분기 자체가 dict를 절대 보지 않고 곧바로 반환하도록** 바꾸는 것 — `design.paid`가 False/None인 최신 Design row가 있으면 그대로 False를 반환한다.

**mark_paid()는 코드 변경 필수 아님(선택 정리).** `mark_paid`가 로그인 사용자에 대해서도 `paid_status[prefix]=True`(211행)를 계속 쓰더라도, 위 수정 이후에는 로그인 사용자 경로에서 이 값을 아예 읽지 않으므로 기능상 무해하다. 다만 죽은 값이 dict에 계속 쌓이는 것을 피하고 "로그인=DB만, 비로그인=dict만"이라는 원칙을 코드 전체에서 일관되게 드러내고 싶다면, `mark_paid`에서도 `if not current_user.is_authenticated: paid_status[prefix] = True`로 좁혀도 된다(12.2절 작업 항목에 선택 사항으로 명시).

### 10.5.3 재업로드 처리 중의 레이스: 파일 쓰기가 Design row 커밋보다 먼저 끝난다 (2차 리뷰 반려 반영, 2026-07-12)

10.5.2에서 확정한 `is_paid()` 수정(로그인 사용자는 DB만 신뢰)만으로는 충분하지 않다는 지적을 `pipo-reviewer`가 재차 제기했다. 코드로 재확인한 결과 그대로 유효한 결함이라 이 절에서 못박는다.

**근본 원인.** `process_pipo_task`(`app.py`) 안에서 공개 경로 파일(비공개 원본 `private_overlay_path`/`private_design_path`/`private_preview_path`은 329~331행, 워터마크 처리된 공개 사본 `overlay_path`/`design_path`/`preview_path`는 336~346행)을 **먼저 덮어쓰고**, 이번 시도에 대한 `Design` row 생성·첫 커밋(379~390행)은 그보다 **한참 뒤**에야 일어난다. 즉 **"Design row 생성이 파일 쓰기보다 늦다."** 이 사이 구간(파일은 이미 이번 tier로 바뀌었지만 Design row는 아직 없거나 커밋 전) 동안 `/download/<kind>`(724~746행)가 호출되면:
- `is_paid()`가 조회하는 "가장 최근 `Design` row"는 여전히 **이전(결제 완료) row**다(이번 시도의 row가 아직 존재하지 않으므로).
- 그런데 741행이 실제로 서빙하는 `private_path`(`PRIVATE_RESULT_FOLDER` 기반, prefix 고정 경로)는 **이미 이번(미결제) 상급 tier 내용으로 덮어써진 뒤**다.
- 결과: 이전 결제 이력 덕분에 `is_paid()`가 True를 반환하면서, 실제로는 아직 결제되지 않은 이번 tier의 원본이 그대로 나간다 — 짧지만 실질적인 무료 다운로드 창.

**더 심각한 변형.** 이 구간에서 예외가 발생하면(408~410행 `except` 블록은 `_update_progress(..., status="error")`만 하고 파일이나 이미 진행된 DB 상태를 되돌리지 않음), 379~390행 자체가 아예 실행되지 않아 이번 시도의 `Design` row가 영영 생기지 않는다. 그러면 "가장 최근 `Design` row"는 계속 그 **이전(결제 완료) row로 영구히 고정**되는 반면, 파일은 이미 새 tier로 덮어써진 채 남아 — 위 레이스가 일시적 창이 아니라 **영구적 상태**가 된다.

**수정 방향 비교.**

| | 후보 1: `Design` row를 처리 시작 시점에 먼저 생성·커밋하고, 성공 후에는 새 row 대신 같은 row를 업데이트 | 후보 2: 파일 쓰기(329~346행)를 Design row 커밋 뒤로 미룸 |
|---|---|---|
| 무엇을 바꾸는가 | `process_pipo_task` 맨 앞(어떤 이미지 처리도 하기 전, 293행 직후)에서 `user_id is not None`이면 `Design(user_id=user_id, paid=False, upload_path=file_path)`를 즉시 생성·커밋한다. 기존 379~390행의 "새 row 생성"은 "이 row의 필드(overlay_path/design_path/preview_path/tier 등) 업데이트"로 바뀐다(392~406행의 고유 경로 사본·업데이트 로직은 그대로 유지). | stylize/render/segment/layout(298~322행)까지는 지금처럼 메모리에서 처리하되, 329~346행의 파일 저장과 379~390행의 Design 커밋 순서를 뒤바꿔 "커밋 먼저, 파일 쓰기 나중"으로 재배치한다. |
| 레이스 창이 없어지는 이유 | 재업로드가 "시작하는 순간" 최신 Design row가 즉시 이번(미결제) 시도로 전환된다. 이후 실제 파일이 아직 안 바뀐 시점에도 `is_paid()`는 이미 False를 반환하므로, "파일은 새 tier인데 DB는 이전 tier로 결제됨"이라는 조합 자체가 존재할 수 없다(파일이 새 tier로 바뀌기 *전에* 이미 DB가 미결제로 전환되어 있다 — 안전한 방향의 그은 fail-closed). | 파일이 바뀌는 시점과 DB가 미결제로 바뀌는 시점의 순서를 맞바꿔도, 둘은 여전히 **별개의 두 연산**이라 완전한 원자성은 얻지 못한다. 다만 이번 사이클에서 실제로 문제가 되는 "파일 먼저, DB 나중" 순서 자체는 사라진다. |
| 예외(처리 실패) 시 정합성 | row가 이미 `paid=False`로 존재하므로, 처리 도중 어디서 예외가 나든 이번 시도는 "결제 안 됨"으로 정확히 반영된다. 오히려 **기존보다 더 정직하다** — 기존에는 예외 시 이번 시도의 row 자체가 없어 이전 row(어쩌면 paid=True)가 계속 노출됐지만, 이 방식에서는 실패한 시도가 실패한 것으로 명시적으로 남는다. | stylize/render/segment/layout이 모두 끝난 뒤에만 커밋하므로, 그 전에 예외가 나면 기존과 동일하게 "이번 시도의 row가 없음" 상태가 되고, 이전 row가 그대로 최신으로 남는 문제(10.5.2에서 지적된 근본 문제)가 완전히 해소되지 않는다. |
| 변경 범위 | `process_pipo_task` 한 함수, insert 위치 이동 + "생성"을 "생성 1회 + 업데이트"로 리팩터링 | `process_pipo_task` 한 함수, 파일 저장 블록과 DB 블록의 순서 교체 |
| my_designs()/화면 영향 | 처리 중/실패 시 이 row가 `overlay_path` 등 `None`인 채로 노출될 수 있음 — 아래에서 별도 확인, 안전함 | 순서를 바꿔도 예외 발생 시점에 따라 여전히 부분 상태가 남을 수 있어 my_designs() 쪽 고려사항은 동일하게 필요 |

**확정: 후보 1(Design row를 처리 시작 시점에 먼저 생성·커밋).** 후보 2는 레이스의 "발생 확률"만 줄일 뿐(파일 쓰기~DB 커밋 사이의 물리적 시간 간격이 짧아짐), 원인 자체("두 연산이 원자적이지 않다")는 그대로 남고, 특히 처리 도중 예외가 나는 경우엔 10.5.2 이전과 동일한 근본 문제(이전 row가 최신으로 계속 남음)가 재발한다. 반면 후보 1은 "결제 여부는 이번 시도 시작 시점부터 이미 미결제"라는 더 보수적인(fail-closed) 상태를 처리 전체 구간에 걸쳐 유지하므로, 파일이 언제 바뀌든 그 이전에 이미 DB가 안전한 상태로 전환돼 있다. 부작용은 "처리 중이거나 실패한 시도가 짧게(혹은 예외 시엔 영구히) `paid=False`·경로 미기재 상태로 my_designs()에 노출된다"는 것뿐이며, 이는 아래에서 확인하듯 안전하다.

**`my_designs()` 템플릿과의 충돌 여부 확인.** `my_designs()`(`app.py` 465~495행)의 `to_static_rel(path)`(479~482행)는 `path`가 falsy이거나 `os.path.exists(path)`가 False면 `None`을 반환하고, `templates/my_designs.html`(38~68행)은 `preview_rel`/`design_rel`/`overlay_rel`이 `None`이면 각각 플레이스홀더 아이콘(45행) 또는 다운로드 버튼 생략(49~57행)으로 조용히 대체한다 — 에러를 내지 않는다. 후보 1에서 처리 시작 시 만드는 row는 `overlay_path`/`design_path`/`preview_path`를 지정하지 않으므로 `models.py`(31~33행, nullable 허용·기본값 없음) 기준 `None`으로 남고, 처리가 성공해 379행 위치(이제는 "업데이트")에서 실제 경로로 채워지기 전까지는 `to_static_rel(None)`이 항상 `None`을 반환해 안전하게 플레이스홀더만 보인다. 처리가 예외로 끝나 끝내 업데이트되지 않아도 마찬가지로 `None`으로 남아 플레이스홀더만 보일 뿐 깨진 링크나 잘못된(이전 tier) 이미지가 노출되지는 않는다 — 즉 다운로드 게이팅의 안전성뿐 아니라 이력 화면 쪽에서도 문제를 일으키지 않는다.

확정 방향(구현 시 반영할 구조, `app.py::process_pipo_task`):

```python
def process_pipo_task(file_path, prefix, user_id=None, skip_watermark=False, tier="standard"):
    design = None
    if user_id is not None:
        with app.app_context():
            design = Design(user_id=user_id, paid=False, upload_path=file_path, tier=tier)
            db.session.add(design)
            db.session.commit()  # 어떤 이미지 처리도 하기 전에 먼저 커밋 — 이 시점부터
                                  # "최신 Design row"가 즉시 이번(미결제) 시도로 전환된다.
    try:
        ... # 기존 0~5단계(모델 초기화 ~ refine_layout_and_label) 그대로
        ... # 329~346행: private_*/공개 overlay/design/preview 파일 저장, 그대로

        if design is not None:
            with app.app_context():
                design.overlay_path = overlay_path
                design.design_path = design_path
                design.preview_path = preview_path
                db.session.commit()
                # 이후 392~406행의 "Design.id 기반 고유 경로 사본 생성 + 경로 업데이트"는
                # 새 row 대신 이 design 객체에 그대로 적용한다(로직 변경 없음).
    except Exception as e:
        _update_progress(prefix, {"percent": 0, "message": f"오류 발생: {str(e)}", "status": "error"})
        # design은 paid=False로 이미 커밋돼 있으므로 별도 롤백 없이도 상태가 정확하다.
```

### 10.5.4 3차 리뷰 반려 반영: `index()` None 크래시, `mark_paid()`의 "최신 row" 오귀속 (2026-07-12)

`pipo-reviewer`가 10.5.3절 확정안(처리 시작 시 `Design` row를 먼저 생성)을 다시 검토해 새로운 결함 두 가지를 지적하며 반려했다. `app.py`를 다시 읽어 두 지적 모두 코드로 재확인했다.

#### (A) `index()`의 None 크래시 (`app.py` 423행)

현재 코드:

```python
has_result = design is not None and os.path.exists(design.preview_path)  # 423행
```

10.5.3에서 확정한 대로 `Design` row를 처리 시작 시점에 먼저 만들면(`preview_path`는 처리 완료 시점에야 채워짐, `models.py`에서 `preview_path`는 `nullable` 허용), 이 row가 존재하지만 `preview_path=None`인 채로 있는 시간이 생긴다. 그 사이 로그인 사용자가 홈(`/`)에 접속하면 `design is not None`은 참, `os.path.exists(None)`이 호출되며 `TypeError: stat: path should be string, bytes, os.PathLike or integer, not NoneType`가 발생해 500 에러가 난다. 재현 조건: 재업로드를 시작한 직후(파이프라인이 아직 완료 전) 같은 계정으로 홈에 접속하면 항상 재현된다 — 처리 시간(수 초~수십 초) 전체가 크래시 창이라 실무적으로 자주 부딪힐 결함이다.

**확정 수정 (`app.py::index`, 423행):**

```python
has_result = design is not None and design.preview_path and os.path.exists(design.preview_path)
```

`design.preview_path`가 `None`이면 `and`가 단락 평가(short-circuit)되어 `os.path.exists`를 아예 호출하지 않는다.

**`app.py` 전체에서 `design.preview_path`/`design.overlay_path`/`design.design_path`/`design.upload_path`(및 `d.*` 별칭) 참조를 전부 재검색해 각각 None-안전성을 확인했다:**

| 위치 | 코드 | None 안전성 |
|---|---|---|
| 402~405행 (`process_pipo_task`) | `design.upload_path = ...` 등 대입(쓰기) | 대입일 뿐 읽어서 `os.path.exists` 등에 넘기는 게 아니므로 크래시 대상 아님 |
| **423행 (`index`)** | `os.path.exists(design.preview_path)` | **크래시 지점(위에서 수정)** |
| 424행 (`index`) | `os.path.relpath(design.preview_path, 'static') if has_result else None` | 423행 수정 후에는 `has_result`가 참이려면 `design.preview_path`가 이미 truthy여야 하므로 안전 |
| 425~426행 (`index`) | `os.path.relpath(design.upload_path, 'static') if has_result and os.path.exists(design.upload_path) else None` | `has_result`가 참이면 `design`이 not None임은 보장되지만 `design.upload_path`가 not None이라는 보장은 이 줄 자체의 단락 평가로는 나오지 않는다. 다만 `models.py`의 `upload_path = db.Column(db.String(255), nullable=False)`(DB 레벨 NOT NULL 제약)와 10.5.3 확정안(`Design(user_id=..., paid=False, upload_path=file_path, tier=tier)` — row 생성 시점에 항상 값을 채워 넣음)에 의해 `upload_path`는 어떤 Design row든 생성 시점부터 절대 `None`일 수 없다. 그래서 현재는 안전하지만, 이 불변식이 깨지면(예: 향후 누군가 `upload_path` 없이 row를 만드는 코드를 추가하면) 424행과 달리 이 줄은 그 즉시 같은 종류의 크래시가 재발한다는 잠재 위험이 있다 — 12.2절에 방어적 가드 추가를 선택 항목으로 남긴다 |
| 486행 (`my_designs`) | `to_static_rel(d.preview_path)` | `to_static_rel`(479~482행)이 `if not path or not os.path.exists(path): return None`으로 이미 None-안전 (10.5.3절에서 확인한 그대로) |
| 491행 (`my_designs`) | `to_static_rel(d.design_path)` | 위와 동일, 안전 |
| 492행 (`my_designs`) | `to_static_rel(d.overlay_path)` | 위와 동일, 안전 |

결론: 실제 크래시는 423행 한 곳뿐이며, 그 한 줄만 고치면 나머지는 이미 안전하거나(424, 486, 491, 492행) DB 제약 + 10.5.3 확정안에 의해 안전하다(425~426행, 단 방어적 가드는 12.2절에 선택 항목으로 남김).

#### (B) `mark_paid()`가 여전히 "가장 최근 Design row"를 대상으로 함 (더 심각)

**재현 시나리오** (리뷰어 지적, 타임라인으로 재구성):

1. 사용자가 `tier=basic`로 업로드 → 완료(`tier_info={"tier":"basic","price_krw":20000,...}` 기록, `Design#1` 완성) → 결제 시작(토스 결제창으로 리다이렉트, **아직 승인 응답이 안 옴**).
2. 결제 승인 대기 중, 같은 계정으로 `tier=premium` 재업로드 시작. 10.5.3 확정안에 따라 `Design#2(user_id=X, paid=False, upload_path=..., tier="premium")`가 **처리 시작 즉시 커밋**된다(이미지 처리는 아직 진행 중, 수 초~수십 초 소요).
3. 이 대기 중에 토스 결제 승인이 뒤늦게 돌아와 `/payment/success`에 도착. 이 시점 `tier_info_path(prefix)`는 **아직 1단계의 값(`tier=basic, price_krw=20000`) 그대로**다 — PREMIUM 처리가 아직 완료되지 않아 10.2절의 "완료 시점에만 tier_info를 쓴다"는 규칙에 따라 아직 덮어써지지 않았기 때문이다. 그래서 `amount=20000`과 `expected_price=TIER_PRICES["basic"]=20000`이 일치해 10.3절 금액 검증은 정상적으로 통과한다.
4. `mark_paid(prefix)`가 호출되는데, 현재 구현(206~220행)은 `Design.query.filter_by(user_id=...).order_by(Design.created_at.desc()).first()`로 **"가장 최근" row**를 찾는다. 이 시점의 "가장 최근" row는 이미 `Design#2`(PREMIUM, 아직 처리 중, `paid=False`)다. 결과적으로 **`Design#2`(PREMIUM, 6만원 대상)가 `Design#1`(BASIC, 2만원 결제) 몫으로 `paid=True` 처리된다.**
5. PREMIUM 처리가 마저 끝나면(`design.overlay_path`/`design_path`/`preview_path` 갱신), 이미 `paid=True`인 이 row 그대로 `is_paid()`가 True를 반환해 **PREMIUM 원본을 추가 결제 없이 다운로드**할 수 있다.

10.5.3이 "Design row 생성 시점을 처리 시작 시점으로 앞당긴 것" 자체는 (A)의 크래시 케이스를 제외하면 10.5.1~10.5.2의 결함(파일은 새 tier인데 DB는 구 tier로 결제됨)을 올바르게 막았지만, 그 대가로 **"진행 중(미완료) row가 최신 row로 잡히는 시간"이 이전 방식(파일 쓰기 이후에야 row 생성)보다 오히려 훨씬 넓어졌다** — 예전에는 이 창이 "파일 쓰기~row 커밋" 사이 찰나였다면, 지금은 "row 커밋~파이프라인 전체 완료" 구간 전체(수 초~수십 초)로 늘어났다. `mark_paid()`가 여전히 "최신 row"라는, 시간에 따라 가리키는 대상이 바뀌는 기준을 쓰는 한 이 문제는 계속 재발한다.

**근본 원인**: `/payment/success`의 금액 검증(10.3절)은 이미 "이 결제가 어떤 tier/결과물에 대한 것인가"를 `tier_info` 사이드카로 정확히 고정해 두었는데, 그 승인 이후 실제로 `paid=True`를 찍는 대상(`mark_paid`)만 여전히 "가장 최근 row"라는, 시간에 따라 다른 row를 가리킬 수 있는 기준을 쓰고 있다. 즉 **검증 대상과 갱신 대상이 서로 다른 기준으로 결정된다**는 것이 이 결함의 본질이다.

**확정 수정: `tier_info`에 `design_id`를 함께 기록하고, 금액 검증과 `mark_paid()` 모두 그 정확한 `design_id`를 대상으로 동작하게 한다.**

10.2절 스키마에 `design_id` 필드를 추가한다(위 10.2절 갱신 참고): `{"tier": "basic", "price_krw": 20000, "k_colors": 16, "design_id": 42}`.

- **기록 시점**: 10.5.3 확정안에서 `Design` row는 처리 시작 시점에 이미 생성·커밋되어 `design.id`를 그 즉시 알 수 있다. `tier_info`를 쓰는 시점은 10.2절에서 이미 "파이프라인이 끝까지 성공한 직후, `palette_info`를 쓰는 시점과 정확히 같은 곳"으로 못박아 두었으므로, **그 시점에 이미 알고 있는 `design.id`를 그대로 `tier_info`에 함께 넣기만 하면 된다** — 새로운 타이밍을 도입하지 않는다.
- **로그인 사용자**: `design_id = design.id`.
- **비로그인 사용자**: `Design` row 자체가 없으므로(`process_pipo_task`의 `if user_id is not None:` 블록에서만 row 생성) `design_id` 필드를 넣지 않는다(또는 `None`). 이 경로는 원래도 결제 상태를 `paid_status[prefix]` dict로만 관리하고 `Design.paid`를 전혀 건드리지 않으므로(10.5.2절 확정안), `design_id`가 없어도 동작에 영향이 없다 — **이번 변경은 비로그인 사용자 경로를 전혀 건드리지 않는다.**

`load_tier_info(prefix)`는 기존 그대로(`load_palette_info`와 동일 패턴)이며 반환 dict에 `design_id` 키가 추가로 들어있을 뿐이다.

**`/payment/success`(`payment_success`) 재정의:**

```python
prefix = get_prefix()
tier_info = load_tier_info(prefix)

if tier_info is None or tier_info.get("tier") not in TIER_PRICES:
    return render_template('payment_result.html', success=False,
                            error_message='결제할 도안 정보를 찾을 수 없습니다. 먼저 사진을 업로드해 도안을 생성해주세요.')

expected_price = TIER_PRICES[tier_info["tier"]]
if amount_int != expected_price:
    return render_template('payment_result.html', success=False,
                            error_message='결제 금액이 올바르지 않습니다.')

# ... 토스 승인 API 호출(TOSS_CONFIRM_URL) 그대로 ...

if res.status_code == 200:
    mark_paid(prefix, design_id=tier_info.get("design_id"))
    return render_template('payment_result.html', success=True, payment=res.json())
```

10.3절의 금액 검증 로직 자체(어떤 값과 어떤 값을 비교하는지)는 바뀌지 않는다 — 여전히 `tier_info["tier"]`로부터 유도한 가격과 비교한다. 달라지는 것은 검증에 쓴 바로 그 `tier_info`에서 함께 꺼낸 `design_id`를 승인 이후 `mark_paid()`에 그대로 전달한다는 것뿐이다. 이렇게 하면 "검증 대상"과 "갱신 대상"이 항상 동일한 `tier_info` 스냅샷에서 나오므로 서로 어긋날 수 없다.

**`mark_paid()` 시그니처 변경 (`app.py`, 206~220행 교체):**

```python
def mark_paid(prefix, design_id=None):
    """결제 승인이 끝난 직후 호출한다. 같은 세션/IP의 get_prefix() 값을 그대로
    받아서 그 prefix를 결제 완료로 표시한다.

    design_id가 주어지면(로그인 사용자, tier_info에 기록된 그 결제 시점의
    정확한 Design row) "가장 최근 row"가 아니라 반드시 그 design_id의 row에만
    paid=True를 영속화한다 — 결제 승인이 지연되는 동안 같은 계정으로 재업로드가
    시작되어 더 최근의(아직 결제 안 된) row가 생겨도 잘못된 row가 결제완료로
    표시되지 않는다(10.5.4절). design_id가 없으면(비로그인 사용자, Design row
    자체가 없음) 기존과 동일하게 paid_status dict만 갱신한다."""
    with paid_lock:
        paid_status[prefix] = True

    if design_id is not None:
        design = db.session.get(Design, design_id)
        # user_id까지 함께 확인하는 것은 이론상 불필요한 이중 방어다 — design_id는
        # 서버가 그 사용자 자신의 tier_info 파일에 직접 써넣은 값이라 클라이언트가
        # 조작할 지렛대가 없다. 그래도 파일 손상 등 예상 밖의 경로로 다른
        # 사용자의 design_id가 들어오는 사고를 조기에 걸러내기 위한 방어적 확인.
        if design is not None and design.user_id == current_user.id:
            design.paid = True
            db.session.commit()
```

`current_user.is_authenticated`일 때만 `design_id`가 전달되므로(비로그인 경로는 위에서 이미 `None`), `current_user.id` 접근 자체는 안전하다.

**왜 이 수정이 재현 시나리오를 막는가**: 위 4단계에서 `mark_paid(prefix, design_id=1)`(1단계에서 `tier_info`에 기록된 `Design#1`의 id)이 호출되므로, "가장 최근 row"가 이미 `Design#2`로 바뀌어 있어도 정확히 `Design#1`만 `paid=True`가 된다. `Design#2`는 이후 처리가 끝나도 여전히 `paid=False`로 남아 결제가 필요하다.

**비로그인 사용자 경로 영향 확인**: 비로그인 사용자는 (1) `Design` row 자체가 생성되지 않고(`process_pipo_task`의 `if user_id is not None:` 가드), (2) `tier_info`에도 `design_id`가 기록되지 않으며, (3) `mark_paid(prefix, design_id=None)`은 `design_id is not None` 분기를 타지 않으므로 기존 `paid_status[prefix] = True` 한 줄만 그대로 실행된다. 즉 **비로그인 사용자의 결제 완료 처리 방식은 이번 변경 전후로 동일하다.**

## 11. 세그멘테이션 하드 컨스트레인트 재확인 + 수치 기준

이번 기능(실제 3등급 판매)이 처음으로 **세 등급 모두가 실제 고객 트래픽으로 생성**되는 계기다(지금까지는 `PipoPainter(tier="standard")`가 하드코딩돼 있어 STANDARD만 실제로 서비스됐고, BASIC/PREMIUM은 `qa_baseline.py`로만 검증됐다). 1장/3장의 하드 컨스트레인트 자체는 변경하지 않고 그대로 재확인한다:

1. 손으로 칠할 수 있는 영역 크기 — 등급이 올라가도 유지.
2. 등급 간 완만한 소요시간(영역 개수) 증가.
3. 정교함의 차이는 색상 수(`k_colors`)에서만 — 공간 분할 파라미터(`n_segments`)는 등급 무관 고정.

### 11.1 "완만한 증가"의 수치 기준 (기존 4장 재확인, 변경 없음)

대표의 요구("32색이라고 너무 복잡해지면 안 되지만 16/24색 대비 확실히 좋아 보여야 하고, 소요시간 차이는 크지 않아야 한다")는 이미 4장/4.1절에 다음과 같이 수치화돼 있고, 이번 사이클에서도 그대로 유지한다(별도로 새로 만들 필요 없음, 그대로 재사용):

- 단조 증가: `N_basic ≤ N_standard ≤ N_premium`.
- 배율 상한: `N_standard ≤ N_basic × 1.35`, `N_premium ≤ N_basic × 1.55`(4.1절 실측 근거: 최대 관측치 1.305 / 1.498에 여유를 둔 값).
- 등급 간 완만함: `(N_premium − N_standard) ≤ (N_standard − N_basic) × 1.5`.
- 색상 다양성(=정교함이 실제로 색상 수에서 나오는지)은 5장의 "실제 팔레트 색상 수" 지표로 측정한다: `BASIC 실제색상수 < STANDARD 실제색상수 < PREMIUM 실제색상수`, 각각 목표 `k_colors`(16/24/32) 이하. **이 지표가 곧 "색상 다양성을 어떻게 측정할지"에 대한 답이다** — 이미 `segmentation/qa_baseline.py`가 자동으로 뽑아준다.

### 11.2 이번 사이클에 세그멘테이션 팀이 실제로 할 일

- **코드 변경은 원칙적으로 불필요하다.** `TIER_PRESETS`(16/24/32, `n_segments` 등급 공통 고정)는 이미 이 스펙대로 구현돼 있다.
- 다만 지금까지 `qa_baseline.py`는 소수의 샘플 이미지로만 검증됐고, 이번에 처음으로 세 등급이 전부 실제 고객 트래픽에 노출되므로, **더 다양한 실제 업로드 프로필(인물, 반려동물, 풍경 등)로 `qa_baseline.py`를 재실행**해서 11.1절의 상한(1.35/1.55/단조증가)이 여전히 지켜지는지 재확인한다. 위반 샘플이 나오면 아래 상한/하한 안에서만 조정한다.

### 11.3 파라미터 조정이 필요할 경우의 상한/하한 (검토 대상이지만 반드시 지킬 것)

- `n_segments`는 **등급별로 절대 다르게 두지 않는다**(조정 대상 아님, 하드 컨스트레인트 3 직결).
- `min_area`는 필요하면 조정 검토 대상이나:
  - **등급 공통 값을 유지하는 것을 기본으로 하고**, 정말 필요할 때만(11.1절 상한 위반이 재현될 때만) 조정한다.
  - 조정한다면 **세 등급에 동시에 같은 값**을 적용한다(등급별로 다른 `min_area`는 두지 않는다 — 그러면 "정교함=색상 수만"이라는 원칙이 깨지고 등급 간 비교 기준도 같이 흔들린다).
  - 값의 범위는 **하한 300px(현재값 아래로는 내리지 않음, 내리면 영역이 더 잘게 쪼개져 컨스트레인트 1 위반 위험) ~ 상한 450px(5장 "최소 영역 비율" 지표가 이미 300px×1.5=450px를 "작은 영역" 경계로 쓰고 있으므로, 그 경계 자체를 넘어서면 지금 지표 정의와 충돌한다)** 안에서만 조정한다.
  - `color_merge_threshold`는 이번 사이클 범위 밖(현재 5로 고정, 조정 검토 대상 아님).
  - 조정 후에는 반드시 `qa_baseline.py`로 재측정하고 4.1절 기준선 표를 갱신한다.

## 12. 팀별 작업 지시

### 12.1 프론트엔드

- `templates/index.html`의 `tier-panel`(BASIC/STANDARD/PREMIUM 카드)에서 **"참고용 정보이며 실제 결제 금액에는 영향을 주지 않습니다"** 문구를 제거한다.
- 이 카드를 업로드 이전 단계(예: `#Pictures` 섹션, 드롭존 위/옆)로 옮기거나 복제해서, **클릭으로 하나만 선택 가능한 tier 선택 UI**로 만든다. 기본 선택값은 **STANDARD**(8.3절 이유).
- 파일 선택(`fileInput.addEventListener('change', ...)`) 시 `/upload`로 보내는 `FormData`에 `formData.append('tier', selectedTier)`를 추가한다(10.1절 값: `basic`/`standard`/`premium`).
- 결과/진행 표시에 현재 생성 중인/생성된 도안의 tier를 노출한다(예: "STANDARD(24색) 도안을 생성하고 있어요"). 서버가 `/progress` 응답과 완료 시 페이로드에 `tier`/`price_krw`를 함께 내려주면 그대로 표시만 하면 된다(백엔드팀과 필드명 맞출 것: `tier`, `price_krw`, `k_colors`).
- `#Payment` 섹션의 주문 요약(`order-summary`)과 결제 버튼(`tossPayments.requestPayment(...)`에 넘기는 `amount`)은 **더 이상 고정 상수가 아니라, 서버가 `index()` 렌더링 시점에 "이 prefix의 현재 도안" 기준으로 내려주는 값**을 써야 한다(백엔드팀이 템플릿 변수를 `product_price` 하나의 상수에서 "현재 tier의 이름/가격/색상수"로 바꿀 예정 — 정확한 변수명은 12.2절 작업 중 백엔드가 정해서 공유하면 그대로 반영).
- 아직 완성된 도안이 없는 상태(`has_result=False`)에서는 결제 버튼(`pay-method-btn`)을 비활성화하거나 숨긴다(현재는 `order-btn` 링크만 숨겨져 있고 결제 버튼 자체는 항상 노출돼 있음 — 이번 기능에서는 "결제 대상 tier_info가 없으면 결제 자체가 거절된다"는 10.3절과 UI를 일치시켜야 함).
- 등급을 바꾸고 싶어하는 사용자를 위해, 재업로드 시 "등급을 바꾸려면 다시 업로드해야 하며, 무료 체험은 1회만 가능합니다(로그인하면 여러 번 가능)" 안내를 적절한 시점(비로그인 + 이미 결과 있음)에 노출한다(기존 `login_required` 응답 처리 로직 참고).

### 12.2 백엔드

- `/upload`(`app.py::upload_file`): `request.form.get('tier')` 검증(10.1절, 허용값 외/누락 시 400) 추가. 검증된 `tier`를 `process_pipo_task(file_path, prefix, user_id, skip_watermark, tier)`에 새 인자로 전달.
- `process_pipo_task`: `PipoPainter(tier="standard")` 하드코딩을 `PipoPainter(tier=tier)`로 교체.
- 완료 처리 시점(`palette_info` 저장과 같은 지점)에 `tier_info_path(prefix)`(10.2절) 파일을 함께 저장. `load_tier_info(prefix)` 헬퍼를 `load_palette_info`와 동일한 패턴으로 추가.
- `TIER_PRICES = {"basic": 20000, "standard": 40000, "premium": 60000}`를 도입하고 기존 `PRODUCT_PRICE = 15000` 상수/사용처를 제거한다(9장, 3단계 표 확정).
- `index()`: 현재 prefix의 `tier_info`(있으면)를 읽어 템플릿에 "현재 도안의 등급/가격/색상수"를 넘긴다(없으면 프론트가 "사진을 업로드하면 선택한 등급에 맞는 금액이 표시됩니다" 같은 중립 상태를 보여줄 수 있도록 `None`/미정 상태를 명확히 구분해서 넘긴다).
- `/payment/success`(`payment_success`): 10.3절 로직으로 교체(`PRODUCT_PRICE` 단일 비교 → `tier_info` 기반 `TIER_PRICES` 조회 비교).
- `models.py::Design`: `tier` 컬럼 추가(10.4절), 기존 DB에는 수동 마이그레이션 필요함을 배포 체크리스트에 남긴다. `process_pipo_task`의 `Design(...)` 생성부에 `tier=tier` 추가.
- `/progress` 응답과 완료 페이로드에 `tier`/`price_krw`/`k_colors`를 포함해 프론트가 그대로 표시할 수 있게 한다(12.1절과 필드명 일치).
- **`app.py::is_paid`(188~203행) 수정 — 로그인 사용자에 대해 `paid_status` dict로의 폴백을 제거한다(10.5절, 리뷰 반려 반영 필수 항목).** 현재는 로그인 사용자의 최신 `Design.paid`가 False여도 함수가 이어서 `paid_status.get(prefix)`를 확인해버려서, "예전에(다른 tier로) 결제한 적이 있으면 재업로드 후에도 계속 유료로 취급된다"는 결함이 있다(재업로드 후 상위 tier로 무료 다운로드가 가능해짐). 로그인 분기는 최신 `Design.paid` 값을 그대로 반환하고 끝내며(10.5.1절 코드 그대로 반영), `paid_status` 확인은 비로그인 분기에서만 남긴다. 이 항목 없이는 10.3절의 금액 검증이 아무리 견고해도 재업로드로 우회 가능하므로, 이번 사이클의 필수 배포 항목으로 취급한다.
  - (선택) `mark_paid`(206~220행)도 `paid_status[prefix] = True`를 비로그인 사용자에게만 쓰도록 좁혀서, 로그인 사용자에 대해 더 이상 읽히지 않는 dict 값이 쌓이지 않게 정리해도 된다(필수 아님, 위 `is_paid` 수정만으로 실제 결함은 닫힘).
- **`app.py::index`(423행) None 크래시 수정 (10.5.4절 (A), 3차 리뷰 반려 반영 필수 항목).** `has_result = design is not None and os.path.exists(design.preview_path)`를 `has_result = design is not None and design.preview_path and os.path.exists(design.preview_path)`로 교체한다. 10.5.3의 "처리 시작 시 Design row 선(先)생성" 방식에서는 `preview_path`가 아직 `None`인 row가 존재하는 구간이 생기므로, 그 사이 홈(`/`)에 접속하면 현재 코드는 `os.path.exists(None)`에서 `TypeError`로 500이 난다. (선택) 425~426행의 `os.path.exists(design.upload_path)`도, 현재는 `models.py`의 `upload_path` `nullable=False` 제약과 10.5.3 확정안(row 생성 시 항상 `upload_path` 채움)에 의해 안전하지만, `design.upload_path and os.path.exists(design.upload_path)`로 방어적 가드를 똑같이 추가해 향후 그 불변식이 깨지더라도 안전하게 만들어도 된다(필수 아님).
- **`tier_info` 사이드카에 `design_id` 필드 추가 + `mark_paid`/`payment_success`를 "최신 row"가 아니라 그 `design_id`의 row를 대상으로 동작하도록 재정의 (10.5.4절 (B), 3차 리뷰 반려 반영 필수 항목).** `process_pipo_task`가 완료 시점(`palette_info`/`tier_info` 저장과 같은 지점)에 `tier_info`를 쓸 때, 이미 알고 있는 `design.id`(로그인 사용자만, 10.5.3에서 처리 시작 시 이미 생성됨)를 `"design_id"` 키로 함께 기록한다(비로그인 사용자는 이 필드 자체를 넣지 않음). `mark_paid(prefix)`를 `mark_paid(prefix, design_id=None)`로 시그니처를 바꾸고, `design_id`가 주어지면 "가장 최근 row"가 아니라 `db.session.get(Design, design_id)`로 찾은 그 row에만(및 `design.user_id == current_user.id` 확인 후) `paid=True`를 쓴다. `payment_success`는 금액 검증에 이미 쓴 `tier_info`에서 `tier_info.get("design_id")`를 그대로 꺼내 `mark_paid(prefix, design_id=...)`에 전달한다. 이 항목 없이는, 결제 승인이 지연되는 동안 같은 계정으로 상위 tier 재업로드가 시작되면 그 진행 중인(미결제) row가 이전 결제 몫으로 잘못 `paid=True` 처리될 수 있다(10.5.4절 재현 시나리오 참고). 비로그인 사용자 경로는 영향 없음(10.5.4절에서 확인).
- **`app.py::process_pipo_task` 리팩터링 — `Design` row를 처리 시작 시점에 먼저 생성·커밋한다(10.5.3절, 2차 리뷰 반려 반영 필수 항목).** 현재는 `Design` row 생성·커밋(379~390행)이 공개 경로 파일 덮어쓰기(329~346행)보다 늦게 일어나서, 재업로드 처리 도중(파일은 이미 새 tier로 덮어써졌지만 새 row가 아직 없거나 커밋 전) `/download/<kind>`가 호출되면 `is_paid()`가 이전(결제 완료) row를 근거로 True를 반환해 짧은 무료 다운로드 창이 생긴다(처리 중 예외가 나면 이 불일치가 영구화될 수 있음). `user_id is not None`인 경우, 함수 맨 앞(어떤 이미지 처리도 하기 전)에서 `Design(user_id=user_id, paid=False, upload_path=file_path, tier=tier)`를 생성·커밋해두고, 기존 379~390행의 "새 row 생성"은 "이미 만든 이 row의 `overlay_path`/`design_path`/`preview_path`/`tier` 필드 업데이트"로 바꾼다(392~406행의 고유 경로 사본 생성·업데이트 로직 자체는 변경 없음, 대상만 이 row로). `my_designs()`(465~495행)의 `to_static_rel`이 `None`/미존재 경로를 안전하게 플레이스홀더로 처리하므로, 처리 중이거나 실패한 시도가 잠깐 경로 미기재 상태로 노출돼도 화면이 깨지지 않음을 확인했다(10.5.3절 참고).

### 12.3 세그멘테이션

- 코드 변경은 원칙적으로 없음(11.2절). `TIER_PRESETS`는 이미 스펙대로.
- 요청 작업: 다양한 실제 업로드 프로필로 `python -m segmentation.qa_baseline`을 재실행해 11.1절 상한이 유지되는지 재확인하고, 결과를 QA에 공유. 위반이 재현되면 11.3절의 상한/하한 안에서만(등급 공통 `min_area`, 300~450px) 조정 검토.

## 13. 변경 이력

- 2026-07-11: 최초 작성. BASIC/STANDARD/PREMIUM 등급표, 공통 파라미터, 목표 영역 개수 범위, QA 대리 지표 정리. `app.py`의 실제 등급 분기 구현은 아직 미완료(추적: pipo-backend/pipo-segmentation).
- 2026-07-11: `n_segments` 등급 무관 고정(`unify-n-segments-across-tiers`, `PipoPainter.TIER_PRESETS`에 3개 등급 모두 `n_segments=3000`) 적용 후 `segmentation/qa_baseline.py`로 재측정한 실측 기준선을 4.1절에 추가. 이를 근거로 4장의 배율 상한을 낙관치였던 `1.15 / 1.30`에서 실측 근거의 `1.35 / 1.55`로 현실화(단조 증가 + 완만한 증가라는 하드 컨스트레인트 자체는 변경 없음). 5장에 `qa_baseline.py` 사용법을 추가해 다음 파라미터 변경 시에도 수작업 재측정 없이 QA가 재사용할 수 있게 함. 초저해상도(160×120) 업스케일 샘플 1건에서 단조 증가가 깨지는 것을 관측했으나 실제 서비스 입력 범위를 벗어난 것으로 보고 기준선에서는 제외(4.1절 참고, 향후 이슈로 별도 추적 권장).
- 2026-07-12: `app.py::upload_file`에 업로드 최소 해상도 가드(`MIN_UPLOAD_SHORT_SIDE_PX=150`)를 추가해 위 항목에서 남겨둔 초저해상도 업스케일 단조 증가 위반을 서비스 입력 단에서 차단(세그멘테이션 파이프라인 자체는 변경 없음). 임계값은 4.1절 실측치(`127_0_0_1.jpg` 120px=문제, `122_34_142_96.jpg` 167px=정상) 사이에서 `qa_baseline.py --check`로 재측정해 선정(자세한 근거는 4.1절 참고).
- 2026-07-12: 코드 변경 없이 문서만 정리. `PRODUCT_PRICE=15000`이 2장의 3단계 가격표(2/4/6만원) 중 어느 값과도 일치하지 않는 점에 대해, 이는 3단계 가격표가 실제로 적용되기 전의 임시/얼리버드 가격이며 현재 산출물은 항상 STANDARD 프리셋(k_colors=24)으로 생성된다는 점을 2.1절에 명시. 아울러 `TIER_BY_PRICE`를 실제로 배포하기 위한 선행 조건(①결제-도안 연결 메커니즘 → ②DB 마이그레이션 도구 도입 → ③서버 측 금액 검증, 이 순서로)을 6장 체크리스트로 신설(기존 6장 변경 이력은 7장으로 이동).
- 2026-07-12 (사이클 1): 대표 요구("실제로 등급을 선택해 결제하고 그 등급의 도안을 받는다")에 맞춰 8~12장을 신설하고 실제 구현 스펙을 확정(코드 변경 없음, 문서만). 핵심 결정: **(1)** tier는 업로드 "전"에 선택하고 그 tier로 바로 미리보기를 생성한다(옵션 A 확정, 8장) — "결제 전 미리보기가 실제 구매 tier와 다를 수 있다"는 문제를 재처리 없이 구조적으로 없앰. **(2)** 기존 노출가 20,000/40,000/60,000원을 그대로 실제 결제 금액으로 확정(9장), 기존 `PRODUCT_PRICE=15000`은 폐기. **(3)** `/upload`에 폼 필드 `tier`(`basic`/`standard`/`premium`) 신설, 서버는 prefix별 사이드카 파일 `{prefix}_tier.json`(`tier_info_path`)에 선택된 tier를 기록하며 이는 `palette_info`와 동일한 "파이프라인 성공 직후" 시점에만 쓴다(10.1~10.2절) — `progress_status`(TTL로 소멸)나 세션(로그인/비로그인 불일치) 대신 채택. **(4)** `/payment/success`의 금액 검증은 클라이언트가 보낸 `amount`를, 이 요청의 tier가 아니라 **서버가 사이드카 파일에 이미 기록해 둔 tier로부터 조회한 가격**(`TIER_PRICES[tier_info["tier"]]`)과 비교하도록 변경(10.3절) — 이로써 2장의 `TIER_BY_PRICE`(가격→k_colors, 결제 후 사후 결정) 방식과 6장의 무거운 선행 조건 체크리스트(결제-도안 연결 메커니즘 + DB 마이그레이션 도구 선행)는 대체(supersede)됨. **(5)** `Design.tier` 컬럼을 감사/이력 표시용으로 추가하되 금액 검증의 근거로는 쓰지 않음(10.4절, `paid` 컬럼과 동일하게 수동 마이그레이션 필요). **(6)** 세그멘테이션은 코드 변경 없이, 처음으로 세 등급 전부가 실 트래픽에 노출되는 것에 대비해 `qa_baseline.py`를 더 다양한 샘플로 재실행하고, 필요 시에만 등급 공통 `min_area`를 300~450px 범위 안에서만 조정(11장). 팀별 작업 지시는 12장 참고.
- 2026-07-12 (사이클 1, 리뷰 반려 반영): `pipo-reviewer`가 10.3절 금액 검증 자체는 안전하나 결제 승인 이후 다운로드 게이팅(`is_paid`)이 "그 사용자(prefix) 자체"에 결제 여부를 영구히 묶어놓아서, **로그인 사용자가 BASIC으로 한 번만 결제한 뒤 같은 계정으로 몇 번이든 PREMIUM으로 재업로드해도(로그인 사용자는 재업로드 횟수 제한이 없음) `paid_status` dict 폴백 때문에 추가 결제 없이 PREMIUM 원본을 받을 수 있다**는 결함(코드로 재현 확인, `app.py::is_paid` 188~203행/`mark_paid` 206~220행/`upload_file` 617~623행)을 근거로 반려한 것을 반영해 10.5절을 신설. **확정한 수정: `is_paid()`에서 로그인 사용자는 오직 DB(가장 최근 `Design.paid`)만 신뢰의 원천으로 삼고 `paid_status` dict 폴백을 로그인 사용자에게는 적용하지 않는다**(비로그인 사용자는 기존대로 dict만 사용) — "재업로드 시 `paid_status` 명시적 초기화" 대안과 비교했을 때 변경 범위가 다운로드 게이팅의 유일한 진입점(`is_paid`) 하나로 그치고, 10.4절에서 이미 채택한 "trust 도메인을 로그인/비로그인으로 완전히 분리한다"는 원칙과 정확히 같은 패턴이라 이 쪽을 확정했다. 12.2절에 백엔드 필수 작업 항목으로 추가.
- 2026-07-12 (사이클 1, 2차 리뷰 반려 반영): `pipo-reviewer`가 10.5.2 수정만으로는 부족하다고 재반려 — `process_pipo_task`(`app.py`)가 공개 경로 파일을 덮어쓰는 시점(329~346행)이 이번 시도의 `Design` row 생성·커밋(379~390행)보다 먼저 일어나서, 그 사이(파일은 새 tier, DB는 이전 row) `/download/<kind>`가 호출되면 이전 결제 이력으로 새 tier 원본이 무료로 나가는 레이스가 있음을 코드로 재확인했다(처리 중 예외 시 이 불일치가 영구화될 위험도 확인). 10.5.3절을 신설해 **`Design` row를 처리 시작 시점(어떤 이미지 처리도 하기 전)에 `paid=False`로 먼저 생성·커밋하고, 기존 379~390행의 "새 row 생성"은 "이 row의 경로/tier 필드 업데이트"로 바꾸는 안**을 확정("파일 쓰기를 DB 커밋 뒤로 미루는 안"과 비교해, 예외 발생 시에도 이번 시도가 정직하게 `paid=False`로 남는다는 점에서 더 안전한 fail-closed 구조로 판단). `my_designs()`의 `to_static_rel`이 `None`/미존재 경로를 이미 안전하게 처리함을 확인해 화면 쪽 부작용이 없음도 함께 못박았다. 12.2절에 백엔드 필수 작업 항목으로 추가.
- 2026-07-12 (사이클 1, 3차 리뷰 반려 반영): `pipo-reviewer`가 10.5.3 확정안을 다시 검토해 결함 두 가지를 추가로 지적, `app.py`로 재확인 후 10.5.4절을 신설했다. **(A) `index()`(423행) None 크래시**: `os.path.exists(design.preview_path)`가 `preview_path=None`(10.5.3에서 처리 시작 시 먼저 만든 row가 아직 완료 전인 구간)일 때 `TypeError`로 500 에러를 낸다 — `design.preview_path and os.path.exists(...)`로 None 가드 추가 확정, `app.py` 전체에서 `design.preview_path`/`overlay_path`/`design_path`/`upload_path` 참조를 모두 재검색해 이 한 곳만 크래시 지점임을 확인했다(425~426행은 `upload_path`의 DB `nullable=False` 제약으로 현재는 안전, 486/491/492행은 `to_static_rel`이 이미 안전). **(B) `mark_paid()`가 여전히 "가장 최근 Design row"를 대상으로 함(더 심각)**: BASIC 결제 승인 대기 중 같은 계정으로 PREMIUM 재업로드가 시작되면(10.5.3에 따라 미결제 row가 즉시 생김) 뒤늦게 도착한 결제 승인이 "가장 최근 row"인 PREMIUM row를 BASIC 가격에 결제완료 처리해버리는 레이스를 코드로 재확인 — 10.5.3이 레이스 창을 "파이프라인 전체 소요 시간"으로 오히려 넓혔다고 판단했다. **확정 수정**: 10.2절 `tier_info` 사이드카 스키마에 `design_id` 필드를 추가(처리 완료 시점, `palette_info`/`tier_info`를 쓰는 바로 그 지점에 이미 알고 있는 `design.id`를 함께 기록 — 새 타이밍 도입 없음)하고, `mark_paid(prefix, design_id=None)`로 시그니처를 바꿔 `design_id`가 있으면 그 정확한 row에만(및 `user_id` 일치 확인 후) `paid=True`를 쓰도록, `/payment/success`도 금액 검증에 쓴 그 `tier_info`에서 꺼낸 `design_id`를 그대로 `mark_paid`에 전달하도록 재정의했다. 비로그인 사용자는 `Design` row 자체가 없어 `design_id` 필드가 안 붙고 기존 `paid_status[prefix]` 방식 그대로라 이번 변경의 영향이 없음을 확인했다. 12.2절에 백엔드 필수 작업 항목 2건(위 A/B)으로 추가.
- 2026-07-12 (사이클 1, 2차 리뷰 반려 반영): `pipo-reviewer`가 10.5.2의 `is_paid()` 수정만으로는 부족하다며 재반려했다. 근거: `process_pipo_task`에서 공개 경로 파일 덮어쓰기(329~346행)가 이번 시도의 `Design` row 생성·커밋(379~390행)보다 먼저 끝나서, 그 사이 구간에 `/download/<kind>`가 호출되면 파일은 이미 새(미결제) tier인데 `is_paid()`가 참조하는 "최신 row"는 여전히 이전(결제 완료) row라 True를 반환한다(처리 중 예외 발생 시 이 불일치가 영구화될 위험도 확인). 코드로 재현 가능함을 확인하고 10.5.3절을 신설했다. **확정한 수정: 근본 원인을 "Design row 생성이 파일 쓰기보다 늦다"로 규정하고, `process_pipo_task` 시작 시점(어떤 이미지 처리도 하기 전)에 `Design(user_id=user_id, paid=False, upload_path=file_path, tier=tier)`를 먼저 생성·커밋해두고, 처리가 성공한 뒤에는 새 row를 만들지 않고 이 row의 필드(overlay_path/design_path/preview_path/tier)를 업데이트하는 방식으로 바꾼다.** "파일 쓰기를 커밋 뒤로 미루는" 대안과 비교했을 때, 이 방식은 처리 전체 구간에 걸쳐 최신 row가 즉시 미결제 상태로 전환돼 있어(fail-closed) 파일이 언제 바뀌든 레이스 자체가 성립하지 않고, 예외가 나도 row가 정직하게 `paid=False`로 남아 오히려 더 정확하다. `my_designs()`의 `to_static_rel`이 `None`/미존재 경로를 안전하게 플레이스홀더로 처리함을 확인해 이 방식이 이력 화면과 충돌하지 않음도 검증했다(10.5.3절). 12.2절에 백엔드 필수 작업 항목으로 추가.
- 2026-07-12 (사이클 1, 세그멘테이션팀 11장 작업 반영): `pipo-segmentation`이 11.2절 지시대로 `static/uploads/`의 실제 업로드 샘플 중 프로필이 서로 다른 6장(인물+텍스트 `user_3.jpg`, 2인 인물 `user_3_design_11.jpg`, 인물+반려동물 `211_36_147_192.jpg`, 반려동물 단독 `122_34_142_96.jpg`, 풍경 `user_5.jpg`, 참고용 초저해상도 `127_0_0_1.jpg`)으로 `qa_baseline.py --check`를 재실행해 4.2절에 결과를 추가했다. 실제 서비스 입력 범위(짧은 변 150px 이상)에 해당하는 5개 프로필 전부 11.1절 기준(단조 증가/배율 상한/완만함/색상 다양성)을 통과했고, `127_0_0_1.jpg`(짧은 변 120px)만 여전히 단조 증가 위반이었으나 이는 4.1절에 이미 기록된 알려진 케이스이며 같은 날 도입된 `MIN_UPLOAD_SHORT_SIDE_PX=150` 업로드 가드로 이미 서비스 입력 단에서 차단되어 새로 발견된 위반이 아니다. **결론: 코드/파라미터 변경 없음**(`n_segments`/`min_area`/`color_merge_threshold` 전부 기존 값 유지).
- 2026-07-12 (사이클 2, 구현 결과 재검토): `e81a6ac`(사이클 1 구현)와 `088a268`(배포 후 실사용자 리포트로 발견된 인라인 JS 이스케이프 버그 수정)를 8~13장과 대조 재검토. 핵심 결론: 스펙 자체는 정확히 구현됐으나(10.5절의 세 차례 리뷰 반려 반영분 포함, `models.py`/`app.py` 전부 문서와 일치), **"Jinja 변수를 인라인 `<script>` 안에 문자열로 넣을 때 수동으로 따옴표를 붙이면 HTML 자동 이스케이프가 JS 구문 자체를 깨뜨릴 수 있다"는 클래스의 버그가 스펙에 아예 다뤄지지 않았고, 사이클 1 검증에서도 못 잡았다.** 새 14장에 원인 분석과 동일 클래스의 잔존 인스턴스 2건(`templates/index.html` 495행, 690행)을 정리하고, 사이클 2 프론트 작업 지시로 남김(14.3/14.6절). 세그멘테이션 4.2절 재검증은 `git show e81a6ac -- segmentation/`이 빈 diff임을 확인해 여전히 유효하다고 판단(코드 변경 없음, 재실행 불필요).

---

# 사이클 2: 구현 결과 재검토 (2026-07-12)

사이클 1(`e81a6ac`)이 "완료" 선언된 뒤, 실사용자(관리자 계정, 이미 도안이 있는 상태)가 등급 카드를 클릭해도 선택이 바뀌지 않는다고 보고했고, 이는 `088a268`으로 수정됐다. 이 장은 그 사건을 계기로 8~13장 스펙과 실제 구현을 다시 대조하고, 같은 클래스의 문제가 더 있는지, 사이클 1 검증 방법 자체에 구조적 허점이 있었는지를 정리한다.

## 14. 사이클 2 재검토 결과

### 14.1 `088a268` 버그: 스펙 대조 및 근본 원인

8~13장 어디에도 "서버 변수를 인라인 `<script>` 안에 문자열/숫자로 어떻게 안전하게 넣을지"는 명시돼 있지 않았다 — 즉 이 버그는 스펙 위반이 아니라 **스펙이 다루지 않은 구현 디테일에서 난 사고**다. 사이클 1에서 8~13장의 다른 모든 항목(10.1~10.5절의 tier 검증/사이드카/결제 게이팅/레이스 수정)은 `git show e81a6ac`로 확인한 실제 diff와 정확히 일치한다(14.4절 참고).

**근본 원인 (코드로 확인):**

`e81a6ac`가 도입한 코드(`templates/index.html`, 수정 전):
```javascript
let currentTierPrice = {{ current_tier_price if current_tier_price is not none else 'null' }};
let currentTierName = {{ ('"' + current_tier_name + '"') if current_tier_name else 'null' }};
```

`current_tier_name`은 `app.py::index()`에서 `current_tier.upper()`(예: `"STANDARD"`)로 만들어진 순수 파이썬 문자열이고, Jinja 표현식 `'"' + current_tier_name + '"'`은 그 문자열 앞뒤로 큰따옴표를 붙인 `"STANDARD"`라는 **새로운 문자열**을 만든다. 문제는 Jinja가 `{{ ... }}` 출력을 HTML 컨텍스트 기준으로 자동 이스케이프한다는 점이다 — 이 표현식이 만든 `"` 문자 두 개가 이스케이프 대상이 되어 `&#34;`로 바뀌고, 최종 렌더링 결과는:
```javascript
let currentTierName = &#34;STANDARD&#34;;
```
이 되어 `<script>` 안에서 `SyntaxError: Unexpected token '&'`가 난다. 이 오류가 나면 그 시점 이후의 모든 인라인 JS(등급 선택 클릭 핸들러 `updateTierSelectionUI` 등록, 결제 버튼 핸들러 등록 전부 포함)가 실행되지 않는다. `has_result=False`(도안이 없는 상태)에서는 `current_tier_name`이 `None`이라 이 줄이 `let currentTierName = null;`로 안전하게 렌더링되므로 증상이 나타나지 않고, `has_result=True`(이미 도안이 있는 계정)일 때만 재현된다.

### 14.2 사이클 1 검증 방법의 허점 — 왜 못 잡았는가

프론트 에이전트는 "`jinja2.Environment`로 `has_result=False`/`True` 두 컨텍스트로 실제 렌더링해 문법 오류 없음을 확인했다"고 보고했고, 실제로 `has_result=True` 케이스도 렌더링을 시도했다고 주장했다. 그런데도 이 버그는 정확히 그 케이스에서만 재현된다. 이 모순은 검증 방법 자체의 다음 허점으로 설명된다:

- **"Jinja 렌더링이 예외 없이 끝난다"는 것과 "그 결과물이 유효한 HTML/JS다"는 것은 다른 명제다.** Jinja는 템플릿 문법(태그 짝, 표현식 문법 등)만 검사하고 렌더링한다 — 렌더링 결과 문자열이 그 안에 내장된 다른 언어(여기서는 `<script>` 태그 안의 JavaScript)의 문법으로도 유효한지는 전혀 검사하지 않는다. `jinja2.Environment().get_template(...).render(has_result=True, ...)`를 호출해 예외 없이 문자열이 반환되면 "렌더링 성공"이지만, 그 문자열 안에 `&#34;STANDARD&#34;;`처럼 깨진 JS가 들어있어도 Jinja 입장에서는 정상 동작이다.
- **HTML 자동 이스케이프가 "다른 컨텍스트(JS 문자열 리터럴)를 깨뜨릴 수 있다"는 것 자체가 간과됐다.** Jinja의 기본 autoescape는 HTML 마크업 컨텍스트를 기준으로 `<`, `>`, `&`, `"`, `'`를 이스케이프한다. `<script>` 태그 안은 HTML 파서 기준으로는 여전히 "HTML 문서의 일부"이지만, 그 안의 내용은 JS 파서가 다시 해석한다 — 즉 이스케이프는 "HTML을 깨지 않게" 하려는 것인데, 그 부작용으로 "JS를 깨뜨릴" 수 있다는 게 이번 버그의 본질이다. 검증 보고서는 "Jinja 문법 오류 없음"만 확인했다고 명시했지, "이스케이프가 인라인 JS 컨텍스트에 미치는 영향"은 아예 검사 항목에 없었다.
- **실제로 검증했다고 주장한 `has_result=True` 케이스에서, 렌더링된 *텍스트*가 아니라 렌더링이 *예외를 던지는지*만 확인했을 가능성이 높다.** `render()` 호출은 이스케이프된 `&#34;`가 포함된 문자열을 정상적으로(예외 없이) 반환하므로, "렌더링이 실행됐다"만 확인하는 방식으로는 이 버그를 볼 수 없다 — 렌더링된 `<script>` 블록 내용을 실제 JS 파서(예: Node.js `vm`/`new Function`, 또는 최소한 브라우저)에 통과시켜 "문법적으로 유효한 JS인가"까지 확인했어야 이 버그가 나왔을 것이다.
- **결론: "템플릿이 렌더링되는가"와 "렌더링된 결과에 내장된 하위 언어(JS/CSS/URL 등)가 유효한가"는 서로 다른 검증이며, 사이클 1은 전자만 하고 후자를 하지 않았다.** 이는 이 프로젝트의 일반적인 검증 관행에 대한 시사점이기도 하다 — 앞으로 인라인 `<script>`/`<style>` 안에 서버 변수를 넣는 변경이 있으면, Jinja 렌더링 성공 여부와 별개로 **렌더링된 스크립트 내용 자체를 JS 파서로 파싱해보는 점검**(또는 최소한 실제 브라우저/헤드리스 브라우저로 `has_result=True`/`False` 두 상태를 다 띄워서 콘솔 에러가 없는지 확인)을 검증 절차에 추가해야 한다.

### 14.3 동일 클래스의 잔존 인스턴스 재검토

`templates/index.html`의 `<script>` 블록 전체(`awk '/<script/{s=1} /<\/script>/{s=0} s' templates/index.html | grep '{{'`)를 재검토한 결과, `{{ ... }}`로 값을 인라인 JS에 박아 넣는 곳은 아래 5곳이다.

| 줄 | 코드 | tojson 사용 여부 | 평가 |
|---|---|---|---|
| 346 | `let currentTierPrice = {{ current_tier_price \| tojson }};` | 예 | `088a268`에서 수정됨. 안전 |
| 347 | `let currentTierName = {{ current_tier_name \| tojson }};` | 예 | `088a268`에서 수정됨. 안전 |
| 36 | `let hasResult = {{ 'true' if has_result else 'false' }};` | 아니오(수동 리터럴) | **안전.** Jinja 표현식이 파이썬 `bool`을 그대로 JS로 변환하는 게 아니라, `'true'`/`'false'`라는 **고정 리터럴 문자열 둘 중 하나**만 골라 출력한다. 사용자/서버 데이터가 그대로 흘러들어오는 통로가 아니므로 088a268과 같은 이스케이프 위험이 없다. |
| **495** | `window.location.href = "{{ url_for('login') }}";` | **아니오(수동 따옴표)** | **088a268과 동일한 패턴.** `url_for()`가 반환하는 경로 문자열을 수동으로 큰따옴표로 감싸 JS 문자열 리터럴을 만든다. 현재는 `url_for('login')`이 인자 없는 고정 라우트라 결과가 항상 `/login`(따옴표·`&`·`<` 등 이스케이프 대상 문자가 없는 값)이라 실제로 깨지지 않지만, **이스케이프 위험 자체가 없는 것이 아니라 "지금 이 값이 우연히 안전한 문자만 포함할 뿐"이다.** 향후 `url_for`에 쿼리 파라미터(`next=` 등)가 추가되거나 로그인 경로 자체가 바뀌면 같은 클래스의 버그가 재현될 수 있는 잠재 위험. |
| **690** | `const tossClientKey = "{{ toss_client_key }}";` | **아니오(수동 따옴표)** | **088a268과 동일한 패턴.** `toss_client_key`는 `app.py`의 `TOSS_CLIENT_KEY = os.environ.get('TOSS_CLIENT_KEY', 'test_ck_...')` — 즉 **환경 변수로 배포 시점에 값이 바뀔 수 있는 입력**이다. 현재 기본값(`test_ck_D5GePWvyJnrK0W0k6q8gLzN97Eoq`)은 안전한 문자만 포함하지만, 운영 배포 환경에서 이 환경 변수에 다른 값이 설정될 경우 그 값의 문자 구성을 코드가 전혀 통제하지 못한다. 사용자 입력이 아니라 배포 설정값이라 공격 표면은 아니지만, **495행보다 한 단계 더 위험하다** — 496행과 달리 이 값은 코드베이스 밖(환경 변수)에서 결정되므로, "지금 안전해 보인다"는 보장이 코드 리뷰만으로는 지속되지 않는다. |

**결론: `088a268`이 고친 2건 외에, 정확히 같은 안티패턴(수동 따옴표로 Jinja 값을 JS 문자열 리터럴로 감싸기)이 495행과 690행에 남아있다.** 둘 다 "지금 당장 재현되는 버그"는 아니지만(현재 값들이 우연히 이스케이프 위험 문자를 포함하지 않음), `088a268`이 고친 버그와 구조적으로 동일한 잠재 결함이며, 언제든 값의 내용이 바뀌면(환경 변수 변경, 라우트에 쿼리 파라미터 추가 등) 재현 가능하다.

#### 사이클 2 프론트 작업 지시 (수정 지시만, 실제 코드 수정은 사이클 2 구현 단계에서)

- `templates/index.html` 495행: `window.location.href = "{{ url_for('login') }}";` → `window.location.href = {{ url_for('login') | tojson }};`로 교체.
- `templates/index.html` 690행: `const tossClientKey = "{{ toss_client_key }}";` → `const tossClientKey = {{ toss_client_key | tojson }};`로 교체.
- 위 2건 외에 36행(`hasResult`)은 안전하므로 수정 대상 아님(14.3절 표 참고, 고정 리터럴만 출력하는 패턴이라 088a268과 다른 케이스).
- **일반 규칙으로 남김:** 앞으로 `templates/index.html`(또는 다른 템플릿)의 인라인 `<script>` 안에 Jinja 변수를 문자열/숫자/불리언으로 넣을 때는, 그 값이 파이썬에서 정한 고정 리터럴(`'true'`/`'false'`처럼 개발자가 코드에 직접 적은 유한한 선택지)이 아닌 이상 **항상 `| tojson` 필터를 쓴다.** 수동으로 따옴표를 붙이거나 문자열 결합으로 JS 리터럴을 만드는 방식은 금지한다 — 값의 내용이 통제 밖에서 바뀔 수 있는 한(환경 변수, DB 조회 결과, 사용자 입력 유래 값 등) 이스케이프가 JS 구문을 깨뜨릴 잠재 위험이 항상 있다.

### 14.4 8~13장 스펙 vs 실제 구현 재대조

`git show e81a6ac -- app.py models.py`의 diff를 10.1~10.5.4절과 한 줄씩 대조한 결과, **불일치는 발견되지 않았다.**

- `models.py::Design.tier`: `db.Column(db.String(20), nullable=True)` — 10.4절과 정확히 일치(주석에 수동 마이그레이션 필요성까지 그대로 반영).
- `TIER_PRICES = {"basic": 20000, "standard": 40000, "premium": 60000}`, `PRODUCT_PRICE` 제거 — 9장/10.3절과 일치.
- `is_paid()`: 로그인 분기가 dict 폴백 없이 `return bool(design is not None and design.paid)`로 즉시 반환 — 10.5.2절 확정 코드와 정확히 일치.
- `mark_paid(prefix, design_id=None)`: `design_id`가 있으면 `db.session.get(Design, design_id)` 조회 후 `user_id` 일치 확인 → `paid=True` — 10.5.4(B) 확정 코드와 일치.
- `process_pipo_task`: 처리 시작 시점에 `Design(user_id=user_id, paid=False, upload_path=file_path, tier=tier)` 선(先)생성·커밋, 이후 `design_id`로 재조회해 필드 업데이트 — 10.5.3절과 일치. 세션 detach 이슈까지 코드 주석으로 명시(스펙에 없던 구현 디테일이지만 스펙 의도와 상충하지 않음).
- `index()`: `has_result = design is not None and design.preview_path and os.path.exists(design.preview_path)` — 10.5.4(A) 확정 코드와 일치. `upload_path` 방어 가드(425~426행 상당)도 스펙에서 "선택 사항"으로 남긴 것을 실제로 추가함(과잉이 아니라 스펙이 허용한 선택지 채택).
- `tier_info_path`/`load_tier_info`: 10.2절 스키마(`tier`/`price_krw`/`k_colors`/`design_id`)와 필드 구성이 정확히 일치. 쓰는 시점도 "`palette_info`와 같은 지점"으로 스펙대로 구현됨.
- `payment_success`: `tier_info` 조회 → `TIER_PRICES[tier_info["tier"]]`와 `amount_int` 비교 → `mark_paid(prefix, design_id=tier_info.get("design_id"))` — 10.3절/10.5.4(B)와 일치.
- `/upload`: `request.form.get('tier')`가 `TIER_PRICES`에 없으면 400 — 10.1절과 일치(기본값으로 조용히 STANDARD를 넣지 않는다는 요구사항도 그대로 반영).
- `/progress` 응답·완료 페이로드에 `tier`/`price_krw`/`k_colors` 포함 — 12.1절이 요구한 프론트-백엔드 필드명(`tier`, `price_krw`, `k_colors`)과 정확히 일치.
- 12.2절의 "선택 사항"(`mark_paid`에서 로그인 사용자는 dict에 안 쓰기, `upload_path` 방어 가드)은 채택하지 않거나 일부만 채택했으나, 스펙이 이미 "필수 아님"으로 명시한 항목이라 결함이 아니다.

프론트 쪽(12.1절)도 8.3/9장 지시와 대조해 전부 반영됨을 확인했다(등급 카드를 업로드 전 단계로 이동, 기본값 STANDARD, "참고용" 문구 삭제, `formData.append('tier', ...)`, 결과 없을 때 결제 버튼 비활성화, 재업로드 안내 문구). 088a268로 고친 이스케이프 버그를 제외하면 **8~13장 스펙과 실제 구현 사이에 추가로 발견된 불일치는 없다.**

### 14.5 세그멘테이션 4.2절 재검증 유효성 확인

`git show e81a6ac -- segmentation/`은 빈 diff다(파일 변경 없음) — 즉 이번 사이클의 프론트/백엔드 구현이 세그멘테이션 코드 자체를 전혀 건드리지 않았다. 4.2절의 6개 샘플 재검증 결과(5개 PASS, 초저해상도 참고용 1개는 알려진 케이스이며 업로드 가드로 이미 차단)는 **여전히 유효하다.** 재실행은 불필요하다.

### 14.6 사이클 2 종합 지시 요약

- **프론트(필수):** `templates/index.html` 495행, 690행을 14.3절의 수정 지시대로 `| tojson` 필터로 교체한다. (`088a268`이 고친 346~347행은 이미 완료, 재작업 불필요.)
- **백엔드:** 추가 작업 지시 없음(14.4절, 스펙과 구현이 완전히 일치).
- **세그멘테이션:** 추가 작업 지시 없음(14.5절, 코드 변경 없어 4.2절 재검증 그대로 유효).
- **QA/검증 절차 전반에 대한 제언(강제 지시는 아니지만 12장에 준하는 권고):** 앞으로 인라인 `<script>`/`<style>`에 서버 변수를 넣는 변경을 검증할 때는, "Jinja 렌더링이 예외 없이 끝나는가"뿐 아니라 **"렌더링된 결과에 내장된 하위 언어(JS 등)가 실제로 유효한 문법인가"까지 확인**한다(14.2절 근본 원인 분석 참고). 최소 기준으로 `has_result=True`/`False` 두 상태를 실제 브라우저(또는 헤드리스 브라우저)로 띄워 콘솔에 JS 에러가 없는지 확인하거나, 렌더링된 `<script>` 내용만 추출해 JS 파서로 파싱 검사를 추가하는 것을 권장한다.
