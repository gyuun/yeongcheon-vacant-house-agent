# Yeongcheon Vacant House Agent 프로젝트 문서

이 프로젝트는 영천시 빈집 관리 업무를 보조하기 위한 LangGraph 기반 에이전트 API/CLI입니다. 현재 핵심 기능은 순찰 이미지 이상 징후 판정, 빈집 재건축 용도 추천, 좌표 주변 공공 CSV 데이터 조회입니다.

## 1. 전체 구조

```text
src/
  api.py                         # FastAPI 엔드포인트
  cli.py                         # yeongcheon-agent CLI
  models.py                      # 공통 입출력 dataclass 모델
  agents/
    patrol_image.py              # 순찰 이미지 이상 추론 에이전트
    redevelopment_recommendation.py
                                  # 재건축 용도 추천 에이전트
    prompts/                     # Gemini 프롬프트
    tools/                       # LangChain tool 래퍼
  services/
    gemini.py                    # Gemini 모델 생성
    geocoding.py                 # VWorld 주소 좌표 변환
    building_ledger.py           # 건축물대장 API 어댑터
    local_csv_data.py            # data/ CSV 로딩 및 반경 검색
    public_data.py               # 빈집 공공데이터 클라이언트 경계/목업
data/                            # 영천시 공공데이터 CSV
docs/                            # 세부 모델/API/데이터 메모
main.py                          # CLI 진입점 호환 래퍼
```

주요 런타임 의존성은 `FastAPI`, `Uvicorn`, `LangChain`, `LangGraph`, `langchain-google-genai`, `Pydantic`입니다. Python은 `>=3.12.2`를 요구합니다.

## 2. 환경 변수

| 변수 | 사용 위치 | 설명 |
| --- | --- | --- |
| `GOOGLE_API_KEY` | `src/services/gemini.py` | 설정되면 Gemini `gemini-3-flash-preview`를 호출합니다. 없으면 로컬 목업/fallback 추론으로 동작합니다. |
| `GEO_CODING_API_KEY` | `src/services/geocoding.py` | `/agents/redevelopment-recommendation` API에서 지번 주소를 WGS84 좌표로 변환할 때 필요합니다. `.env`도 자동 로드합니다. |
| `BUILDING_OPEN_API_KEY_ENCODING` | `src/services/building_ledger.py` | 건축물대장 API Encoding 인증키입니다. |
| `BUILDING_OPEN_API_KEY_DECODING` | `src/services/building_ledger.py` | Encoding 키가 없을 때 사용하는 Decoding 인증키입니다. |
| `BUILDING_OPEN_API_KEY` | `src/services/building_ledger.py` | 기존 호환용 fallback 키입니다. |
| `BUILDING_LEGAL_DONG_CODES` | `src/services/building_ledger.py` | 로컬 법정동 CSV에 없는 법정동 코드를 JSON으로 보강할 때 사용합니다. 기본은 `data/법정동코드 조회자료.csv`를 사용합니다. |

## 3. 에이전트 기준 설명

### 3.1 순찰 이미지 이상 추론 에이전트

파일: `src/agents/patrol_image.py`

목적: 순찰 로봇이 촬영한 현재 이미지와 기준 이미지를 비교해 빈집의 이상 징후를 판정합니다.

입력 모델: `PatrolImageInput`

```json
{
  "house_id": "YC-001",
  "spot_id": "front-gate",
  "captured_image_base64": "<current-image-base64>",
  "baseline_image_base64": "<baseline-image-base64>",
  "captured_at": "2026-05-13T10:00:00+09:00",
  "metadata": {
    "robot_id": "robot-1",
    "weather": "clear"
  }
}
```

사용 도구 및 외부 모델:

| 도구/서비스 | 역할 |
| --- | --- |
| Gemini `gemini-3-flash-preview` | 이미지 2장을 함께 받아 시각적 변화, 침입 흔적, 화재/연기, 쓰레기 투기, 붕괴, 누수, 훼손, 안전 위험을 판단합니다. |
| `patrol_prompt.md` | 순찰 이미지 비교 기준과 구조화 응답 요구사항을 모델에 전달합니다. |
| 로컬 목업 판정 | `GOOGLE_API_KEY`가 없으면 base64 문자열 길이 차이를 이용해 deterministic demo 판정을 만듭니다. |

추론 흐름:

1. LangGraph 노드 `infer_image_anomaly`가 실행됩니다.
2. 기준 이미지와 현재 이미지를 Gemini 멀티모달 메시지로 전달합니다.
3. Gemini 응답은 `PatrolImageDecision` Pydantic 스키마로 강제 구조화됩니다.
4. 구조화에 실패하면 `risk_level=medium`, `is_anomaly=true`의 fallback 판정을 반환해 담당자 검토가 가능하게 합니다.
5. 최종 응답은 `PatrolImageAssessment`로 정규화됩니다.

응답 형태: `PatrolImageAssessment`

```json
{
  "house_id": "YC-001",
  "spot_id": "front-gate",
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

### 3.2 빈집 재건축 용도 추천 에이전트

파일: `src/agents/redevelopment_recommendation.py`

목적: 지번 주소, 좌표, 사진, 공공데이터, 건축물대장 정보를 종합해 빈집의 재활용/재건축 용도를 추천합니다.

입력: API에서는 `RedevelopmentRecommendationRequest`, 그래프 내부에서는 `RedevelopmentState`를 사용합니다.

```json
{
  "house_id": "YC-001",
  "address": "경상북도 영천시 중앙동 1-1",
  "photo_image_base64": "<photo-base64>",
  "photo_image_mime_type": "image/jpeg",
  "radius_km": 0.5,
  "administrative_area": "동부동",
  "max_records_per_layer": 5,
  "max_total_records": 20
}
```

사용 도구 및 데이터:

| 도구/서비스 | 역할 |
| --- | --- |
| VWorld 지오코딩 | API 엔드포인트에서 지번 주소를 WGS84 `latitude`, `longitude`로 변환합니다. |
| `search_building_ledger_by_jibun` | 지번 주소를 건축물대장 API 파라미터로 파싱하고 기본개요/표제부를 조회하는 LangChain tool입니다. |
| `get_building_ledger_info` | 그래프 내부에서 실제 `BuildingLedgerInfo`를 가져옵니다. 실패하면 목업 건축물대장으로 fallback합니다. |
| `find_nearby_public_data` | 좌표 주변 `data/*.csv` 레이어를 반경 검색하는 LangChain tool입니다. |
| `get_nearby_public_data_bundle` | 그래프 내부에서 `NearbyGeoDataBundle` typed model을 직접 가져옵니다. |
| Gemini `gemini-3-flash-preview` | 사진 해석 서브에이전트에서 빈집 외관, 주변 경관, 접근성, 인접 시설, 마당/공터, 도로 접면 등을 해석합니다. |
| `MockPublicDataClient` | 실제 빈집 원천 API가 없을 때 `YC-001`, `YC-002` 등 데모 빈집 레코드를 제공합니다. |

LangGraph 노드 흐름:

```text
fetch_public_data
  ├─ interpret_photo
  └─ analyze_nearby_context
        ↓
recommend_redevelopment_use
```

노드별 추론:

| 노드 | 추론/처리 내용 |
| --- | --- |
| `fetch_public_data` | `house_id`가 있으면 목업 빈집 레코드를 조회합니다. `address` 기반 요청이면 주소 해시로 임시 `house_id`를 만들고 기본 빈집 속성을 구성합니다. 이후 건축물대장 정보를 조회하고 건축물 노후도, 구조 등급, 주용도, 면적, 지역지구구역 등을 요약합니다. |
| `interpret_photo` | 사진이 없으면 사진 분석을 보류했다는 낮은 신뢰도 리포트를 생성합니다. 사진이 있고 Gemini 키가 있으면 외관/주변 경관/도로 접면/생활권 분위기에서 맥락 신호와 기회 신호를 추출합니다. 키가 없으면 입력 상태 기반 목업 리포트를 생성합니다. |
| `analyze_nearby_context` | 좌표가 없으면 주변 공공데이터 분석을 보류합니다. 좌표가 있으면 반경 내 CSV 레이어를 검색하고 공원, 녹지, 보건, 복지, 숙박, 음식점, 공장, 일자리 등 레이어명을 기반으로 입지 신호를 요약합니다. |
| `recommend_redevelopment_use` | 건축물대장 리포트, 사진 리포트, 주변 데이터 리포트, 노후도/공실기간/구조등급/민원/도로접근성/공공시설거리/토지면적을 종합해 최종 `recommended_use`를 결정합니다. |

추천 규칙의 현재 우선순위:

| 신호 | 추천 방향 |
| --- | --- |
| `공원`, `녹지`, `경관`, `쉼터` | 마을 쉼터, 소규모 정원, 경관형 커뮤니티 공간 |
| `보건`, `복지`, `노인`, `급식`, `무더위쉼터` | 생활복지 거점 또는 돌봄 연계 커뮤니티 시설 |
| `숙박`, `음식점`, `착한가격`, `테마파크` | 체류형 로컬 상권 연계 공간 또는 관광 안내 거점 |
| `공장`, `제조`, `일자리` | 소규모 창업, 작업장, 일자리 지원 거점 |
| 공공시설 120m 이내, 토지 70㎡ 이상 | 마을 공유공간 또는 생활 SOC 연계 거점 |
| 도로 30m 이내 | 소규모 주차장 또는 골목 환경개선 부지 |
| 그 외 | 임시 녹지 및 경관 정비 |

응답 형태: `RedevelopmentRecommendation`

```json
{
  "house_id": "ADDR-12345",
  "recommended_use": "마을 쉼터, 소규모 정원, 경관형 커뮤니티 공간",
  "rationale": [
    "건축물 노후도 35년",
    "공실 기간 4년",
    "구조 등급 C",
    "최근 1년 민원 3건",
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

### 3.3 주변 공공데이터 조회 기능

파일: `src/services/local_csv_data.py`, `src/agents/tools/local_csv_geo_data.py`

목적: `data/` 아래 영천시 공공데이터 CSV를 레이어 단위로 읽고, 좌표/행정구역 기준으로 주변 맥락 데이터를 반환합니다. 독립 API `/nearby`와 재건축 추천 에이전트의 주변 맥락 분석에서 함께 사용합니다.

입력:

```json
{
  "latitude": 35.9682723,
  "longitude": 128.931526,
  "radius_km": 2,
  "administrative_area": "동부동",
  "max_records_per_layer": 5,
  "max_total_records": 20
}
```

레이어 분류:

| 분류 | 설명 |
| --- | --- |
| `coordinate` | `위도/경도`, `lat/lon`, 또는 산사태 데이터의 도/분/초 좌표가 있는 CSV입니다. Haversine 거리로 반경 검색합니다. |
| `administrative_area` | 좌표는 없지만 `읍면동`, `행정동`, `법정동` 단위로 묶인 CSV입니다. 요청의 `administrative_area`와 일치하면 포함합니다. |
| `address_unresolved` | 주소는 있으나 좌표가 없는 CSV입니다. 현재 반경 검색에서는 제외하며, 추후 주소-좌표 보강 대상입니다. |

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
    "returned_objects": 30,
    "coordinate_layers_with_matches": 4,
    "administrative_layers_with_matches": 1,
    "coordinate_records": 1000,
    "unresolved_records": 300,
    "max_records_per_layer": 5,
    "max_total_records": 20
  }
}
```

## 4. API 엔드포인트

서버 파일: `src/api.py`

### `GET /health`

서버 상태 확인용 엔드포인트입니다.

응답:

```json
{
  "status": "ok"
}
```

### `POST /agents/patrol-image`

순찰 이미지 이상 추론 에이전트를 실행합니다.

요청 body: `PatrolImageInput`

필수 필드:

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `house_id` | `string` | 빈집 식별자 |
| `spot_id` | `string` | 촬영 지점 식별자 |
| `captured_image_base64` | `string` | 현재 촬영 이미지 |
| `baseline_image_base64` | `string` | 기준 이미지 |

선택 필드:

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `captured_at` | `string \| null` | 촬영 시각 |
| `metadata` | `object` | 로봇 ID, GPS, 날씨 등 추가 정보 |

응답 body: `PatrolImageAssessment`

### `POST /agents/redevelopment-recommendation`

빈집 재건축 용도 추천 에이전트를 실행합니다.

중요: 이 API는 요청의 `address`를 VWorld 지오코딩으로 먼저 좌표 변환합니다. 따라서 `GEO_CODING_API_KEY`가 필요합니다. 좌표 변환 실패 시 `422`, 키 미설정 등 서비스 설정 문제는 `503`을 반환합니다.

요청 필드:

| 필드 | 타입 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `house_id` | `string \| null` | `null` | 빈집 식별자 |
| `address` | `string` | 필수 | 빈집 지번 주소 |
| `photo_image_base64` | `string` | 필수 | 빈집 사진 base64 |
| `photo_image_mime_type` | `string` | `image/jpeg` | 사진 MIME type |
| `radius_km` | `number` | `0.5` | 주변 공공데이터 검색 반경 |
| `administrative_area` | `string \| null` | `null` | 행정구역명 |
| `max_records_per_layer` | `integer \| null` | `5` | CSV 레이어별 최대 반환 수 |
| `max_total_records` | `integer \| null` | `20` | 전체 최대 반환 수 |

응답 body: `RedevelopmentRecommendation`

### `POST /nearby`

좌표 주변 영천시 공공 CSV 데이터를 조회합니다. 에이전트 추천 없이 데이터 레이어를 직접 확인할 때 사용합니다.

요청 필드:

| 필드 | 타입 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `latitude` | `number` | 필수 | WGS84 위도 |
| `longitude` | `number` | 필수 | WGS84 경도 |
| `radius_km` | `number` | `0.5` | 검색 반경 km |
| `administrative_area` | `string \| null` | `null` | 행정구역 레이어 매칭용 읍면동/행정동/법정동 |
| `max_records_per_layer` | `integer \| null` | `5` | CSV 레이어별 최대 반환 수 |
| `max_total_records` | `integer \| null` | `20` | 전체 최대 반환 수 |

응답 body: `NearbyGeoDataBundle`에 `summary`를 더한 JSON입니다.

## 5. 서버 사용 방법

의존성은 `uv` 기준으로 실행합니다.

```bash
uv sync
```

기본 서버 실행:

```bash
uv run yeongcheon-agent serve
```

호스트/포트 지정:

```bash
uv run yeongcheon-agent serve --host 127.0.0.1 --port 8000
```

코드 변경 시 자동 reload:

```bash
uv run yeongcheon-agent serve --host 127.0.0.1 --port 8000 --reload
```

서버가 뜨면 기본 URL은 다음과 같습니다.

```text
http://127.0.0.1:8000
```

FastAPI 문서는 기본적으로 다음 경로에서 확인할 수 있습니다.

```text
http://127.0.0.1:8000/docs
http://127.0.0.1:8000/redoc
```

헬스 체크:

```bash
curl http://127.0.0.1:8000/health
```

순찰 이미지 에이전트 호출:

```bash
curl -X POST http://127.0.0.1:8000/agents/patrol-image \
  -H 'Content-Type: application/json' \
  -d '{
    "house_id": "YC-001",
    "spot_id": "front-gate",
    "baseline_image_base64": "baseline-image-placeholder",
    "captured_image_base64": "captured-image-placeholder-with-visible-difference"
  }'
```

재건축 용도 추천 에이전트 호출:

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

주변 공공데이터 조회:

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

## 6. CLI 사용 방법

CLI entrypoint는 `pyproject.toml`의 `[project.scripts]`에 정의된 `yeongcheon-agent = "src.cli:main"`입니다. `main.py`도 같은 CLI를 호출합니다.

### 서버 실행

```bash
uv run yeongcheon-agent serve
uv run yeongcheon-agent serve --host 127.0.0.1 --port 8000 --reload
```

### 순찰 이미지 데모

```bash
uv run yeongcheon-agent patrol
```

이 명령은 코드에 내장된 placeholder base64 문자열로 `PatrolImageInput`을 만들고 순찰 이미지 에이전트를 실행합니다. `GOOGLE_API_KEY`가 없으면 목업 판정이 출력됩니다.

### 재건축 추천 데모

`house_id` 기반 목업 빈집:

```bash
uv run yeongcheon-agent redevelopment --house-id YC-001
uv run yeongcheon-agent redevelopment --house-id YC-002
```

주소와 사진 기반:

```bash
uv run yeongcheon-agent redevelopment \
  --address "경상북도 영천시 중앙동 1-1" \
  --photo-base64 "<base64-photo>" \
  --photo-mime-type image/jpeg
```

좌표와 반경 검색 포함:

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

주의: CLI의 `redevelopment` 명령은 API와 달리 주소를 자동 지오코딩하지 않습니다. 주변 공공데이터 분석을 포함하려면 `--lat`, `--lon`을 직접 전달해야 합니다.

### 주변 공공데이터 조회

```bash
uv run yeongcheon-agent nearby \
  --lat 35.9682723 \
  --lon 128.931526 \
  --radius-km 2
```

행정구역 레이어 포함:

```bash
uv run yeongcheon-agent nearby \
  --lat 35.9682723 \
  --lon 128.931526 \
  --radius-km 2 \
  --admin-area 동부동
```

반환 수 제한:

```bash
uv run yeongcheon-agent nearby \
  --lat 35.9682723 \
  --lon 128.931526 \
  --radius-km 2 \
  --max-per-layer 5 \
  --max-total 20
```

`main.py`를 직접 호출해도 동일하게 동작합니다.

```bash
uv run python main.py patrol
uv run python main.py redevelopment --house-id YC-001
uv run python main.py nearby --lat 35.9682723 --lon 128.931526 --radius-km 2
```

## 7. 현재 구현상 주의점

- `GOOGLE_API_KEY`가 없으면 Gemini 기반 실제 이미지 판독은 실행되지 않고 목업/fallback 응답이 반환됩니다.
- `/agents/redevelopment-recommendation` API는 반드시 VWorld 지오코딩을 거치므로 `GEO_CODING_API_KEY`가 없으면 실행되지 않습니다.
- CLI `redevelopment`는 주소 자동 지오코딩을 하지 않으므로 주변 데이터 분석이 필요하면 좌표를 직접 넘겨야 합니다.
- 건축물대장 API 키가 없거나 주소 파싱/조회가 실패하면 추천 흐름은 중단되지 않고 `mock-building-ledger` 정보로 계속 진행됩니다.
- 주변 공공데이터 검색은 현재 좌표가 있는 CSV와 행정구역 단위 CSV만 사용합니다. 주소만 있는 CSV는 `address_unresolved`로 분류되고 반경 검색에서 제외됩니다.
- 실제 빈집 원천 API는 아직 연결되지 않았습니다. `PublicDataClient` 구현체를 교체하면 `fetch_public_data` 단계에서 실제 데이터를 사용할 수 있습니다.
