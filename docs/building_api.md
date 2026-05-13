# 건축물대장 API 연동 메모

## 대상 API

| 우선순위 | 상세기능 | 경로 | 사용 목적 |
| --- | --- | --- | --- |
| 1 | 건축HUB_건축물대장 기본개요 조회 | `/getBrBasisOulnInfo` | 지번 주소 정합성, 대장종류/구분, 지역/지구/구역 확인 |
| 2 | 건축HUB_건축물대장 표제부 조회 | `/getBrTitleInfo` | 건물 용도, 구조, 면적, 주차 등 우선순위/활용 추천 핵심 정보 확인 |

입력 주소는 항상 지번 주소로 들어온다고 가정한다. 따라서 API 어댑터는 도로명주소 변환을 하지 않고, 지번 주소를 아래 요청 파라미터로 분해한다.

## 공통 요청 파라미터

| 항목명 | 필수 | 설명 | 예시 |
| --- | --- | --- | --- |
| `sigunguCd` | 필수 | 시군구코드 | `47230` |
| `bjdongCd` | 필수 | 법정동코드 | `25000` |
| `platGbCd` | 선택 | 대지구분코드. `0`: 대지, `1`: 산, `2`: 블록 | `0` |
| `bun` | 선택 | 번. 4자리 zero-padding 권장 | `0012` |
| `ji` | 선택 | 지. 없으면 `0000` | `0000` |
| `numOfRows` | 선택 | 페이지당 목록 수 | `10` |
| `pageNo` | 선택 | 페이지번호 | `1` |

`BUILDING_OPEN_API_KEY` 환경변수에 공공데이터포털 인증키를 넣는다. Encoding 키를 우선 사용한다.

영천시 `sigunguCd`는 `47230`으로 고정한다. 지번 주소의 법정동/리 이름은 `bjdongCd`로 변환해야 한다. 현재 도구에는 시내 법정동 일부가 내장되어 있고, 읍/면 리 단위 코드는 운영 환경에서 `BUILDING_LEGAL_DONG_CODES`에 JSON으로 추가할 수 있다.

```bash
BUILDING_LEGAL_DONG_CODES='{"금호읍 덕성리":"25022","청통면 호당리":"33026"}'
```

예시:

```text
https://apis.data.go.kr/1613000/BldRgstHubService/getBrBasisOulnInfo?sigunguCd=47230&bjdongCd=25000&platGbCd=0&bun=0012&ji=0000&serviceKey=...
https://apis.data.go.kr/1613000/BldRgstHubService/getBrTitleInfo?sigunguCd=47230&bjdongCd=25000&platGbCd=0&bun=0012&ji=0000&serviceKey=...
```

## 에이전트 필수 응답 필드

`priority_recommendation.py`는 원문 응답 전체가 아니라 아래 필드만 정규화해서 사용한다.

| 정규화 필드 | 출처 API | 판단 용도 |
| --- | --- | --- |
| `address` | 기본개요/표제부 | 입력 지번 또는 대표 주소 |
| `jibun_address` | 기본개요/표제부 | 지번 주소 정합성 확인 |
| `road_name_address` | 기본개요/표제부 | 담당자 확인용 보조 주소 |
| `ledger_type` | 기본개요 | 대장종류 확인 |
| `ledger_category` | 기본개요 | 일반/집합 등 대장구분 확인 |
| `district_zone` | 기본개요 | 용도지역/지구/구역 기반 활용 제약 판단 |
| `plat_gb_cd` | 기본개요/표제부 | 대지/산/블록 구분 |
| `bun` | 기본개요/표제부 | API 재조회용 번 |
| `ji` | 기본개요/표제부 | API 재조회용 지 |
| `main_use` | 표제부 | 주거/근린생활/창고 등 추천 활용 방향 판단 |
| `structure` | 표제부 | 구조 위험도와 보강 가능성 판단 |
| `roof_structure` | 표제부 | 외관/누수/노후 리스크 보조 판단 |
| `land_area_m2` | 표제부 | 공유공간, 주차장, 녹지 활용 가능 면적 판단 |
| `building_area_m2` | 표제부 | 기존 건축물 규모 판단 |
| `total_floor_area_m2` | 표제부 | 리모델링/활용 가능 규모 판단 |
| `building_coverage_ratio` | 표제부 | 증축/활용 여지 보조 판단 |
| `floor_area_ratio` | 표제부 | 증축/활용 여지 보조 판단 |
| `parking_count` | 표제부 | 접근성/생활 SOC 활용 보조 판단 |
| `approval_year` | 표제부 | 건축물 노후도 계산 |

## 코드 연결

- 서비스: `src/services/building_ledger.py`
- LangChain tool: `search_building_ledger_by_jibun`
- 에이전트 연결: `src/agents/priority_recommendation.py`의 건축물대장 조회 단계

API 키가 없거나 주소의 법정동/리 코드 매핑이 없으면 도구는 `ok=false`와 실패 이유를 반환한다. 에이전트 본 흐름은 기존 목업 건축물대장 정보로 fallback하여 데모 실행이 끊기지 않는다.

## 제외 API

초기 우선순위/활용 추천에는 아래 API를 호출하지 않는다.

| 상세기능 | 제외 이유 |
| --- | --- |
| 층별개요 조회 | 층별 용도/면적은 복합건물 세부 검토 단계에서만 필요 |
| 전유공용면적 조회 | 집합건축물 전유부 단위 분석이 필요할 때만 사용 |
| 주택가격 조회 | 매입/보상/사업비 산정 단계에서 사용 |
| 전유부 조회 | 동/호 단위 빈집일 때만 사용 |
| 오수정화시설 조회 | 숙박/주거 재사용 세부 검토 단계에서 사용 |
| 총괄표제부 조회 | 여러 동 또는 단지형 건축물일 때만 사용 |
| 부속지번 조회 | 부속 필지 정합성 문제가 있을 때만 사용 |
| 지역지구구역 조회 | 기본개요의 지역/지구/구역 정보가 부족할 때만 보강 |
