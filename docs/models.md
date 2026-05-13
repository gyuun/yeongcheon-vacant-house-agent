# Models

`src/models.py`는 두 에이전트가 주고받는 핵심 데이터 구조를 정의한다. 현재 모델들은 `dataclass(frozen=True)`로 선언되어 있어 생성 후 값이 바뀌지 않는 불변 객체로 취급한다.

## RiskLevel

순찰 이미지 이상 추론 결과의 위험도를 나타내는 Enum이다.

| 값 | 의미 |
| --- | --- |
| `low` | 이상 징후가 없거나 즉시 조치가 필요하지 않은 상태 |
| `medium` | 담당자 확인 또는 현장 재확인이 필요한 상태 |
| `high` | 안전, 침입, 훼손, 붕괴 등 즉시 대응이 필요한 가능성이 높은 상태 |

## MaintenancePriority

빈집 정비 우선순위를 나타내는 Enum이다.

| 값 | 의미 |
| --- | --- |
| `low` | 단기 정비 우선순위가 낮은 대상 |
| `medium` | 정비 후보군으로 관리하고 추가 데이터 확인이 필요한 대상 |
| `high` | 정비 계획에 우선 반영할 필요가 큰 대상 |
| `urgent` | 안전조치, 철거, 보강 등 긴급 검토가 필요한 대상 |

## PatrolImageInput

순찰 로봇이 특정 빈집의 특정 촬영 지점에서 보낸 이미지 비교 요청 데이터다. 기준 이미지와 현재 촬영 이미지를 함께 전달해 이상 여부를 추론한다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `house_id` | `str` | 빈집 식별자 |
| `spot_id` | `str` | 촬영 지점 식별자. 예: `front-gate`, `back-yard` |
| `captured_image_base64` | `str` | 순찰 로봇이 현재 촬영한 이미지의 base64 문자열 |
| `baseline_image_base64` | `str` | 평상시 상태를 나타내는 기준 이미지의 base64 문자열 |
| `captured_at` | `str \| None` | 촬영 시각. 아직 형식은 고정하지 않았지만 ISO 8601 문자열 사용을 권장 |
| `metadata` | `dict[str, Any]` | 로봇 ID, 위치 좌표, 날씨, 촬영 각도 등 부가 정보 |

## PatrolImageAssessment

순찰 이미지 이상 추론 에이전트의 판정 결과다. Gemini 응답 또는 로컬 목업 추론 결과가 이 구조로 정규화된다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `house_id` | `str` | 판정 대상 빈집 식별자 |
| `spot_id` | `str` | 판정 대상 촬영 지점 식별자 |
| `is_anomaly` | `bool` | 기준 이미지 대비 이상 여부 |
| `risk_level` | `RiskLevel` | 이상 징후의 위험도 |
| `summary` | `str` | 판정 요약 |
| `evidence` | `list[str]` | 이미지상 차이, 모델 관찰 근거, 목업 판정 근거 |
| `recommended_actions` | `list[str]` | 담당자 알림, 현장 재확인, 정기 순찰 유지 등 권장 조치 |
| `raw_model_output` | `str \| None` | Gemini 원문 응답. 목업 또는 정규화된 응답만 사용할 때는 `None` 가능 |

## VacantHouseRecord

공공데이터 API 또는 목업 클라이언트에서 가져오는 빈집 원천 데이터다. 정비 우선순위 산정과 용도 추천의 입력으로 사용한다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `house_id` | `str` | 빈집 식별자 |
| `address` | `str` | 빈집 주소 또는 행정구역 |
| `building_age_years` | `int` | 건축물 노후도 |
| `vacancy_years` | `int` | 공실 기간 |
| `structure_grade` | `str` | 구조 상태 등급. 현재는 `A`부터 `E`까지의 등급을 가정 |
| `complaints_last_year` | `int` | 최근 1년 민원 건수 |
| `distance_to_road_m` | `float` | 도로까지의 거리 |
| `distance_to_public_facility_m` | `float` | 공공시설까지의 거리 |
| `land_area_m2` | `float` | 토지 면적 |
| `latitude` | `float \| None` | WGS84 위도. 좌표가 없는 지번-only 데이터는 `None` |
| `longitude` | `float \| None` | WGS84 경도. 좌표가 없는 지번-only 데이터는 `None` |
| `metadata` | `dict[str, Any]` | 데이터 출처, API 응답 원문 ID, 행정동 코드 등 부가 정보 |

## BuildingLedgerInfo

지번 주소로 조회한 건축물대장 기본개요/표제부 정보를 에이전트 판단에 필요한 필드만 정규화한 구조다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `address` | `str` | 입력 또는 대표 지번 주소 |
| `jibun_address` | `str \| None` | 대장상 지번 주소 |
| `road_name_address` | `str \| None` | 대장상 도로명주소 |
| `ledger_type` | `str \| None` | 대장종류 |
| `ledger_category` | `str \| None` | 대장구분 |
| `plat_gb_cd` | `str \| None` | 대지구분코드 |
| `bun` | `str \| None` | 번 |
| `ji` | `str \| None` | 지 |
| `main_use` | `str \| None` | 주용도 |
| `structure` | `str \| None` | 구조 |
| `roof_structure` | `str \| None` | 지붕구조 |
| `land_area_m2` | `float \| None` | 대지면적 |
| `building_area_m2` | `float \| None` | 건축면적 |
| `total_floor_area_m2` | `float \| None` | 연면적 |
| `building_coverage_ratio` | `float \| None` | 건폐율 |
| `floor_area_ratio` | `float \| None` | 용적률 |
| `parking_count` | `int \| None` | 주차대수 |
| `district_zone` | `str \| None` | 지역/지구/구역 |
| `approval_year` | `int \| None` | 사용승인연도 |
| `source` | `str` | 데이터 출처 어댑터 |
| `raw` | `dict[str, Any]` | 원문 API 응답 또는 디버깅 정보 |

## PriorityRecommendation

빈집 정비 우선순위 및 활용 용도 추천 에이전트의 결과 데이터다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `house_id` | `str` | 추천 대상 빈집 식별자 |
| `priority` | `MaintenancePriority` | 정비 우선순위 |
| `score` | `float` | 우선순위 산정 점수. 현재 목업 로직에서는 0부터 100까지의 범위 |
| `recommended_use` | `str` | 철거, 보강, 공유공간, 주차장, 녹지 등 추천 활용 방향 |
| `rationale` | `list[str]` | 추천 판단 근거 |
| `required_data` | `list[str]` | 실제 행정 판단 전에 추가로 확인해야 할 데이터 |

## 확장 메모

- 공공데이터 API가 확정되면 `VacantHouseRecord`에 실제 API 필드를 추가하거나 `metadata`에 원문 응답을 보존한다.
- Gemini 응답을 더 엄격히 통제하려면 `PatrolImageAssessment.evidence`에 들어갈 근거 형식을 표준화하는 편이 좋다.
- 외부 API와 직접 맞닿는 모델이 많아지면 dataclass 대신 Pydantic 모델로 전환해 검증, 직렬화, 스키마 생성을 강화할 수 있다.
