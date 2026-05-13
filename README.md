# Yeongcheon Vacant House Agent

영천시 공공데이터 활용 빈집 자동관리 에이전트 서비스 골격입니다.

## Agent 1: 순찰 이미지 이상 추론

순찰 로봇이 특정 스팟에서 촬영한 위치 정보와 현재 이미지를 base64로 전달하면 로컬 파일 시스템의 평상시 이미지와 비교하여 이상 여부를 판단합니다.

- 기본 모델명: `gemini-3-flash-preview`
- 실제 호출 조건: `GOOGLE_API_KEY` 환경변수 설정
- 입력: `PatrolImageInput`
- 출력: `PatrolImageAssessment`

## Agent 2: 빈집 재건축 용도 추천

메인 에이전트는 빈집 주소, 좌표, 사진을 입력받아 주소 기반 건축물대장 조회를 먼저 수행합니다. 건축물대장 API가 확정되기 전까지는 `fetch_building_ledger_by_address` 목업 경계를 사용합니다.
이후 사진 해석 서브에이전트와 좌표 주변 공공데이터 분석 서브에이전트를 호출하고, 건축물대장 정보와 두 리포트를 종합해 최종 재건축 용도를 추천합니다.
기존 `house_id` 기반 데모는 `MockPublicDataClient`를 통해 계속 지원합니다. 이후 실제 API 래퍼가 정해지면 `PublicDataClient` 구현체와 건축물대장 조회 함수만 교체하면 됩니다.
판단 결과는 DB에 저장됩니다.
재건축 용도 추천은 LLM as Judge 를 통해 결정 됩니다.

- 입력: `address`, `latitude`, `longitude`, `photo_image_base64`, 선택적으로 `house_id`
- 출력: `PriorityRecommendation`
- 현재 판단 요소: 건축물대장 정보, 사진 기반 외관/주변 경관 맥락, 주변 공공데이터, 노후도, 공실 기간, 구조 등급, 민원 건수, 도로 접근성, 공공시설 거리, 토지 면적

`data/` 아래 CSV들은 `LocalCsvGeoDataRepository`가 CSV별 레이어로 읽습니다. 각 행은 `GeoDataObject`로 정규화되고, 원본 row는 `properties`에 보존됩니다.

CSV 레이어는 세 종류로 나뉩니다.

- `coordinate`: `위도/경도` 컬럼 또는 산사태 데이터의 `위도 도/분/초`, `경도 도/분/초`가 있는 데이터. 좌표 기준 반경 검색에 바로 사용합니다.
- `administrative_area`: 좌표는 없고 `읍면동`, `행정동`, `법정동` 같은 행정구역 단위로 묶인 데이터. 좌표에서 행정동이 판정되면 해당 동 row를 함께 제공합니다.
- `address_unresolved`: 지번/도로명주소는 있지만 좌표가 없는 데이터. 추후 주소-좌표 변환으로 증강하기 전까지 반경 검색에서는 제외합니다.

빈집 레코드에 좌표가 있거나 요청 payload에 좌표가 있으면 추천 그래프가 주변 CSV 컨텍스트를 같이 전달합니다.

## 실행

```bash
uv run yeongcheon-agent serve
uv run yeongcheon-agent patrol
uv run yeongcheon-agent priority --house-id YC-001
uv run yeongcheon-agent priority --address "경상북도 영천시 중앙동" --photo-base64 "<base64-photo>"
uv run yeongcheon-agent priority --house-id YC-001 --lat 35.9682723 --lon 128.931526 --radius-km 2
uv run yeongcheon-agent priority --address "경상북도 영천시 중앙동" --photo-base64 "<base64-photo>" --lat 35.9682723 --lon 128.931526 --radius-km 2
uv run yeongcheon-agent nearby --lat 35.9682723 --lon 128.931526 --radius-km 2
uv run yeongcheon-agent nearby --lat 35.9682723 --lon 128.931526 --radius-km 2 --admin-area 동부동
uv run yeongcheon-agent nearby --lat 35.9682723 --lon 128.931526 --radius-km 2 --max-per-layer 10 --max-total 50
```

또는:

```bash
uv run python main.py patrol
uv run python main.py priority --house-id YC-002
uv run python main.py nearby --lat 35.9682723 --lon 128.931526 --radius-km 2
```

### 로컬 API

`serve` 명령은 기본적으로 `http://127.0.0.1:8000`에 FastAPI 서버를 띄웁니다.

```bash
uv run yeongcheon-agent serve --host 127.0.0.1 --port 8000
```

엔드포인트:

- `GET /health`
- `POST /agents/patrol-image`
- `POST /agents/priority-recommendation`
- `POST /nearby`

순찰 이미지 에이전트:

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

재건축 용도 추천 에이전트:

```bash
curl -X POST http://127.0.0.1:8000/agents/priority-recommendation \
  -H 'Content-Type: application/json' \
  -d '{
    "address": "경상북도 영천시 중앙동 1-1",
    "photo_image_base64": "<base64-photo>",
    "radius_km": 2
  }'
```

`/agents/priority-recommendation`은 프론트엔드에서 받은 지번 주소를 `src/services/geocoding.py`의 VWorld API로 먼저 좌표 변환한 뒤, 변환된 `latitude`/`longitude`를 재건축 용도 추천 에이전트에 전달합니다. 좌표 변환에는 `GEO_CODING_API_KEY`가 필요합니다.

## 구조

```text
src/
  api.py                         # 로컬호스트 FastAPI 엔드포인트
  agents/
    patrol_image.py              # 순찰 이미지 추론 LangGraph
    priority_recommendation.py   # 재건축 용도 추천 LangGraph
    tools/
      local_csv_geo_data.py      # 주변 공공 CSV 검색 LangChain tool
  services/
    gemini.py                    # Gemini 모델 생성 어댑터
    local_csv_data.py            # data/ CSV 좌표 객체화 및 반경 검색
    public_data.py               # 공공데이터 클라이언트 인터페이스 및 목업
  models.py                      # 입출력 데이터 모델
  cli.py                         # 데모 CLI
```
