# 건축물대장 API 연동 메모

## 대상 API

| 검토순서 | 상세기능 | 경로 | 사용 목적 |
| --- | --- | --- | --- |
| 1 | 건축HUB_건축물대장 기본개요 조회 | `/getBrBasisOulnInfo` | 지번 주소 정합성, 대장종류/구분, 지역/지구/구역 확인 |
| 2 | 건축HUB_건축물대장 표제부 조회 | `/getBrTitleInfo` | 건물 용도, 구조, 면적, 주차 등 재건축 용도 추천 핵심 정보 확인 |

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

`BUILDING_OPEN_API_KEY_DECODING` 환경변수에 공공데이터포털 Decoding 인증키를 넣는다. 없으면 `BUILDING_OPEN_API_KEY_ENCODING`을 사용하고, 기존 호환용으로 `BUILDING_OPEN_API_KEY`도 마지막에 확인한다. 요청 시 코드는 인증키를 URL 파라미터로 다시 인코딩한다.

영천시 `sigunguCd`는 `47230`으로 고정한다. 지번 주소의 법정동/리 이름은 `data/법정동코드 조회자료.csv`의 `법정동명`에서 자동 검색하고, 10자리 `법정동코드` 중 앞 5자리를 `sigunguCd`, 뒤 5자리를 `bjdongCd`로 사용한다.
CSV에 없는 임시 코드는 운영 환경에서 `BUILDING_LEGAL_DONG_CODES`에 JSON으로 추가할 수 있지만, 기본 흐름은 로컬 CSV 조회를 우선한다.

예시:

```text
https://apis.data.go.kr/1613000/BldRgstHubService/getBrBasisOulnInfo?sigunguCd=47230&bjdongCd=25000&platGbCd=0&bun=0012&ji=0000&serviceKey=...
https://apis.data.go.kr/1613000/BldRgstHubService/getBrTitleInfo?sigunguCd=47230&bjdongCd=25000&platGbCd=0&bun=0012&ji=0000&serviceKey=...
```

## 에이전트 전달 필드

`redevelopment_recommendation.py`와 `search_building_ledger_by_jibun`은 원문 응답 전체가 아니라 아래 필드만 정규화해서 사용한다. LangChain tool 응답에는 `raw` 원문 페이로드를 넣지 않고, `ledger`와 `field_descriptions`만 전달한다.

| 정규화 필드 | 원문 필드 | 출처 API | 에이전트용 설명 |
| --- | --- | --- | --- |
| `address` | `platPlc` | 기본개요/표제부 | 대표 지번 주소. 입력 주소와 대장 조회 결과를 대조할 때 사용 |
| `jibun_address` | `platPlc` | 기본개요/표제부 | 건축물대장에 등록된 지번 주소 |
| `road_name_address` | `newPlatPlc` | 기본개요/표제부 | 건축물대장에 등록된 도로명주소. 현장 확인용 보조 주소 |
| `ledger_type` | `regstrGbCdNm` | 기본개요/표제부 | 대장 구분. 일반/집합 등 권리·건물 단위 해석에 참고 |
| `ledger_category` | `regstrKindCdNm` | 기본개요/표제부 | 대장 종류. 표제부/일반건축물 등 조회 결과 성격 확인 |
| `district_zone` | `jiyukCdNm`, `etcJiyuk`, `jiguCdNm`, `etcJigu`, `guyukCdNm`, `etcGuyuk` | 기본개요 우선 | 용도지역·지구·구역 정보. 행정·법적 제약 가능성 판단 |
| `plat_gb_cd` | `platGbCd` | 기본개요/표제부 | 대지구분코드. `0`: 대지, `1`: 산, `2`: 블록 |
| `bun` | `bun` | 기본개요/표제부 | 지번의 본번. 건축물대장 API 재조회용 식별값 |
| `ji` | `ji` | 기본개요/표제부 | 지번의 부번. 없으면 `0000`으로 정규화 |
| `main_use` | `mainPurpsCdNm`, `etcPurps` | 표제부 | 대장상 주용도. 주거, 근린생활, 창고, 노유자시설 등 활용 방향 판단의 핵심 근거 |
| `structure` | `strctCdNm`, `etcStrct` | 표제부 | 대장상 주구조. 철근콘크리트, 벽돌, 목조 등 재사용 가능성과 철거 위험 판단 |
| `roof_structure` | `roofCdNm`, `etcRoof` | 표제부 | 대장상 지붕 구조. 노후 상태와 보수 범위 판단의 보조 근거 |
| `land_area_m2` | `platArea` | 표제부 | 대지면적. 공유공간, 주차장, 녹지 등 외부 공간 확보 가능성 판단 |
| `building_area_m2` | `archArea` | 표제부 | 건축면적. 기존 건물이 차지하는 바닥 규모 판단 |
| `total_floor_area_m2` | `totArea` | 표제부 | 연면적. 리모델링이나 재사용 가능한 전체 실내 규모 판단 |
| `building_coverage_ratio` | `bcRat` | 표제부 | 건폐율. 대지 대비 건축면적 비율로 증축·외부공간 여지 판단 |
| `floor_area_ratio` | `vlRat` | 표제부 | 용적률. 대지 대비 연면적 비율로 추가 개발 여지 판단 |
| `parking_count` | `totPkngCnt`, `indrMechUtcnt`, `oudrMechUtcnt` | 표제부 | 대장상 주차대수. 접근성, 생활 SOC 전환, 주차장 활용 판단의 보조 근거 |
| `approval_year` | `useAprDay` | 표제부 | 사용승인연도. 건축물 노후도 산정과 구조 안전성 검토 필요성 판단 |
| `source` | 내부 값 | 어댑터 | 데이터 출처 어댑터 이름 |

## 코드 연결

- 서비스: `src/services/building_ledger.py`
- LangChain tool: `search_building_ledger_by_jibun`
- 에이전트 연결: `src/agents/redevelopment_recommendation.py`의 건축물대장 조회 단계

API 키가 없거나 주소의 법정동/리 코드 매핑이 없으면 도구는 `ok=false`와 실패 이유를 반환한다. 에이전트 본 흐름은 가짜 건축물대장 정보를 만들지 않고 오류를 반환한다.

## 제외 API

초기 재건축 용도 추천에는 아래 API를 호출하지 않는다.

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

## 표제부 원문 필드 선별 기준

표제부 응답에는 허가번호, 인증등급, 승강기, 부속건축물, 도로명 세부 코드 등 많은 행정 원문 필드가 포함된다. 초기 재건축 추천 에이전트에는 아래 판단에 직접 쓰이는 필드만 넘긴다.

| 판단 축 | 사용하는 표제부 원문 필드 | 제외하는 대표 필드 |
| --- | --- | --- |
| 주소·필지 정합성 | `platPlc`, `newPlatPlc`, `platGbCd`, `bun`, `ji` | `sigunguCd`, `bjdongCd`, `naRoadCd`, `naBjdongCd`, `naMainBun`, `naSubBun` |
| 대장 성격 확인 | `regstrGbCdNm`, `regstrKindCdNm` | `regstrGbCd`, `regstrKindCd`, `mgmBldrgstPk`, `rnum`, `crtnDay` |
| 용도·재사용 가능성 | `mainPurpsCdNm`, `etcPurps`, `strctCdNm`, `etcStrct`, `roofCdNm`, `etcRoof` | `mainPurpsCd`, `strctCd`, `roofCd`, `bldNm`, `dongNm`, `mainAtchGbCd` |
| 규모·밀도 | `platArea`, `archArea`, `totArea`, `bcRat`, `vlRat` | `vlRatEstmTotArea`, `totDongTotArea`, `heit`, `grndFlrCnt`, `ugrndFlrCnt` |
| 접근·주차 | `totPkngCnt`, `indrMechUtcnt`, `oudrMechUtcnt` | `indrMechArea`, `oudrMechArea`, `indrAutoArea`, `oudrAutoArea` |
| 노후도 | `useAprDay` | `pmsDay`, `stcnsDay`, `pmsnoYear`, `pmsnoKikCd`, `pmsnoGbCd` |

층수, 높이, 세대수, 승강기, 에너지/친환경/지능형 인증, 내진설계 정보는 향후 상세 안전성·사업성 검토에서는 유용할 수 있다. 다만 현재 에이전트의 1차 추천 단계에서는 추천 용도 판단 근거로 직접 사용하지 않으므로 기본 전달 필드에서 제외한다.
