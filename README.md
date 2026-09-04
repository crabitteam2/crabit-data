# 위시 저축 리캡 & 피드 추천 시스템

학생들의 "위시리스트(목표 저축)" 활동을 바탕으로 **주간 활동 요약**, **월말 리캡**을 자동 생성하고, 학생별로 관련성 높은 피드를 골라주는 **피드 추천 시스템**을 포함.

백엔드 연동용 무상태 HTTP 서비스의 로컬 개발 서버는 `CRABIT_RECAP_TOKEN=... python -m recap_service`로 실행합니다. 운영에서는 digest로 고정한 이미지와 Gunicorn 엔트리포인트를 사용하며, 포트를 host에 publish하지 않고 backend 전용 private network에만 연결합니다. 이미지 빌드·환경 변수·검증·장애 경계는 [`docs/deployment/README.md`](docs/deployment/README.md)에 있습니다.

정식 내부 계약과 제한·오류·재시도 경계는 [`api/recap-generation-v1.yaml`](api/recap-generation-v1.yaml)에 있습니다. Spring은 스냅샷·생성 ID·재시도·저장을 소유하고 Python은 상태를 저장하지 않은 채 고정된 입력을 동기 계산합니다. 개발 서버가 바인딩되면 stdout에 `recap-service-ready` JSON 한 줄을 출력합니다. 교차 저장소 인수 테스트에서는 `CRABIT_RECAP_PORT=0`으로 OS가 고른 루프백 포트를 이 이벤트에서 읽거나 [`tests/real_service_harness.py`](tests/real_service_harness.py)의 컨텍스트 매니저를 재사용할 수 있습니다.

운영 이미지까지 포함한 저장소 검증은 다음 순서로 실행합니다.

```bash
python -m unittest discover -s tests -v
python -m compileall monthly_batch.py monthly_recap.py recap_presenter.py recap_service weekly_batch.py weekly_recap.py tests
image="crabit-recap:sha-$(git rev-parse --short=12 HEAD)"
docker build --build-arg VCS_REF="$(git rev-parse HEAD)" --tag "${image}" .
./scripts/deployment/verify-image.sh "${image}" "$(git rev-parse HEAD)"
./scripts/deployment/verify-runtime.sh "${image}"
./scripts/deployment/verify-workflow.sh
git diff --check
```

`input_digest`는 `generation_id`와 `input_digest` 자체를 제외한 요청을 RFC 8785/JCS로 직렬화한 정확한 SHA-256입니다. 객체 삽입 순서 기반 JSON은 호환 입력으로 허용하지 않습니다. Java 생산자와 Python 검증기가 함께 사용할 숫자·Unicode 기준 벡터는 [`tests/fixtures/jcs-cross-language-vectors.jsonl`](tests/fixtures/jcs-cross-language-vectors.jsonl)에 있습니다.

## 1. 한눈에 보는 구성

### 루트 (리캡)

| 파일 | 역할 |
|---|---|
| `generate_data.py` | 테스트용 더미 데이터(CSV) 생성 로직 (참고용, 아래 2번 참고) |
| `monthly_recap.py` | 월말 리캡 **계산 로직** (핵심 변수, 저축 유형 판별, 4개 섹션 데이터 생성) |
| `monthly_batch.py` | 학원 전체 학생을 순회하며 월말 리캡을 **실행**하고 결과를 저장 |
| `weekly_recap.py` | 주간 활동 요약 **계산 로직** (1~3페이지 데이터 생성) |
| `weekly_batch.py` | 학원 전체 학생을 순회하며 주간 리캡을 **실행**하고 결과를 저장 |
| `recap_presenter.py` | 배치 계산 결과를 화면용(`view`)과 내부 분석용(`internal_metrics`)으로 분리 |
| `wish_category_classifier.py` | 위시 제목을 카테고리로 분류 (피드 추천 시스템에서 사용, 나머지 리캡 로직과는 독립적) |

### `feed/` 폴더 (피드 추천)

| 파일 | 역할 |
|---|---|
| `candidate_extraction.py` | 1단계: 가벼운 규칙 기반으로 관련성 높은 후보 피드 추출 |
| `feed_scoring.py` | 2단계: 후보들에 점수를 매겨 랭킹 |
| `diversity_rules.py` | 3단계: 다양성 확보 및 노출 규칙(MMR, 강제 슬롯 등) 적용 |
| `feed_recommend.py` | 메인 실행 — 학원 전체 학생 대상 추천 결과를 JSON으로 저장 |
| `feed_recommend_ind.py` | *(참고용)* 학생 1명만 콘솔에 출력해보는 테스트 스크립트 |

`feed/` 폴더의 모듈들은 `monthly_recap.py`, `weekly_recap.py`, `wish_category_classifier.py`(전부 루트에 위치)를 import해서 씁니다. `feed_recommend.py`, `feed_recommend_ind.py`는 실행 시 `sys.path`에 루트 폴더를 추가해 이 import가 되도록 처리되어 있습니다.

`monthly_*`와 `weekly_*`는 데이터 모델(`Wish`, `SavingsTransaction`, `CardAccount`, `UserProfile` 등)을 `monthly_recap.py`에서 공유합니다. `weekly_recap.py`는 여기에 `FeedPost`만 추가로 정의합니다.

## 2. `generate_data.py` (참고용)

리캡/피드 추천 스크립트들은 모두 `data/` 폴더의 CSV 파일을 읽습니다. 이 저장소에는 `generate_data.py`로 만든 데이터가 `data/` 폴더에 이미 포함되어 있으므로, **이 파일을 실행할 필요가 없습니다.** 어떤 로직으로 더미 데이터를 만들었는지 참고하거나, 데이터를 새로 생성하고 싶을 때만 실행하면 됩니다.

```bash
python generate_data.py
```

생성되는 파일 (모두 `data/` 폴더 안):

- `card_accounts.csv` — 계좌(학생) 정보
- `users.csv` — 학생 프로필(이름, 나이)
- `wishes.csv` — 위시(저축 목표) 목록
- `savings_transactions.csv` — 입금/출금/이체/환급 거래 내역
- `feed_posts.csv` — 위시 공유 피드
- `profile_visits.csv` — 프로필 방문 기록

학원 1개(`aca1`), 학생 30명, 2026년 8월 기준 4가지 저축 유형(불도저형/꾸준형/단기집중형/탐색형)이 골고루 나오도록 설계된 시뮬레이션 데이터입니다. 재실행하면 `random.seed(42)`라서 학생 배치는 같지만, 오늘 날짜(`date.today()`)를 시뮬레이션 종료일로 쓰기 때문에 실행 시점에 따라 데이터 양은 달라질 수 있습니다.

## 3. 월말 리캡

### 실행

```bash
python monthly_batch.py
```

### 무엇을 하는가

1. `aca1` 학원 소속 계좌를 전부 조회
2. 계좌(학생)별로 `compute_core_metrics`로 이번 달 저축 횟수(`save_count`)를 먼저 확인
3. **3회 미만이면 비활동으로 간주해 리캡 생성 자체를 건너뜀** (활동량 조건 있음)
4. 3회 이상이면 `generate_monthly_recap`을 호출해 아래 내용을 계산
   - **0. 저축 유형**: 불도저형 → 꾸준형 → 단기집중형 → 탐색형(기본값 겸용) 순으로 판별
   - **1. 객관적 성과**: 총 저축액, 완료한 위시 수, 대표 위시 달성률 변화
   - **2. 저축 패턴 분석**: 가장 많이 모은 주/요일, 규칙성, 평균 저축액
   - **3. 그룹 내 비교**: 동일 학원·비슷한 나이대(±2세) 학생들 대비 백분위
   - **4. 페이스 분석**: 현재 속도 유지 시 목표 달성 예상일, 기한 내 달성을 위한 일일 필요 저축액

### 결과물

`monthly_batch.py`를 그대로 실행하면 학원 폴더에 **`output_monthly_recap.json`**이 생성됩니다. 계좌 ID별로 `recap_presenter.present_monthly_recap()`을 거쳐 화면에 바인딩할 `view`와 QA·디버깅용 `internal_metrics`가 분리된 형태입니다.

CSV로 한 줄씩(계좌당 한 행) 저장하고 싶다면 파일 하단의 주석 처리된 `write_monthly_results_csv` 호출부를 활성화하면 됩니다.

## 4. 주간 활동 요약

### 실행

```bash
python weekly_batch.py
```

### 무엇을 하는가

월말 리캡과 달리 **활동량과 무관하게 학원 내 전원**에게 생성합니다. `reference_date`(기본값: 오늘, 보통 매주 월요일 실행 가정) 기준으로 가장 최근에 끝난 한 주(월~일)를 계산해서:

- **1페이지 (지난주 성과)**: 저축 횟수/순저축액/새 위시 등록 수, 대표 위시 마일스톤(50/80/100% 돌파) 여부, 연속 저축 스트릭
- **2페이지 (성장 리포트)**: 프로필 방문 수/방문자 수와 전주 대비 증감률
- **3페이지 (학원 친구들의 성공 스토리)**: 같은 학원에서 지난주에 위시를 완료하고 피드에 공유한 사례 (본인 것은 제외)

### 결과물

`output_weekly_recap.json` — 계좌 ID별로 `view`/`internal_metrics`가 분리된 개인화 리포트.

학원 전체 완료+공유 목록(본인 제외 없이 관리자/QA 참고용으로 보고 싶을 때)은 파일 하단의 주석 처리된 `write_weekly_success_stories_csv` 호출부를 활성화해 별도 CSV로 저장할 수 있습니다.

## 5. `recap_presenter.py`가 하는 일

`monthly_batch.py`, `weekly_batch.py`의 원본 계산 결과(raw dict)를 그대로 화면에 내보내지 않고, 두 부분으로 나눠줍니다.

- `view`: 프론트엔드가 바로 바인딩할 수 있는 필드만 (메시지 문구, 수치 등)
- `internal_metrics`: 화면에는 없지만 QA/디버깅/분석에 필요한 값 (예: 저축 유형 판별 근거, 방문자 수 변화 이전 값 등)

`to_json()`으로 date/datetime을 ISO 문자열로 변환해 직렬화까지 처리합니다.

## 6. `wish_category_classifier.py`

리캡 로직과는 데이터를 공유하지 않는 별도 기능이며, 아래 피드 추천 시스템에서 사용됩니다. 위시 **제목**만 보고 11개 카테고리(패션/문구/전자기기/취미/스포츠/게임/도서/뷰티/굿즈/생활용품/기타) 중 하나로 분류합니다.

- 방식: 카테고리별 대표 키워드와 위시 제목 사이의 문자 n-gram TF-IDF + 코사인 유사도
- 형태소 분석기 없이 한국어를 다루기 때문에, 실시간으로 위시 1건씩 호출해도 부담 없음
- 유사도가 임계값(`DEFAULT_MIN_SIMILARITY = 0.05`) 미만이면 "기타"로 분류

```python
from wish_category_classifier import classify_wish_category

classify_wish_category("나이키 축구화")  # -> "스포츠"
```

단독 실행(`python wish_category_classifier.py`)하면 샘플 제목들에 대한 분류 결과와 유사도 점수를 출력합니다. `CATEGORY_KEYWORDS`에 키워드를 추가/수정한 뒤에는 `reset_classifier()`를 호출해야 다음 호출부터 재학습된 벡터가 반영됩니다.

## 7. 피드 추천 시스템 (`feed/` 폴더)

학생이 앱에 접속했을 때 볼 만한 관련성 높은 피드를 골라주는 3단계 파이프라인입니다. 학습 모델 없이 전부 규칙/가중합으로 동작하도록 되어 있어서, 나중에 특정 단계만 모델로 교체하기 쉬운 구조입니다.

### 실행

```bash
python feed/feed_recommend.py
```

`feed_recommend_ind.py`는 학생 1명에 대해 콘솔에 순위를 출력해보는 디버깅용 스크립트.

### 파이프라인 흐름

**1단계 — 후보 추출 (`candidate_extraction.py`)**
같은 학원의 피드 전체(친구 개념 없음)를 대상으로, 연산이 가벼운 규칙만으로 상위 `top_n`(기본 100개)개를 빠르게 걸러냅니다.
- 사용자의 대표 위시 기준 카테고리/금액대/기간 3개 중 몇 개가 일치하는지 (`basic_similarity`)
- 위시 제목 문자열 유사도 (`difflib`, `title_similarity`)
- 과거에 이 작성자를 방문한 적 있는지, 방문했던 계정들의 위시 카테고리와 겹치는지

**2단계 — 점수 계산 (`feed_scoring.py`)**
1단계 후보들에 아래 피처를 계산해 가중합(`WeightedSumScorer`)으로 점수를 매기고 상위 `top_n`(기본 40개)개로 좁힙니다.
- 1단계 신호(`basic_similarity`, `title_similarity`, 방문 이력) 재사용
- 저축 유형 기반 적합도(`type_relevance`): 나와 같은 유형이거나 불도저형/꾸준형 같은 모범 사례일수록 높음
- 저축 빈도(페이스) 유사도, 완료 위시(성공 사례) 가산점, 최신성(최근일수록 높음)
- `FeedScorer` 프로토콜만 지키면 나중에 학습 모델로 스코어러를 교체 가능

**3단계 — 다양성 및 규칙 (`diversity_rules.py`)**
2단계 결과를 받아 아래 순서로 최종 노출 목록(기본 20개)을 만듭니다.
1. MMR로 관련성과 다양성을 함께 고려한 초안 순서 생성
2. 최근 48시간 내 완료된 피드가 없으면 강제로 끼워넣기
3. 상위 10개 안에 불도저형/꾸준형의 완료 사례가 최소 2개 있도록 보정
4. 동일 카테고리가 연속 2개를 넘지 않도록 순서만 재배치 (구성은 유지)

### 결과물

`feed_recommend.py` 실행 시 루트 폴더에 **`feed_recommendations_aca1.json`**이 생성됩니다. `{학생 계정 ID: [feed_id, ...]}` 형태로, 학생마다 노출 순서대로 정렬된 피드 ID 리스트를 담고 있습니다.

## 8. 전체 실행 순서 요약

```bash
python monthly_batch.py       # output_monthly_recap.json 생성
python weekly_batch.py        # output_weekly_recap.json 생성
python feed/feed_recommend.py # feed_recommendations_aca1.json 생성
```

세 배치 모두 이미 제공된 `data/` 폴더를 그대로 읽으므로 순서는 상관없습니다. `generate_data.py`와 `wish_category_classifier.py`는 위 파이프라인과 무관하게, 데이터를 새로 만들거나 카테고리 분류만 단독으로 쓰고 싶을 때 참고하면 됩니다.

## 9. 실제 서비스 적용 시 참고

- `monthly_batch.py`, `weekly_batch.py`, `feed_recommend.py`의 데이터 로딩 부분은 지금은 `data/` CSV를 읽도록 되어 있지만, 실제 서비스에서는 이 부분만 사용 중인 DB 조회 로직으로 교체하면 됩니다.
- `academy_id`, `academy_name`, `year`/`month`, `reference_date` 등은 각 실행 스크립트의 `if __name__ == "__main__":` 블록에서 하드코딩되어 있으니, 스케줄러(예: 월말/매주 월요일 크론, 혹은 접속 시점 실시간 호출)에 맞게 파라미터를 채워 넣어야 합니다.
- `feed_scoring.py`의 `FeedScorer` 프로토콜을 지키는 새 클래스를 만들면, 나중에 학습된 랭킹 모델로 2단계 점수 계산만 교체할 수 있습니다.
