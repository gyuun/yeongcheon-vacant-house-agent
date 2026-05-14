# Yeongcheon Vacant House Agent

영천시 빈집 관리 업무를 보조하는 LangGraph 기반 에이전트 API/CLI 서버입니다. 다른 프론트엔드/백엔드 기능 폴더와 통합될 때는 이 서버를 독립 FastAPI 서비스 또는 Python 패키지 모듈로 붙이면 됩니다.

현재 제공 기능은 다음 3가지입니다.

- 순찰 이미지 이상 징후 판정: 기준 이미지와 순찰 로봇 촬영 이미지를 비교합니다.
- 빈집 재건축/재활용 용도 추천: 주소, 사진, 건축물대장, 주변 공공 CSV 데이터를 종합합니다.
- 좌표 주변 공공데이터 조회: `data/` 아래 영천시 CSV를 좌표/행정구역 기준으로 검색합니다.

## 빠른 실행

요구사항:

- Python `>=3.12.2`
- `uv`

설치 및 서버 실행:

```bash
uv sync
uv run yeongcheon-agent serve --host 127.0.0.1 --port 8000
```

개발 중 자동 reload:

```bash
uv run yeongcheon-agent serve --host 127.0.0.1 --port 8000 --reload
```

서버 기본 주소:

```text
http://127.0.0.1:8000
```

API 문서:

```text
http://127.0.0.1:8000/docs
http://127.0.0.1:8000/redoc
```

헬스 체크:

```bash
curl http://127.0.0.1:8000/health
```

## 통합 요약

프론트엔드 또는 다른 백엔드에서 직접 호출해야 하는 엔드포인트는 다음입니다.

| Method | Path | 용도 |
| --- | --- | --- |
| `GET` | `/health` | 서버 상태 확인 |
| `POST` | `/agents/patrol-image` | 순찰 이미지 이상 징후 판정 |
| `POST` | `/agents/redevelopment-recommendation` | 빈집 재건축/재활용 용도 추천 |
| `POST` | `/nearby` | 좌표 주변 공공 CSV 데이터 조회 |

주의할 점:

- `/agents/redevelopment-recommendation`은 입력 `address`를 VWorld API로 좌표 변환한 뒤 에이전트를 실행하므로 `GEO_CODING_API_KEY`가 필요합니다.
- 순찰 이미지 판정과 재건축 추천의 사진 해석에는 `GOOGLE_API_KEY` 또는 `GEMINI_API_KEY`가 필요합니다.
- 재건축 추천은 건축물대장 API 조회가 실패하면 가짜 대장 데이터를 만들지 않고 오류를 반환합니다.
- `house_id`는 `data/house/mapping.csv`의 주소/좌표 매핑을 찾는 로컬 fixture 키로만 사용합니다.

## 환경 변수

`.env` 파일은 일부 서비스에서 자동 로드됩니다. 운영 통합 시에는 프로세스 환경 변수로 주입하는 것을 권장합니다.

| 변수 | 필수 여부 | 사용 위치 | 설명 |
| --- | --- | --- | --- |
| `GOOGLE_API_KEY` 또는 `GEMINI_API_KEY` | 이미지 판정/사진 해석 사용 시 필수 | `src/services/gemini.py` | Gemini `gemini-3-flash-preview` 호출용 |
| `GEO_CODING_API_KEY` | 재건축 추천 API 사용 시 필수 | `src/services/geocoding.py` | VWorld 주소 좌표 변환 API 키 |
| `BUILDING_OPEN_API_KEY_DECODING` | 재건축 추천 API 사용 시 필수 | `src/services/building_ledger.py` | 공공데이터포털 건축물대장 API Decoding 인증키. 우선 사용 |
| `BUILDING_OPEN_API_KEY_ENCODING` | 선택 | `src/services/building_ledger.py` | 건축물대장 API Encoding 인증키. Decoding 키가 없을 때 사용 |
| `BUILDING_OPEN_API_KEY` | 선택 | `src/services/building_ledger.py` | 기존 환경 변수명 호환용 키 |
| `BUILDING_LEGAL_DONG_CODES` | 선택 | `src/services/building_ledger.py` | 로컬 법정동 CSV에 없는 법정동 코드를 JSON으로 보강 |
| `LOG_LEVEL` | 선택 | `src/api.py`, `src/cli.py` | 기본값 `INFO` |

예시:

```bash
GOOGLE_API_KEY=AI************************************
GEO_CODING_API_KEY=************************************
BUILDING_OPEN_API_KEY_DECODING=************************************
BUILDING_OPEN_API_KEY_ENCODING=************************************
```

건축물대장 연동 코드는 Decoding 키를 우선 읽고, 요청 시 URL 파라미터로 다시 인코딩합니다.

## API 계약

### `GET /health`

응답:

```json
{
  "status": "ok"
}
```

### `POST /agents/patrol-image`

순찰 로봇이 촬영한 현재 이미지와 서버의 기준 이미지를 비교해 이상 여부를 반환합니다. 기준 이미지는 `data/house/mapping.csv`에서 `house_id`로 찾습니다.

요청 body:

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `house_id` | `string` | 예 | 빈집 식별자 |
| `captured_image_base64` | `string` | 예 | 현재 촬영 이미지 base64 |
| `captured_at` | `string \| null` | 아니오 | 촬영 시각. ISO 8601 권장 |

요청 예시:

```bash
curl -X POST http://127.0.0.1:8000/agents/patrol-image \
  -H 'Content-Type: application/json' \
  -d '{
    "house_id": "YC-001",
    "captured_image_base64": "captured-image-placeholder-with-visible-difference"
  }'
```

응답 예시:

```json
{
  "house_id": "YC-001",
  "is_anomaly": true,
  "risk_level": "medium",
  "summary": "기준 이미지 대비 출입구 주변 변화가 감지되었습니다.",
  "evidence": [
    "출입문 주변 물체 변화",
    "외벽 하단 훼손 가능성"
  ],
  "recommended_actions": [
    "담당자 육안 검토",
    "현장 재확인"
  ],
  "raw_model_output": null
}
```

오류:

- `422`: `house_id`에 매핑된 기준 이미지가 없거나 요청 값이 유효하지 않음
- `502`: 모델 호출 실패
- `503`: Gemini quota/rate limit

### `POST /agents/redevelopment-recommendation`

지번 주소, 사진, 건축물대장, 주변 공공데이터를 종합해 빈집 재건축/재활용 용도를 추천합니다. API 계층에서 `address`를 VWorld로 먼저 지오코딩하고, 변환된 좌표를 LangGraph에 전달합니다. `data/house/mapping.csv`에 없는 실제 주소도 지오코딩에 성공하면 주변 CSV 반경 검색까지 수행합니다.

요청 body:

| 필드 | 타입 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| `house_id` | `string \| null` | 아니오 | `null` | 빈집 식별자. 없으면 주소 기반 임시 ID 생성 |
| `address` | `string` | 예 | 없음 | 빈집 지번 주소 |
| `photo_image_base64` | `string` | 예 | 없음 | 빈집 사진 base64 |
| `photo_image_mime_type` | `string` | 아니오 | `image/jpeg` | 사진 MIME type |
| `radius_km` | `number` | 아니오 | `0.5` | 주변 공공데이터 검색 반경 |
| `administrative_area` | `string \| null` | 아니오 | `null` | 행정구역 레이어 매칭용 읍면동/행정동/법정동 |
| `max_records_per_layer` | `integer \| null` | 아니오 | `5` | CSV 레이어별 최대 반환 수 |
| `max_total_records` | `integer \| null` | 아니오 | `20` | 전체 최대 반환 수 |

요청 예시:

```bash
curl -X POST http://127.0.0.1:8000/agents/redevelopment-recommendation \
  -H 'Content-Type: application/json' \
  -d '{
    "address": "경상북도 영천시 중앙동 1-1",
    "photo_image_base64": "<base64-photo>",
    "photo_image_mime_type": "image/jpeg",
    "radius_km": 2,
    "administrative_area": "동부동",
    "max_records_per_layer": 5,
    "max_total_records": 20
  }'
```

응답 예시:

```json
{
  "house_id": "ADDR-12345",
  "recommended_use": "마을 쉼터, 소규모 정원, 경관형 커뮤니티 공간",
  "explanation": "대상지는 요청 주소, 건축물대장, 현장 사진, 주변 공공데이터를 기준으로 활용 가능성을 검토했습니다.\n사진 해석과 주변 공공데이터를 함께 보면 여유 부지, 경관, 녹지 활용 가능성이 있어 주민 휴식형 공간으로 전환하는 방향이 적합합니다.\n최종 실행 전에는 소유자 동의, 상세 공부 확인, 예산과 주민 수요를 추가로 확인해야 합니다.",
  "rationale": [
    "주소: 경상북도 영천시 중앙동 1-1",
    "데이터 출처: request",
    "building_ledger: ...",
    "photo_interpretation: ...",
    "nearby_context: ..."
  ],
  "required_data": [
    "소유자 동의 여부",
    "토지/건축물대장 상세",
    "정비 예산",
    "인근 주민 수요"
  ]
}
```

오류:

- `422`: 주소를 좌표로 변환하지 못함
- `502`: 모델 호출 실패
- `503`: `GEO_CODING_API_KEY` 미설정, Gemini quota/rate limit, 지오코딩 서비스 설정 문제

### `POST /nearby`

좌표 주변 영천시 공공 CSV 데이터를 조회합니다. 재건축 추천 없이 주변 데이터만 확인하거나, 다른 서비스가 입지 데이터를 직접 쓰고 싶을 때 사용합니다.

요청 body:

| 필드 | 타입 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| `latitude` | `number` | 예 | 없음 | WGS84 위도 |
| `longitude` | `number` | 예 | 없음 | WGS84 경도 |
| `radius_km` | `number` | 아니오 | `0.5` | 검색 반경 km |
| `administrative_area` | `string \| null` | 아니오 | `null` | 행정구역 레이어 매칭용 |
| `max_records_per_layer` | `integer \| null` | 아니오 | `5` | CSV 레이어별 최대 반환 수 |
| `max_total_records` | `integer \| null` | 아니오 | `20` | 전체 최대 반환 수 |

요청 예시:

```bash
curl -X POST http://127.0.0.1:8000/nearby \
  -H 'Content-Type: application/json' \
  -d '{
    "latitude": 35.9682723,
    "longitude": 128.931526,
    "radius_km": 2,
    "administrative_area": "동부동",
    "max_records_per_layer": 5,
    "max_total_records": 20
  }'
```

응답 형태:

```json
{
  "center": {
    "latitude": 35.9682723,
    "longitude": 128.931526
  },
  "radius_km": 2,
  "administrative_area": "동부동",
  "layers": [
    {
      "source": "영천시_도시공원위치및벤치개수현황",
      "source_file": "영천시_도시공원위치및벤치개수현황.csv",
      "kind": "coordinate",
      "objects": [
        {
          "object": {
            "source": "영천시_도시공원위치및벤치개수현황",
            "row_number": 1,
            "name": "마현산공원",
            "category": "도시공원",
            "address": "경상북도 영천시 교촌동 11-36",
            "coordinate": {
              "latitude": 35.9723852,
              "longitude": 128.926406
            },
            "properties": {
              "개수": "21"
            }
          },
          "distance_km": 0.7
        }
      ],
      "matched_records": 1,
      "returned_records": 1,
      "total_records": 10,
      "coordinate_records": 10,
      "unresolved_records": 0
    }
  ],
  "summary": {
    "csv_layers": 25,
    "layers_with_matches": 5,
    "matched_objects": 30,
    "returned_objects": 20,
    "coordinate_layers_with_matches": 4,
    "administrative_layers_with_matches": 1,
    "coordinate_records": 1000,
    "unresolved_records": 300,
    "max_records_per_layer": 5,
    "max_total_records": 20
  }
}
```

## 에이전트 내부 흐름

### 순찰 이미지 이상 추론

파일:

- `src/agents/patrol_image.py`
- `src/agents/prompts/patrol_prompt.md`
- `data/house/mapping.csv`

흐름:

1. `PatrolImageInput.house_id`로 `data/house/mapping.csv`에서 기준 이미지 base64 텍스트 파일을 찾습니다.
2. 기준 이미지와 현재 이미지를 Gemini 멀티모달 메시지로 전달합니다.
3. Gemini 응답을 `PatrolImageDecision` Pydantic 스키마로 구조화합니다.
4. 구조화 실패 시 오류를 반환해 모델 응답 문제를 드러냅니다.
5. 최종 응답은 `PatrolImageAssessment`로 정규화됩니다.

주요 판정 항목:

- 침입 흔적
- 화재/연기
- 쓰레기 투기
- 붕괴/누수/훼손
- 기준 이미지 대비 외관 변화
- 안전 위험

### 빈집 재건축 용도 추천

파일:

- `src/agents/redevelopment_recommendation.py`
- `src/agents/prompts/redevelopment_*.md`
- `src/agents/tools/building_ledger.py`
- `src/agents/tools/local_csv_geo_data.py`
- `src/services/building_ledger.py`
- `src/services/geocoding.py`
- `src/services/local_csv_data.py`

LangGraph 노드:

```text
fetch_public_data
  ├─ interpret_photo
  └─ analyze_nearby_context
        ↓
recommend_redevelopment_use
```

노드 역할:

| 노드 | 역할 |
| --- | --- |
| `fetch_public_data` | `house_id` 기반 빈집 레코드 조회 또는 주소 기반 임시 레코드 구성, 건축물대장 조회 |
| `interpret_photo` | Gemini로 사진의 외관, 주변 경관, 도로 접면, 접근성, 생활권 분위기 해석 |
| `analyze_nearby_context` | 좌표와 행정구역으로 주변 CSV 레이어 검색 및 입지 신호 요약 |
| `recommend_redevelopment_use` | 건축물대장, 사진, 주변 데이터, 노후도, 공실 기간, 구조 등급 등을 종합해 최종 추천 |

건축물대장 연동:

- 지번 주소를 `sigunguCd`, `bjdongCd`, `bun`, `ji`로 파싱한 뒤 공공데이터포털 건축물대장 기본개요(`/getBrBasisOulnInfo`)와 표제부(`/getBrTitleInfo`)를 조회합니다.
- 에이전트에는 원문 응답 전체를 넘기지 않고 `address`, `main_use`, `structure`, `roof_structure`, `land_area_m2`, `building_area_m2`, `total_floor_area_m2`, `building_coverage_ratio`, `floor_area_ratio`, `parking_count`, `district_zone`, `approval_year` 등 재건축 추천에 필요한 정규화 필드만 전달합니다.
- LangChain tool `search_building_ledger_by_jibun` 응답은 `ledger`와 `field_descriptions`를 포함합니다. `raw` 원문 페이로드는 에이전트 응답에서 제외합니다.
- 필드 선별 기준과 원문 필드 매핑은 `docs/building_api.md`에 정리되어 있습니다.

현재 추천 방향:

| 신호 | 추천 방향 |
| --- | --- |
| 공원, 녹지, 경관, 쉼터 | 마을 쉼터, 소규모 정원, 경관형 커뮤니티 공간 |
| 보건, 복지, 노인, 급식, 무더위쉼터 | 생활복지 거점 또는 돌봄 연계 커뮤니티 시설 |
| 숙박, 음식점, 착한가격, 테마파크 | 체류형 로컬 상권 연계 공간 또는 관광 안내 거점 |
| 공장, 제조, 일자리 | 소규모 창업, 작업장, 일자리 지원 거점 |
| 공공시설 120m 이내, 토지 70㎡ 이상 | 마을 공유공간 또는 생활 SOC 연계 거점 |
| 도로 30m 이내 | 소규모 주차장 또는 골목 환경개선 부지 |
| 그 외 | 임시 녹지 및 경관 정비 |

### 주변 공공데이터 조회

파일:

- `src/services/local_csv_data.py`
- `src/agents/tools/local_csv_geo_data.py`
- `data/*.csv`

CSV 레이어 분류:

| 분류 | 설명 |
| --- | --- |
| `coordinate` | `위도/경도`, `lat/lon`, 또는 산사태 데이터의 도/분/초 좌표가 있는 CSV. Haversine 거리로 반경 검색 |
| `administrative_area` | 좌표는 없지만 `읍면동`, `행정동`, `법정동` 단위로 묶인 CSV. 요청의 `administrative_area`와 일치하면 포함 |
| `address_unresolved` | 주소는 있으나 좌표가 없는 CSV. 현재 반경 검색에서는 제외, 추후 주소-좌표 변환으로 보강 가능 |

최종 추천 에이전트와 API 응답에는 CSV 원문 전체를 그대로 전달하지 않고, `NearbyGeoDataBundle`로 정규화된 결과와 요약만 전달합니다. 원본 row의 비어 있지 않은 값은 각 객체의 `properties`에 보존됩니다.

## CLI 사용

CLI entrypoint는 `pyproject.toml`에 정의되어 있습니다.

```toml
[project.scripts]
yeongcheon-agent = "src.cli:main"
```

서버 실행:

```bash
uv run yeongcheon-agent serve
uv run yeongcheon-agent serve --host 127.0.0.1 --port 8000 --reload
```

순찰 이미지 데모:

```bash
uv run yeongcheon-agent patrol
```

재건축 추천 데모:

```bash
uv run yeongcheon-agent redevelopment --house-id YC-001
uv run yeongcheon-agent redevelopment --house-id YC-002
```

주소/사진 기반. `--lat`, `--lon`을 생략하면 CLI가 주소를 VWorld로 지오코딩한 뒤 주변 공공데이터를 검색합니다.

```bash
uv run yeongcheon-agent redevelopment \
  --address "경상북도 영천시 중앙동 1-1" \
  --photo-base64 "<base64-photo>" \
  --photo-mime-type image/jpeg
```

좌표와 주변 데이터 포함:

```bash
uv run yeongcheon-agent redevelopment \
  --address "경상북도 영천시 중앙동 1-1" \
  --photo-base64 "<base64-photo>" \
  --lat 35.9682723 \
  --lon 128.931526 \
  --radius-km 2 \
  --admin-area 동부동 \
  --max-per-layer 5 \
  --max-total 20
```

주변 공공데이터 조회:

```bash
uv run yeongcheon-agent nearby \
  --lat 35.9682723 \
  --lon 128.931526 \
  --radius-km 2 \
  --admin-area 동부동 \
  --max-per-layer 5 \
  --max-total 20
```

`main.py`를 직접 호출해도 같은 CLI가 실행됩니다.

```bash
uv run python main.py patrol
uv run python main.py redevelopment --house-id YC-001
uv run python main.py nearby --lat 35.9682723 --lon 128.931526 --radius-km 2
```

## 테스트와 검증

로컬 API 서버를 백그라운드로 띄운 뒤 `data/house/mapping.csv`의 6개 샘플을 호출하는 사용자 테스트 스크립트가 있습니다.

```bash
uv run scripts/run_user_tests.py
```

이 테스트는 Gemini/VWorld 키가 설정되어 있고 API 응답에 가짜 데이터 표시 문자열이 없어야 통과하도록 설계되어 있습니다.

건축물대장 API 원문 응답과 에이전트가 실제로 보는 정규화 정보를 같이 확인하려면 다음 스크립트를 사용합니다.

```bash
uv run python scripts/dump_building_api_mapping_responses.py
```

출력에는 엔드포인트별 raw 응답 뒤에 `agent_view: normalized fields shown to redevelopment agent` 섹션이 붙습니다. 원문 응답만 보고 싶으면 `--no-agent-view`를 추가합니다.

간단한 수동 검증 순서:

```bash
uv sync
uv run yeongcheon-agent serve --host 127.0.0.1 --port 8000
curl http://127.0.0.1:8000/health
```

## 프로젝트 구조

```text
src/
  api.py                         # FastAPI 엔드포인트
  cli.py                         # yeongcheon-agent CLI
  models.py                      # 공통 입출력 dataclass 모델
  agents/
    patrol_image.py              # 순찰 이미지 이상 추론 LangGraph
    redevelopment_recommendation.py
                                  # 재건축 용도 추천 LangGraph
    prompts/                     # Gemini 프롬프트
    tools/                       # LangChain tool 래퍼
  services/
    gemini.py                    # Gemini 모델 생성 어댑터
    geocoding.py                 # VWorld 주소 좌표 변환
    building_ledger.py           # 건축물대장 API 어댑터
    local_csv_data.py            # data/ CSV 로딩 및 반경 검색
data/
  house/                         # 순찰 이미지 기준/샘플 데이터
  *.csv                          # 영천시 공공데이터 CSV
docs/
  address_to_latlong.md          # 주소 좌표 변환 메모
  building_api.md                # 건축물대장 API 메모
  data_doc.md                    # 데이터 처리 메모
  models.md                      # 모델 메모
  redevelopment_data_schema.md   # 재건축 추천용 CSV 스키마
main.py                          # CLI 진입점 호환 래퍼
pyproject.toml                   # 패키지/의존성/CLI 설정
```

주요 런타임 의존성:

- `fastapi`
- `uvicorn`
- `langchain`
- `langgraph`
- `langchain-google-genai`
- `pydantic`

## 통합 시 확인 지점

실제 서비스와 붙일 때 가장 먼저 볼 파일은 다음입니다.

| 연동 대상 | 파일 | 현재 상태 |
| --- | --- | --- |
| 프론트 요청 API | `src/api.py` | FastAPI 엔드포인트 정의 |
| 주소 좌표 변환 | `src/services/geocoding.py` | VWorld API 사용 |
| 건축물대장 | `src/services/building_ledger.py` | 공공데이터포털 건축물대장 기본개요/표제부 조회 |
| 주변 공공데이터 | `src/services/local_csv_data.py` | 로컬 CSV 기반 |
| 모델 제공자 | `src/services/gemini.py` | Gemini `gemini-3-flash-preview` |
| 프롬프트 | `src/agents/prompts/*.md` | 업무 기준 프롬프트 |

## 운영상 주의점

- `GOOGLE_API_KEY`와 `GEMINI_API_KEY`가 모두 없으면 이미지 판독 요청은 실패합니다.
- `/agents/redevelopment-recommendation`은 반드시 VWorld 지오코딩을 거치므로 `GEO_CODING_API_KEY`가 없으면 `503`을 반환합니다.
- CLI `redevelopment`도 주소 입력 시 VWorld 지오코딩을 수행합니다. `--lat`, `--lon`을 직접 주면 해당 좌표를 우선 사용합니다.
- 건축물대장 API 키가 없거나 주소 파싱/조회가 실패하면 재건축 추천 요청은 실패합니다.
- 주변 공공데이터 검색은 좌표가 있는 CSV와 행정구역 단위 CSV만 사용합니다.
- 주소만 있는 CSV는 `address_unresolved`로 분류되고 반경 검색에서 제외됩니다.
- `data/.geocoding_cache.json`, `__pycache__`, `.DS_Store` 등은 런타임/로컬 산출물입니다.
