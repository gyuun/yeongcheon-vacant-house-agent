https://www.vworld.kr/dev/v4dv_geocoderguide2_s001.do

요청 예시: 
- https://api.vworld.kr/req/address?service=address&request=getCoord&key=인증키&[요청파라미터]

| 파라미터 | 선택 | 설명 | 유효값 |
| :--|:--|:--|:--|
| service | O/1 | 요청 서비스명 | address(기본값) |
| version | O/1 | 요청 서비스 버전 | 2.0(기본값) | 
| request | M/1 | 요청 서비스 오퍼레이션 | GetCoord |
| key | M/1 | 발급받은 api key | |
| format | O/1 | 응답결과 포맷 | json(기본값), xml |
| errorFormat	| O/1	| 에러 응답결과 포맷, 생략 시 format파라미터에 지정된 포맷으로 설정	| json, xml |
| type	| M/1	| 검색 주소 유형	| PARCEL : 지번주소, ROAD : 도로명주소 |
| address	| M/1	| 검색 키워드 지번주소 : 법정동 + 지번까지 입력 ex) 관양동 1588-8 ex) 경기도 안양시 동안구 관양동 1588-8 도로명주소 : 시군구 + 도로명 + 건물번호 입력 ex) 부림로169번길 22 ex) 안양시 동안구 부림로169번길 22	|
| refine	|O/1	|정제되어 있는 주소의 경우 false로 설정하여 주소 정제 없이 빠르게 처리	| true(기본값), false |
| simple	| O/1	| 응답결과 간략 출력 여부	| true, false(기본값) |
| crs	| O/1	| 응답결과 좌표계	| 지원좌표계 참고, EPSG:4326(기본값) |
| callback	| O/1	| format값이 json일 경우 callback함수를 지원합니다.	|  |