# 사용자 사용 테스트
이제 모든 실제를 가장한 목데이터인 data/mapping.csv 를 사용하여
src/agents/patrol_image.py, redevelopment_recommendation.py 를 이 6개 데이터에 한정해서 완벽하게 작동하는지 테스트해야함.
서버단에서 api 호출이 폴백으로 인한 하드코딩된 모킹 문자열이 반환되는것이 아닌, 실제 제미나이 호출이어야한다.

## 테스트 시나리오

각 실제 테스트 시나리오를 정해두고 이에따라 진행한다.
1. patrol_image.py
- 입력으로 house_id, captured_image_base64 이 주어짐을 가정.
  
- 현재 입력 모델: `PatrolImageInput`
```json 
{
  "house_id": "YC-001",
  "captured_image_base64": "<current-image-base64>",
  "baseline_image_base64": "<baseline-image-base64>",
  "captured_at": "2026-05-13T10:00:00+09:00",
  "metadata": {
    "robot_id": "robot-1",
    "weather": "clear"
  }
}
```
  - 변경 사항: 
    - spot_id는 존재하지 않으므로 데이터 스키마에서 삭제해야함.
    - baseline_image_base64 는 입력으로 받지 않고, house_id가 들어오면 그걸 사용해 baseline_image_base64를 채워넣어야함 (현재는 파일로 존재하므로 data/house/Hx_with_roof.txt 의 base64 문자열을 가져와야함)
    - metadata도 불필요하므로 삭제

- 현재 응답 형태: `PatrolImageAssessment`
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
  - 변경 사항: 
    - spot_id는 존재하지 않으므로 데이터 스키마에서 삭제해야함.

- 분석: 이미지는 모두 지붕의 유무 차이이며, 지붕 유무 외 다른 변화는 없다. 에이전트가 이를 잡아내는 지 확인해야한다.


2. redevelopment_recommendation.py
- 입력으로 "address", "photo_image_base64" 정보만 들어옴을 가정. 따라서 data/mapping.csv 데이터의 주소와 그에따른 data/house의 파일명 (hX_without_roof.txt)을 사용하여 입력으로 제공할것

입력 형태: API에서는 `RedevelopmentRecommendationRequest`, 그래프 내부에서는 `RedevelopmentState`를 사용합니다.

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

  - 변경 사항: 
    - 딱히 없음.

- 분석:
  - 현재 6개 데이터의 주소에 대해 지오코딩 좌표변환이 잘 이루어 지는지? (차이가난다면 지오코딩결과로 data/mapping.csv의 좌표컬럼 교체하기)
  - 각 서브에이전트가 정해진 폴백이 아닌 정확히 추론해서 리포트를 생성하는지? 생성 과정에서 문제는 없는지
  - 추론 결과가 타당한지?