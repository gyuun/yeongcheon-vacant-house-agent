# 재건축 용도 추천용 로컬 CSV 데이터 스키마

`redevelopment_recommendation.py`는 빈집 좌표를 기준으로 `data/*.csv`를 `LocalCsvGeoDataRepository`로 읽고, 주변 공공데이터를 `NearbyGeoDataBundle` 형태로 요약해 추천 근거에 반영한다.

## 공통 정규화 스키마

각 CSV 행은 원천 컬럼명을 유지하되 추천 에이전트가 공통으로 사용할 수 있도록 아래 필드로 정규화된다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `source` | string | 날짜 suffix를 제거한 CSV 레이어명 |
| `source_file` | string | 원본 CSV 파일명 |
| `row_number` | integer | CSV 내 1-based 행 번호 |
| `name` | string/null | 시설명, 업소명, 상호, 기관명 등 표시 이름 |
| `category` | string/null | 업종, 구분, 시설 유형, 법정동 등 분류 |
| `address` | string/null | 도로명/지번/소재지 주소 |
| `administrative_area` | string/null | 읍면동, 행정동, 법정동, 법정동명 |
| `coordinate.latitude` | number/null | WGS84 위도 |
| `coordinate.longitude` | number/null | WGS84 경도 |
| `properties` | object | 추천에 필요한 원천 CSV별 세부 속성 |

## 레이어 결합 방식

| `kind` | 조건 | 추천 사용 방식 |
| --- | --- | --- |
| `coordinate` | `위도/경도`, `latitude/longitude`, 산사태 DMS, 또는 `좌표정보(X/Y)`가 있는 레이어 | 빈집 좌표 반경 검색 후 거리순 사용 |
| `administrative_area` | 좌표 없이 읍면동/행정동 단위 통계만 있는 레이어 | 요청에 `administrative_area`가 있을 때 같은 행정구역 row 사용 |
| `address_unresolved` | 주소나 장소명은 있으나 좌표가 없는 레이어 | 반경 검색 제외. 지오코딩 또는 별도 장소 사전 필요 |

## 신규 반영 데이터

`data/new_data`의 22개 CSV를 `data/`로 옮기면서 UTF-8-SIG로 변환했다. CP949/EUC-KR 입력 19개 파일은 UTF-8로 재저장했고, 주소 기반 좌표 보강은 VWorld 지오코딩 API와 `data/.geocoding_cache.json` 캐시를 사용했다.

처리 결과:

| 항목 | 값 |
| --- | ---: |
| 신규 CSV 파일 | 22 |
| 전체 행 | 4,962 |
| 좌표 보유 행 | 4,133 |
| 이번 처리에서 지오코딩된 행 | 631 |
| 지오코딩 실패 행 | 9 |
| 장소명만 있고 주소가 없어 미해결인 행사/축제 행 | 820 |

## 신규 레이어별 추천 신호

| 레이어 | 주요 정규화 컬럼 | `properties` 주요 컬럼 | 추천 신호 |
| --- | --- | --- | --- |
| CCTV | `name=관리기관명`, `address=소재지도로명주소/소재지지번주소`, `coordinate` | 설치목적구분, 카메라대수, 촬영방면정보, 보관일수 | 안전/방범 인프라 |
| 경로당 | `name=시설명`, `administrative_area=행정동명`, `address`, `coordinate` | 건물층수, 담당부서명, 관리기관전화번호 | 노인 돌봄, 마을 커뮤니티 |
| 노인교실 | `name=시설명`, `address`, `coordinate` | 시설종류, 운영주체, 인원수, 운영상태 | 노인 교육/복지 수요 |
| 마을회관 | `name=시설명`, `address`, `coordinate` | 원천 행 위치 정보 | 주민 커뮤니티 거점 |
| 장애인 복지시설 | `name=시설명`, `address`, `coordinate` | 연락처, 시설장, 인원수 | 복지 접근성 |
| 지역아동센터 | `name=시설명`, `address`, `coordinate` | 정원, 현원, 운영시간, 급식 | 아동 돌봄 수요 |
| 의료기관 | `name=의료기관명`, `address=소재지`, `coordinate` | 운영시간, 진료과목, 병상수, 전화번호 | 보건 접근성 |
| 약국/한약방/의료기기판매업소 | `name=상호`, `address`, `coordinate` | 전화번호, 담당부서, 데이터기준일 | 생활 보건 상권 |
| 동물병원/동물약국 | `name=상호`, `address`, `coordinate` | 전화번호, 방사선 기기, 기준일 | 반려동물 생활 서비스 |
| 동네체육시설/체육시설업 | `name=체육시설명/상호`, `address`, `coordinate` | 원천 행 위치 정보 | 생활 체육/공공활용 |
| 캠핑장/농어촌민박 | `name=상호/사업장명`, `address`, `coordinate` | 객실수, 업태구분명, 영업상태명, 전화번호 | 관광/체류형 활용 |
| 카페/미용업 | `name=업소명`, `category=업종명`, `address`, `coordinate` | 업태명, 데이터기준일 | 생활 상권 밀도 |
| 장례식장 | `name=명칭`, `address`, `coordinate` | 종류, 시설면적, 빈소수 | 특수 생활시설 접근성 |
| 영천시농산물산지 | `name=사업장명`, `address`, `coordinate` | 주요품목 | 농산물/로컬푸드 연계 |
| 토석채취허가 및 채석신고 | `name=수허가자 상호`, `address=허가지 주소`, `coordinate` | 토석채취용도, 허가면적, 허가량, 허가기간 | 환경/개발 제약 신호 |
| 행사및축제 | `name=행사명`, `category=구분명` | 행사내용, 장소명, 담당부서명, 행사기간 | 현재 장소명만 있어 반경 검색 제외 |

## 추천 로직 연결

주변 데이터 요약은 최종 추천의 `rationale`에 레이어별 건수로 들어간다. 현재 키워드 기반 추천은 다음 신호를 우선 반영한다.

| 신호 키워드 | 추천 방향 |
| --- | --- |
| 공원, 녹지, 경관, 쉼터 | 마을 쉼터, 소규모 정원, 경관형 커뮤니티 공간 |
| 보건, 복지, 노인, 급식, 무더위쉼터 | 생활복지 거점 또는 돌봄 연계 커뮤니티 시설 |
| 숙박, 음식점, 착한가격, 테마파크, 캠핑장, 민박 | 체류형 로컬 상권 연계 공간 또는 관광 안내 거점 |
| 공장, 제조, 일자리 | 소규모 창업, 작업장, 일자리 지원 거점 |
| CCTV, 산사태, 토석채취 등 위험/안전 신호 | 추천 근거의 제약/주의 신호로 사용 |
